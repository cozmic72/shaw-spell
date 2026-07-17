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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
UPSTREAM_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"

# Supplement candidate sources that make up the basis alongside upstream ReadLex.
SUPPLEMENT_PATHS = [
    PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json",
    PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json",
]

# The record's origin, derived from which basis file supplied it. Upstream
# ReadLex is the sanctioned dictionary; the supplements are candidates.
UPSTREAM_SOURCE = "readlex"
SUPPLEMENT_SOURCES = {
    "supplement-wordnet-reliable.json": "wordnet",
    "supplement-wiktionary-reliable.json": "wiktionary",
}

# Provenance fields a record may carry beyond the canonical core, in output
# order. `note` is patch metadata and is deliberately NOT emitted to the
# dictionary. `status` lives in the record because downstream consumers read it.
PROVENANCE_FIELDS = ["confidence", "source", "status"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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


def build_basis():
    """Traverse the basis once, returning both the record index and the origin
    of each anchor.

      index   (word_lower, pos, shaw, var) -> the basis candidate. Upstream
              ReadLex is seen first and wins over a supplement that attests the
              same natural key.
      source  same key -> origin label.
    """
    index = {}
    source = {}
    for source_path in [UPSTREAM_PATH, *SUPPLEMENT_PATHS]:
        label = basis_source(source_path)
        for entries in load_json(source_path).values():
            for entry in entries:
                key = anchor_of(entry)
                index.setdefault(key, entry)
                source.setdefault(key, label)
    return index, source


def build_basis_index():
    """The basis record index alone (the applicator does not need origins)."""
    return build_basis()[0]
