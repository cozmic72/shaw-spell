#!/usr/bin/env python3
"""
Deduplicate editorial.csv in-place: collapse rows that differ only in source.

When multiple rows share the same (word, pos, var, shaw), keeps the one with
the most editorial content (non-blank verdict/overrides), merges sources with +.

Preserves all existing edits. Safe to run repeatedly.

Usage:
    python3 src/tools/dedup_editorial.py
"""

import csv
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
EDITORIAL_PATH = PROJECT_ROOT / "data" / "editorial.csv"

COLUMNS = [
    "word", "pos", "var", "shaw", "ipa", "verdict",
    "shaw_override", "pos_override", "var_override",
    "source", "status", "confidence", "notes",
]


def read_csv(path):
    """Read editorial CSV."""
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
            for col in COLUMNS:
                if col not in cleaned:
                    cleaned[col] = ""
            rows.append(cleaned)
    return rows


def has_edits(row):
    """Check if a row has any human editorial content."""
    return any(row.get(col, "") for col in ("shaw_override", "pos_override", "var_override", "verdict"))


def merge_rows(group):
    """Merge a group of duplicate rows into one, preserving edits."""
    # Prefer the row with the most editorial content
    edited = [r for r in group if has_edits(r)]
    if edited:
        # If multiple edited rows (shouldn't happen), take the first
        best = edited[0]
    else:
        # Take highest confidence
        best = max(group, key=lambda r: int(r.get("confidence", 0) or 0))

    # Merge sources
    all_sources = sorted(set(r["source"] for r in group if r["source"]))
    best["source"] = "+".join(all_sources)

    # Merge notes (deduplicated)
    all_notes = set()
    for r in group:
        if r.get("notes"):
            all_notes.add(r["notes"])
    best["notes"] = "; ".join(sorted(all_notes)) if all_notes else ""

    # Take highest confidence
    best["confidence"] = str(max(int(r.get("confidence", 0) or 0) for r in group))

    return best


def write_csv(path, rows):
    """Write CSV with minimal quoting (lossless — preserves embedded commas/newlines)."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL,
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: str(row.get(col, "")) for col in COLUMNS})


def main():
    print(f"Reading {EDITORIAL_PATH}...")
    rows = read_csv(EDITORIAL_PATH)
    print(f"  {len(rows):,} rows")

    # Group by identity key
    groups = defaultdict(list)
    for row in rows:
        key = (row["word"].lower(), row["pos"], row["var"], row["shaw"])
        groups[key].append(row)

    # Merge duplicates
    merged = []
    dupes_merged = 0
    for key, group in groups.items():
        if len(group) > 1:
            merged.append(merge_rows(group))
            dupes_merged += len(group) - 1
        else:
            merged.append(group[0])

    # Sort
    merged.sort(key=lambda r: (r["word"].lower(), r["pos"], r["var"], -int(r.get("confidence", 0) or 0)))

    print(f"  Merged {dupes_merged:,} duplicate rows")
    print(f"  {len(merged):,} rows after dedup")

    write_csv(EDITORIAL_PATH, merged)
    print(f"  Written to {EDITORIAL_PATH}")


if __name__ == "__main__":
    main()
