#!/usr/bin/env python3
"""
Generate a ReadLex-format JSON supplement from Britfone pronunciation data.

Britfone provides Standard Southern British (SSB) IPA pronunciations.
This script converts them to ReadLex format with Shavian transliterations.

Limitations:
- Britfone is non-rhotic, so linking/intrusive R is not restored.
  We convert ɹ→r but do not attempt to add capital R where the spelling
  has 'r' but Britfone omits it (e.g., "water" = wɔːtə, not wɔːtəR).
  The variant field "RSSB" signals this is SSB-based data.
- POS is always "UNC" (unclassified) since Britfone has no POS data.
- Frequency is always 0 since Britfone has no frequency data.

Usage:
    python3 src/tools/generate_britfone_supplement.py
"""

import csv
import json
import re
import sys
from pathlib import Path

# Ensure the tools directory is on the path so we can import ipa_to_shavian
TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOLS_DIR))

from ipa_to_shavian import ipa_to_shavian

PROJECT_ROOT = Path(__file__).parent.parent.parent
BRITFONE_CSV = PROJECT_ROOT / "external" / "britfone" / "britfone.main.3.0.1.csv"
READLEX_JSON = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
OUTPUT_JSON = PROJECT_ROOT / "data" / "supplement-britfone.json"


def parse_britfone_word(raw_word: str) -> tuple[str, int]:
    """Parse a Britfone word field, returning (word, variant_number).

    Examples:
        "HELLO"    -> ("hello", 0)
        "HELLO(1)" -> ("hello", 1)
        "HELLO(2)" -> ("hello", 2)
        "COSTA_RICA" -> ("costa rica", 0)
    """
    # Strip variant number suffix like (1), (2)
    match = re.match(r'^(.+?)\((\d+)\)$', raw_word)
    if match:
        word = match.group(1)
        variant = int(match.group(2))
    else:
        word = raw_word
        variant = 0

    # Lowercase and replace underscores with spaces
    word = word.lower().replace('_', ' ')
    return word, variant


def britfone_ipa_to_readlex(phonemes_str: str) -> str:
    """Convert Britfone space-separated IPA to a ReadLex-style IPA string.

    Steps:
    1. Join space-separated phonemes into a single string
    2. Convert: ɐ→ʌ, ɹ→r (ɛ stays as-is since the converter handles it)
    """
    # Join phonemes (remove spaces)
    ipa = phonemes_str.replace(' ', '')

    # Symbol conversions
    ipa = ipa.replace('ɐ', 'ʌ')
    ipa = ipa.replace('ɹ', 'r')

    return ipa


def main():
    if not BRITFONE_CSV.exists():
        print(f"Error: Britfone CSV not found: {BRITFONE_CSV}", file=sys.stderr)
        sys.exit(1)

    # Load ReadLex for overlap stats
    readlex_words = set()
    if READLEX_JSON.exists():
        with open(READLEX_JSON, 'r', encoding='utf-8') as f:
            readlex_data = json.load(f)
        for entries in readlex_data.values():
            for entry in entries:
                readlex_words.add(entry['Latn'].lower())
        print(f"Loaded ReadLex: {len(readlex_words)} unique words")
    else:
        print("Warning: ReadLex not found, skipping overlap stats")

    # Parse Britfone CSV
    # Format: "WORD, phoneme1 ˈphoneme2 phoneme3"
    # The file uses ", " as separator between word and phonemes
    word_pronunciations: dict[str, list[str]] = {}  # word -> list of IPA strings
    total_lines = 0
    parse_errors = 0

    with open(BRITFONE_CSV, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total_lines += 1

            # Split on first comma
            parts = line.split(',', 1)
            if len(parts) != 2:
                parse_errors += 1
                continue

            raw_word = parts[0].strip()
            phonemes_str = parts[1].strip()

            word, _variant = parse_britfone_word(raw_word)
            ipa = britfone_ipa_to_readlex(phonemes_str)

            if word not in word_pronunciations:
                word_pronunciations[word] = []
            # Avoid duplicate IPA for same word
            if ipa not in word_pronunciations[word]:
                word_pronunciations[word].append(ipa)

    print(f"Parsed Britfone: {total_lines} lines, {len(word_pronunciations)} unique words")
    if parse_errors:
        print(f"  Parse errors: {parse_errors}")

    # Build ReadLex-format output
    supplement: dict[str, list[dict]] = {}
    conversion_errors = 0

    for word, ipa_list in sorted(word_pronunciations.items()):
        entries = []
        for ipa in ipa_list:
            try:
                shaw = ipa_to_shavian(ipa)
            except Exception as e:
                conversion_errors += 1
                print(f"  Conversion error for '{word}' (ipa={ipa}): {e}", file=sys.stderr)
                continue

            entries.append({
                "Latn": word,
                "Shaw": shaw,
                "pos": "UNC",
                "ipa": ipa,
                "freq": 0,
                "var": "RSSB",
            })

        if entries:
            # Key uses first pronunciation's Shavian
            key = f"{word}_UNC_{entries[0]['Shaw']}"
            supplement[key] = entries

    # Write output
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(supplement, f, ensure_ascii=False, indent=2)

    # Stats
    britfone_words = set(word_pronunciations.keys())
    overlap = britfone_words & readlex_words
    new_words = britfone_words - readlex_words

    print(f"\nOutput: {OUTPUT_JSON}")
    print(f"  Total entries: {len(supplement)}")
    print(f"  Words also in ReadLex: {len(overlap)}")
    print(f"  Words NOT in ReadLex (new): {len(new_words)}")
    if conversion_errors:
        print(f"  Conversion errors: {conversion_errors}")

    # Show some sample new words
    if new_words:
        sample = sorted(new_words)[:10]
        print(f"\n  Sample new words: {', '.join(sample)}")


if __name__ == '__main__':
    main()
