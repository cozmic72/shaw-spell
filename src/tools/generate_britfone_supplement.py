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
import subprocess
import sys
from pathlib import Path

# Ensure the tools directory is on the path so we can import ipa_to_shavian
TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOLS_DIR))

from ipa_to_shavian import ipa_to_shavian, normalize_ipa, check_missing_r
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
            ["shave", "-q"],
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


def _score_confidence(word: str, ipa: str, shaw_rules: str,
                      have_ml: bool, ml_model) -> tuple[str, str]:
    """Score conversion confidence based on multiple signals.

    Returns (confidence_level, review_notes) where:
        confidence_level: "high", "medium", or "low"
        review_notes: human-readable explanation of concerns (empty if high)
    """
    notes = []

    # Signal 1: ML model disagrees with rules
    if have_ml and ml_model:
        ipa_stripped = strip_stress(ipa)
        ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
        shaw_ml = ipa_to_shavian(ml_ipa)
        if shaw_ml != shaw_rules:
            notes.append(f"ml_disagrees:{shaw_ml}")

    # Signal 2: word has 'r' in spelling — r-restoration may be incomplete
    word_lower = word.lower()
    if 'r' in word_lower:
        # Check if the IPA has fewer r/R than the spelling has 'r'
        spelling_r_count = word_lower.count('r')
        ipa_r_count = ipa.count('r') + ipa.count('R')
        if spelling_r_count > ipa_r_count:
            notes.append(f"r_gap:spelling={spelling_r_count},ipa={ipa_r_count}")

    # Signal 2b: word has 'r' in spelling but Shavian has NO r-sound at all
    missing_r = check_missing_r(word, shaw_rules)
    if missing_r:
        notes.append(missing_r)

    # Signal 3: unknown characters passed through
    known_shaw = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")
    unknown = set(shaw_rules) - known_shaw
    if unknown:
        notes.append(f"unknown_chars:{''.join(unknown)}")

    # Signal 4: multiple pronunciations for same word
    # (handled at the word level, not here)

    # Determine confidence level
    if not notes:
        return "high", ""
    elif any(n.startswith("unknown_chars") for n in notes):
        return "low", "; ".join(notes)
    elif any(n.startswith("missing_r") for n in notes):
        return "low", "; ".join(notes)
    elif any(n.startswith("ml_disagrees") for n in notes) and any(n.startswith("r_gap") for n in notes):
        return "low", "; ".join(notes)
    else:
        return "medium", "; ".join(notes)


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
    confidence_counts = {"high": 0, "medium": 0, "low": 0}

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

            # Score confidence
            confidence, review_notes = _score_confidence(
                word, ipa, shaw_rules, have_ml, ml_model if have_ml else None
            )
            confidence_counts[confidence] += 1

            entry = {
                "Latn": word,
                "Shaw": shaw_rules,
                "pos": "UNC",
                "ipa": ipa,
                "freq": 0,
                "var": "RSSB",
                "confidence": confidence,
            }
            if review_notes:
                entry["review"] = review_notes

            entries.append(entry)

        if entries:
            key = f"{word}_UNC_{entries[0]['Shaw']}"
            supplement[key] = entries

    # Consult `shave` tool for medium/low confidence entries
    review_words = set()
    for key, entries in supplement.items():
        for e in entries:
            if e.get("confidence") in ("medium", "low"):
                review_words.add(e["Latn"])

    if review_words:
        print(f"\n  Consulting `shave` tool for {len(review_words)} review words...")
        shave_results = _batch_shave(sorted(review_words))
        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in supplement.items():
            for e in entries:
                if e.get("confidence") not in ("medium", "low"):
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue
                shave_shaw = shave_results[w]
                review = e.get("review", "")

                if shave_shaw == e["Shaw"]:
                    # shave agrees with our rules — upgrade confidence
                    e["confidence"] = "medium" if e["confidence"] == "low" else "high"
                    e["review"] = review + "; shave_agrees"
                    shave_upgraded += 1
                else:
                    # Check if shave agrees with ML
                    ml_shaw = None
                    if "ml_disagrees:" in review:
                        ml_shaw = review.split("ml_disagrees:")[1].split(";")[0].strip()

                    if ml_shaw and shave_shaw == ml_shaw:
                        # shave + ML consensus overrides rules
                        old_shaw = e["Shaw"]
                        e["Shaw"] = shave_shaw
                        e["confidence"] = "high"
                        e["review"] = f"overridden:was={old_shaw}; shave+ml_consensus"
                        shave_overridden += 1
                    else:
                        e["review"] = review + f"; shave_says:{shave_shaw}"

        # Fix keys for overridden entries
        new_supplement = {}
        for key, entries in supplement.items():
            new_key = f"{entries[0]['Latn']}_UNC_{entries[0]['Shaw']}"
            new_supplement[new_key] = entries
        supplement = new_supplement

        print(f"  Upgraded {shave_upgraded} entries based on shave agreement")
        print(f"  Overrode {shave_overridden} entries based on shave+ML consensus")

        # Recount confidence
        confidence_counts = {"high": 0, "medium": 0, "low": 0}
        for key, entries in supplement.items():
            for e in entries:
                confidence_counts[e.get("confidence", "high")] += 1

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
    print(f"  Confidence: high={confidence_counts['high']}, "
          f"medium={confidence_counts['medium']}, low={confidence_counts['low']}")
    if conversion_errors:
        print(f"  Conversion errors: {conversion_errors}")

    # Show some sample new words
    if new_words:
        sample = sorted(new_words)[:10]
        print(f"\n  Sample new words: {', '.join(sample)}")


if __name__ == '__main__':
    main()
