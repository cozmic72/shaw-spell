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

Two record shapes meet here, and the mapping between them lives in one place:

  canonical   the ReadLex on-disk shape: Latn/Shaw/pos/ipa/freq/var (+provenance).
              What the basis holds and the applicator emits.
  record      the patch/UI shape: word/shaw/pos/ipa/freq/var/status (+provenance).
              What a patch stores and the editor displays. Self-contained — the
              patch's `record` IS the wanted state, emitted verbatim with no merge.
"""

import json
import sys
from pathlib import Path

from dialect_mergers import MERGER_TRAP_BATH

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UPSTREAM_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"

# Supplement candidate sources that make up the basis alongside upstream ReadLex.
# These are the PHRASE-FILTERED views of the merger-classified candidates
# (reliable -> deduped -> classified -> filtered; see the supplement pruning
# chain): candidates an established entry already resolves to, or sum-of-parts
# phrase noise, are dropped upstream, so the basis — and thus the editor's review
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
PROVENANCE_FIELDS = ["confidence", "source", "status"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def reinterpret_upstream(entry):
    """Map a raw upstream ReadLex entry onto the dialect model, in place. A
    `var: "TrapBath"` record is the trap-bath-merged form: its base accent is RRP
    and the merger moves to the additive `mergers` field. Every other entry is
    returned untouched. The single reinterpretation shared by the basis loader and
    the applicator, so the anchor identity (which includes var) is consistent
    wherever the pipeline consumes ReadLex."""
    if entry.get("var") == UPSTREAM_MERGER_VAR:
        entry["var"] = UPSTREAM_MERGER_BASE
        entry["mergers"] = [MERGER_TRAP_BATH]
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
    """Whether a patch is a FLAG — "looked at, no verdict yet". A flag carries the
    source record unchanged with a meta marker; it counts as reviewed (leaves the
    unreviewed pool) but is NOT an editorial change, so the applicator treats it as
    a no-op. The single definition shared by the overlay and the applicator."""
    return bool(patch.get("meta", {}).get("flag"))


def record_to_output(record):
    """The canonical dictionary entry (Latn/Shaw/...) for a patch's complete
    `record` (word/shaw/...). Emitted verbatim — no merge with the source. The
    single UI-shape → canonical mapping shared by the applicator (which writes it
    to data/readlex.json) and the overlay (which round-trips display records)."""
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
    for field in PROVENANCE_FIELDS:
        if entry.get(field) not in (None, ""):
            record[field] = entry[field]
    return record


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
