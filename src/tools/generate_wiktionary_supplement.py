#!/usr/bin/env python3
"""
Extract pronunciation data from Wiktionary JSONL dump and produce
ReadLex-format JSON supplement files.

Two output files:
  - data/supplement-wiktionary-reliable.json: entries with dialect-labelled IPA
  - data/supplement-wiktionary-speculative.json: entries with IPA but no dialect label

Usage:
    python3 src/tools/generate_wiktionary_supplement.py
"""

import json
import sys
import re
from pathlib import Path
from collections import Counter

# Add tools directory to path for ipa_to_shavian
sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import ipa_to_shavian

PROJECT_ROOT = Path(__file__).parent.parent.parent
WIKTIONARY_JSONL = PROJECT_ROOT / "external" / "wiktionary" / "kaikki.org-dictionary-English.jsonl"
RELIABLE_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"
SPECULATIVE_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-speculative.json"

# POS mapping: Wiktionary → CLAWS C5
POS_MAP = {
    "noun": "NN1",
    "verb": "VVI",
    "adj": "AJ0",
    "adv": "AV0",
    "prep": "PRP",
    "conj": "CJC",
    "pron": "PNP",
    "det": "DT0",
    "intj": "ITJ",
    "name": "NP0",
    "particle": "AV0",
    "num": "CRD",
    "phrase": "UNC",
    "prefix": "UNC",
    "suffix": "UNC",
    "infix": "UNC",
    "affix": "UNC",
    "abbrev": "UNC",
    "contraction": "UNC",
    "character": "UNC",
    "symbol": "UNC",
    "punct": "UNC",
}

# Dialect tag classification
RSSB_TAGS = {"Received-Pronunciation", "UK", "British"}
RGAM_TAGS = {"General-American", "US"}


def classify_dialect(tags: list[str]) -> str | None:
    """Classify a list of tags into a dialect variant.

    Returns "RSSB", "RGAM", or None if no recognizable dialect tag.
    """
    tag_set = set(tags) if tags else set()
    has_rssb = bool(tag_set & RSSB_TAGS)
    has_rgam = bool(tag_set & RGAM_TAGS)
    if has_rssb and not has_rgam:
        return "RSSB"
    if has_rgam and not has_rssb:
        return "RGAM"
    if has_rssb and has_rgam:
        # Both — ambiguous, treat as unlabelled
        return None
    return None


def strip_ipa_delimiters(ipa: str) -> str:
    """Strip surrounding /.../ or [...] from IPA string."""
    ipa = ipa.strip()
    if len(ipa) >= 2:
        if (ipa[0] == '/' and ipa[-1] == '/') or (ipa[0] == '[' and ipa[-1] == ']'):
            ipa = ipa[1:-1]
    return ipa


def clean_ipa(ipa: str) -> str:
    """Clean Wiktionary IPA for use with ipa_to_shavian converter.

    Strips delimiters, removes syllable dots, and handles common
    Wiktionary conventions.
    """
    ipa = strip_ipa_delimiters(ipa)
    # Remove syllable boundary dots
    ipa = ipa.replace('.', '')
    # Remove tie bars
    ipa = ipa.replace('͡', '')
    # Remove parenthesized optional segments like (ə) — keep the content
    ipa = re.sub(r'\(([^)]*)\)', r'\1', ipa)
    return ipa


def is_broad_transcription(ipa_raw: str) -> bool:
    """Check if this is a broad (phonemic) transcription in slashes."""
    ipa_raw = ipa_raw.strip()
    return ipa_raw.startswith('/') and ipa_raw.endswith('/')


def make_key(word: str, pos: str, shaw: str) -> str:
    """Create a ReadLex-format key: word_POS_shaw"""
    return f"{word}_{pos}_{shaw}"


def process_entry(entry: dict, reliable: dict, speculative: dict, stats: Counter):
    """Process a single Wiktionary entry, adding to reliable or speculative dicts."""
    word = entry.get("word", "")
    pos_raw = entry.get("pos", "")
    sounds = entry.get("sounds", [])

    if not word or not sounds:
        return

    pos = POS_MAP.get(pos_raw, "UNC")
    stats["total_entries"] += 1

    # Collect IPA entries, preferring broad transcriptions
    for sound in sounds:
        ipa_raw = sound.get("ipa")
        if not ipa_raw:
            continue

        tags = sound.get("tags", [])

        # Prefer broad transcription (slashes) over narrow (brackets)
        # but accept narrow if that's all we have
        is_broad = is_broad_transcription(ipa_raw)

        ipa_clean = clean_ipa(ipa_raw)
        if not ipa_clean:
            continue

        stats["with_ipa"] += 1

        # Generate Shavian
        try:
            shaw = ipa_to_shavian(ipa_clean)
        except Exception:
            stats["shavian_errors"] += 1
            continue

        if not shaw:
            continue

        dialect = classify_dialect(tags)

        entry_data = {
            "Latn": word,
            "Shaw": shaw,
            "pos": pos,
            "ipa": ipa_clean,
            "freq": 0,
            "var": dialect if dialect else "UNC",
        }

        key = make_key(word, pos, shaw)

        if dialect:
            stats[f"dialect_{dialect}"] += 1
            stats["reliable_entries"] += 1
            if key not in reliable:
                reliable[key] = []
            # Avoid exact duplicates
            if entry_data not in reliable[key]:
                reliable[key].append(entry_data)
        else:
            stats["speculative_entries"] += 1
            if key not in speculative:
                speculative[key] = []
            if entry_data not in speculative[key]:
                speculative[key].append(entry_data)


def main():
    if not WIKTIONARY_JSONL.exists():
        print(f"ERROR: Input file not found: {WIKTIONARY_JSONL}", file=sys.stderr)
        sys.exit(1)

    reliable = {}
    speculative = {}
    stats = Counter()

    print(f"Processing {WIKTIONARY_JSONL}...")
    print("This may take a few minutes for ~1.45M lines.")
    print()

    with open(WIKTIONARY_JSONL, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i > 0 and i % 200000 == 0:
                print(f"  ...processed {i:,} lines ({stats['total_entries']:,} English entries with sounds)")

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                stats["json_errors"] += 1
                continue

            # Only English
            if entry.get("lang_code") != "en":
                stats["non_english"] += 1
                continue

            process_entry(entry, reliable, speculative, stats)

    total_lines = i + 1
    print(f"  ...done. {total_lines:,} total lines.")
    print()

    # Write outputs
    print(f"Writing reliable supplement ({len(reliable):,} keys)...")
    RELIABLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(RELIABLE_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(reliable, f, ensure_ascii=False, indent=2)
    print(f"  -> {RELIABLE_OUTPUT}")

    print(f"Writing speculative supplement ({len(speculative):,} keys)...")
    with open(SPECULATIVE_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(speculative, f, ensure_ascii=False, indent=2)
    print(f"  -> {SPECULATIVE_OUTPUT}")

    print()
    print("=== Summary ===")
    print(f"Total lines in JSONL:       {total_lines:,}")
    print(f"Non-English skipped:        {stats['non_english']:,}")
    print(f"English entries with sounds: {stats['total_entries']:,}")
    print(f"Sound items with IPA:       {stats['with_ipa']:,}")
    print(f"Shavian conversion errors:  {stats['shavian_errors']:,}")
    print(f"JSON parse errors:          {stats['json_errors']:,}")
    print()
    print(f"Reliable entries (dialect-labelled):")
    print(f"  Total:  {stats['reliable_entries']:,}")
    print(f"  RSSB:   {stats['dialect_RSSB']:,}")
    print(f"  RGAM:   {stats['dialect_RGAM']:,}")
    print(f"  Keys:   {len(reliable):,}")
    print()
    print(f"Speculative entries (no dialect label):")
    print(f"  Total:  {stats['speculative_entries']:,}")
    print(f"  Keys:   {len(speculative):,}")


if __name__ == "__main__":
    main()
