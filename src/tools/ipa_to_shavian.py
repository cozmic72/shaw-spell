#!/usr/bin/env python3
"""
Rule-based IPA-to-Shavian converter for ReadLex-format IPA strings.

Handles ReadLex-specific conventions:
  - Capital R = linking/intrusive r (part of r-colored vowels)
  - Capital N/T/V/F/Ð = word signs for and/to/of/for/the
  - Uppercase Ə = schwa variant (in suffixes like -Əd, -Əz)
  - Uppercase Æ = TRAP-BATH short variant (maps to 𐑨)
  - Uppercase Ɑ = TRAP-BATH long variant (maps to 𐑭)
  - Uppercase I = weak vowel variant (maps to 𐑩)
  - + = affix/morpheme boundary (compound Shavian letters split here)
  - ʍ = voiceless w (maps to 𐑢)
  - ̩ = syllabic mark (ignored)

Usage:
    from ipa_to_shavian import ipa_to_shavian
    shaw = ipa_to_shavian("əˈbæk")  # Returns "𐑩𐑚𐑨𐑒"

    # Or run as script to validate against ReadLex:
    python3 ipa_to_shavian.py [--validate] [--verbose]
"""

import sys
import json
from pathlib import Path

# IPA-to-Shavian mapping rules, ordered longest-first for greedy matching.
# R-colored vowels and diphthongs (with capital R = ReadLex linking r)
# These must come before their component parts.
PHONEME_MAP = [
    # Word signs (uppercase single chars)
    ("N", "𐑯"),   # "and"
    ("T", "𐑑"),   # "to"
    ("V", "𐑝"),   # "of"
    ("F", "𐑓"),   # "for"
    ("Ð", "𐑞"),   # "the"

    # ReadLex uppercase variants
    ("Ə", "𐑩"),   # uppercase schwa (suffix variant)
    ("Æ", "𐑨"),   # TRAP-BATH short variant
    ("Ɑː", "𐑭"), # TRAP-BATH long variant (with length)
    ("Ɑ", "𐑭"),   # TRAP-BATH long variant (without length)
    ("I", "𐑩"),   # weak vowel variant (maps to schwa in Shavian)
    ("L", "𐑤"),   # voiceless lateral (Welsh ll, approximated)

    # Yew ligature (must come before j and uː)
    ("juː", "𐑿"),  # YEW ligature: you, use, new

    # R-colored long vowels/diphthongs (with capital R)
    ("ɜːR", "𐑻"),  # NURSE (stressed): bird, err
    ("ɑːR", "𐑸"),  # START: far, car
    ("ɔːR", "𐑹"),  # NORTH/FORCE: for, more
    ("eəR", "𐑺"),  # SQUARE: air, Mary
    ("ɪəR", "𐑽"),  # NEAR: dear, here
    ("ʊəR", "𐑫𐑼"), # CURE: poor, sure

    # R-colored long vowels/diphthongs (with lowercase r)
    ("ɜːr", "𐑻"),  # NURSE: bird (lowercase r variant)
    ("ɑːr", "𐑸"),  # START: far (lowercase r variant)
    ("ɔːr", "𐑹"),  # NORTH/FORCE: for (lowercase r variant)
    ("eər", "𐑺"),  # SQUARE: air (lowercase r variant)
    ("ɪər", "𐑽"),  # NEAR: dear (lowercase r variant)
    ("ʊər", "𐑫𐑼"), # CURE: poor (lowercase r variant)

    # R-colored short vowels (with capital R or lowercase r)
    ("əR", "𐑼"),   # lettER (unstressed): better
    ("ər", "𐑼"),   # lettER (lowercase r variant)

    # Standalone capital R after other vowels
    ("R", "𐑮"),    # linking r (general case)

    # Diphthongs (standard IPA)
    ("eɪ", "𐑱"),   # FACE: say, make
    ("aɪ", "𐑲"),   # PRICE: my, time
    ("ɔɪ", "𐑶"),   # CHOICE: boy, joy
    ("aʊ", "𐑬"),   # MOUTH: now, out
    ("əʊ", "𐑴"),   # GOAT: go, no
    ("oʊ", "𐑴"),   # GOAT (GenAm variant)
    ("ɪə", "𐑾"),   # NEAR (without R): idea, area
    ("eə", "𐑺"),   # SQUARE (without R, rare in ReadLex)
    ("ʊə", "𐑫𐑼"), # CURE (without R)

    # Long vowels
    ("iː", "𐑰"),   # FLEECE: be, see
    ("ɑː", "𐑭"),   # BATH/PALM: father
    ("ɔː", "𐑷"),   # THOUGHT: caught, all
    ("uː", "𐑵"),   # GOOSE: too, blue
    ("ɜː", "𐑻"),   # NURSE without R (rare in ReadLex)
    ("ɛː", "𐑻"),   # NURSE variant (tradesperson etc.)

    # Affricates (must come before component stops/fricatives)
    ("tʃ", "𐑗"),   # CHURCH: chop
    ("dʒ", "𐑡"),   # JUDGE: jug

    # Short vowels
    ("æ", "𐑨"),    # TRAP: cat
    ("ɛ", "𐑧"),    # DRESS variant (strict IPA)
    ("e", "𐑧"),    # DRESS: pet, bed
    ("ɪ", "𐑦"),    # KIT: it, bit
    ("ɒ", "𐑪"),    # LOT: not, got
    ("ʌ", "𐑳"),    # STRUT: but, cup
    ("ʊ", "𐑫"),    # FOOT: good, book
    ("ɔ", "𐑷"),    # (rare without length mark)
    ("ə", "𐑩"),    # commA: about
    ("ɐ", "𐑳"),    # STRUT (Britfone variant)

    # Consonants
    ("ŋ", "𐑙"),    # RING
    ("θ", "𐑔"),    # THIN
    ("ð", "𐑞"),    # THIS
    ("ʃ", "𐑖"),    # SHIP
    ("ʒ", "𐑠"),    # MEASURE
    ("ʍ", "𐑢"),    # voiceless W (whine) - maps to 𐑢 per ReadLex
    ("j", "𐑘"),    # YES
    ("ɡ", "𐑜"),    # GOT (IPA g)
    ("ɹ", "𐑮"),    # (Britfone r variant)

    # Simple consonants (ASCII)
    ("p", "𐑐"),
    ("b", "𐑚"),
    ("t", "𐑑"),
    ("d", "𐑛"),
    ("k", "𐑒"),
    ("g", "𐑜"),    # ASCII g
    ("f", "𐑓"),
    ("v", "𐑝"),
    ("s", "𐑕"),
    ("z", "𐑟"),
    ("h", "𐑣"),
    ("m", "𐑥"),
    ("n", "𐑯"),
    ("l", "𐑤"),
    ("r", "𐑮"),
    ("w", "𐑢"),
    ("i", "𐑦"),    # allophonic short i (happy tensing)
    ("u", "𐑫"),    # allophonic weak u (ReadLex convention: bare u = 𐑫)
    ("y", "𐑘"),    # rare: used in some foreign words
    ("a", "𐑨"),    # rare standalone
    ("o", "𐑪"),    # rare standalone
]

# Characters to skip/pass through
PASSTHROUGH = set(" -.'̩")
SKIP = set("ˈˌ")  # stress marks only; ː is part of phoneme patterns


def ipa_to_shavian(ipa: str) -> str:
    """Convert a ReadLex-format IPA string to Shavian script.

    Handles affix boundaries (+) by converting each segment separately,
    preventing compound Shavian letters from spanning morpheme boundaries.

    Args:
        ipa: IPA string using ReadLex conventions (capital R, word signs, etc.)

    Returns:
        Shavian string
    """
    # Split on affix boundaries, convert each segment, rejoin
    if '+' in ipa:
        segments = ipa.split('+')
        return ''.join(_convert_segment(seg) for seg in segments)
    return _convert_segment(ipa)


def _convert_segment(ipa: str) -> str:
    """Convert a single IPA segment (no affix boundaries) to Shavian.

    Strips stress marks and length marks before matching so that compound
    phonemes like ər are not broken by intervening ˈ or ˌ.
    """
    # Strip stress marks and length marks — they don't affect Shavian output
    stripped = ''
    for ch in ipa:
        if ch not in SKIP:
            stripped += ch
    return _convert_stripped(stripped)


def _convert_stripped(ipa: str) -> str:
    """Convert a stress-mark-free IPA string to Shavian."""
    result = []
    pos = 0
    length = len(ipa)

    while pos < length:
        char = ipa[pos]

        # Pass through spaces, hyphens, dots, apostrophes, syllabic marks
        if char in PASSTHROUGH:
            result.append(char)
            pos += 1
            continue

        # Try greedy longest-first match
        matched = False
        for phoneme, shavian in PHONEME_MAP:
            plen = len(phoneme)
            if ipa[pos:pos + plen] == phoneme:
                result.append(shavian)
                pos += plen
                matched = True
                break

        if not matched:
            # Unknown character — pass through
            result.append(char)
            pos += 1

    return "".join(result)


def validate_against_readlex(readlex_path: str, verbose: bool = False) -> dict:
    """Validate the converter against all ReadLex entries.

    Returns dict with counts: total, correct, incorrect, and list of mismatches.
    """
    with open(readlex_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    correct = 0
    mismatches = []

    for key, entries in data.items():
        for entry in entries:
            ipa = entry['ipa']
            expected = entry['Shaw']
            predicted = ipa_to_shavian(ipa)

            total += 1
            if predicted == expected:
                correct += 1
            else:
                mismatches.append({
                    'word': entry['Latn'],
                    'ipa': ipa,
                    'expected': expected,
                    'predicted': predicted,
                    'pos': entry.get('pos', ''),
                })

    accuracy = correct / total * 100 if total else 0
    result = {
        'total': total,
        'correct': correct,
        'incorrect': len(mismatches),
        'accuracy': accuracy,
        'mismatches': mismatches,
    }

    if verbose:
        print(f"Total entries: {total}")
        print(f"Correct:       {correct} ({accuracy:.2f}%)")
        print(f"Mismatches:    {len(mismatches)}")
        print()
        # Show first 50 mismatches
        for m in mismatches[:50]:
            print(f"  {m['word']:25s} ipa={m['ipa']:35s}")
            print(f"    expected:  {m['expected']}")
            print(f"    predicted: {m['predicted']}")
            print()

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IPA-to-Shavian converter")
    parser.add_argument("--validate", action="store_true",
                        help="Validate against ReadLex")
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed mismatches")
    parser.add_argument("--ipa", type=str,
                        help="Convert a single IPA string")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    readlex_path = project_root / "external" / "readlex" / "readlex.json"

    if args.ipa:
        print(ipa_to_shavian(args.ipa))
    elif args.validate:
        result = validate_against_readlex(str(readlex_path), verbose=args.verbose)
        print(f"\nAccuracy: {result['accuracy']:.2f}% ({result['correct']}/{result['total']})")
        if not args.verbose and result['mismatches']:
            print(f"Run with --verbose to see mismatches")
    else:
        parser.print_help()
