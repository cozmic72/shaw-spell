#!/usr/bin/env python3
"""
Annotate each combined supplement record with `has_definition`: a PROVENANCE
boolean recording whether the upstream source(s) that produced the candidate
carry a definition for it. Absence of a definition is a real signal (a bare
pronunciation with no gloss), so the editor surfaces has/no-definition as a pill
and a filter facet.

This is a SEPARATE annotation pass, NOT a change to the -reliable generators.
The generators consult the non-deterministic `shave` tool, so re-running them
would re-spell low-confidence records and orphan the owner's patches (see
docs / MEMORY). This pass only READS the same source files the generators read
and JOINS `has_definition` onto EXISTING combined records by (word, pos) — it
re-shaves nothing and touches no anchor field.

It runs directly after combine_supplements.py, on the source-combined pool, so
the field rides verbatim through the rest of the pruning chain (dedup ->
classify -> collapse -> decontaminate -> filter) into the editorial basis. Each
combined record already carries a `source` LIST (the origins that attested its
anchor, unioned by combine). `has_definition` is the LOGICAL OR over that list:
true if ANY attesting source has a definition for the record's (word, pos). A
wordnet-def record and a wiktionary-no-def record that combined onto one anchor
are has_definition=true. (The one later union point — the identical-dialect
collapse in collapse_identical_dialects.py — ORs the flag alongside its source
union, so the OR invariant holds at every merge.)

Definition provenance per source, matching each generator's word/pos keying:
  - WordNet: generate_wordnet_supplement maps a YAML (word, wn_pos) to a record
    keyed (word_lower, c5_pos) via POS_MAP. A wn_pos's pos_data lists `sense`s,
    each pointing at a `synset`; the definition lives in the synset YAML files
    (adj/adv/noun/verb.*.yaml). So (word_lower, c5_pos) has a definition iff some
    wn_pos mapping to that c5_pos has a sense whose synset carries a non-empty
    definition. POS_MAP is many-to-one (a/s -> AJ0), so all contributing wn_pos
    are OR-ed into the c5_pos bucket.
  - Wiktionary: generate_wiktionary_supplement maps a kaikki entry's `pos` to a
    record keyed (word, c5_pos) via its own POS_MAP (defaulting to UNC), skipping
    affix words (leading/trailing hyphen). A (word, c5_pos) has a definition iff
    some matching kaikki entry has a sense with a non-empty gloss. The generators'
    POS_MAP / affix-skip are reused here (imported), not re-implemented, so the
    matching can never drift from what produced the records.

Inputs:  data/supplement-combined-raw.json (combine output),
         external/english-wordnet/src/yaml/ (entry + synset YAML),
         external/wiktionary/kaikki.org-dictionary-English.jsonl.
Output:  data/supplement-combined-defs.json — the dedup filter reads this next.

Usage:
    python3 src/tools/annotate_definitions.py
"""

import json
import sys
from collections import Counter
from glob import glob
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from basis import PROJECT_ROOT
import generate_wordnet_supplement as wordnet_gen
import generate_wiktionary_supplement as wiktionary_gen

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-raw.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-defs.json"

WORDNET_YAML_DIR = PROJECT_ROOT / "external" / "english-wordnet" / "src" / "yaml"
WIKTIONARY_JSONL = (PROJECT_ROOT / "external" / "wiktionary"
                    / "kaikki.org-dictionary-English.jsonl")

# The source labels combine_supplements writes onto each record's `source` list.
SOURCE_WORDNET = "wordnet"
SOURCE_WIKTIONARY = "wiktionary"

# The synset YAML files carry the WordNet definitions (the entry YAML only points
# at synset ids). Same globs as build_wordnet_cache.parse_synset_files.
SYNSET_GLOBS = ("adj.*.yaml", "adv.*.yaml", "noun.*.yaml", "verb.*.yaml")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def synsets_with_definition():
    """The set of synset ids carrying a non-empty definition, read from the synset
    YAML files (adj/adv/noun/verb.*.yaml). The entry YAML only references synsets;
    the definition text lives here."""
    defined = set()
    for pattern in SYNSET_GLOBS:
        for path in sorted(WORDNET_YAML_DIR.glob(pattern)):
            data = yaml.safe_load(open(path, encoding="utf-8"))
            if not data:
                continue
            for synset_id, synset_data in data.items():
                if isinstance(synset_data, dict) and synset_data.get("definition"):
                    defined.add(synset_id)
    return defined


def wordnet_def_keys():
    """The set of (word_lower, c5_pos) the WordNet source carries a definition for.

    Walks the entry YAML exactly as generate_wordnet_supplement does — single-word
    entries, POS_MAP filtering wn_pos to a c5 tag — and marks the key defined iff
    some contributing wn_pos has a sense whose synset carries a definition. POS_MAP
    is many-to-one, so several wn_pos may OR into one (word, c5_pos) bucket."""
    defined_synsets = synsets_with_definition()
    keys = set()
    for path in sorted(glob(str(WORDNET_YAML_DIR / "entries-*.yaml"))):
        data = yaml.safe_load(open(path, encoding="utf-8"))
        if not data:
            continue
        for word, pos_dict in data.items():
            if not wordnet_gen.is_single_word(word):
                continue
            word_lower = word.lower()
            for wn_pos, pos_data in pos_dict.items():
                c5_pos = wordnet_gen.POS_MAP.get(wn_pos)
                if c5_pos is None:
                    continue
                senses = pos_data.get("sense") or []
                if any(isinstance(s, dict) and s.get("synset") in defined_synsets
                       for s in senses):
                    keys.add((word_lower, c5_pos))
    return keys


def wiktionary_def_keys():
    """The set of (word, c5_pos) the Wiktionary source carries a definition for.

    Streams the kaikki JSONL exactly as generate_wiktionary_supplement does —
    English only, affix words (leading/trailing hyphen) skipped, pos mapped via its
    POS_MAP (default UNC) — and marks the key defined iff some matching entry has a
    sense with a non-empty gloss."""
    keys = set()
    with open(WIKTIONARY_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("lang_code") != "en":
                continue
            word = entry.get("word", "")
            if not word or word.startswith("-") or word.endswith("-"):
                continue
            if not any(sense.get("glosses") for sense in entry.get("senses", [])):
                continue
            c5_pos = wiktionary_gen.POS_MAP.get(entry.get("pos", ""), "UNC")
            keys.add((word, c5_pos))
    return keys


def build_def_keys():
    """Build the (WordNet, Wiktionary) definition key sets from the source YAML/
    JSONL. The disk-reading edge the annotate pure fn consumes; call once."""
    wn_keys = wordnet_def_keys()
    wikt_keys = wiktionary_def_keys()
    return wn_keys, wikt_keys


def annotate(supplement, wn_keys, wikt_keys, tallies=None):
    """Set `has_definition` on every record: the LOGICAL OR, over the record's
    attesting sources, of whether that source carries a definition for the
    record's (word, pos). A source not in the record's list does not contribute.
    Mutates records in place; returns the supplement."""
    if tallies is None:
        tallies = Counter()
    for entries in supplement.values():
        for entry in entries:
            sources = entry.get("source", [])
            wn_word = entry["Latn"].lower()
            has_def = (
                (SOURCE_WORDNET in sources
                 and (wn_word, entry["pos"]) in wn_keys)
                or (SOURCE_WIKTIONARY in sources
                    and (entry["Latn"], entry["pos"]) in wikt_keys)
            )
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
    print("Building WordNet definition index...")
    wn_keys = wordnet_def_keys()
    print(f"  WordNet (word, pos) with definition: {len(wn_keys):,}")
    print("Building Wiktionary definition index (streaming kaikki)...")
    wikt_keys = wiktionary_def_keys()
    print(f"  Wiktionary (word, pos) with definition: {len(wikt_keys):,}")

    annotate(supplement, wn_keys, wikt_keys, tallies)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(supplement, f, ensure_ascii=False, indent=4)
    print(f"\nWrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in supplement.values()):,} records")

    report(tallies)


if __name__ == "__main__":
    main()
