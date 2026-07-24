#!/usr/bin/env python3
"""
DETECT + FILL: complete the committed definition corpus against its gloss sources.

data/definitions-latin-{gb,us}.json (the SOURCE OF TRUTH, keyed `lemma|synset`)
had drifted INCOMPLETE relative to WordNet: data/wordnet-comprehensive.json
carries glosses (e.g. aioli, synset 07850750-n) with no corpus entry, so
has_definition over-claimed and the editor/export showed nothing. The owner's
invariant: the corpus contains ALL WordNet definitions.

This tool is FILL-MISSING-ONLY. It detects every (lemma, synset) with a WordNet
gloss but no corpus entry and APPENDS it; pre-existing entries are NEVER touched
(rewriting would orphan the owner's definition-correction patches — asserted, not
assumed). Filled entries match the corpus's wordnet-synset conventions exactly
(verified against all 88,023 existing synset-keyed entries):

    key    = f"{lemma}|{synset}"      exact lemma case, as in the WordNet cache
    entry  = {definition, examples: [], pos}   no source/confidence annotations
    pos    = the WordNet cache pos_entries key (n/v/a/r/s, or n-1 homograph tags)
    definition = definitions[0]       (every cache sense carries exactly one)

The Shavian side (data/definitions-shavian-{gb,us}.json, keyed identically) is
then extended for the NEW keys only, via build_definition_caches's shave batch
(shave's own shipped dictionary — never our readlex). Existing Shavian entries
are untouched. Both outputs stay deterministically key-sorted; a second run
detects zero missing and writes nothing (idempotent).

MANUAL tool: `make complete-definitions` (never part of the normal build — shave
is expensive). Run it after the WordNet cache (or a future gloss source) changes.

Usage:
    python3 src/tools/complete_definition_corpus.py [--gb|--us]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from basis import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "src" / "dictionaries"))
from build_definition_caches import POS_TO_SHAVIAN, batch_transliterate_to_shavian

DATA = PROJECT_ROOT / "data"
WORDNET_CACHE = DATA / "wordnet-comprehensive.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(obj, path):
    """Deterministic, byte-idempotent serialization — the exact json params of
    build_definition_caches / split_definition_corpus (no trailing newline)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)


def wordnet_glosses():
    """Every `lemma|synset` -> latin entry the WordNet cache carries a gloss for,
    in the corpus's wordnet-synset shape. Fails LOUD on a colliding key with
    differing content (would mean the cache's lemma/synset pairing broke)."""
    glosses = {}
    for lemma, wn_entry in load_json(WORDNET_CACHE).items():
        for wn_pos, pos_data in wn_entry["pos_entries"].items():
            for variant in pos_data["sense_variants"]:
                definitions = variant.get("definitions") or []
                if not definitions or not definitions[0]:
                    continue
                key = f"{lemma}|{variant['synset']}"
                entry = {
                    "definition": definitions[0],
                    "examples": [],
                    "pos": wn_pos,
                }
                if glosses.setdefault(key, entry) != entry:
                    raise ValueError(
                        f"{key}: conflicting glosses within the WordNet cache")
    return glosses


def gloss_sources():
    """Every gloss source the corpus must cover, as `lemma|synset` -> latin
    entry dicts. WordNet only today; the LLM-drafted gloss list (task #33)
    plugs in here as a further dict when it lands."""
    return [wordnet_glosses()]


def complete_dialect(dialect, sources):
    """Fill one dialect's latin+shavian corpus files with the sources' missing
    entries. Returns the number of entries added (0 = already complete)."""
    latin_path = DATA / f"definitions-latin-{dialect}.json"
    shavian_path = DATA / f"definitions-shavian-{dialect}.json"

    latin = load_json(latin_path)
    shavian = load_json(shavian_path)
    if set(latin) != set(shavian):
        raise ValueError(
            f"{dialect}: latin/shavian key sets differ — the corpus is already "
            f"inconsistent; refusing to extend it")

    missing = {}
    for glosses in sources:
        for key, entry in glosses.items():
            if key not in latin:
                missing[key] = entry
    print(f"[{dialect.upper()}] corpus: {len(latin):,} keys; "
          f"missing: {len(missing):,}")
    if not missing:
        return 0

    assert not set(missing) & set(latin)  # fill-missing-only: never overwrite
    latin.update(missing)

    new_keys = sorted(missing)
    transliterations = batch_transliterate_to_shavian(
        [missing[key]["definition"] for key in new_keys], dialect)
    for key, shaw_def in zip(new_keys, transliterations):
        pos = missing[key]["pos"]
        shavian[key] = {
            "transliterated_definition": shaw_def,
            "transliterated_pos": POS_TO_SHAVIAN.get(pos, pos),
            "transliterated_examples": [],
        }

    write_json(latin, latin_path)
    write_json(shavian, shavian_path)
    print(f"[{dialect.upper()}] filled {len(missing):,} entries -> "
          f"{latin_path.relative_to(PROJECT_ROOT)} + "
          f"{shavian_path.relative_to(PROJECT_ROOT)} ({len(latin):,} keys)")
    return len(missing)


def main():
    dialects = ("gb", "us")
    if "--gb" in sys.argv:
        dialects = ("gb",)
    elif "--us" in sys.argv:
        dialects = ("us",)

    print("Loading gloss sources...")
    sources = gloss_sources()
    print(f"  WordNet: {sum(len(s) for s in sources):,} (lemma, synset) glosses")

    for dialect in dialects:
        complete_dialect(dialect, sources)
    print("\nDone.")


if __name__ == "__main__":
    main()
