#!/usr/bin/env python3
"""
ONE-OFF: split the merged Shavian definitions corpus into a Latin source-of-truth
and a Shavian derived transliteration file.

Background. data/definitions-shavian-{gb,us}.json historically embedded BOTH the
English source gloss AND its Shavian transliteration per record. The separate
data/definitions-latin-{gb,us}.json had DRIFTED into unrelated lemma-keyed junk. The
owner's decision (Option 2): the merged Shavian file already carries the complete,
correctly-keyed Latin source, so carve it out ONCE — no re-transliteration, ever —
to establish the honest layering going forward:

    definitions-latin-{gb,us}.json     the SOURCE  (English gloss/pos/examples)
    definitions-shavian-{gb,us}.json    DERIVED     (Shavian transliteration only)

Both keyed identically on `lemma|synset`. This is pure JSON reshaping on data already
on disk: it NEVER invokes shave. After this split, the Shavian file DERIVES from the
Latin file via one straight-through transliterate-all pass
(src/dictionaries/build_definition_caches.py).

Record split (per key, per dialect):
    Latin (source):   {definition, pos, examples[, source][, confidence]}
    Shavian (derived): {transliterated_definition, transliterated_pos,
                        transliterated_examples}

`source`/`confidence` are source annotations the gap pass added (present only on gap
entries); they ride with the Latin source. Every field is accounted for: the union of
the two output records reproduces the input record exactly (asserted).

Output is deterministically key-sorted (byte-idempotent). This tool is idempotent
against its own outputs is NOT a goal — it consumes the merged Shavian file; run it
once, review, commit, then this tool is spent.

Usage:
    python3 src/tools/split_definition_corpus.py [--dry-run]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from basis import PROJECT_ROOT

DATA = PROJECT_ROOT / "data"

# The source (Latin) fields and the derived (Shavian) fields. Optional source
# annotations (source, confidence) are carried only when present on the record.
LATIN_FIELDS = ("definition", "pos", "examples")
LATIN_OPTIONAL = ("source", "confidence")
SHAVIAN_FIELDS = ("transliterated_definition", "transliterated_pos",
                  "transliterated_examples")


def split_record(key, record):
    """Carve one merged record into (latin, shavian). Fails LOUD if a required field
    is missing or an unexpected field appears — the split must be total and lossless,
    never silently dropping data."""
    seen = set(record)
    expected = set(LATIN_FIELDS) | set(LATIN_OPTIONAL) | set(SHAVIAN_FIELDS)
    unexpected = seen - expected
    if unexpected:
        raise ValueError(f"{key}: unexpected fields {sorted(unexpected)} — refusing "
                         "to drop data in the split")

    latin = {}
    for field in LATIN_FIELDS:
        if field not in record:
            raise ValueError(f"{key}: missing required source field {field!r}")
        latin[field] = record[field]
    for field in LATIN_OPTIONAL:
        if field in record:
            latin[field] = record[field]

    shavian = {}
    for field in SHAVIAN_FIELDS:
        if field not in record:
            raise ValueError(f"{key}: missing required derived field {field!r}")
        shavian[field] = record[field]

    return latin, shavian


def split_dialect(dialect, dry_run):
    merged_path = DATA / f"definitions-shavian-{dialect}.json"
    latin_path = DATA / f"definitions-latin-{dialect}.json"
    shavian_path = DATA / f"definitions-shavian-{dialect}.json"  # rewritten derived

    with open(merged_path, "r", encoding="utf-8") as f:
        merged = json.load(f)
    print(f"[{dialect.upper()}] merged corpus: {len(merged):,} keys")

    latin, shavian = {}, {}
    for key, record in merged.items():
        latin[key], shavian[key] = split_record(key, record)

    # Deterministic, byte-idempotent output.
    latin_text = json.dumps(latin, ensure_ascii=False, indent=2, sort_keys=True)
    shavian_text = json.dumps(shavian, ensure_ascii=False, indent=2, sort_keys=True)

    if dry_run:
        print(f"[{dialect.upper()}] --dry-run: not writing "
              f"{latin_path.name} / {shavian_path.name}")
        return

    with open(latin_path, "w", encoding="utf-8") as f:
        f.write(latin_text)
    with open(shavian_path, "w", encoding="utf-8") as f:
        f.write(shavian_text)
    print(f"[{dialect.upper()}] wrote {latin_path.relative_to(PROJECT_ROOT)} "
          f"({len(latin):,} keys) + {shavian_path.relative_to(PROJECT_ROOT)} "
          f"({len(shavian):,} keys)")


def main():
    dry_run = "--dry-run" in sys.argv
    for dialect in ("gb", "us"):
        split_dialect(dialect, dry_run)
    print("\nDone." + (" (dry run — no files written)" if dry_run else ""))


if __name__ == "__main__":
    main()
