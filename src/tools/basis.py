#!/usr/bin/env python3
"""
The editorial BASIS: the raw combination of all upstream sources, computed
on-demand and indexed by the natural key a patch's anchor resolves against.

This is the single implementation of the anchor/basis logic shared by the
applicator (src/tools/apply_patches.py, which emits data/readlex.json) and the
editor daemon (src/editor/editord.py, which annotates the basis with each
record's patch-state). Neither keeps its own copy — see
docs/editorial-overlay-design.md.

  - The basis is upstream ReadLex (external/readlex/readlex.json) plus the
    wordnet and wiktionary supplement candidates. Every candidate, including
    the unreviewed supplemental ones, is a record in the basis. Nothing is
    frozen.
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
import sys
from pathlib import Path

from dialect_mergers import MERGER_TRAP_BATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UPSTREAM_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"

# Supplement candidate sources that make up the basis alongside upstream ReadLex.
# These are the PHRASE-FILTERED views of the merger-classified candidates
# (reliable -> deduped -> classified -> collapsed -> filtered; see the supplement
# pruning chain): candidates an established entry already resolves to, identical-
# spelling dialect variants (collapsed to one RRP record), or sum-of-parts phrase
# noise, are dropped upstream, so the basis — and thus the editor's review
# surface — never sees them. Each record carries its `mergers` annotation.
SUPPLEMENT_PATHS = [
    PROJECT_ROOT / "data" / "supplement-wordnet-filtered.json",
    PROJECT_ROOT / "data" / "supplement-wiktionary-filtered.json",
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

# The record's origin, derived from which basis file supplied it. Upstream
# ReadLex is the sanctioned dictionary; the supplements are candidates.
UPSTREAM_SOURCE = "readlex"
SUPPLEMENT_SOURCES = {
    "supplement-wordnet-filtered.json": "wordnet",
    "supplement-wiktionary-filtered.json": "wiktionary",
}

# Provenance fields a record may carry beyond the canonical core, in output
# order. `note` is patch metadata and is deliberately NOT emitted to the
# dictionary. `status` lives in the record because downstream consumers read it.
PROVENANCE_FIELDS = ["confidence", "source", "status", "ipa_source"]

# A patch's operation. An accept sanctions the anchored basis record (with any
# intrinsic edits in `changes`); a drop removes it; a flag is a production no-op.
OP_ACCEPT = "accept"
OP_DROP = "drop"
OP_FLAG = "flag"

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
# the basis (upstream drifted since the decision was made). The caller surfaces
# it as an orphan and fails loud — never a silent drop or a stale snapshot.
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


def is_flag_patch(patch):
    """Whether a patch is a FLAG — "looked at, no verdict yet". A flag leaves the
    anchored basis record untouched; it counts as reviewed (leaves the unreviewed
    pool) but is NOT an editorial change, so the applicator treats it as a no-op.
    The single definition shared by the overlay and the applicator."""
    return patch.get("op") == OP_FLAG


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
                              the basis, PATCH_ORPHAN — the caller fails loud."""
    # A flag is "looked at, no verdict yet" whether the row is a basis candidate
    # or an authored one — in both cases nothing reaches production, so this test
    # precedes the authored/anchored split.
    if is_flag_patch(patch):
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


def basis_source(path):
    """The origin label for records loaded from a basis file."""
    if path == UPSTREAM_PATH:
        return UPSTREAM_SOURCE
    source = SUPPLEMENT_SOURCES.get(path.name)
    if source is None:
        raise ValueError(f"unknown basis source file: {path}")
    return source


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
    """Traverse the basis once, returning both the record index and the origin
    of each anchor.

      index   (word_lower, pos, shaw, var) -> the basis candidate. Upstream
              ReadLex is seen first and wins over a supplement that attests the
              same natural key.
      source  same key -> origin label.

    With enrich_freq, every record is put on the corpus frequency scale so the
    editor's freq-desc sort triages the review pool by real frequency, uniformly
    with production. The applicator does not emit basis freq (it enriches its
    merged output separately) so it leaves this off — paying neither the corpus
    load nor the pass.
    """
    index = {}
    source = {}
    for source_path in [UPSTREAM_PATH, *SUPPLEMENT_PATHS]:
        label = basis_source(source_path)
        data = (load_upstream() if source_path == UPSTREAM_PATH
                else load_json(source_path))
        for entries in data.values():
            for entry in entries:
                key = anchor_of(entry)
                index.setdefault(key, entry)
                source.setdefault(key, label)
    if enrich_freq:
        enrich_basis_frequency(index)
    return index, source


def build_basis_index():
    """The basis record index alone (the applicator does not need origins)."""
    return build_basis()[0]
