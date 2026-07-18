#!/usr/bin/env python3
"""
Collapse identical-spelling dialect variants of a supplement candidate into one
universal (RRP wildcard) record before it reaches the editorial basis.

The merger classifier leaves a (word, pos) group carrying one record per
(dialect var, spelling). When two or more DIFFERENT specific dialects spell the
word the SAME way (e.g. `portmanteau`/AJ0 is 𐑐𐑹𐑑𐑥𐑨𐑯𐑑𐑴 under both RSSB and
GenAm), that one spelling is universal — it covers every dialect — so the
reviewer should see it ONCE, not once per dialect. RRP is the wildcard the model
already uses for "all dialects" (see filter_supplement_duplicates.py), so the
identical-spelling specifics collapse into a single RRP record.

  RSSB 𐑐𐑹𐑑𐑥𐑨𐑯𐑑𐑴 + GenAm 𐑐𐑹𐑑𐑥𐑨𐑯𐑑𐑴  -> one RRP 𐑐𐑹𐑑𐑥𐑨𐑯𐑑𐑴 (all dialects)
  RSSB 𐑓𐑷𐑤𐑕 vs GenAm 𐑓𐑪𐑤𐑕 (different shaw) -> both kept (real dialect difference)

The collapse is per distinct spelling within a (word.lower(), pos) group. Only a
spelling carried by 2+ distinct specific dialects collapses; a spelling unique to
one dialect is that dialect's own fact and is left alone. A spelling whose
records disagree on the additive `mergers` flag is NOT collapsed — a merger flag
is a real within-accent difference, so the records stay separate. If an RRP
record for the spelling already exists, the specifics fold into it rather than
minting a second RRP.

Provenance is merged following the codebase convention (dedup_editorial.py):
highest confidence wins, and the payload of the highest-confidence record
(ipa/freq/review) represents the collapsed record. A candidate a patch already
anchors to has left the review surface and is exempt — collapsing it away would
orphan the patch's anchor (apply_patches.py fails loud on that).

This is a pruning-chain stage between the merger classifier and the phrase
filter: reliable -> deduped -> classified -> HERE (collapsed) -> filtered ->
basis. The phrase filter and basis read the collapsed output verbatim.

Inputs:  data/supplement-{wordnet,wiktionary}-classified.json,
         data/patches/patches.jsonl.
Outputs: data/supplement-{wordnet,wiktionary}-collapsed.json  — the phrase filter
         reads these next. The -classified.json files are left untouched.

Usage:
    python3 src/tools/collapse_identical_dialects.py
"""

import json
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, anchor_of
from filter_supplement_duplicates import anchored_keys, load_patches

# (classified input, collapsed output) per supplement source.
SUPPLEMENTS = [
    (PROJECT_ROOT / "data" / "supplement-wordnet-classified.json",
     PROJECT_ROOT / "data" / "supplement-wordnet-collapsed.json"),
    (PROJECT_ROOT / "data" / "supplement-wiktionary-classified.json",
     PROJECT_ROOT / "data" / "supplement-wiktionary-collapsed.json"),
]

# The var wildcard: an RRP record covers every dialect, so a spelling agreed on
# by 2+ specific dialects collapses into a single RRP record (matching the
# specificity lattice in filter_supplement_duplicates.py).
VAR_WILDCARD = "RRP"

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def mergers_of(entry):
    """The record's mergers as a hashable, order-independent signature."""
    return tuple(sorted(entry.get("mergers") or ()))


def collapse_representative(entries):
    """The single RRP record standing in for a set of identical-spelling records.
    Provenance is merged per dedup_editorial.py: the highest-confidence record
    supplies the payload (ipa/freq/review) and its confidence; var becomes the
    RRP wildcard. The set is spelling- and mergers-identical by construction, so
    Shaw and mergers carry through unchanged."""
    best = max(entries, key=lambda entry: (entry.get("confidence", 0),
                                           entry.get("ipa", "")))
    record = dict(best)
    record["var"] = VAR_WILDCARD
    return record


def partition_collapses(entries, exempt_keys):
    """Whether a same-(word,pos) set of identical-spelling records collapses, and
    the reason it does not when it does not.

    Collapses iff 2+ DISTINCT specific dialects (non-RRP vars) carry the spelling
    and every record agrees on the mergers flag; a patch-anchored record blocks
    the collapse (it has left the review surface)."""
    specific_vars = {entry.get("var", "") for entry in entries
                     if entry.get("var", "") != VAR_WILDCARD}
    if len(specific_vars) < 2:
        return False, "single-dialect"
    if len({mergers_of(entry) for entry in entries}) > 1:
        return False, "mergers-differ"
    if any(anchor_of(entry) in exempt_keys for entry in entries):
        return False, "patch-anchored"
    return True, None


def collapse_supplement(supplement, exempt_keys, tallies, samples):
    """A copy of a supplement dict with identical-spelling dialect variants
    collapsed to one RRP record. Records are regrouped by (word.lower(), pos) and
    partitioned by spelling; each collapsible partition becomes a single RRP
    record, folding into an existing RRP for the spelling if one is present."""
    groups = defaultdict(lambda: defaultdict(list))
    for entries in supplement.values():
        for entry in entries:
            groups[(entry["Latn"].lower(), entry["pos"])][entry["Shaw"]].append(entry)

    collapsed = defaultdict(list)
    for by_shaw in groups.values():
        for shaw_entries in by_shaw.values():
            does_collapse, reason = partition_collapses(shaw_entries, exempt_keys)
            if not does_collapse:
                tallies[reason] += len(shaw_entries)
                for entry in shaw_entries:
                    collapsed[output_bucket_key(entry)].append(entry)
                continue
            record = collapse_representative(shaw_entries)
            tallies["collapsed-groups"] += 1
            tallies["collapsed-records-removed"] += len(shaw_entries) - 1
            if len(samples) < SAMPLE_LIMIT:
                samples.append((shaw_entries, record))
            collapsed[output_bucket_key(record)].append(record)

    return {key: collapsed[key] for key in collapsed}


def format_entry(entry):
    return f"var={entry.get('var', '')} conf={entry.get('confidence', '')}"


def report(tallies, samples):
    print("\n=== identical-dialect collapse report ===")
    print(f"Groups collapsed to RRP:   {tallies['collapsed-groups']:,}")
    print(f"Records removed:           {tallies['collapsed-records-removed']:,}")
    print(f"Left (single dialect):     {tallies['single-dialect']:,}")
    print(f"Left (mergers differ):     {tallies['mergers-differ']:,}")
    print(f"Left (patch-anchored):     {tallies['patch-anchored']:,}")

    print("\nSample collapsed (identical spelling across dialects -> one RRP):")
    for shaw_entries, record in samples:
        vars_seen = ", ".join(sorted(entry.get("var", "") for entry in shaw_entries))
        print(f"  {record['Latn']} [{record['pos']}] {record['Shaw']}: "
              f"{{{vars_seen}}} -> {VAR_WILDCARD}")


def main():
    exempt_keys = anchored_keys(load_patches())

    tallies = Counter()
    samples = []

    for classified_path, collapsed_path in SUPPLEMENTS:
        supplement = load_json(classified_path)
        collapsed = collapse_supplement(supplement, exempt_keys, tallies, samples)
        with open(collapsed_path, "w", encoding="utf-8") as f:
            json.dump(collapsed, f, ensure_ascii=False, indent=4)
        print(f"Wrote {collapsed_path.relative_to(PROJECT_ROOT)}: "
              f"{sum(len(v) for v in collapsed.values()):,} records")

    report(tallies, samples)


if __name__ == "__main__":
    main()
