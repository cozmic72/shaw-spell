#!/usr/bin/env python3
"""
Annotate each combined supplement record with `has_definition`: whether a
DISPLAYABLE definition exists for the record's word. Absence of a definition is
a real signal (a bare pronunciation with no gloss), so the editor surfaces
has/no-definition as a pill and a filter facet.

The predicate tests the shipped definition ARTIFACT itself —
data/definitions-latin-{gb,us}.json, the committed source of truth the editor
(editor/definitions.py) and the dictionary export actually display from — NOT
the upstream WordNet YAML / Wiktionary JSONL. Testing the upstream sources
over-claimed: a gloss present upstream but absent from the artifact flagged
has_definition with nothing to show. Artifact membership is drift-proof by
construction: the flag is true iff an entry exists in what ships.
(complete_definition_corpus.py is the manual tool that fills the artifact from
the upstream gloss sources.)

Membership is LEMMA-LEVEL: the artifact is keyed `lemma|synset` and the editor
looks definitions up by lowercased headword alone (no POS), so the flag matches
the display exactly. The artifact's own pos tags (WordNet letters, wikt strings)
are not comparable to the records' C5 tags, and comparing them would only make
the flag stricter than what is actually shown. Source attestation is likewise
not consulted: whatever source produced the record, the editor will display the
artifact's entry for its headword.

This is a SEPARATE annotation pass, NOT a change to the -reliable generators.
It runs directly after combine_supplements.py, on the source-combined pool, so
the field rides verbatim through the rest of the pruning chain (dedup ->
classify -> collapse -> decontaminate -> filter) into the editorial basis. (The
one later union point — the identical-dialect collapse in
collapse_identical_dialects.py — ORs the flag alongside its source union; a
word-level predicate is invariant under that merge.)

Inputs:  data/supplement-combined-raw.json (combine output),
         data/definitions-latin-{gb,us}.json (the definition artifact).
Output:  data/supplement-combined-defs.json — the dedup filter reads this next.

Usage:
    python3 src/tools/annotate_definitions.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from basis import PROJECT_ROOT

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-raw.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-defs.json"

LATIN_DEF_PATHS = (PROJECT_ROOT / "data" / "definitions-latin-gb.json",
                   PROJECT_ROOT / "data" / "definitions-latin-us.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_def_lemmas():
    """The set of lowercased headwords the definition artifact carries an entry
    for, from both dialect files (their key sets are identical today; the union
    keeps the flag honest — displayable in SOME dialect — if they ever drift).
    Keys are `lemma|synset`; fails loud on a malformed key rather than silently
    mis-indexing (same guard as editor/definitions.py)."""
    lemmas = set()
    for path in LATIN_DEF_PATHS:
        for key in load_json(path):
            word, sep, _ = key.partition("|")
            if not sep or not word:
                raise ValueError(f"{path.name}: malformed definition key {key!r}")
            lemmas.add(word.lower())
    return lemmas


def annotate(supplement, def_lemmas, tallies=None):
    """Set `has_definition` on every record: true iff the definition artifact
    has an entry for the record's lowercased word — exactly what the editor and
    the shipped dictionaries can display. Mutates records in place; returns the
    supplement."""
    if tallies is None:
        tallies = Counter()
    for entries in supplement.values():
        for entry in entries:
            has_def = entry["Latn"].lower() in def_lemmas
            entry["has_definition"] = has_def
            tallies["has_definition" if has_def else "no_definition"] += 1
    return supplement


def report(tallies):
    print("\n=== definition annotation report ===")
    print(f"has_definition:  {tallies['has_definition']:,}")
    print(f"no_definition:   {tallies['no_definition']:,}")


def main():
    tallies = Counter()

    supplement = load_json(INPUT_PATH)
    print("Indexing the definition artifact...")
    def_lemmas = build_def_lemmas()
    print(f"  artifact headwords with a definition: {len(def_lemmas):,}")

    annotate(supplement, def_lemmas, tallies)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(supplement, f, ensure_ascii=False, indent=4)
    print(f"\nWrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in supplement.values()):,} records")

    report(tallies)


if __name__ == "__main__":
    main()
