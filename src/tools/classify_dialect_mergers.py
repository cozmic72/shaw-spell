#!/usr/bin/env python3
"""
Classify each supplement candidate's within-accent vowel mergers, annotating it
with a `mergers` list before it reaches the editorial basis.

The supplement candidates carry a scalar base-accent `var` (every multi-spelling
group is exactly an {RSSB, GenAm} pair — RSSB is the non-merged British standard,
GenAm the merged American accent). This stage layers the merger axis on top: a
GenAm spelling that is an exact vowel-merger swap (trap-bath 𐑭->𐑨 or cot-caught
𐑷->𐑪) of an RSSB sibling in the same (word, pos) group is tagged with that
merger. Its base `var` is unchanged — the flag is additive.

  RSSB record                     -> base RSSB, no merger (the non-merged form)
  GenAm = merger swap of a sibling -> base GenAm, mergers=[<that merger>]
  GenAm differing otherwise        -> base GenAm, no merger (just base accent)
  single spelling for the group    -> no merger

A record's `mergers` is emitted only when non-empty, keeping the field additive:
absent means the empty list. See dialect_mergers.py for the swap detection and
docs/dialect-mergers.md for the model.

This is a pruning-chain stage between the duplicate filter and the identical-
dialect collapse over the source-combined pool: combined-deduped -> HERE
(classified) -> collapsed -> decontaminated -> filtered -> basis. Downstream
stages pass records through verbatim, so the `mergers` annotation survives to the
basis. Only the annotation is added; no candidate is dropped or reshaped, and the
per-record `source` list is preserved by the dict copy.

Because the pool is source-combined, an RSSB sibling one source attested now sits
in the same group as a GenAm candidate from another source, so cross-source
merger swaps are tagged here — intended, and the reason combining runs before
this stage.

Inputs:  data/supplement-combined-deduped.json
Outputs: data/supplement-combined-classified.json

Usage:
    python3 src/tools/classify_dialect_mergers.py
"""

import json
from collections import Counter, defaultdict

from basis import PROJECT_ROOT
from dialect_mergers import merger_of

# (deduped input, classified output) — one combined pool.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-deduped.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-classified.json"

# The non-merged British standard: an RSSB spelling is the canonical form a GenAm
# merger swap is measured against, and is never itself tagged.
BASE_NON_MERGED = "RSSB"

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def non_merged_spellings(supplement):
    """(word_lower, pos) -> the set of RSSB spellings attesting it. These are the
    canonical forms a GenAm candidate's merger swap is measured against."""
    index = defaultdict(set)
    for entries in supplement.values():
        for entry in entries:
            if entry.get("var") == BASE_NON_MERGED:
                index[(entry["Latn"].lower(), entry["pos"])].add(entry["Shaw"])
    return index


def merger_for(entry, non_merged_index):
    """The (merger, non_merged_sibling) `entry` is tagged with, or (None, None).
    Only a GenAm spelling that is an exact merger swap of some RSSB sibling in its
    (word, pos) group is tagged; RSSB (and unmatched GenAm) forms carry none."""
    if entry.get("var") == BASE_NON_MERGED:
        return None, None
    siblings = non_merged_index.get((entry["Latn"].lower(), entry["pos"]))
    if not siblings:
        return None, None
    shaw = entry["Shaw"]
    # Sorted so the tagged merger and its reported sibling are deterministic
    # regardless of set iteration order.
    for sibling in sorted(siblings):
        merger = merger_of(sibling, shaw)
        if merger is not None:
            return merger, sibling
    return None, None


def classify_supplement(supplement, tallies, samples):
    """A copy of a supplement dict with each record's `mergers` set. The field is
    written only when non-empty (additive: absent == empty)."""
    non_merged_index = non_merged_spellings(supplement)
    classified = {}
    for key, entries in supplement.items():
        annotated = []
        for entry in entries:
            record = dict(entry)
            merger, sibling = merger_for(entry, non_merged_index)
            if merger is not None:
                record["mergers"] = [merger]
                tallies[merger] += 1
                if len(samples[merger]) < SAMPLE_LIMIT:
                    samples[merger].append((entry, sibling))
            else:
                record.pop("mergers", None)
                tallies["none"] += 1
            annotated.append(record)
        classified[key] = annotated
    return classified


def report(tallies, samples):
    tagged = tallies["trap-bath"] + tallies["cot-caught"]
    total = tagged + tallies["none"]
    print("\n=== dialect merger classification report ===")
    print(f"Records classified: {total:,}")
    print(f"  trap-bath tagged: {tallies['trap-bath']:,}")
    print(f"  cot-caught tagged:{tallies['cot-caught']:,}")
    print(f"  no merger:        {tallies['none']:,}")

    for merger in ("trap-bath", "cot-caught"):
        print(f"\nSample [{merger}]:")
        for entry, sibling in samples[merger]:
            print(f"  {entry['Latn']} [{entry['pos']}]: "
                  f"RSSB {sibling} -> GenAm {entry['Shaw']}")


def main():
    tallies = Counter()
    samples = defaultdict(list)

    supplement = load_json(INPUT_PATH)
    classified = classify_supplement(supplement, tallies, samples)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(classified, f, ensure_ascii=False, indent=4)
    tagged = sum(1 for entries in classified.values()
                 for entry in entries if entry.get("mergers"))
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in classified.values()):,} records, "
          f"{tagged:,} merger-tagged")

    report(tallies, samples)


if __name__ == "__main__":
    main()
