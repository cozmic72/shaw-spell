#!/usr/bin/env python3
"""
The editorial BASIS: the raw combination of all upstream sources, computed
on-demand and indexed by the natural key a patch's anchor resolves against.

This is the single implementation of the anchor/basis logic shared by the
applicator (src/tools/apply_patches.py, which emits data/readlex.json) and the
editor daemon (src/editor/editord.py, which annotates the basis with each
record's patch-state). Neither keeps its own copy — see
docs/editorial-overlay-design.md.

  - The basis is the combined supplement pool — which, since the core fold-in,
    CONTAINS upstream ReadLex (external/readlex/readlex.json) as ordinary
    records: core is collated into the pool at combine time under the `readlex`
    source label (see combine_supplements.SOURCES) and rides the whole pruning
    chain untouched. Every candidate, including the unreviewed supplemental
    ones, is a record in the basis. Nothing is frozen.
  - A patch's `anchor` is the natural key (word.lower(), pos, shaw, var) of the
    ONE basis record it reviews. Each dialect var is reviewed independently.

A patch is a MINIMAL DIFF over the live basis, not a full-record snapshot:

    {anchor, op, changes, meta}

  op        "accept"  — sanction the anchored basis record, with the intrinsic
                        edits in `changes` layered over it (empty = accept as-is).
            "drop"    — emit nothing for the anchored key.
            "flag"    — "looked at, no verdict yet"; a production no-op.
  changes   the INTRINSIC field edits {word, shaw, pos, ipa, var, mergers,
            variant} an accept lays over the basis record — and ONLY those. For
            an authorship patch (anchor null) `changes` is the WHOLE record, as
            there is no basis to diff against.

resolve_patch layers a patch over the live basis to the canonical output record,
so a decision follows upstream as it drifts rather than freezing a stale copy.
Derived provenance is NOT stored in `changes`: `source` comes from the basis
origin map, `confidence` from the basis record, and `freq` is replaced wholesale
by the stage-2 frequency pass — so an accept's status is always "sanctioned".

Two record shapes meet here, and the mapping between them lives in one place:

  canonical   the ReadLex on-disk shape: Latn/Shaw/pos/ipa/freq/var (+provenance).
              What the basis holds and the applicator emits.
  record      the patch/UI shape: word/shaw/pos/ipa/freq/var/status (+provenance).
              What the editor displays and an authorship patch's `changes` holds.
"""

import json
import os
import sys
from pathlib import Path

from dialect_mergers import MERGER_TRAP_BATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UPSTREAM_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"

# The MUTABLE data clone. Everything writable (the patch stores, readlex.json,
# the combined supplement, the definitions corpora) resolves under here; the
# read-only basis under external/ stays on PROJECT_ROOT. Defaults to the in-repo
# data/ (laptop/dev); a deploy sets SHAW_SPELL_DATA_DIR (systemd:
# /var/lib/shaw-spell/data) to relocate the clone wholesale.
DATA_ROOT = (Path(os.environ["SHAW_SPELL_DATA_DIR"]).resolve()
             if os.environ.get("SHAW_SPELL_DATA_DIR")
             else PROJECT_ROOT / "data")

# The ONE pool that makes up the basis: the phrase-filtered view of the
# SOURCE-COMBINED, merger-classified pool (combine -> defs-annotated -> deduped
# -> classified -> collapsed -> decontaminated -> filtered; see the supplement
# pruning chain). Upstream ReadLex core and the per-source wordnet and
# wiktionary pools
# are unified up front (combine_supplements.py) so every prune runs on the union;
# candidates an established entry already resolves to, identical-spelling dialect
# variants (collapsed onto the highest-precedence var), candidates whose Shavian
# carries a non-Shavian character (unmapped IPA passthrough), or sum-of-parts
# phrase noise, are dropped upstream, so the basis — and thus the editor's review
# surface — never sees them. Core records ride the chain untouched (never
# dropped, relabelled or flag-mutated; see is_upstream), so every upstream
# anchor appears here exactly once — the basis's ONLY union point. Each record
# carries its `mergers` annotation, its
# `source` list (the origins that attested its anchor), and its `has_definition`
# provenance boolean (whether any attesting source carries a definition).
SUPPLEMENT_PATHS = [
    DATA_ROOT / "supplement-combined-filtered.json",
]

# ReadLex's read-only `var: "TrapBath"` records ARE the trap-bath-merged form. The
# dialect model separates base accent from merger, so the pipeline reinterprets
# them at consumption (ReadLex is a read-only submodule): base accent RRP, with
# the merger carried in the additive `mergers` field. This is the one intended
# break from the old scalar-var shape.
UPSTREAM_MERGER_VAR = "TrapBath"
UPSTREAM_MERGER_BASE = "RRP"

# ReadLex's read-only `var: "RRPVar"`/`"RRPvar"` records (both casings occur
# upstream) are free-variation alternate spellings within RRP — same accent, not
# the canonical spelling. The dialect model separates base accent from that
# marker, so the pipeline reinterprets them at the same seam: base accent RRP,
# with the alternate carried in the additive boolean `variant` field.
UPSTREAM_VARIANT_VARS = ("RRPVar", "RRPvar")
UPSTREAM_VARIANT_BASE = "RRP"

# An upstream var typo: two dugong records carry "Gen Am" (with a space) for the
# canonical GenAm accent. Normalised at the same consumption seam so the anchor
# identity (which includes var) is consistent wherever the pipeline reads ReadLex.
UPSTREAM_VAR_TYPO = "Gen Am"
UPSTREAM_VAR_TYPO_FIX = "GenAm"

# Upstream ReadLex is the sanctioned dictionary; every record loaded from it
# carries this origin. Combine collates core into the pool under this label
# (first in source precedence, so core wins content on a same-anchor collision),
# and it doubles as the not-new novelty marker: the editor's novelty facet
# classifies a `readlex`-sourced row as known, never new-*. Supplement records
# carry their own `source` list (the origins that attested the anchor), written
# by the combine + prune chain.
UPSTREAM_SOURCE = "readlex"


def is_upstream(entry):
    """Whether a pool/basis record is upstream ReadLex core: collated into the
    combined pool at combine time under the `readlex` source label (see
    combine_supplements.SOURCES). The single upstream test every pipeline stage
    shares. Core records are pre-accepted reference data: a stage may READ them
    (occupancy lanes, established scopes, canonical attestations) and may UNION
    attestation onto them (source labels, has_definition), but must never drop,
    relabel, respell, or flag-mutate one."""
    return UPSTREAM_SOURCE in (entry.get("source") or ())

# A GENERAL-PURPOSE informational field: a catch-all list of non-essential
# metadata strings that rides end-to-end from a supplement source to the basis and
# editor (its first intended use is Wiktionary quality tags — obsolete/dialectal/
# dated… — but it holds any informational label). A LIST like `mergers`/`source`,
# so tags accumulate and round-trip uniformly. Additive: absent means "no info",
# and a record without it behaves exactly as before. Deliberately NOT the patch
# `note` (which is patch metadata, never emitted): this is a RECORD field, DERIVED
# and read-only (not in INTRINSIC_FIELDS), surfaced but never an editable patch field.
INFO_FIELD = "info"

# Provenance fields a record may carry beyond the canonical core, in output
# order. `note` is patch metadata and is deliberately NOT emitted to the
# dictionary. `status` lives in the record because downstream consumers read it.
# The rrp_* fields are the RRP reclassifier's review-triage provenance
# (reclassify_rrp.py): rrp_outcome (PASS/PASS_RESPELL/STAY/REVIEW/SKIP_MERGER),
# rrp_tier (A..F confidence), rrp_review (True on a low-confidence flag). The
# generated_* fields are the RRP generator's PROPOSE-ALONGSIDE provenance
# (generate_rrp.py): generated_shaw (a minted RRP spelling proposed BESIDE the
# record's own Shaw, never overwriting it), generated_tier (A..F), generated_method
# ("ipa-converter"), generated_from (lineage/witnesses), generated_flags (a gated
# site). merger_gate records a D3 flag-strip (which flag was removed and why the
# canonical counterpart was not high-confidence). Like source/ipa_source they are
# all DERIVED — carried through so the editor can surface and sort the review pool,
# never an editable patch field (not in INTRINSIC_FIELDS).
PROVENANCE_FIELDS = ["confidence", "source", "status", "ipa_source",
                     "rrp_outcome", "rrp_tier", "rrp_review",
                     "generated_shaw", "generated_tier", "generated_method",
                     "generated_from", "generated_flags", "merger_gate"]

# ORIGINAL-VALUE provenance (orig_*): the pre-transform value of a key field a
# pipeline transform CHANGED. The natural key is (word, pos, shaw, var), so any
# transform that rewrites `var` (the identical-dialect collapse) or respells
# `shaw` (a forthcoming RRP classifier) moves a record's key and ORPHANS every
# editorial patch anchored to the old key. Recording the pre-image lets the
# applicator AUTO-RE-ANCHOR such a patch (see reanchor_index / apply_patches):
# a transformed record still carries the key its patch was written against.
#
# Additive, like `mergers`/`variant`: a field is present only when that field was
# actually changed, and absent means "unchanged" — a record without any orig_*
# behaves exactly as before this convention existed (backward-compatible).
#
# SET-ONCE (FIRST pre-image wins). A patch is anchored against the value the
# owner reviewed — the ORIGINAL, before ANY transform touched it. So a second
# transform that changes the same field again must NOT overwrite an existing
# orig_*: mark_original is a no-op when the field is already recorded. orig_*
# always holds the earliest pre-image, which is the anchor a patch resolves to.
#
# DERIVED, never owner-editable: orig_* is set by transforms, so it is excluded
# from INTRINSIC_FIELDS (a patch's `changes` may not carry it) — but it is carried
# through the record <-> output mappings like `mergers` so it survives to the basis
# where the applicator reads it. The field it shadows -> the orig key it records:
ORIG_FIELDS = {"var": "orig_var", "shaw": "orig_shaw", "ipa": "orig_ipa"}

# A patch's operation. An accept sanctions the anchored basis record (with any
# intrinsic edits in `changes`); a drop removes it; a flag is a production no-op.
OP_ACCEPT = "accept"
OP_DROP = "drop"
OP_FLAG = "flag"
# An edit persisted on navigate but not yet accepted — DIRTY. It carries the
# field changes (so they are not lost) but is reviewed=False and ships nothing;
# pressing Accept rewrites it as OP_ACCEPT. No legacy patch is op="edit".
OP_EDIT = "edit"

# The intrinsic, human-editable fields — the ONLY keys a patch's `changes` may
# carry. Everything else (source, confidence, freq, status) is DERIVED at apply:
# source from the basis origin map, confidence from the basis record, freq from
# the stage-2 frequency pass, and status is implied by the op (accept ->
# "sanctioned"). Storing any of them in `changes` would freeze a value the
# pipeline recomputes.
INTRINSIC_FIELDS = ("word", "shaw", "pos", "ipa", "var", "mergers", "variant")

# The status every accepted record carries. An accept IS a sanction; the old
# finer statuses (new / pos-gap / supplement / pos-gap-shifted) collapse to this
# one, so the operation alone determines status — it is never stored in a patch.
ACCEPTED_STATUS = "sanctioned"

# resolve_patch's sentinel for a flag: the anchored basis record is left exactly
# as upstream had it (no removal, no re-emit). Distinct from None, which a drop
# returns to mean "emit nothing".
PATCH_NOOP = object()

# resolve_patch's sentinel for an accept whose anchor no longer resolves against
# the basis (upstream drifted since the decision was made). The applicator soft-
# fails on it — logs and skips it, retaining the patch in the store — and the
# editor overlay surfaces it as an `orphaned` pseudo-row for the owner to re-anchor
# or discard. Never a silent drop or a stale snapshot.
PATCH_ORPHAN = object()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def reinterpret_upstream(entry):
    """Map a raw upstream ReadLex entry onto the dialect model, in place. A
    `var: "TrapBath"` record is the trap-bath-merged form: its base accent is RRP
    and the merger moves to the additive `mergers` field. A `var: "RRPVar"`/
    `"RRPvar"` record is a free-variation alternate spelling within RRP: its base
    accent is RRP and the alternate moves to the additive boolean `variant` field.
    A `var: "Gen Am"` record carries an upstream typo for the canonical GenAm
    accent, corrected here. Every other entry is returned untouched. The single
    reinterpretation shared by the basis loader and the applicator, so the anchor
    identity (which includes var) is consistent wherever the pipeline consumes
    ReadLex."""
    if entry.get("var") == UPSTREAM_MERGER_VAR:
        entry["var"] = UPSTREAM_MERGER_BASE
        entry["mergers"] = [MERGER_TRAP_BATH]
    elif entry.get("var") in UPSTREAM_VARIANT_VARS:
        entry["var"] = UPSTREAM_VARIANT_BASE
        entry["variant"] = True
    elif entry.get("var") == UPSTREAM_VAR_TYPO:
        entry["var"] = UPSTREAM_VAR_TYPO_FIX
    return entry


def load_upstream():
    """Upstream ReadLex with its TrapBath records reinterpreted onto the dialect
    model (see reinterpret_upstream). The shape every pipeline reader sees."""
    data = load_json(UPSTREAM_PATH)
    for entries in data.values():
        for entry in entries:
            reinterpret_upstream(entry)
    return data


def anchor_of(entry):
    """The natural key of a canonical basis record: (word_lower, pos, shaw, var).
    Records identical but for var are distinct facts, so var is in the key."""
    return (entry.get("Latn", "").lower(), entry.get("pos", ""),
            entry.get("Shaw", ""), entry.get("var", ""))


def anchor_key(anchor):
    """The (word_lower, pos, shaw, var) a patch's `anchor` resolves against — the
    single derivation shared by the applicator, the overlay and the patch store."""
    return (anchor["word"].lower(), anchor["pos"], anchor["shaw"], anchor["var"])


# The canonical-entry (Latn/Shaw/...) field a transform changes, and the natural-
# key slot it occupies. mark_original works on the canonical shape because that is
# what pipeline transforms (collapse_identical_dialects, a future classifier) read
# and write. `ipa` shadows no key slot — orig_ipa is pure visibility, never a
# re-anchor axis (ipa is not in the anchor key).
_ORIG_ENTRY_FIELD = {"var": "var", "shaw": "Shaw", "ipa": "ipa"}


def mark_original(entry, field, old_value):
    """Record `old_value` as the pre-transform value of `field` on a canonical
    basis `entry`, in place — the shared way a transform preserves what it changed
    (see ORIG_FIELDS). `field` is one of "var" / "shaw" / "ipa".

    Call it AFTER updating the field: `entry["var"] = new; mark_original(entry,
    "var", old)`. It records `old_value` under orig_<field> unless one of two guards
    applies:

      SET-ONCE — if the entry already carries orig_<field> (an earlier transform
      changed it first), this is a NO-OP. The earliest pre-image is the one a patch
      was anchored against, so a later transform never overwrites it. orig_<field>
      always holds the value the field started at.

      NO-CHANGE — if old_value equals the value now on the entry, nothing changed,
      so no orig_<field> is planted. This keeps the field additive: orig_<field> is
      present iff the field genuinely differs from where it started.

    Fails loud on an unknown field rather than silently mis-recording provenance."""
    orig_key = ORIG_FIELDS.get(field)
    if orig_key is None:
        raise ValueError(f"mark_original: {field!r} is not an orig-tracked field "
                         f"(one of {sorted(ORIG_FIELDS)})")
    if orig_key in entry:
        return  # set-once: keep the FIRST pre-image (the patch anchor's value)
    if entry.get(_ORIG_ENTRY_FIELD[field], "") == old_value:
        return  # no genuine change; stay additive
    entry[orig_key] = old_value


def reanchor_index(basis_index):
    """Map every recoverable OLD natural key to the CURRENT key of the basis record
    that carries it — the auto-re-anchor lookup the applicator consults before
    soft-failing an orphaned patch.

    A basis record that a transform rewrote carries the pre-image of what changed
    in orig_var / orig_shaw (orig_ipa is not a key axis, so it is ignored here).
    Reconstructing the key the record had BEFORE the transform — its current key
    with the changed slot(s) swapped back to the orig value — yields the exact key
    a patch was anchored against. That old key maps to the record's current key, so
    an orphaned anchor matching it re-anchors to where the record lives now.

    Only records carrying an orig_* key contribute (an untouched record's key never
    moved, so it needs no redirect). A collision — two records both claiming the
    same old key — cannot be resolved to one target, so it is dropped from the index
    (the patch stays orphaned and is surfaced, never silently mis-applied)."""
    old_to_current = {}
    collided = set()
    for current_key, entry in basis_index.items():
        old_key = _pre_transform_key(current_key, entry)
        if old_key == current_key:
            continue  # no key-moving orig_* on this record
        if old_key in old_to_current or old_key in collided:
            collided.add(old_key)
            old_to_current.pop(old_key, None)
            continue
        old_to_current[old_key] = current_key
    return old_to_current


def _pre_transform_key(current_key, entry):
    """The natural key `entry` had before its key-moving transforms — its current
    key with each orig-tracked key slot (shaw, var) swapped back to the recorded
    pre-image. Slots without an orig_* are left as-is. Equal to current_key when the
    record carries no key-moving orig_*."""
    word, pos, shaw, var = current_key
    if "orig_shaw" in entry:
        shaw = entry["orig_shaw"]
    if "orig_var" in entry:
        var = entry["orig_var"]
    return (word, pos, shaw, var)


def anchor_from_key(key):
    """A patch-anchor dict {word, pos, shaw, var} for a natural key tuple — the
    inverse of anchor_key. Used to re-point an orphaned patch's anchor at the
    current key of the record that now carries its pre-image."""
    word, pos, shaw, var = key
    return {"word": word, "pos": pos, "shaw": shaw, "var": var}


def reanchor_patch(patch, reanchor_map):
    """A copy of an orphaned `patch` re-pointed at the CURRENT key of the record
    carrying its pre-image, or None if no orig_* record covers its anchor.

    The applicator's FIRST resort for an anchor that no longer resolves against the
    basis: a key-moving transform (var relabel, respell) rewrote the record but
    preserved its old key in orig_* (see reanchor_index / mark_original), so the
    old key the patch was anchored against maps to where the record lives now. The
    returned patch has the SAME op/changes/id/meta — only its anchor moves, and only
    in memory for this apply. The store on disk is never rewritten (the transforms
    carry orig_* forward, so re-anchoring is recomputed every apply, not persisted).

    None when the anchor's old key is absent from the map (no record preserved this
    pre-image, or a collision dropped it) — the caller then soft-fails as before."""
    current_key = reanchor_map.get(anchor_key(patch["anchor"]))
    if current_key is None:
        return None
    return {**patch, "anchor": anchor_from_key(current_key)}


def is_flag_patch(patch):
    """Whether a patch is a FLAG — "looked at, no verdict yet". A flag leaves the
    anchored basis record untouched; it counts as reviewed (leaves the unreviewed
    pool) but is NOT an editorial change, so the applicator treats it as a no-op.
    The single definition shared by the overlay and the applicator."""
    return patch.get("op") == OP_FLAG


def is_dirty_patch(patch):
    """Whether a patch is DIRTY — an EDIT persisted on navigate but not yet
    accepted. An op="edit" patch carries the field changes so they are not lost,
    but the record is NOT reviewed (acceptance is explicit) and its changes do NOT
    ship: reviewed=False in the overlay, a production no-op in the applicator.
    Pressing Accept rewrites it as op="accept", promoting it to edited/accepted.
    No legacy patch carries op="edit" (they are accept/drop/flag/None), so
    migration is a no-op. Shared by the overlay's state derivation and the
    applicator."""
    return patch.get("op") == OP_EDIT


def record_to_output(record):
    """The canonical dictionary entry (Latn/Shaw/...) for a resolved `record`
    (word/shaw/...). The single UI-shape → canonical mapping shared by the
    applicator (which writes it to data/readlex.json) and the overlay (which
    round-trips display records)."""
    entry = {
        "Latn": record["word"],
        "Shaw": record["shaw"],
        "pos": record["pos"],
        "ipa": record.get("ipa", ""),
        "freq": record.get("freq", 0),
        "var": record.get("var", ""),
    }
    if record.get("mergers"):
        entry["mergers"] = record["mergers"]
    if record.get("variant"):
        entry["variant"] = record["variant"]
    if record.get("has_definition"):
        entry["has_definition"] = record["has_definition"]
    if record.get(INFO_FIELD):
        entry[INFO_FIELD] = record[INFO_FIELD]
    for orig_key in ORIG_FIELDS.values():
        if orig_key in record:
            entry[orig_key] = record[orig_key]
    for field in PROVENANCE_FIELDS:
        if record.get(field) not in (None, ""):
            entry[field] = record[field]
    return entry


def output_to_record(entry):
    """The patch/UI `record` shape for a canonical basis entry — the inverse of
    record_to_output. What an untouched basis candidate looks like as a record."""
    record = {
        "word": entry.get("Latn", ""),
        "shaw": entry.get("Shaw", ""),
        "pos": entry.get("pos", ""),
        "ipa": entry.get("ipa", ""),
        "freq": entry.get("freq", 0),
        "var": entry.get("var", ""),
    }
    if entry.get("mergers"):
        record["mergers"] = entry["mergers"]
    if entry.get("variant"):
        record["variant"] = entry["variant"]
    if entry.get("has_definition"):
        record["has_definition"] = entry["has_definition"]
    if entry.get(INFO_FIELD):
        record[INFO_FIELD] = entry[INFO_FIELD]
    for orig_key in ORIG_FIELDS.values():
        if orig_key in entry:
            record[orig_key] = entry[orig_key]
    for field in PROVENANCE_FIELDS:
        if entry.get(field) not in (None, ""):
            record[field] = entry[field]
    return record


def effective_record(base_entry, changes, source):
    """The resolved UI-shape record for an ACCEPTED anchor: the basis record
    (`base_entry`, canonical shape) turned back into a record, with the patch's
    intrinsic `changes` laid over it, its origin-derived `source`, the basis
    record's confidence carried through, and status set to the sanction.

    The single overlay layering shared by the applicator (resolve_patch, which
    canonicalises this for readlex.json) and the overlay (which shows it in the
    UI): one definition of "accept = basis + edits", so the two can never drift."""
    record = output_to_record(base_entry)
    record.update(changes)
    record["source"] = source
    if "confidence" in base_entry:
        record["confidence"] = base_entry["confidence"]
    record["status"] = ACCEPTED_STATUS
    return record


def resolve_patch(patch, basis_index, basis_source):
    """The canonical dictionary entry a patch resolves to over the LIVE basis, or
    a sentinel the caller acts on. The single applied-shape resolution shared by
    the applicator and the overlay — the one place the patch model is interpreted.

      op flag                 PATCH_NOOP: production no-op. For an anchored flag
                              the basis record is left as-is; for an authored
                              flag (anchor null) the authored record is NOT
                              emitted — a flag is "no verdict yet" either way.
      anchor null (authored)  record_to_output(changes): `changes` is the whole
                              self-contained record (no basis to diff against).
      op drop                 None: emit nothing for the anchored key.
      op accept               record_to_output(effective_record(...)): the basis
                              record with the intrinsic `changes` laid over it,
                              sanctioned. If the anchor no longer resolves against
                              the basis, PATCH_ORPHAN — the applicator soft-fails
                              (logs + skips + retains) and the editor surfaces it."""
    # A flag is "looked at, no verdict yet" whether the row is a basis candidate
    # or an authored one — in both cases nothing reaches production, so this test
    # precedes the authored/anchored split.
    if is_flag_patch(patch):
        return PATCH_NOOP

    # A DIRTY patch (op="edit", edited but not yet accepted) is not shippable: its
    # edits are persisted in the store but withheld from production until Accept
    # rewrites it as op="accept", so the record ships in its unpatched form — a
    # no-op, exactly like a flag. Legacy patches are never op="edit", so they ship
    # as before. The test precedes the authored/anchored split: an authored dirty
    # edit (were one ever minted) is equally unshippable.
    if is_dirty_patch(patch):
        return PATCH_NOOP

    if patch["anchor"] is None:
        return record_to_output(patch["changes"])

    op = patch["op"]
    if op == OP_DROP:
        return None
    if op != OP_ACCEPT:
        raise ValueError(f"unknown patch op: {op!r}")

    key = anchor_key(patch["anchor"])
    base_entry = basis_index.get(key)
    if base_entry is None:
        return PATCH_ORPHAN
    return record_to_output(
        effective_record(base_entry, patch["changes"], basis_source[key]))


def enrich_basis_frequency(index):
    """Put every basis record on the corpus frequency scale, in place — the SAME
    replace-all pass the production build applies to readlex.json (see
    apply_frequency_data.enrich_entry), so a review-pool candidate carries the
    exact freq the record it becomes will ship with. Reuses the corpus + UK/US
    variant logic rather than reimplementing it.

    The imports are function-local: apply_frequency_data imports PROJECT_ROOT from
    this module, so a module-level import here would be a cycle.

    Corpus-absent is the ONE justified graceful skip: the editor must start on a
    fresh clone (before `make setup`) even without frequency data. Production's
    apply_frequency_data still fails loud on a missing corpus — this skip only
    spares the editor, and is logged so a silent freq-0 basis is never a mystery.
    """
    from apply_frequency_data import CORPUS_PATH, enrich_all, load_corpus

    if not CORPUS_PATH.exists():
        print(f"basis: frequency corpus absent ({CORPUS_PATH.name}); "
              "review-pool candidates carry no freq. Run `make setup`.",
              file=sys.stderr)
        return
    enrich_all({None: list(index.values())}, load_corpus())


def build_basis(enrich_freq=False):
    """Traverse the basis once, returning both the record index and the origins
    of each anchor.

      index   (word_lower, pos, shaw, var) -> the basis candidate. The pool is
              the single union point: upstream ReadLex core rides IN it (collated
              at combine, first in source precedence, so a core record wins
              content on a same-anchor collision) — it is NOT unioned in again
              here, so every upstream anchor appears exactly once.
      source  same key -> ordered list of the origin labels that attested it,
              deduped, read straight off each record's `source` list (the union
              the combine + collapse chain recorded for that anchor). A core
              record contributes the readlex label this way — the multi-source
              agreement signal, preserved for filtering.

    With enrich_freq, every record is put on the corpus frequency scale so the
    editor's freq-desc sort triages the review pool by real frequency, uniformly
    with production. The applicator does not emit basis freq (it enriches its
    merged output separately) so it leaves this off — paying neither the corpus
    load nor the pass.
    """
    index = {}
    source = {}
    for source_path in SUPPLEMENT_PATHS:
        data = load_json(source_path)
        for entries in data.values():
            for entry in entries:
                key = anchor_of(entry)
                index.setdefault(key, entry)
                sources = source.setdefault(key, [])
                for label in entry.get("source", []):
                    if label not in sources:
                        sources.append(label)
    if enrich_freq:
        enrich_basis_frequency(index)
    return index, source


def build_basis_index():
    """The basis record index alone (the applicator does not need origins)."""
    return build_basis()[0]
