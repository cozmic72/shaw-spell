#!/usr/bin/env python3
"""
Generate a merged readlex.json that includes the original ReadLex entries
plus high-confidence supplement entries, appropriately flagged.

Original ReadLex entries: untouched (no new fields)
Supplement entries: tagged with source, confidence, status="supplement"

Usage:
    python3 src/tools/generate_merged_readlex.py [--min-confidence N]
"""

import json
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "readlex.json"

SUPPLEMENTS = [
    ("britfone", PROJECT_ROOT / "data" / "supplement-britfone.json"),
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"),
]


def main():
    parser = argparse.ArgumentParser(description="Generate merged ReadLex with supplements")
    parser.add_argument("--min-confidence", type=int, default=80,
                        help="Minimum confidence %% to include (default: 80)")
    args = parser.parse_args()

    # Load original ReadLex
    print(f"Loading ReadLex from {READLEX_PATH}...")
    with open(READLEX_PATH, 'r', encoding='utf-8') as f:
        merged = json.load(f)

    original_keys = len(merged)
    original_entries = sum(len(v) for v in merged.values())
    print(f"  Original: {original_keys:,} keys, {original_entries:,} entries")

    # Build lookup of existing words (for dedup reporting)
    existing_words = set()
    for key, entries in merged.items():
        for e in entries:
            existing_words.add(e['Latn'].lower())

    # Track stats
    stats = {
        "added_keys": 0,
        "added_entries": 0,
        "skipped_low_confidence": 0,
        "skipped_numeral": 0,
        "skipped_unknown_chars": 0,
        "overlap_entries": 0,
        "new_word_entries": 0,
        "by_source": {},
    }

    # Valid Shavian chars (for filtering)
    known_shaw = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘"
                     "𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")

    for source_name, supplement_path in SUPPLEMENTS:
        if not supplement_path.exists():
            print(f"  Skipping {source_name}: file not found")
            continue

        print(f"\nProcessing {source_name}...")
        with open(supplement_path, 'r', encoding='utf-8') as f:
            supplement = json.load(f)

        source_stats = {"added": 0, "skipped": 0, "overlap": 0, "new": 0}

        for key, entries in supplement.items():
            for entry in entries:
                confidence = entry.get("confidence", 0)

                # Filter: minimum confidence
                if confidence < args.min_confidence:
                    stats["skipped_low_confidence"] += 1
                    source_stats["skipped"] += 1
                    continue

                # Filter: skip numerals
                word = entry.get("Latn", "")
                if word and word[0].isdigit():
                    stats["skipped_numeral"] += 1
                    source_stats["skipped"] += 1
                    continue

                # Filter: skip entries with unconverted IPA chars in Shavian
                shaw = entry.get("Shaw", "")
                if set(shaw) - known_shaw:
                    stats["skipped_unknown_chars"] += 1
                    source_stats["skipped"] += 1
                    continue

                # Build the merged entry
                merged_entry = {
                    "Latn": entry["Latn"],
                    "Shaw": entry["Shaw"],
                    "pos": entry.get("pos", "UNC"),
                    "ipa": entry.get("ipa", ""),
                    "freq": entry.get("freq", 0),
                    "var": entry.get("var", "UNC"),
                    "confidence": confidence,
                    "source": source_name,
                    "status": "supplement",
                }

                # Include review notes if present
                review = entry.get("review", "")
                if review:
                    merged_entry["review"] = review

                # Build key matching ReadLex convention
                merged_key = f"{entry['Latn']}_{entry.get('pos', 'UNC')}_{entry['Shaw']}"

                # Add to merged dict
                if merged_key not in merged:
                    merged[merged_key] = []
                    stats["added_keys"] += 1

                # Avoid exact duplicates and redundant supplements
                is_dup = False
                for existing in merged[merged_key]:
                    if (existing.get("Latn", "").lower() == merged_entry["Latn"].lower()
                            and existing.get("Shaw") == merged_entry["Shaw"]
                            and existing.get("var") == merged_entry["var"]):
                        # Same word+shaw+var — redundant regardless of source
                        is_dup = True
                        break

                if not is_dup:
                    merged[merged_key].append(merged_entry)
                    stats["added_entries"] += 1
                    source_stats["added"] += 1

                    if word.lower() in existing_words:
                        stats["overlap_entries"] += 1
                        source_stats["overlap"] += 1
                    else:
                        stats["new_word_entries"] += 1
                        source_stats["new"] += 1

        stats["by_source"][source_name] = source_stats
        print(f"  Added {source_stats['added']:,} entries "
              f"({source_stats['new']:,} new words, {source_stats['overlap']:,} overlapping)")
        print(f"  Skipped {source_stats['skipped']:,} (below confidence / filtered)")

    # Write output
    print(f"\nWriting merged readlex to {OUTPUT_PATH}...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)

    final_keys = len(merged)
    final_entries = sum(len(v) for v in merged.values())

    print(f"\n=== Summary ===")
    print(f"Original ReadLex:    {original_keys:,} keys, {original_entries:,} entries")
    print(f"Merged ReadLex:      {final_keys:,} keys, {final_entries:,} entries")
    print(f"New keys added:      {stats['added_keys']:,}")
    print(f"New entries added:    {stats['added_entries']:,}")
    print(f"  New words:         {stats['new_word_entries']:,}")
    print(f"  Overlap entries:   {stats['overlap_entries']:,}")
    print(f"Skipped:")
    print(f"  Low confidence:    {stats['skipped_low_confidence']:,}")
    print(f"  Numerals:          {stats['skipped_numeral']:,}")
    print(f"  Unknown chars:     {stats['skipped_unknown_chars']:,}")
    print(f"Min confidence:      {args.min_confidence}%")
    print()
    for source, ss in stats["by_source"].items():
        print(f"  {source}: +{ss['added']:,} ({ss['new']:,} new, {ss['overlap']:,} overlap, {ss['skipped']:,} skipped)")


if __name__ == "__main__":
    main()
