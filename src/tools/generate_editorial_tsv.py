#!/usr/bin/env python3
"""
Generate editorial TSV files for reviewing supplement entries against ReadLex.

Appends new entries to existing editorial.tsv, preserving all previous verdicts
and overrides. Run this after updating supplement data to pick up new entries.

Outputs:
  data/editorial.tsv            — entries needing editorial review (collapsed across dialects)
  data/editorial-duplicates.tsv — entries that match ReadLex (word, shaw)
  data/editorial-drops.tsv      — fragments, affixes, and other rejects
  data/readlex-reference.tsv    — all ReadLex entries for reference

See data/README.md for column reference and workflow documentation.

Usage:
    python3 src/tools/generate_editorial_tsv.py           # append new entries
    python3 src/tools/generate_editorial_tsv.py --rebuild  # regenerate from scratch
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"

SUPPLEMENTS = [
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"),
]

EDITORIAL_PATH = PROJECT_ROOT / "data" / "editorial.tsv"
DUPLICATES_PATH = PROJECT_ROOT / "data" / "editorial-duplicates.tsv"
DROPS_PATH = PROJECT_ROOT / "data" / "editorial-drops.tsv"
REFERENCE_PATH = PROJECT_ROOT / "data" / "readlex-reference.tsv"

COLUMNS = [
    "word", "pos", "var", "shaw", "ipa", "confidence", "source", "status",
    "readlex_var", "shaw_override", "pos_override", "var_override", "verdict", "notes",
]


def sort_key(row):
    """Sort by word (case-insensitive), pos, var, confidence descending."""
    return (row["word"].lower(), row["pos"], row["var"], -int(row["confidence"]))


def classify_status(word, shaw, readlex_words):
    """Determine status based on word, shaw, and ReadLex presence."""
    if word.startswith("-") or word.endswith("-"):
        return "affix"
    if shaw.startswith("-") or shaw.endswith("-"):
        return "fragment"
    if word.lower() in readlex_words:
        return "supplement"  # alternate spelling/pronunciation of existing word
    return "new"  # word not in ReadLex at all


def sanitize_field(value):
    """Replace tabs and newlines in field values."""
    if isinstance(value, str):
        return value.replace("\t", " ").replace("\n", " ").replace("\r", "")
    return value


def format_tsv_field(value):
    """Format a field for TSV output, quoting if necessary (Numbers-compatible)."""
    val = str(sanitize_field(value))
    if '"' in val:
        val = '"' + val.replace('"', '""') + '"'
    elif ',' in val:
        val = '"' + val + '"'
    return val


def write_tsv(path, columns, rows):
    """Write rows to a TSV file in Apple Numbers-compatible format (CRLF, no trailing newline)."""
    with open(path, "wb") as f:
        lines = ["\t".join(columns)]
        for row in rows:
            lines.append("\t".join(format_tsv_field(row[col]) for col in columns))
        f.write("\r\n".join(lines).encode("utf-8"))


def read_existing_editorial(path):
    """Read an existing editorial TSV, returning rows and a set of identity keys."""
    rows = []
    keys = set()
    if not path.exists():
        return rows, keys

    with open(path, "r", encoding="utf-8", newline="") as f:
        content = f.read()
    # Handle CRLF
    lines = content.split("\n")
    if not lines:
        return rows, keys

    reader = csv.DictReader(lines, delimiter="\t")
    for row in reader:
        # Strip CRLF artifacts from values
        cleaned = {}
        for k, v in row.items():
            if k is None:
                continue
            k = k.strip().rstrip("\r")
            cleaned[k] = v.strip().rstrip("\r") if v else ""
        # Ensure all columns present
        for col in COLUMNS:
            if col not in cleaned:
                cleaned[col] = ""
        rows.append(cleaned)
        # Identity key: (word_lower, pos, shaw) — var excluded because collapsing changes it
        identity = (cleaned["word"].lower(), cleaned["pos"], cleaned["shaw"])
        keys.add(identity)

    return rows, keys


def generate_editorial(rebuild=False):
    """Generate editorial TSV files from supplement data.

    In append mode (default), reads existing editorial.tsv and only adds
    entries not already present. All existing verdicts/overrides are preserved.

    In rebuild mode (--rebuild), regenerates from scratch.
    """
    # Load ReadLex for lookups
    readlex_shaw_vars = defaultdict(set)  # (word_lower, shaw) -> set of var tags
    readlex_words = set()  # all words in ReadLex (lowercase)
    if READLEX_PATH.exists():
        with open(READLEX_PATH, "r", encoding="utf-8") as f:
            readlex = json.load(f)
        for _key, entries in readlex.items():
            for entry in entries:
                var = entry.get("var", "") or "RRP"
                readlex_shaw_vars[(entry["Latn"].lower(), entry["Shaw"])].add(var)
                readlex_words.add(entry["Latn"].lower())
        print(f"Loaded ReadLex: {len(readlex_shaw_vars):,} unique (word, shaw) pairs, {len(readlex_words):,} words")

    # Load existing editorial files if appending
    if rebuild:
        existing_editorial, existing_editorial_keys = [], set()
        existing_duplicates, existing_duplicates_keys = [], set()
        existing_drops, existing_drops_keys = [], set()
        print("Rebuild mode: regenerating all files from scratch")
    else:
        existing_editorial, existing_editorial_keys = read_existing_editorial(EDITORIAL_PATH)
        existing_duplicates, existing_duplicates_keys = read_existing_editorial(DUPLICATES_PATH)
        existing_drops, existing_drops_keys = read_existing_editorial(DROPS_PATH)
        print(f"Loaded existing: {len(existing_editorial):,} editorial, "
              f"{len(existing_duplicates):,} duplicates, {len(existing_drops):,} drops")

    all_existing_keys = existing_editorial_keys | existing_duplicates_keys | existing_drops_keys

    # Collect all supplement entries
    new_editorial = []
    new_duplicates = []
    new_drops = []
    skipped_existing = 0

    for source_name, supplement_path in SUPPLEMENTS:
        if not supplement_path.exists():
            print(f"  WARNING: {supplement_path} not found, skipping")
            continue

        with open(supplement_path, "r", encoding="utf-8") as f:
            supplement = json.load(f)

        for _key, entries in supplement.items():
            for entry in entries:
                word = entry.get("Latn", "")
                shaw = entry.get("Shaw", "")
                pos = entry.get("pos", "UNC")
                var = entry.get("var", "")
                status = classify_status(word, shaw, readlex_words)

                rl_vars = readlex_shaw_vars.get((word.lower(), shaw))
                readlex_var = ", ".join(sorted(rl_vars)) if rl_vars else ""

                # Check if already in any existing file
                identity = (word.lower(), pos, shaw)
                if identity in all_existing_keys:
                    skipped_existing += 1
                    continue

                row = {
                    "word": word,
                    "pos": pos,
                    "var": var,
                    "shaw": shaw,
                    "ipa": entry.get("ipa", ""),
                    "confidence": entry.get("confidence", 0),
                    "source": source_name,
                    "status": status,
                    "readlex_var": readlex_var,
                    "shaw_override": "",
                    "pos_override": "",
                    "var_override": "",
                    "verdict": "",
                    "notes": entry.get("review", ""),
                }

                # Route to the right bucket
                if status in ("affix", "fragment"):
                    row["verdict"] = "drop"
                    new_drops.append(row)
                elif readlex_var:
                    row["verdict"] = "duplicate"
                    new_duplicates.append(row)
                elif " " in word and "shave_agrees" in row.get("notes", ""):
                    row["verdict"] = "drop"
                    new_drops.append(row)
                else:
                    new_editorial.append(row)

    # Generate CotCaught variants from GenAm entries that contain 𐑪 (LOT).
    # GenAm IPA never has true LOT — bare ɔ/ɑ gets normalized to ɒ→𐑪 during
    # supplement generation. The original vowel was the merged cot-caught vowel,
    # so we also emit a variant with 𐑷 (THOUGHT) for Americans who write it that way.
    LOT = "𐑪"
    THOUGHT = "𐑷"
    cot_caught_entries = []
    for row in list(new_editorial):
        if row["var"] != "GenAm":
            continue
        if LOT not in row["shaw"]:
            continue
        variant_shaw = row["shaw"].replace(LOT, THOUGHT)
        variant_identity = (row["word"].lower(), row["pos"], variant_shaw)
        if variant_identity in all_existing_keys:
            continue
        # Check it's not already a duplicate of ReadLex
        rl_vars = readlex_shaw_vars.get((row["word"].lower(), variant_shaw))
        if rl_vars:
            continue
        cot_caught_entries.append({
            "word": row["word"],
            "pos": row["pos"],
            "var": "CotCaught",
            "shaw": variant_shaw,
            "ipa": row["ipa"],
            "confidence": row["confidence"],
            "source": row["source"],
            "status": row["status"],
            "readlex_var": "",
            "shaw_override": "",
            "pos_override": "",
            "var_override": "",
            "verdict": "",
            "notes": "cot-caught variant of GenAm " + row["shaw"],
        })
    new_editorial.extend(cot_caught_entries)

    print(f"Skipped (already in editorial files): {skipped_existing:,}")
    print(f"CotCaught variants generated: {len(cot_caught_entries):,}")
    print(f"New entries: {len(new_editorial):,} editorial, "
          f"{len(new_duplicates):,} duplicates, {len(new_drops):,} drops")

    # Combine existing + new
    all_editorial = list(existing_editorial) + new_editorial
    all_duplicates = list(existing_duplicates) + new_duplicates
    all_drops = list(existing_drops) + new_drops

    # Collapse same-shaw dialect pairs in editorial rows (new entries only;
    # existing rows are already collapsed and may have been edited)
    if new_editorial:
        # Only collapse among the new entries
        grouped = defaultdict(list)
        for row in new_editorial:
            grouped[(row["word"].lower(), row["pos"], row["shaw"])].append(row)

        collapsed_new = []
        collapse_count = 0
        for (word_lower, pos, shaw), group in grouped.items():
            vars_in_group = set(r["var"] for r in group)
            if "RSSB" in vars_in_group and "GenAm" in vars_in_group:
                best = max(group, key=lambda r: int(r["confidence"]))
                best["var"] = "RRP"
                all_sources = sorted(set(r["source"] for r in group))
                best["source"] = "+".join(all_sources)
                collapse_count += len(group) - 1
                collapsed_new.append(best)
            else:
                collapsed_new.extend(group)

        # Replace new_editorial portion with collapsed version
        all_editorial = list(existing_editorial) + collapsed_new
        print(f"Collapsed dialect pairs (new entries): {collapse_count:,} rows removed")

    all_editorial.sort(key=sort_key)
    all_duplicates.sort(key=sort_key)
    all_drops.sort(key=sort_key)

    write_tsv(EDITORIAL_PATH, COLUMNS, all_editorial)
    write_tsv(DUPLICATES_PATH, COLUMNS, all_duplicates)
    write_tsv(DROPS_PATH, COLUMNS, all_drops)

    # Stats
    print(f"\n=== editorial.tsv ===")
    print(f"Total rows: {len(all_editorial):,}")
    verdict_counts = defaultdict(int)
    status_counts = defaultdict(int)
    for row in all_editorial:
        v = row["verdict"] or "(needs review)"
        verdict_counts[v] += 1
        status_counts[row["status"]] += 1
    print(f"By status:")
    for s in sorted(status_counts):
        print(f"  {s:16s} {status_counts[s]:,}")
    print(f"By verdict:")
    for v in sorted(verdict_counts):
        print(f"  {v:20s} {verdict_counts[v]:,}")

    print(f"\n=== editorial-duplicates.tsv ===")
    print(f"Total rows: {len(all_duplicates):,}")

    print(f"\n=== editorial-drops.tsv ===")
    print(f"Total rows: {len(all_drops):,}")

    return all_editorial


def generate_readlex_reference():
    """Generate readlex-reference.tsv from ReadLex."""
    if not READLEX_PATH.exists():
        print(f"ERROR: {READLEX_PATH} not found")
        sys.exit(1)

    with open(READLEX_PATH, "r", encoding="utf-8") as f:
        readlex = json.load(f)

    rows = []
    for _key, entries in readlex.items():
        for entry in entries:
            var = entry.get("var", "") or "RRP"

            rows.append({
                "word": entry.get("Latn", ""),
                "pos": entry.get("pos", "UNC"),
                "var": var,
                "shaw": entry.get("Shaw", ""),
                "ipa": entry.get("ipa", ""),
                "confidence": 100,
                "source": "readlex",
                "status": "readlex",
                "readlex_var": "",
                "shaw_override": "",
                "pos_override": "",
                "var_override": "",
                "verdict": var,
                "notes": "",
            })

    rows.sort(key=sort_key)
    write_tsv(REFERENCE_PATH, COLUMNS, rows)

    var_counts = defaultdict(int)
    for row in rows:
        var_counts[row["var"]] += 1

    print(f"\n=== readlex-reference.tsv ===")
    print(f"Total rows: {len(rows):,}")
    print(f"By var/verdict:")
    for v in sorted(var_counts):
        print(f"  {v:16s} {var_counts[v]:,}")

    return rows


def main():
    rebuild = "--rebuild" in sys.argv

    print("Generating editorial TSV files...")
    generate_editorial(rebuild=rebuild)
    generate_readlex_reference()
    print(f"\nWritten:")
    print(f"  {EDITORIAL_PATH}")
    print(f"  {DUPLICATES_PATH}")
    print(f"  {DROPS_PATH}")
    print(f"  {REFERENCE_PATH}")


if __name__ == "__main__":
    main()
