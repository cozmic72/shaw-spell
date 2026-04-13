#!/usr/bin/env python3
"""Generate a TSV report of fragment/affix entries in Wiktionary supplement data.

Identifies two kinds of rejects:
  - Affix words: Latn field starts or ends with '-'
  - Fragment Shaw: Shaw field starts or ends with '-' but Latn does NOT have '-'

For each reject, tries to find a "full form" — another entry for the same word
(same Latn, same var) where Shaw does NOT start/end with '-'.
"""

import json
import csv
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
RELIABLE = PROJECT / "data" / "supplement-wiktionary-reliable.json"
SPECULATIVE = PROJECT / "data" / "supplement-wiktionary-speculative.json"
OUTPUT = PROJECT / "data" / "review-wiktionary-rejects.tsv"


def has_dash(s: str) -> bool:
    return s.startswith("-") or s.endswith("-")


def load_entries(path: Path, speculative: bool = False):
    """Yield (entry_dict, is_speculative) for every entry in a supplement file."""
    if not path.exists():
        return
    with open(path) as f:
        data = json.load(f)
    for key, variants in data.items():
        if not isinstance(variants, list):
            variants = [variants]
        for entry in variants:
            yield entry, speculative


def main():
    # Collect all entries and index full forms for lookup
    all_entries = []
    # full_forms: (latn_lower, var) -> list of entries with clean Shaw
    full_forms: dict[tuple[str, str], list[dict]] = {}

    sources = [
        (RELIABLE, False),
        (SPECULATIVE, True),
    ]

    for path, spec in sources:
        for entry, is_spec in load_entries(path, speculative=spec):
            all_entries.append((entry, is_spec))
            latn = entry.get("Latn", "")
            shaw = entry.get("Shaw", "")
            var = entry.get("var", "")
            if not has_dash(latn) and not has_dash(shaw):
                key = (latn.lower(), var)
                full_forms.setdefault(key, []).append(entry)

    # Identify rejects
    rejects = []
    for entry, is_spec in all_entries:
        latn = entry.get("Latn", "")
        shaw = entry.get("Shaw", "")
        var = entry.get("var", "")

        if has_dash(latn):
            rtype = "affix-spec" if is_spec else "affix"
        elif has_dash(shaw):
            rtype = "fragment-spec" if is_spec else "fragment"
        else:
            continue

        # Look for full form (same word, same var, clean Shaw)
        # For affixes, strip dashes from Latn for lookup
        lookup_word = latn.strip("-").lower()
        candidates = full_forms.get((lookup_word, var), [])
        # Pick the highest-confidence full form
        best = max(candidates, key=lambda e: e.get("confidence", 0)) if candidates else None

        rejects.append({
            "type": rtype,
            "word": latn,
            "pos": entry.get("pos", ""),
            "var": var,
            "ipa": entry.get("ipa", ""),
            "shaw_fragment": shaw,
            "full_ipa": best["ipa"] if best else "",
            "full_shaw": best["Shaw"] if best else "",
            "confidence": entry.get("confidence", ""),
        })

    # Sort by type, then word
    rejects.sort(key=lambda r: (r["type"], r["word"].lower()))

    # Write TSV
    fieldnames = [
        "type", "word", "pos", "var", "ipa",
        "shaw_fragment", "full_ipa", "full_shaw", "confidence",
    ]
    with open(OUTPUT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rejects)

    # Summary stats
    total = len(rejects)
    affix_count = sum(1 for r in rejects if r["type"].startswith("affix"))
    fragment_count = sum(1 for r in rejects if r["type"].startswith("fragment"))
    fragments_with_full = sum(
        1 for r in rejects
        if r["type"].startswith("fragment") and r["full_shaw"]
    )

    print(f"Total rejects: {total}")
    print(f"  Affix entries:    {affix_count}")
    print(f"  Fragment entries:  {fragment_count}")
    print(f"  Fragments with full form available: {fragments_with_full}")
    print(f"Output written to: {OUTPUT}")


if __name__ == "__main__":
    main()
