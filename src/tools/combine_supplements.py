#!/usr/bin/env python3
"""
Combine the per-source supplement candidates into ONE pool before pruning, so
every downstream filter runs on the union rather than per-source in parallel.

Historically each source (wordnet, wiktionary) was threaded through the whole
pruning chain independently and only met at the basis. That let a cross-source
duplicate slip through: the identical-spelling dialect prune (collapse_identical_
dialects.py) runs per group and could not see that one source's GenAm spelling
and another source's RSSB spelling of the SAME word were the same fact. Combining
first puts both in one group, so the prune collapses them to one record.

Merge key = the FULL anchor (word.lower(), pos, Shaw, var), exactly the identity
basis.anchor_of computes. Two records sharing all four fields are ONE record and
their `source` labels union; two records sharing (word, pos, shaw) but differing
in `var` are KEPT SEPARATE — the dialect prune adjudicates those downstream.

Records gain a `source` LIST field here (they carry none upstream). Sources are
iterated in canonical order; the first to attest an anchor keeps its record
verbatim (wordnet wins on content, matching basis.build_basis's load order), and
every later source that also attests the anchor only adds its label to the list.

Inputs:  data/supplement-wordnet-reliable.json (wordnet uses reliable directly)
         and data/supplement-wiktionary-neardot.json (wiktionary after rescue +
         NEAR syllable-dot correction).
Output:  data/supplement-combined-raw.json  — the duplicate filter reads this
         next. The input files are left untouched.

Usage:
    python3 src/tools/combine_supplements.py
"""

import json
from collections import Counter

from basis import PROJECT_ROOT, anchor_of

# Canonical source order: the first source to attest an anchor keeps its record
# verbatim (wordnet wins on content), matching basis.build_basis's load order.
SOURCES = [
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-neardot.json"),
]

OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-raw.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def combine(tallies):
    """Merge the per-source supplements into one anchor-keyed pool. Returns an
    anchor -> record map in first-seen order; each record carries a `source` list
    accumulating every origin that attested its anchor, deduped and order-stable."""
    merged = {}
    for label, path in SOURCES:
        supplement = load_json(path)
        for entries in supplement.values():
            for entry in entries:
                anchor = anchor_of(entry)
                if anchor in merged:
                    sources = merged[anchor]["source"]
                    if label not in sources:
                        sources.append(label)
                    tallies["merged"] += 1
                else:
                    record = dict(entry)
                    record["source"] = [label]
                    merged[anchor] = record
                    tallies["records"] += 1
    return merged


def bucket(merged):
    """Group the merged records into the `word_pos_shaw` buckets the pruning chain
    reads, buckets sorted and records in first-seen order for a byte-stable file."""
    buckets = {}
    for record in merged.values():
        buckets.setdefault(output_bucket_key(record), []).append(record)
    return {key: buckets[key] for key in sorted(buckets)}


def report(tallies):
    print("\n=== supplement combine report ===")
    print(f"Distinct anchors (records): {tallies['records']:,}")
    print(f"Cross-anchor attestations merged into source lists: "
          f"{tallies['merged']:,}")


def main():
    tallies = Counter()
    merged = combine(tallies)
    buckets = bucket(merged)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(buckets, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in buckets.values()):,} records")
    report(tallies)


if __name__ == "__main__":
    main()
