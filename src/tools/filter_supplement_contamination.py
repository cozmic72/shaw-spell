#!/usr/bin/env python3
"""
Drop supplement candidates whose Shavian carries a contaminating character
before they reach the editorial basis.

ipa_to_shavian passes an unmapped IPA symbol (a foreign/dialectal phoneme
outside PHONEME_MAP) through verbatim, so a candidate's `Shaw` can end up with a
Latin letter, an IPA symbol, a diacritic or a digit in it — e.g. `𐑕𐑑𐑸 𐑑𐑮ĕ𐑒`
(Star Trek, ĕ U+0115) or `𐑩𐑚ʏ𐑯` (aboon, ʏ U+028F). Shavian has no such
characters; the record is garbage and must not reach the reviewer. A candidate
is dropped iff its `Shaw` contains any character that is NOT a Shavian letter
(U+10450–U+1047F), a space, a hyphen, an apostrophe or the naming dot — the
contamination test contains_non_shavian defines in ipa_to_shavian.py, reused
here so the drop rule and the converter's own notion of "non-Shavian" cannot
drift. Legit hyphen/apostrophe/space/naming-dot candidates are untouched.

This runs ONLY on the supplement candidates, never on upstream ReadLex: the
ring-point/word-joiner acronym markers, variation-selector ligatures, digits and
hyphens in the shipped dictionary are intentional ReadLex conventions, not
review candidates. A candidate a patch already anchors to has left the review
surface and is exempt — dropping it would orphan the patch's anchor
(apply_patches.py fails loud on that).

This is a pruning-chain stage between the identical-dialect collapse and the
phrase filter over the source-combined pool: combined-collapsed -> HERE
(decontaminated) -> filtered -> basis. The phrase filter reads the decontaminated
output next; records pass through verbatim (only contaminated ones are dropped),
so each candidate's `mergers` annotation and `source` list survive.

Inputs:  data/supplement-combined-collapsed.json,
         data/patches/patches.jsonl.
Outputs: data/supplement-combined-decontaminated.json  — the phrase filter reads
         this next. The combined-collapsed file is left untouched; the dropped
         candidates are regenerable machine output.

Usage:
    python3 src/tools/filter_supplement_contamination.py
"""

import json
from collections import Counter

from basis import PROJECT_ROOT, anchor_of
from filter_supplement_duplicates import anchored_keys, load_patches
from ipa_to_shavian import contains_non_shavian

# (collapsed input, decontaminated output) — one combined pool.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-collapsed.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-decontaminated.json"

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prune_supplement(supplement, exempt_keys, dropped_samples):
    """A copy of a supplement dict with contaminated candidates removed. A
    candidate whose `Shaw` contains a non-Shavian character is dropped unless a
    patch anchors it (it has left the review surface). Returns (pruned,
    dropped_count)."""
    pruned = {}
    dropped = 0
    for key, entries in supplement.items():
        kept_entries = []
        for entry in entries:
            if (contains_non_shavian(entry["Shaw"])
                    and anchor_of(entry) not in exempt_keys):
                dropped += 1
                if len(dropped_samples) < SAMPLE_LIMIT:
                    dropped_samples.append(entry)
                continue
            kept_entries.append(entry)
        if kept_entries:
            pruned[key] = kept_entries
    return pruned, dropped


def format_entry(entry):
    contaminants = "".join(sorted(
        {ch for ch in entry["Shaw"] if contains_non_shavian(ch)}))
    return (f"{entry['Latn']!r} shaw={entry['Shaw']} "
            f"contaminants={contaminants!r}")


def report(total_dropped, dropped_samples):
    print("\n=== contamination pruning report ===")
    print(f"Dropped (non-Shavian in Shaw): {total_dropped:,}")
    print("\nSample dropped (unmapped IPA passthrough):")
    for entry in dropped_samples:
        print(f"  {format_entry(entry)}")


def main():
    exempt_keys = anchored_keys(load_patches())

    dropped_samples = []
    total_dropped = 0

    supplement = load_json(INPUT_PATH)
    pruned, dropped = prune_supplement(supplement, exempt_keys, dropped_samples)
    total_dropped += dropped
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in pruned.values()):,} candidates kept")

    report(total_dropped, dropped_samples)


if __name__ == "__main__":
    main()
