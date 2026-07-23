#!/usr/bin/env python3
"""
Generate a ReadLex-format JSON supplement from Britfone pronunciation data.

Britfone provides Standard Southern British (SSB) IPA pronunciations.
This script converts them to ReadLex format with Shavian transliterations.

Limitations:
- Britfone is non-rhotic; linking/intrusive R is restored via
  normalize_ipa()'s _restore_rhoticity() using spelling alignment.
  The variant field "RSSB" signals this is SSB-based data.
- POS is always "UNC" (unclassified) since Britfone has no POS data.
- Frequency is always 0 since Britfone has no frequency data.

Usage:
    python3 src/tools/generate_britfone_supplement.py
"""

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

# Ensure the tools directory is on the path so we can import ipa_to_shavian
TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOLS_DIR))

from ipa_to_shavian import ipa_to_shavian, normalize_ipa, score_confidence, upgrade_confidence_shave
from ml_ipa_normalizer import ml_normalize_ipa, load_model, strip_stress

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


def britfone_ipa_to_readlex(phonemes_str: str, word: str = "") -> str:
    """Convert Britfone space-separated IPA to a ReadLex-style IPA string.

    Steps:
    1. Join space-separated phonemes into a single string
    2. Normalize to ReadLex conventions (symbol conversion + r-restoration)
    """
    # Join phonemes (remove spaces)
    ipa = phonemes_str.replace(' ', '')
    # Use normalize_ipa for proper dialect conversion
    return normalize_ipa(ipa, word=word, source="britfone")


def _batch_shave(words: list[str]) -> dict[str, str]:
    """Run words through the `shave` tool and return word→shavian mapping."""
    try:
        input_text = "\n".join(words)
        result = subprocess.run(
            ["shave", "-q", "-b"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = result.stdout.strip().split("\n")
        mapping = {}
        for word, shaw_line in zip(words, lines):
            shaw = shaw_line.strip()
            if shaw:
                mapping[word] = shaw
        return mapping
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  Warning: shave tool unavailable: {e}", file=sys.stderr)
        return {}


def _compute_ml_shaw(word: str, ipa: str, have_ml: bool, ml_model) -> str | None:
    """Get ML model's Shavian prediction, or None if unavailable."""
    if not have_ml or not ml_model:
        return None
    ipa_stripped = strip_stress(ipa)
    ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
    return ipa_to_shavian(ml_ipa)


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
            ipa = britfone_ipa_to_readlex(phonemes_str, word=word)

            if word not in word_pronunciations:
                word_pronunciations[word] = []
            # Avoid duplicate IPA for same word
            if ipa not in word_pronunciations[word]:
                word_pronunciations[word].append(ipa)

    print(f"Parsed Britfone: {total_lines} lines, {len(word_pronunciations)} unique words")
    if parse_errors:
        print(f"  Parse errors: {parse_errors}")

    # Build ReadLex-format output with confidence scoring
    supplement: dict[str, list[dict]] = {}
    conversion_errors = 0

    # Load ML model for confidence comparison
    try:
        ml_model = load_model()
        have_ml = True
    except FileNotFoundError:
        have_ml = False
        print("  Warning: ML model not found, skipping ML confidence comparison")

    for word, ipa_list in sorted(word_pronunciations.items()):
        entries = []
        for ipa in ipa_list:
            try:
                shaw_rules = ipa_to_shavian(ipa)
            except Exception as e:
                conversion_errors += 1
                print(f"  Conversion error for '{word}' (ipa={ipa}): {e}", file=sys.stderr)
                continue

            # Get ML prediction for confidence comparison
            ml_shaw = _compute_ml_shaw(word, ipa, have_ml, ml_model)

            # Score confidence as percentage
            conf_pct, notes = score_confidence(word, ipa, shaw_rules, ml_shaw)

            entry = {
                "Latn": word,
                "Shaw": shaw_rules,
                "pos": "UNC",
                "ipa": ipa,
                "freq": 0,
                "var": "RSSB",
                "confidence": conf_pct,
            }
            if notes:
                entry["review"] = "; ".join(notes)
            # Stash ml_shaw for shave consultation later
            entry["_ml_shaw"] = ml_shaw

            entries.append(entry)

        if entries:
            key = f"{word}_UNC_{entries[0]['Shaw']}"
            supplement[key] = entries

    # Consult `shave` tool for entries below 89% confidence
    review_words = set()
    for key, entries in supplement.items():
        for e in entries:
            if e.get("confidence", 89) < 89:
                review_words.add(e["Latn"])

    if review_words:
        print(f"\n  Consulting `shave` tool for {len(review_words)} review words...")
        shave_results = _batch_shave(sorted(review_words))
        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in supplement.items():
            for e in entries:
                if e.get("confidence", 89) >= 89:
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue
                shave_shaw = shave_results[w]
                ml_shaw = e.pop("_ml_shaw", None)
                notes = [n for n in e.get("review", "").split("; ") if n]

                new_pct, notes, override = upgrade_confidence_shave(
                    e["confidence"], notes, e["Shaw"], shave_shaw, ml_shaw
                )
                e["confidence"] = new_pct
                e["review"] = "; ".join(notes) if notes else ""
                if override:
                    e["Shaw"] = override
                    shave_overridden += 1
                elif new_pct > e.get("confidence", 0):
                    shave_upgraded += 1

        # Fix keys for overridden entries
        new_supplement = {}
        for key, entries in supplement.items():
            new_key = f"{entries[0]['Latn']}_UNC_{entries[0]['Shaw']}"
            new_supplement[new_key] = entries
        supplement = new_supplement

        print(f"  Upgraded {shave_upgraded} entries based on shave agreement")
        print(f"  Overrode {shave_overridden} entries based on shave+ML consensus")

    # Clean up internal fields and compute stats
    conf_buckets = {"high (>=80)": 0, "medium (30-79)": 0, "low (<30)": 0}
    for key, entries in supplement.items():
        for e in entries:
            e.pop("_ml_shaw", None)
            if not e.get("review"):
                e.pop("review", None)
            pct = e.get("confidence", 89)
            if pct >= 80:
                conf_buckets["high (>=80)"] += 1
            elif pct >= 30:
                conf_buckets["medium (30-79)"] += 1
            else:
                conf_buckets["low (<30)"] += 1

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
    print(f"  Confidence: {conf_buckets}")
    if conversion_errors:
        print(f"  Conversion errors: {conversion_errors}")

    # Show some sample new words
    if new_words:
        sample = sorted(new_words)[:10]
        print(f"\n  Sample new words: {', '.join(sample)}")


if __name__ == '__main__':
    main()
