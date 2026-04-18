#!/usr/bin/env python3
"""
Generate a merged readlex.json that includes the original ReadLex entries
plus editorially approved supplement entries.

When an editorial.tsv exists, only entries with verdict "keep" or "supplemental"
are included. Override columns (shaw_override, pos_override, var_override) are
applied. When no editorial.tsv exists, falls back to confidence-based filtering.

Original ReadLex entries: untouched (no new fields)
Supplement entries: tagged with source, confidence, status="supplement"

Usage:
    python3 src/tools/generate_merged_readlex.py [--min-confidence N]
"""

import csv
import json
import argparse
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "readlex.json"
EDITORIAL_PATH = PROJECT_ROOT / "data" / "editorial.tsv"
EDITORIAL_MANUAL_PATH = PROJECT_ROOT / "data" / "editorial-manual.tsv"
EDITORIAL_POS_GAPS_PATH = PROJECT_ROOT / "data" / "editorial-pos-gaps.tsv"

SUPPLEMENTS = [
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"),
]


def load_editorial():
    """Load editorial verdicts from TSV. Returns dict keyed by (word_lower, pos, shaw)."""
    if not EDITORIAL_PATH.exists():
        return None

    editorial = {}
    with open(EDITORIAL_PATH, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    lines = content.split("\n")
    reader = csv.DictReader(lines, delimiter="\t")
    for row in reader:
        # Clean CRLF artifacts
        cleaned = {}
        for k, v in row.items():
            if k is None:
                continue
            k = k.strip().rstrip("\r")
            cleaned[k] = v.strip().rstrip("\r") if v else ""

        word = cleaned.get("word", "")
        pos = cleaned.get("pos", "")
        shaw = cleaned.get("shaw", "")
        key = (word.lower(), pos, shaw)

        editorial[key] = {
            "verdict": cleaned.get("verdict", ""),
            "shaw_override": cleaned.get("shaw_override", ""),
            "pos_override": cleaned.get("pos_override", ""),
            "var_override": cleaned.get("var_override", ""),
            "ipa_override": cleaned.get("ipa_override", ""),
        }

    return editorial


def load_editorial_tsv(path, require_keep_verdict=False):
    """Load editorial entries from a TSV with the standard column layout.

    Returns a list of row-dicts (one per row). When require_keep_verdict is
    True, only rows with verdict == 'keep' are returned — used for the
    pos-gaps file where most rows are unreviewed.
    """
    if not path.exists():
        return None

    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    lines = content.split("\n")
    reader = csv.DictReader(lines, delimiter="\t")
    for row in reader:
        cleaned = {}
        for k, v in row.items():
            if k is None:
                continue
            k = k.strip().rstrip("\r")
            cleaned[k] = v.strip().rstrip("\r") if v else ""
        if not cleaned.get("word"):
            continue
        if require_keep_verdict and cleaned.get("verdict") != "keep":
            continue
        rows.append(cleaned)
    return rows


def apply_manual_overrides(merged, manual_rows, source_label="manual"):
    """Apply editorial entries to the merged dict.

    For each row, the (Latn-lower, pos, var) triple identifies a slot.
    Any existing entries in that slot are replaced (logged). Entries with the
    same (word, pos) but different var are left alone. Entries with the same
    (word, pos, var) but only a different shaw spelling are also replaced —
    the editorial row is treated as the authoritative spelling for that slot.

    source_label is written into each new entry's source/status fields and
    used in the override log line so different editorial sources are
    distinguishable in output.
    """
    stats = {
        "manual_rows": 0,
        "overrode_existing": 0,
        "added_new": 0,
        "added_to_existing_key": 0,
    }

    # Build an index: (word_lower, pos, var) -> list of (key, entry_index) into merged
    # so we can find and remove what we're overriding.
    slot_index = defaultdict(list)
    for key, entries in merged.items():
        for i, e in enumerate(entries):
            slot = (e.get("Latn", "").lower(), e.get("pos", ""), e.get("var", ""))
            slot_index[slot].append((key, i))

    for row in manual_rows:
        stats["manual_rows"] += 1
        word = row["word"]
        pos = row.get("pos_override") or row["pos"]
        var = row.get("var_override") or row.get("var") or "RRP"
        shaw = row.get("shaw_override") or row["shaw"]
        ipa = row.get("ipa_override") or row.get("ipa", "")
        notes = row.get("notes", "")

        slot = (word.lower(), pos, var)

        # Remove any existing entries in this slot (across any merged keys),
        # logging each replacement.
        for old_key, _idx in slot_index.get(slot, []):
            old_entries = merged.get(old_key, [])
            kept = []
            for e in old_entries:
                e_slot = (e.get("Latn", "").lower(), e.get("pos", ""), e.get("var", ""))
                if e_slot == slot:
                    print(f"  {source_label} override: {word!r} pos={pos} var={var} "
                          f"old shaw={e.get('Shaw')!r} → new shaw={shaw!r}")
                    stats["overrode_existing"] += 1
                else:
                    kept.append(e)
            if kept:
                merged[old_key] = kept
            else:
                del merged[old_key]

        # Build the new entry
        manual_entry = {
            "Latn": word,
            "Shaw": shaw,
            "pos": pos,
            "ipa": ipa,
            "freq": 0,
            "var": var,
            "source": source_label,
            "status": source_label,
        }
        if notes:
            manual_entry["review"] = notes

        merged_key = f"{word}_{pos}_{shaw}"
        if merged_key in merged:
            merged[merged_key].append(manual_entry)
            stats["added_to_existing_key"] += 1
        else:
            merged[merged_key] = [manual_entry]
            stats["added_new"] += 1

    return stats


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

    # Load editorial verdicts
    editorial = load_editorial()
    if editorial is not None:
        reviewed = sum(1 for e in editorial.values() if e["verdict"])
        print(f"  Editorial: {len(editorial):,} entries, {reviewed:,} reviewed")
        use_editorial = True
    else:
        print(f"  Editorial: not found, using confidence-based filtering")
        use_editorial = False

    # Track stats
    stats = {
        "added_keys": 0,
        "added_entries": 0,
        "skipped_low_confidence": 0,
        "skipped_numeral": 0,
        "skipped_unknown_chars": 0,
        "skipped_editorial": 0,
        "skipped_unreviewed": 0,
        "overlap_entries": 0,
        "new_word_entries": 0,
        "by_source": {},
        "by_verdict": defaultdict(int),
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
                word = entry.get("Latn", "")
                shaw = entry.get("Shaw", "")
                pos = entry.get("pos", "UNC")
                var = entry.get("var", "UNC")
                ipa_override = ""

                # Editorial filtering (when editorial.tsv exists)
                if use_editorial:
                    ed_key = (word.lower(), pos, shaw)
                    ed = editorial.get(ed_key)
                    if ed is None:
                        # Not in editorial — skip (it's in drops or duplicates)
                        stats["skipped_editorial"] += 1
                        source_stats["skipped"] += 1
                        continue
                    verdict = ed["verdict"]
                    if verdict not in ("keep", "supplemental"):
                        if verdict == "":
                            stats["skipped_unreviewed"] += 1
                        else:
                            stats["skipped_editorial"] += 1
                        source_stats["skipped"] += 1
                        continue
                    stats["by_verdict"][verdict] += 1
                    # Apply overrides
                    if ed["shaw_override"]:
                        shaw = ed["shaw_override"]
                    if ed["pos_override"]:
                        pos = ed["pos_override"]
                    if ed["var_override"]:
                        var = ed["var_override"]
                    ipa_override = ed.get("ipa_override", "")
                else:
                    # Fallback: confidence-based filtering
                    if confidence < args.min_confidence:
                        stats["skipped_low_confidence"] += 1
                        source_stats["skipped"] += 1
                        continue

                # Filter: skip numerals
                if word and word[0].isdigit():
                    stats["skipped_numeral"] += 1
                    source_stats["skipped"] += 1
                    continue

                # Filter: skip entries with unconverted IPA chars in Shavian
                if set(shaw) - known_shaw:
                    stats["skipped_unknown_chars"] += 1
                    source_stats["skipped"] += 1
                    continue

                # Build the merged entry
                entry_ipa = entry.get("ipa", "")
                if use_editorial and ipa_override:
                    entry_ipa = ipa_override
                merged_entry = {
                    "Latn": word,
                    "Shaw": shaw,
                    "pos": pos,
                    "ipa": entry_ipa,
                    "freq": entry.get("freq", 0),
                    "var": var,
                    "confidence": confidence,
                    "source": source_name,
                    "status": "supplement",
                }

                # Include review notes if present
                review = entry.get("review", "")
                if review:
                    merged_entry["review"] = review

                # Build key matching ReadLex convention
                merged_key = f"{word}_{pos}_{shaw}"

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
        print(f"  Skipped {source_stats['skipped']:,}")

    # Apply pos-gaps (only verdict=keep rows) before manual, so manual still wins
    # on any slot collision.
    pos_gap_rows = load_editorial_tsv(EDITORIAL_POS_GAPS_PATH, require_keep_verdict=True)
    if pos_gap_rows is not None:
        print(f"\nApplying pos-gaps from {EDITORIAL_POS_GAPS_PATH.name} "
              f"({len(pos_gap_rows):,} approved rows)...")
        gap_stats = apply_manual_overrides(merged, pos_gap_rows, source_label="pos-gap")
        stats["pos_gap"] = gap_stats
        print(f"  Approved rows:         {gap_stats['manual_rows']:,}")
        print(f"  Overrode existing:     {gap_stats['overrode_existing']:,}")
        print(f"  Added new key:         {gap_stats['added_new']:,}")
        print(f"  Added to existing key: {gap_stats['added_to_existing_key']:,}")
    else:
        print(f"\nNo pos-gaps file at {EDITORIAL_POS_GAPS_PATH} — skipping.")

    # Apply manual editorial overrides last so they trump everything above.
    manual_rows = load_editorial_tsv(EDITORIAL_MANUAL_PATH)
    if manual_rows is not None:
        print(f"\nApplying manual editorial from {EDITORIAL_MANUAL_PATH.name} "
              f"({len(manual_rows):,} rows)...")
        manual_stats = apply_manual_overrides(merged, manual_rows, source_label="manual")
        stats["manual"] = manual_stats
        print(f"  Manual rows:           {manual_stats['manual_rows']:,}")
        print(f"  Overrode existing:     {manual_stats['overrode_existing']:,}")
        print(f"  Added new key:         {manual_stats['added_new']:,}")
        print(f"  Added to existing key: {manual_stats['added_to_existing_key']:,}")
    else:
        print(f"\nNo manual editorial file at {EDITORIAL_MANUAL_PATH} — skipping.")

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
    if use_editorial:
        print(f"  Not in editorial:  {stats['skipped_editorial']:,}")
        print(f"  Unreviewed:        {stats['skipped_unreviewed']:,}")
        print(f"  By verdict:")
        for v, c in sorted(stats["by_verdict"].items()):
            print(f"    {v:16s}   {c:,}")
    else:
        print(f"  Low confidence:    {stats['skipped_low_confidence']:,}")
    print(f"  Numerals:          {stats['skipped_numeral']:,}")
    print(f"  Unknown chars:     {stats['skipped_unknown_chars']:,}")
    print()
    for source, ss in stats["by_source"].items():
        print(f"  {source}: +{ss['added']:,} ({ss['new']:,} new, {ss['overlap']:,} overlap, {ss['skipped']:,} skipped)")

    # Var distribution
    var_counts = {}
    for key, entries in merged.items():
        for e in entries:
            v = e.get("var", "")
            var_counts[v] = var_counts.get(v, 0) + 1
    print(f"\nVar distribution:")
    for v in sorted(var_counts.keys()):
        label = v if v else "(none)"
        print(f"  {label:16s} {var_counts[v]:,}")


if __name__ == "__main__":
    main()
