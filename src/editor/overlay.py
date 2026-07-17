#!/usr/bin/env python3
"""
The annotated view: the basis with every record labelled by its patch-state.

This is the one non-trivial piece of the editor (see
docs/editorial-overlay-design.md). It overlays data/patches/patches.jsonl on
the basis, resolving each patch's `anchor` against the basis by the SAME natural
key (word, pos, shaw, var) the applicator uses — imported from src/tools/basis.py,
never re-implemented here.

Under the settled model a patch's `record` is complete and authoritative, so an
annotated row's DISPLAYED content is simply the patch's `record` when a patch
exists on its anchor, else the untouched source record. There is no source+patch
merge — that merge was the source of the "edit invisible in the UI" bug.

Each annotated record carries the displayed content (word/shaw/pos/ipa/freq/var
plus provenance), its stable `anchor` (immutable identity, so an edited row never
moves), a `reviewed` flag (a patch exists — the primary filter partition), and a
`patch_state` for the ledger stamp:

    unreviewed  no patch resolves to this anchor
    edited      a patch supplies a record (accept / edit / respell)
    dropped     a patch drops it (record is null)
    flagged     a patch marks it "looked at, no verdict yet" (see is_flag_patch)
    authored    a standalone record no basis anchor attests (anchor is null)

`dropped` rows still DISPLAY the source content (flagged, not hidden — the editor
must see a drop to roll it back). `authored` rows are not in the basis; they are
synthesized into the view so the editor sees everything a human has ruled on.
"""

import threading

from basis import (UPSTREAM_SOURCE, anchor_key, build_basis, is_flag_patch,
                   output_to_record)

PATCH_STATE_UNREVIEWED = "unreviewed"
PATCH_STATE_EDITED = "edited"
PATCH_STATE_DROPPED = "dropped"
PATCH_STATE_FLAGGED = "flagged"
PATCH_STATE_AUTHORED = "authored"

UPSTREAM_STATUS = "sanctioned"
SUPPLEMENT_STATUS = "supplement"
AUTHORED_STATUS = "manual"

# A candidate's novelty against the ESTABLISHED data (upstream ReadLex + sanctioned
# patches) for its word — see EstablishedIndex. Empty = not classified (any).
NOVELTY_NEW_WORD = "new-word"        # the word is absent from established
NOVELTY_NEW_SPELLING = "new-spelling"  # word present, this shaw is new
NOVELTY_NEW_POS = "new-pos"          # word+shaw present, this pos is new
NOVELTY_KNOWN = "known"              # word+shaw+pos all established (see classify)


def _ui_record(record, anchor, source, default_status, reviewed, patch_state, patch):
    """One annotated row in the UI record shape (word/shaw/...). Provenance the
    record carries (source/status/confidence) wins; the origin-derived defaults
    stand in otherwise.

    `anchor` is the record's stable natural key {word, pos, shaw, var}. It never
    changes when the record is edited, so an edited row keeps its place and is
    still found by the anchor the patch was written against."""
    return {
        "word": record.get("word", ""),
        "shaw": record.get("shaw", ""),
        "pos": record.get("pos", ""),
        "ipa": record.get("ipa", ""),
        "freq": record.get("freq", 0),
        "var": record.get("var", ""),
        "source": record.get("source", source),
        "confidence": record.get("confidence"),
        "status": record.get("status", default_status),
        "anchor": anchor,
        "reviewed": reviewed,
        "patch_state": patch_state,
        "patch": patch,
    }


def annotate_basis_record(candidate, source, patch):
    """One annotated row for a basis candidate under its overlaid patch.

    Unpatched: displays the source record, unreviewed. Patched with a record:
    displays that record (accept/edit/respell), reviewed. Patched to a drop:
    displays the source record, flagged dropped. Flag patch: displays the source
    record, reviewed-but-undecided."""
    anchor = {"word": candidate["Latn"], "pos": candidate["pos"],
              "shaw": candidate["Shaw"], "var": candidate.get("var", "")}
    default_status = UPSTREAM_STATUS if source == "readlex" else SUPPLEMENT_STATUS

    if patch is None:
        shown, reviewed, state = output_to_record(candidate), False, PATCH_STATE_UNREVIEWED
    elif is_flag_patch(patch):
        shown, reviewed, state = output_to_record(candidate), True, PATCH_STATE_FLAGGED
    elif patch["record"] is None:
        shown, reviewed, state = output_to_record(candidate), True, PATCH_STATE_DROPPED
    else:
        shown, reviewed, state = patch["record"], True, PATCH_STATE_EDITED

    return _ui_record(shown, anchor, source, default_status, reviewed, state, patch)


def annotate_authored_record(patch):
    """One annotated row from an authorship patch (anchor is null): the record a
    human invented, which has no basis anchor. Its displayed content IS the
    record; its stable anchor is that record's own natural key."""
    record = patch["record"]
    anchor = {"word": record["word"], "pos": record["pos"],
              "shaw": record["shaw"], "var": record.get("var", "")}
    return _ui_record(record, anchor, record.get("source", AUTHORED_STATUS),
                      AUTHORED_STATUS, True, PATCH_STATE_AUTHORED, patch)


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
    by_anchor_index as authored rows are added and removed.

    The daemon is multithreaded (ThreadingMixIn): an in-place write mutates the
    shared index while readers iterate it, so a lock guards every mutating op and
    every read that touches the structure. Readers hand back a snapshot, never a
    live reference the caller would iterate after releasing the lock."""

    def __init__(self, basis_index, basis_source, patches):
        self.basis_index = basis_index
        self.basis_source = basis_source
        self.anchored, self.authored = _index_patches_by_anchor(patches)
        self.by_anchor_index = _build_records(
            basis_index, basis_source, self.anchored, self.authored)
        self.by_word_index = _build_word_index(self.by_anchor_index)
        self.established = EstablishedIndex(basis_index, basis_source, patches)
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

    def by_word(self, word):
        """A snapshot of every annotated record whose Latin word matches `word`
        case-insensitively — the related-entries read. Resolved through the
        lowercased-word index (O(hits), not a full-view scan) under the lock."""
        with self._lock:
            return [record
                    for key in self.by_word_index.get(word.lower(), ())
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
            key = anchor_key(removed["record"])
            self._forget_record(key, lambda r: r["patch_state"] == PATCH_STATE_AUTHORED
                                and r["patch"]["id"] == prior_id)
            self._apply_authored_patch(patch)

    def apply_unpatch_anchor(self, anchor):
        """Remove the anchored patch on the given anchor, reverting its basis
        record to the untouched source annotation."""
        key = anchor_key(anchor)
        with self._lock:
            self.anchored.pop(key, None)
            self._reannotate_basis_anchor(key, None)

    def apply_unpatch_id(self, patch_id):
        """Remove the authorship patch with the given id, dropping its row."""
        with self._lock:
            removed = self.authored.pop(patch_id, None)
            if removed is None:
                raise KeyError(f"no authored patch in view: {patch_id}")
            key = anchor_key(removed["anchor"] or removed["record"])
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
        annotated = annotate_basis_record(candidate, self.basis_source[key], patch)
        self._replace_record(key, annotated,
                             lambda r: r["patch_state"] != PATCH_STATE_AUTHORED)

    def _apply_authored_patch(self, patch):
        self.authored[patch["id"]] = patch
        annotated = annotate_authored_record(patch)
        key = anchor_key(patch["record"])
        self._replace_record(
            key, annotated,
            lambda r: r["patch_state"] == PATCH_STATE_AUTHORED
            and r["patch"]["id"] == patch["id"])

    def _replace_record(self, key, annotated, predicate):
        """Swap the record on `key` matching `predicate` for `annotated`,
        keeping its position; append if none matched (a new row). A new anchor
        key (an authored word absent from the basis) is registered on the word
        index so the related read finds it."""
        records = self.by_anchor_index.setdefault(key, [])
        for i, record in enumerate(records):
            if predicate(record):
                records[i] = annotated
                return
        if not records:
            self.by_word_index.setdefault(key[0], set()).add(key)
        records.append(annotated)

    def _forget_record(self, key, predicate):
        """Drop the record on `key` matching `predicate` from the index. When the
        anchor empties, deregister it from the word index too."""
        records = self.by_anchor_index.get(key, [])
        for i, record in enumerate(records):
            if predicate(record):
                del records[i]
                if not records:
                    self.by_anchor_index.pop(key, None)
                    self._deregister_word(key)
                return
        raise KeyError(f"no record to forget on anchor: {key}")

    def _deregister_word(self, key):
        keys = self.by_word_index.get(key[0])
        if keys is not None:
            keys.discard(key)
            if not keys:
                self.by_word_index.pop(key[0], None)


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


def _build_records(basis_index, basis_source, anchored, authored):
    """The per-anchor record index: anchor key -> its annotated rows, built once
    from the basis and overlay. Basis anchors come first (in basis order), then
    authored rows appended — the order the flattened `records` view preserves."""
    index = {}
    for key, candidate in basis_index.items():
        index.setdefault(key, []).append(
            annotate_basis_record(candidate, basis_source[key], anchored.get(key)))

    for patch in authored.values():
        record = annotate_authored_record(patch)
        index.setdefault(anchor_key(record["anchor"]), []).append(record)

    return index


def _build_word_index(by_anchor_index):
    """Map each lowercased Latin word to the set of anchor keys carrying it — the
    related-entries lookup. The anchor key's first element IS that lowercased word
    (see anchor_key), so this is a regrouping of the existing keys."""
    word_index = {}
    for key in by_anchor_index:
        word_index.setdefault(key[0], set()).add(key)
    return word_index


class EstablishedIndex:
    """The established dictionary — upstream ReadLex plus sanctioned patches — for
    the novelty classification, mirroring the same established-set definition the
    duplicate filter uses (filter_supplement_duplicates.build_established_index).

    Maps each lowercased Latin word to the set of (shaw, pos) pairs established for
    it, which answers all three novelty questions: is the word established at all
    (key present), is this shaw established for the word (any pair with that shaw),
    is this word+shaw+pos established (exact pair present).

    Built once from the initial basis + patch set — the established baseline a
    candidate is judged against. In-session review verdicts do not move a candidate
    into "established"; that is the reviewed/state filter's concern, not novelty's."""

    def __init__(self, basis_index, basis_source, patches):
        self._pairs_by_word = {}
        for key, entry in basis_index.items():
            if basis_source[key] == UPSTREAM_SOURCE:
                self._register(key[0], entry["Shaw"], entry["pos"])
        # A patch establishes an entry only if sanctioned; other patch states are
        # still under review and establish nothing (mirrors the duplicate filter).
        for patch in patches:
            record = patch.get("record")
            if record is None or record.get("status") != UPSTREAM_STATUS:
                continue
            self._register(record["word"].lower(), record["shaw"], record["pos"])

    def _register(self, word_lower, shaw, pos):
        self._pairs_by_word.setdefault(word_lower, set()).add((shaw, pos))

    def classify(self, word, shaw, pos):
        """The highest-precedence novelty of a candidate against established data:
        new-word > new-spelling > new-pos, else known (word+shaw+pos all
        established — a same word+shaw+pos entry the duplicate filter keeps
        because it differs only by dialect var)."""
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

    basis_index, basis_source = build_basis()
    return AnnotatedView(basis_index, basis_source, load_patches())
