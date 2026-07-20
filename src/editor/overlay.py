#!/usr/bin/env python3
"""
The annotated view: the basis with every record labelled by its patch-state.

This is the one non-trivial piece of the editor (see
docs/editorial-overlay-design.md). It overlays data/patches/patches.jsonl on
the basis, resolving each patch's `anchor` against the basis by the SAME natural
key (word, pos, shaw, var) the applicator uses — imported from src/tools/basis.py,
never re-implemented here.

Under the settled model a patch is a MINIMAL DIFF over the live basis: an accept
displays the basis record with the patch's intrinsic `changes` laid over it
(basis.effective_record — the SAME layering the applicator emits, so the UI can
never diverge from what ships); a flag or a drop displays the untouched source
record. An accept-as-is (empty `changes`) and an accept-with-edits differ only in
whether `changes` is non-empty, which `patch_state` reflects.

Each annotated record carries the displayed content (word/shaw/pos/ipa/freq/var
plus provenance), its stable `anchor` (immutable identity, so an edited row never
moves), a `reviewed` flag (a patch exists — the primary filter partition), and a
`patch_state` for the ledger stamp:

    unreviewed  no patch resolves to this anchor
    accepted    an accept with no edits (changes empty) — sanctioned as-is
    edited      an accept carrying intrinsic edits (accept-with-edits / respell)
    dropped     a drop (op == "drop")
    flagged     a flag "looked at, no verdict yet" (see is_flag_patch)
    authored    a standalone record no basis anchor attests (anchor is null)
    orphaned    an ANCHORED patch whose anchor no longer resolves against the basis
                (upstream drifted out from under the decision — see below)

`dropped` rows still DISPLAY the source content (flagged, not hidden — the editor
must see a drop to roll it back). `authored` rows are not in the basis; they are
synthesized into the view so the editor sees everything a human has ruled on.

`orphaned` rows are the soft-fail counterpart of the applicator's orphan handling
(apply_patches.py): an anchored patch whose anchor key is absent from the current
basis (upstream drifted out from under a decision). There are two sub-kinds, carried
on the row as `orphan_kind` (see ORPHAN_* constants) so the owner can triage them
apart:

  lost-accept       an ACCEPT whose anchor vanished — a LOST VERDICT, a record the
                    owner sanctioned that no longer resolves to anything shippable.
                    Act on it: clear to discard, or re-accept a live anchor.

  resurfaced-drop   a DROP whose anchor vanished BUT whose same (word,pos,shaw) is
                    back in the basis under a DIFFERENT var — the record was
                    relabelled (RSSB/GenAm→RRP) and the drop no longer resolves to
                    it. The drop is EVADED: the junk the owner suppressed (e.g. a
                    contraction fragment like `'s`) has RETURNED. Surfacing this is
                    the whole point of the case — it was invisible before.

Either way there is no basis row to annotate, so the patch is synthesized into the
view from its OWN anchor + changes, marked `orphaned`, so the owner can find it (via
the `orphaned` filter) and act.

A DROP whose (word,pos,shaw) is WHOLLY absent from the basis is genuinely SATISFIED
(the record it wanted gone IS gone) and is NOT surfaced — it drops out of the view
as before. A FLAG of a vanished anchor shipped nothing and is never a lost verdict,
so it is not surfaced either. Surfacing those benign no-ops would bury the two real
lost verdicts. (Of ~107 orphaned drops the owner found, ~102 had resurfaced — only
~5 were genuinely satisfied.)

NOTE (owner question, deliberately NOT acted on here): this is an editor-VIEW change
only. The SHIPPED dictionary (apply_patches.py) still lets a resurfaced-drop through
— it does not re-suppress the relabelled record. Whether it should is a separate
decision for the owner; the overlay only surfaces the problem.
"""

import threading

from basis import (INFO_FIELD, OP_ACCEPT, OP_DROP, ORIG_FIELDS, UPSTREAM_SOURCE,
                   anchor_key, build_basis, effective_record, is_flag_patch,
                   output_to_record)

PATCH_STATE_UNREVIEWED = "unreviewed"
PATCH_STATE_ACCEPTED = "accepted"
PATCH_STATE_EDITED = "edited"
PATCH_STATE_DROPPED = "dropped"
PATCH_STATE_FLAGGED = "flagged"
PATCH_STATE_AUTHORED = "authored"
PATCH_STATE_ORPHANED = "orphaned"

UPSTREAM_STATUS = "sanctioned"
SUPPLEMENT_STATUS = "supplement"
AUTHORED_STATUS = "manual"
ORPHANED_STATUS = "orphaned"

# Why an anchored patch orphaned — the sub-kind of an `orphaned` row, so the owner
# can triage the two very differently:
#   lost-accept    an ACCEPT whose anchor vanished — a lost verdict, the sanctioned
#                  record no longer resolves to anything shippable (re-anchor or clear)
#   resurfaced-drop  a DROP whose anchor vanished BUT the same (word,pos,shaw) is back
#                  in the basis under a DIFFERENT var — the drop is EVADED, the junk
#                  the owner suppressed has returned (URGENT: re-suppress at the new var)
ORPHAN_LOST_ACCEPT = "lost-accept"
ORPHAN_RESURFACED_DROP = "resurfaced-drop"

# A candidate's novelty against the upstream ReadLex corpus ONLY for its word —
# see EstablishedIndex. This is an immutable fact ("does this word/spelling/pos
# appear upstream?"); sanctioning a record never changes it. Empty = not classified.
NOVELTY_NEW_WORD = "new-word"        # the word is absent from upstream ReadLex
NOVELTY_NEW_SPELLING = "new-spelling"  # word present upstream, this shaw is new
NOVELTY_NEW_POS = "new-pos"          # word+shaw present upstream, this pos is new
NOVELTY_KNOWN = "known"              # word+shaw+pos all present upstream (see classify)


def _novelty(record, source, established):
    """The record's novelty bucket against upstream ReadLex (new-word/new-spelling/
    new-pos/known), attached to the UI shape so the owner sees at a glance whether a
    row is new to the dictionary — the same signal the daemon's novelty filter uses.

    Mirrors _matches_novelty's short-circuit exactly: an upstream row IS the baseline
    novelty is measured against, so it is `known` by definition and spared a
    classify() call. Every other row is classified live (cheap dict lookups). Because
    both this and the filter call the SAME established.classify, the badge and the
    filter can never disagree."""
    if UPSTREAM_SOURCE in source:
        return NOVELTY_KNOWN
    return established.classify(
        record.get("word", ""), record.get("shaw", ""), record.get("pos", ""))


def _ui_record(record, anchor, source, default_status, reviewed, patch_state, patch,
               established):
    """One annotated row in the UI record shape (word/shaw/...). Provenance the
    record carries (source/status/confidence) wins; the origin-derived defaults
    stand in otherwise.

    `anchor` is the record's stable natural key {word, pos, shaw, var}. It never
    changes when the record is edited, so an edited row keeps its place and is
    still found by the anchor the patch was written against.

    `mergers` is the additive within-accent vowel-merger list — always present in
    the annotated shape (empty == canonical) so the UI can display and edit it,
    though it is emitted to disk only when non-empty (see basis.record_to_output).
    `variant` is the additive boolean marking a within-accent free-variation
    alternate spelling — always present (False == canonical), emitted to disk only
    when True (see basis.record_to_output).
    `has_definition` is the provenance boolean marking whether the upstream
    source(s) carry a definition for this record — always present (False == no
    upstream definition) so the UI can show the `def` pill and filter on it.
    `novelty` is the record's bucket against upstream ReadLex (new-word/new-spelling/
    new-pos/known) — always present so the UI can badge new-* rows (see _novelty).

    `orig_var`/`orig_shaw`/`orig_ipa` are DERIVED provenance: the pre-transform
    value of a key field a pipeline stage changed (see basis.mark_original —
    e.g. the identical-dialect collapse records the var a record was relabelled
    from). They are additive, present only when a transform actually changed that
    field, so each is passed through only when the record carries it. Read-only in
    the UI: the owner never edits provenance, it is shown as an audit marker (the
    original var a record was collapsed from, so the transformation is visible).

    `info` is the general-purpose informational field (see basis.INFO_FIELD): a
    catch-all list of non-essential metadata strings (e.g. Wiktionary quality tags
    obsolete/dialectal/dated). Additive and read-only — passed through only when the
    record carries it, so a record without it is unaffected.

    `op` is the patch's operation (accept/drop/flag), or None for an unreviewed
    row. It is carried onto the UI shape so the owner can tell WHAT verdict a
    reviewed row records — most useful on orphan rows, where a lost accept
    (redundant) and an EVADED drop (junk resurfaced under a relabelled var) need
    distinct triage. The daemon strips the raw `patch` object from the wire shape
    (serialisable), so anything the UI needs from the patch — here, the op — must
    ride on the record itself."""
    ui = {
        "word": record.get("word", ""),
        "shaw": record.get("shaw", ""),
        "pos": record.get("pos", ""),
        "ipa": record.get("ipa", ""),
        "freq": record.get("freq", 0),
        "var": record.get("var", ""),
        "mergers": record.get("mergers", []),
        "variant": bool(record.get("variant")),
        "has_definition": bool(record.get("has_definition")),
        "novelty": _novelty(record, source, established),
        "source": record.get("source", source),
        "confidence": record.get("confidence"),
        "status": record.get("status", default_status),
        "anchor": anchor,
        "reviewed": reviewed,
        "patch_state": patch_state,
        "op": patch.get("op") if patch else None,
        "patch": patch,
    }
    for orig_key in ORIG_FIELDS.values():
        if record.get(orig_key) not in (None, ""):
            ui[orig_key] = record[orig_key]
    if record.get(INFO_FIELD):
        ui[INFO_FIELD] = record[INFO_FIELD]
    return ui


def annotate_basis_record(candidate, source, patch, established):
    """One annotated row for a basis candidate under its overlaid patch.

    Unpatched: displays the source record, unreviewed. Accepted: displays the
    basis record with the patch's intrinsic `changes` laid over it, sanctioned
    (state `accepted` when `changes` is empty, `edited` when it carries edits).
    Dropped: displays the source record, flagged dropped. Flag: displays the
    source record, reviewed-but-undecided."""
    anchor = {"word": candidate["Latn"], "pos": candidate["pos"],
              "shaw": candidate["Shaw"], "var": candidate.get("var", "")}
    default_status = (UPSTREAM_STATUS if UPSTREAM_SOURCE in source
                      else SUPPLEMENT_STATUS)

    if patch is None:
        shown, reviewed, state = output_to_record(candidate), False, PATCH_STATE_UNREVIEWED
    elif is_flag_patch(patch):
        shown, reviewed, state = output_to_record(candidate), True, PATCH_STATE_FLAGGED
    elif patch["op"] == OP_DROP:
        shown, reviewed, state = output_to_record(candidate), True, PATCH_STATE_DROPPED
    else:
        changes = patch["changes"]
        shown = effective_record(candidate, changes, source)
        state = PATCH_STATE_EDITED if changes else PATCH_STATE_ACCEPTED
        reviewed = True

    return _ui_record(shown, anchor, source, default_status, reviewed, state, patch,
                      established)


def annotate_authored_record(patch, established):
    """One annotated row from an authorship patch (anchor is null): the record a
    human invented, which has no basis anchor. Its displayed content IS the record
    (the patch's `changes`, self-contained — no basis to diff against); its stable
    anchor is that record's own natural key.

    An authored record's source is a single origin (the author), a scalar in the
    patch. It is normalised to a one-element LIST here so the whole UI/daemon sees
    a uniform list-valued `source` — the same shape a basis record carries."""
    record = patch["changes"]
    anchor = {"word": record["word"], "pos": record["pos"],
              "shaw": record["shaw"], "var": record.get("var", "")}
    ui = _ui_record(record, anchor, [AUTHORED_STATUS], AUTHORED_STATUS, True,
                    PATCH_STATE_AUTHORED, patch, established)
    if not isinstance(ui["source"], list):
        ui["source"] = [ui["source"]]
    return ui


def annotate_orphaned_record(patch, orphan_kind, established):
    """One annotated row for an ORPHANED anchored patch: its anchor key is absent
    from the current basis, so there is no basis record to annotate. The row is
    synthesized from the patch itself — the anchor supplies the identity and the
    displayed word/pos/shaw/var (the record the decision was made against), with
    the patch's intrinsic `changes` laid over it so the owner sees the intended
    edit, not just the stale anchor. Marked `orphaned` and reviewed, so it is a
    dangling decision the owner must re-anchor or discard.

    `orphan_kind` (see ORPHAN_* constants) records WHY it orphaned so the owner can
    triage: a `lost-accept` is a sanction whose record vanished (re-anchor or clear);
    a `resurfaced-drop` is a suppression the basis EVADED — the same (word,pos,shaw)
    is back under a different var, so the junk returned and the owner must act. It
    rides on the UI shape (`orphan_kind`) alongside the patch `op` so the UI can
    label the two apart.

    Displaying the anchor overlaid with `changes` (rather than a full basis record)
    is the best available reconstruction: the basis record is gone, but the anchor
    plus the intended edit is exactly the lost-verdict content the owner needs to
    decide what to do. A drop's empty `changes` leaves the anchor showing as-is."""
    anchor = patch["anchor"]
    record = {"word": anchor["word"], "shaw": anchor["shaw"],
              "pos": anchor["pos"], "var": anchor.get("var", "")}
    record.update(patch["changes"])
    ui = _ui_record(record, anchor, [ORPHANED_STATUS], ORPHANED_STATUS, True,
                    PATCH_STATE_ORPHANED, patch, established)
    ui["orphan_kind"] = orphan_kind
    return ui


class AnnotatedView:
    """The basis overlaid with the patch store. Loaded once; filtered in memory
    per request. A write updates the affected anchor incrementally rather than
    rebuilding the whole ~238K-record view (see apply_patch / apply_unpatch).

    The basis (index + per-anchor origin) and the patch overlay (anchored map +
    authored map) are retained so a write can re-annotate one anchor in place.
    `by_anchor_index` maps an anchor key to the records carrying it, so both the
    per-anchor read and the in-place update are O(1). `by_word_index` maps a
    lowercased Latin word to the anchor keys carrying it, so the related-entries
    read is O(hits) rather than a full-view scan; it is kept in step with
    by_anchor_index as authored rows are added and removed. `by_shaw_index` mirrors
    it on the Shavian spelling, so variant siblings (same shaw, different Latin
    word — estrogen/oestrogen) join the same related read.

    The daemon is multithreaded (ThreadingMixIn): an in-place write mutates the
    shared index while readers iterate it, so a lock guards every mutating op and
    every read that touches the structure. Readers hand back a snapshot, never a
    live reference the caller would iterate after releasing the lock."""

    def __init__(self, basis_index, basis_source, patches):
        self.basis_index = basis_index
        self.basis_source = basis_source
        self.anchored, self.authored = _index_patches_by_anchor(patches)
        self.established = EstablishedIndex(basis_index, basis_source)
        self.by_anchor_index = _build_records(
            basis_index, basis_source, self.anchored, self.authored, self.established)
        self.by_word_index = _build_word_index(self.by_anchor_index)
        self.by_shaw_index = _build_shaw_index(self.by_anchor_index)
        self._lock = threading.Lock()

    @property
    def records(self):
        """Every annotated row, in basis-then-authored order (the order a full
        rebuild produces). Flattened from the per-anchor index on demand — the
        list the request handler filters and sorts. (Flattening the whole ~205K
        view each read is a known ~5.7ms cost, accepted for now.)"""
        with self._lock:
            return [record for group in self.by_anchor_index.values() for record in group]

    def by_anchor(self, key):
        """A snapshot of the records on `key` — a copy, so the caller may iterate
        it after the lock is released without racing a concurrent write."""
        with self._lock:
            return list(self.by_anchor_index.get(key, ()))

    def basis_record(self, key):
        """The UNTOUCHED basis record on `key` in UI (record) shape, or None if the
        basis holds no such anchor. This is the reference an accept's `changes`
        diffs against — the raw upstream/supplement candidate, never a prior
        patch's annotation. Read under the lock (basis_index is not mutated after
        construction, but the lock keeps the access uniform with the others)."""
        with self._lock:
            candidate = self.basis_index.get(key)
            return output_to_record(candidate) if candidate is not None else None

    def by_word(self, word):
        """A snapshot of every annotated record whose Latin word matches `word`
        case-insensitively — the related-entries read. Resolved through the
        lowercased-word index (O(hits), not a full-view scan) under the lock."""
        with self._lock:
            return [record
                    for key in self.by_word_index.get(word.lower(), ())
                    for record in self.by_anchor_index.get(key, ())]

    def by_shaw(self, shaw):
        """A snapshot of every annotated record whose Shavian spelling matches
        `shaw` exactly — the variant-sibling half of the related-entries read.
        Resolved through the shaw index (O(hits), not a full-view scan) under the
        lock, mirroring by_word."""
        with self._lock:
            return [record
                    for key in self.by_shaw_index.get(shaw, ())
                    for record in self.by_anchor_index.get(key, ())]

    def authored_patch(self, patch_id):
        """The authorship patch with `patch_id`, or None. A snapshot read under the
        lock — the caller reads its record without racing a concurrent write."""
        with self._lock:
            return self.authored.get(patch_id)

    def apply_patch(self, patch):
        """Overlay a written patch on its anchor, re-annotating only the affected
        records in place. An anchored patch re-annotates the basis record on that
        anchor; an authorship patch (anchor null) adds or replaces the authored
        record for its record's natural key. The result is identical to what a
        full rebuild would produce for that anchor — the same annotate_* function
        is applied to the same inputs."""
        with self._lock:
            if patch["anchor"] is None:
                self._apply_authored_patch(patch)
            else:
                self._reannotate_basis_anchor(anchor_key(patch["anchor"]), patch)

    def apply_reauthor(self, patch, prior_id):
        """Re-annotate an authorship entry re-decided in place: drop the row for
        `prior_id` and overlay `patch` (anchor null). A re-authorship changes the
        record, so `patch` has a NEW id; the prior authored row is found by
        `prior_id`, not the new one. Fails loud if no authored row carries it."""
        with self._lock:
            removed = self.authored.pop(prior_id, None)
            if removed is None:
                raise KeyError(f"no authored patch in view: {prior_id}")
            key = anchor_key(removed["changes"])
            self._forget_record(key, lambda r: r["patch_state"] == PATCH_STATE_AUTHORED
                                and r["patch"]["id"] == prior_id)
            self._apply_authored_patch(patch)

    def apply_unpatch_anchor(self, anchor):
        """Remove the anchored patch on the given anchor. If the basis holds the
        anchor, its record reverts to the untouched source annotation. If it does
        not, the patch was ORPHANED (a synthesized pseudo-row with no basis record):
        forget that row entirely — discarding the dangling decision is exactly what
        the owner asked for."""
        key = anchor_key(anchor)
        with self._lock:
            self.anchored.pop(key, None)
            if key in self.basis_index:
                self._reannotate_basis_anchor(key, None)
            else:
                self._forget_record(
                    key, lambda r: r["patch_state"] == PATCH_STATE_ORPHANED)

    def apply_unpatch_id(self, patch_id):
        """Remove the authorship patch with the given id, dropping its row."""
        with self._lock:
            removed = self.authored.pop(patch_id, None)
            if removed is None:
                raise KeyError(f"no authored patch in view: {patch_id}")
            key = anchor_key(removed["anchor"] or removed["changes"])
            self._forget_record(key, lambda r: r["patch_state"] == PATCH_STATE_AUTHORED
                                and r["patch"]["id"] == patch_id)

    def _reannotate_basis_anchor(self, key, patch):
        """Replace the basis record on `key` with its re-annotation under `patch`.
        Fails loud if the basis holds no such anchor — an anchored write must
        resolve to a basis record, never silently no-op."""
        candidate = self.basis_index.get(key)
        if candidate is None:
            raise KeyError(f"no basis record on anchor: {key}")
        if patch is not None:
            self.anchored[key] = patch
        annotated = annotate_basis_record(candidate, self.basis_source[key], patch,
                                          self.established)
        self._replace_record(key, annotated,
                             lambda r: r["patch_state"] != PATCH_STATE_AUTHORED)

    def _apply_authored_patch(self, patch):
        self.authored[patch["id"]] = patch
        annotated = annotate_authored_record(patch, self.established)
        key = anchor_key(patch["changes"])
        self._replace_record(
            key, annotated,
            lambda r: r["patch_state"] == PATCH_STATE_AUTHORED
            and r["patch"]["id"] == patch["id"])

    def _replace_record(self, key, annotated, predicate):
        """Swap the record on `key` matching `predicate` for `annotated`,
        keeping its position; append if none matched (a new row). A new anchor
        key (an authored word absent from the basis) is registered on the word
        and shaw indexes so the related read finds it."""
        records = self.by_anchor_index.setdefault(key, [])
        for i, record in enumerate(records):
            if predicate(record):
                records[i] = annotated
                return
        if not records:
            self.by_word_index.setdefault(key[0], set()).add(key)
            self.by_shaw_index.setdefault(key[2], set()).add(key)
        records.append(annotated)

    def _forget_record(self, key, predicate):
        """Drop the record on `key` matching `predicate` from the index. When the
        anchor empties, deregister it from the word and shaw indexes too."""
        records = self.by_anchor_index.get(key, [])
        for i, record in enumerate(records):
            if predicate(record):
                del records[i]
                if not records:
                    self.by_anchor_index.pop(key, None)
                    self._deregister_word(key)
                    self._deregister_shaw(key)
                return
        raise KeyError(f"no record to forget on anchor: {key}")

    def _deregister_word(self, key):
        keys = self.by_word_index.get(key[0])
        if keys is not None:
            keys.discard(key)
            if not keys:
                self.by_word_index.pop(key[0], None)

    def _deregister_shaw(self, key):
        keys = self.by_shaw_index.get(key[2])
        if keys is not None:
            keys.discard(key)
            if not keys:
                self.by_shaw_index.pop(key[2], None)


def _index_patches_by_anchor(patches):
    """Split the store: anchored patches keyed by (word_lower, pos, shaw, var),
    authorship patches (anchor null) keyed by patch id. Both are the live overlay
    a write mutates in step with the patch store."""
    anchored = {}
    authored = {}
    for patch in patches:
        if patch["anchor"] is None:
            authored[patch["id"]] = patch
        else:
            anchored[anchor_key(patch["anchor"])] = patch
    return anchored, authored


def _build_records(basis_index, basis_source, anchored, authored, established):
    """The per-anchor record index: anchor key -> its annotated rows, built once
    from the basis and overlay. Basis anchors come first (in basis order), then
    authored rows, then ORPHANED anchored patches (those whose anchor key is absent
    from the basis) synthesized as pseudo-rows — the order the flattened `records`
    view preserves.

    An anchored ACCEPT is orphaned when the basis holds no record on its anchor key
    (upstream drifted). It has no basis row to annotate, so it is surfaced from the
    patch itself (annotate_orphaned_record) rather than dropped from the view —
    mirroring the applicator's soft-fail, which logs and retains such a patch.

    A DROP whose anchor vanished is surfaced ONLY when it was EVADED: the same
    (word_lower, pos, shaw) is back in the basis under a DIFFERENT var (upstream
    relabelled the record — e.g. RSSB/GenAm→RRP — so the junk the owner suppressed
    returned under a new key the drop no longer resolves against). A drop whose
    (word,pos,shaw) is genuinely absent from the basis is SATISFIED (its record is
    gone) and stays unsurfaced. A flag shipped nothing and is never a lost verdict.
    The resurfaced-drop test consults `resurfaced_key_index`, the (word,pos,shaw)→
    var-set fold of the basis (see _build_resurfaced_index)."""
    resurfaced_index = _build_resurfaced_index(basis_index)
    index = {}
    for key, candidate in basis_index.items():
        index.setdefault(key, []).append(
            annotate_basis_record(candidate, basis_source[key], anchored.get(key),
                                  established))

    for patch in authored.values():
        record = annotate_authored_record(patch, established)
        index.setdefault(anchor_key(record["anchor"]), []).append(record)

    for key, patch in anchored.items():
        if key in basis_index:
            continue
        orphan_kind = _orphan_kind(patch, key, resurfaced_index)
        if orphan_kind is not None:
            index.setdefault(key, []).append(
                annotate_orphaned_record(patch, orphan_kind, established))

    return index


def _build_resurfaced_index(basis_index):
    """Map each basis (word_lower, pos, shaw) to the set of vars carrying it — the
    fold that answers "did a dropped record resurface under a different var?". The
    anchor key is (word_lower, pos, shaw, var), so this drops the var slot and
    collects it into a set. Built once per view build; consulted per orphaned
    drop."""
    resurfaced = {}
    for word_lower, pos, shaw, var in basis_index:
        resurfaced.setdefault((word_lower, pos, shaw), set()).add(var)
    return resurfaced


def _orphan_kind(patch, key, resurfaced_index):
    """The orphan sub-kind (ORPHAN_* ) to surface for an anchored patch whose anchor
    `key` is absent from the basis, or None to leave it unsurfaced.

    An ACCEPT is a lost verdict — matching the applicator's resolve_patch, which
    returns PATCH_ORPHAN for an accept alone (ORPHAN_LOST_ACCEPT).

    A DROP is surfaced ONLY as a resurfaced-drop: its (word_lower, pos, shaw) is
    present in the basis under some var, and — since its own anchor var is absent
    (`key` not in basis) — that var necessarily differs. The suppressed record has
    returned under a relabelled var, so the drop is EVADED, not satisfied
    (ORPHAN_RESURFACED_DROP). A drop whose (word,pos,shaw) is wholly absent is
    satisfied (the record it wanted gone IS gone) and stays unsurfaced.

    A FLAG shipped nothing and is never a lost verdict."""
    op = patch.get("op")
    if op == OP_ACCEPT:
        return ORPHAN_LOST_ACCEPT
    if op == OP_DROP:
        word_lower, pos, shaw, _var = key
        if (word_lower, pos, shaw) in resurfaced_index:
            return ORPHAN_RESURFACED_DROP
    return None


def _build_word_index(by_anchor_index):
    """Map each lowercased Latin word to the set of anchor keys carrying it — the
    related-entries lookup. The anchor key's first element IS that lowercased word
    (see anchor_key), so this is a regrouping of the existing keys."""
    word_index = {}
    for key in by_anchor_index:
        word_index.setdefault(key[0], set()).add(key)
    return word_index


def _build_shaw_index(by_anchor_index):
    """Map each Shavian spelling to the set of anchor keys carrying it — the
    variant-sibling half of the related-entries lookup. The anchor key's third
    element IS the shaw (see anchor_key), so this is a regrouping of the existing
    keys."""
    shaw_index = {}
    for key in by_anchor_index:
        shaw_index.setdefault(key[2], set()).add(key)
    return shaw_index


class EstablishedIndex:
    """The upstream ReadLex corpus — and ONLY the upstream corpus — for the novelty
    classification. Novelty is an immutable fact about a candidate ("does this
    word/spelling/pos appear in upstream ReadLex?"); sanctioning a record must never
    reclassify it, so the index deliberately excludes patches. (The duplicate
    filter's established set additionally includes sanctioned patches; that is
    correct for dedup but wrong here — see filter_supplement_duplicates.)

    Maps each lowercased Latin word to the set of (shaw, pos) pairs upstream holds
    for it, which answers all three novelty questions: is the word upstream at all
    (key present), is this shaw upstream for the word (any pair with that shaw),
    is this word+shaw+pos upstream (exact pair present)."""

    def __init__(self, basis_index, basis_source):
        self._pairs_by_word = {}
        for key, entry in basis_index.items():
            if UPSTREAM_SOURCE in basis_source[key]:
                self._register(key[0], entry["Shaw"], entry["pos"])

    def _register(self, word_lower, shaw, pos):
        self._pairs_by_word.setdefault(word_lower, set()).add((shaw, pos))

    def classify(self, word, shaw, pos):
        """The highest-precedence novelty of a candidate against upstream ReadLex:
        new-word > new-spelling > new-pos, else known (word+shaw+pos all present
        upstream). A sanctioned supplement absent from upstream keeps its true
        novelty (new-*) forever — sanctioning does not make it known."""
        pairs = self._pairs_by_word.get(word.lower())
        if pairs is None:
            return NOVELTY_NEW_WORD
        if not any(established_shaw == shaw for established_shaw, _ in pairs):
            return NOVELTY_NEW_SPELLING
        if (shaw, pos) not in pairs:
            return NOVELTY_NEW_POS
        return NOVELTY_KNOWN


def load_view():
    """Build the annotated view from the current basis and patch store."""
    from patchstore import load_patches

    basis_index, basis_source = build_basis(enrich_freq=True)
    return AnnotatedView(basis_index, basis_source, load_patches())
