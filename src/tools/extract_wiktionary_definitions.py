#!/usr/bin/env python3
"""
Extract definitions from Wiktionary JSONL dump for words in readlex
that lack definitions.

Reads the Wiktionary JSONL line-by-line (streaming) and outputs
data/definitions-wiktionary.json with definitions keyed as lemma|wikt-N.

Usage:
    ./src/tools/extract_wiktionary_definitions.py
"""

import sys
import json
from pathlib import Path


# POS mapping: Wiktionary pos -> single-letter WordNet-style
POS_MAP = {
    "noun": "n",
    "verb": "v",
    "adj": "a",
    "adv": "r",
}

MAX_SENSES_PER_WORD = 5
MIN_GLOSS_LENGTH = 5


def main():
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent

    wiktionary_path = project_dir / "external/wiktionary/kaikki.org-dictionary-English.jsonl"
    readlex_path = project_dir / "data/readlex.json"
    existing_defs_path = project_dir / "data/definitions-latin-gb.json"
    output_path = project_dir / "data/definitions-wiktionary.json"

    # Validate inputs exist
    if not wiktionary_path.exists():
        print(f"ERROR: Wiktionary JSONL not found at {wiktionary_path}")
        sys.exit(1)
    if not readlex_path.exists():
        print(f"ERROR: readlex not found at {readlex_path}")
        sys.exit(1)
    if not existing_defs_path.exists():
        print(f"ERROR: existing definitions not found at {existing_defs_path}")
        sys.exit(1)

    # Load readlex to get target words
    print("Loading readlex...")
    with open(readlex_path, "r", encoding="utf-8") as f:
        readlex = json.load(f)

    readlex_words = set()
    for key, entries in readlex.items():
        for e in entries:
            readlex_words.add(e["Latn"].lower())
    print(f"  {len(readlex_words)} unique words in readlex")

    # Load existing definitions to find words that already have them
    print("Loading existing definitions...")
    with open(existing_defs_path, "r", encoding="utf-8") as f:
        existing_defs = json.load(f)

    words_with_defs = set()
    for k in existing_defs:
        words_with_defs.add(k.split("|")[0].lower())
    print(f"  {len(words_with_defs)} words already have definitions")

    # Words we need definitions for
    target_words = readlex_words - words_with_defs
    print(f"  {len(target_words)} words need definitions")

    # Stream Wiktionary JSONL and collect definitions
    print(f"\nStreaming Wiktionary JSONL from {wiktionary_path}...")
    wikt_defs = {}  # word -> list of (pos, definition) tuples
    lines_processed = 0

    with open(wiktionary_path, "r", encoding="utf-8") as f:
        for line in f:
            lines_processed += 1
            if lines_processed % 500_000 == 0:
                print(f"  processed {lines_processed:,} lines, found defs for {len(wikt_defs)} words...")

            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            word = entry.get("word", "").lower()
            if not word or word not in target_words:
                continue

            # Skip if we already have enough senses for this word
            if word in wikt_defs and len(wikt_defs[word]) >= MAX_SENSES_PER_WORD:
                continue

            pos_raw = entry.get("pos", "")
            pos = POS_MAP.get(pos_raw, pos_raw)

            senses = entry.get("senses", [])
            for sense in senses:
                if word in wikt_defs and len(wikt_defs[word]) >= MAX_SENSES_PER_WORD:
                    break

                glosses = sense.get("glosses", [])
                if not glosses:
                    continue

                gloss = glosses[0]  # Take first gloss
                if len(gloss) < MIN_GLOSS_LENGTH:
                    continue

                if word not in wikt_defs:
                    wikt_defs[word] = []
                wikt_defs[word].append((pos, gloss))

    print(f"  Finished: processed {lines_processed:,} lines")
    print(f"  Found definitions for {len(wikt_defs)} words")
    total_defs = sum(len(v) for v in wikt_defs.values())
    print(f"  Total definitions: {total_defs}")

    # Build output in the expected format: {lemma|wikt-N: [{definition, pos, examples, source}]}
    output = {}
    for word, defs_list in sorted(wikt_defs.items()):
        for i, (pos, definition) in enumerate(defs_list, 1):
            key = f"{word}|wikt-{i}"
            output[key] = [
                {
                    "definition": definition,
                    "pos": pos,
                    "examples": [],
                    "source": "Wiktionary",
                }
            ]

    print(f"\nWriting {len(output)} definition entries to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("Done!")
    print(f"\nSummary:")
    print(f"  New definitions added: {total_defs}")
    print(f"  Words covered: {len(wikt_defs)}")
    print(f"  Words still missing: {len(target_words) - len(wikt_defs)}")


if __name__ == "__main__":
    main()
