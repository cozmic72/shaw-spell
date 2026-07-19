#!/usr/bin/env python3
"""
Collapse identical-spelling dialect variants of a supplement candidate down the
dialect hierarchy before the candidate reaches the editorial basis.

The merger classifier leaves a (word, pos) group carrying one record per
(dialect var, spelling). When two or more DIFFERENT dialects spell the word the
SAME way, that identical spelling is not a real dialect difference — it is the
same fact stated per dialect — so the group collapses onto the highest-precedence
dialect's var.

  RRP > RSSB > GenAm  (RRP highest; any other var ranks below GenAm)

  RSSB 𐑖𐑦𐑑𐑦 + GenAm 𐑖𐑦𐑑𐑦  -> one RSSB record (the GenAm is relabelled onto it)
  RRP + RSSB + GenAm (same shaw) -> one RRP record
  RSSB 𐑓𐑷𐑤𐑕 vs GenAm 𐑓𐑪𐑤𐑕 (different shaw) -> both kept (real difference)

RELABEL, don't drop. Because the pool is now source-combined (see
combine_supplements.py), a lower-precedence var and its higher-precedence twin
may come from DIFFERENT sources — e.g. wordnet's GenAm 𐑖𐑦𐑑𐑦 and wiktionary's
RSSB 𐑖𐑦𐑑𐑦. Dropping the loser would discard its source attestation. Instead
every record in a collapsing group is REWRITTEN to the winning var, then records
that now share the full anchor (word, pos, shaw, var) MERGE into one whose
`source` is the UNION of the merged records' source lists. So the multi-source
agreement signal survives the collapse rather than being thrown away.

  wordnet GenAm 𐑖𐑦𐑑𐑦 (source=[wordnet]) relabels to RSSB
  wiktionary RSSB 𐑖𐑦𐑑𐑦 (source=[wiktionary]) stays RSSB
  -> one RSSB 𐑖𐑦𐑑𐑦 record, source=[wordnet, wiktionary]

Payload tie-break when relabelled records merge: the record that was ALREADY the
winning var keeps its payload (ipa/freq/confidence/mergers/...); a record that
was merely relabelled contributes ONLY its source labels. If several records were
already the winning var (a genuine within-var duplicate), the first-seen keeps
the payload. The winning var's own record is the authentic spelling for that
accent, so its content — not a lower-precedence var's — is the one to keep.

The collapse is per distinct spelling within a (word.lower(), pos) group. Only a
spelling carried by 2+ distinct dialect vars collapses; a spelling unique to one
var is that var's own fact and is left alone. A spelling whose records disagree
on the additive `mergers` flag is NOT collapsed — a merger flag is a real
within-accent difference, so every record stays.

This stage is patch-unaware: it collapses purely on the dialect hierarchy. If a
lower-precedence var the owner anchored is relabelled away, its patch orphans and
apply_patches.py fails loud — that is intentional and handled downstream.

This is a pruning-chain stage between the merger classifier and the contamination
filter: combined-classified -> HERE (collapsed) -> decontaminated -> filtered ->
basis. Downstream stages read the collapsed output verbatim.

Inputs:  data/supplement-combined-classified.json.
Outputs: data/supplement-combined-collapsed.json.

Usage:
    python3 src/tools/collapse_identical_dialects.py
"""

import json
from collections import Counter, defaultdict

from basis import PROJECT_ROOT

# (classified input, collapsed output) — one combined pool.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-classified.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-collapsed.json"

# Dialect precedence: lower rank wins. Any var not listed ranks below every
# listed var (UNKNOWN_RANK), so it always loses an identical-spelling collision.
PRECEDENCE = {"RRP": 0, "RSSB": 1, "GenAm": 2}
UNKNOWN_RANK = len(PRECEDENCE)

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


def var_rank(entry):
    """Precedence rank of a record's dialect var; unlisted vars rank lowest."""
    return PRECEDENCE.get(entry.get("var", ""), UNKNOWN_RANK)


def union_sources(into, extra):
    """Append `extra`'s source labels to `into`'s, deduped and order-stable."""
    sources = into.setdefault("source", [])
    for label in extra.get("source", ()):
        if label not in sources:
            sources.append(label)


def collapse_group(entries):
    """The collapsed records for one same-(word,pos) set of identical-spelling
    records, and the tally reason.

    Collapses iff 2+ distinct dialect vars carry the spelling and every record
    agrees on the mergers flag: every record is relabelled to the winning
    (highest-precedence) var, then records sharing that var merge into one whose
    payload is the winning-var record's (a relabelled record contributes only its
    source). Records disagreeing on the mergers flag are left intact (a real
    within-accent difference)."""
    vars_present = {entry.get("var", "") for entry in entries}
    if len(vars_present) < 2:
        return entries, "single-dialect"
    if len({mergers_of(entry) for entry in entries}) > 1:
        return entries, "mergers-differ"

    winning_rank = min(var_rank(entry) for entry in entries)
    winning_var = next(entry.get("var", "") for entry in entries
                       if var_rank(entry) == winning_rank)

    # The already-winning-var records keep the payload (first-seen wins on a
    # within-var duplicate); the relabelled losers only feed their source in.
    merged = None
    for entry in entries:
        if entry.get("var", "") == winning_var:
            if merged is None:
                merged = dict(entry)
            else:
                union_sources(merged, entry)
    for entry in entries:
        if entry.get("var", "") != winning_var:
            union_sources(merged, entry)
    return [merged], "collapsed"


def collapse_supplement(supplement, tallies, samples):
    """A copy of a supplement dict with identical-spelling dialect variants
    collapsed onto the highest-precedence var. Records are regrouped by
    (word.lower(), pos) and partitioned by spelling; each colliding partition is
    relabelled to its highest-precedence var and merged."""
    groups = defaultdict(lambda: defaultdict(list))
    for entries in supplement.values():
        for entry in entries:
            groups[(entry["Latn"].lower(), entry["pos"])][entry["Shaw"]].append(entry)

    collapsed = defaultdict(list)
    for by_shaw in groups.values():
        for shaw_entries in by_shaw.values():
            kept, reason = collapse_group(shaw_entries)
            if reason == "collapsed":
                tallies["collapsed-groups"] += 1
                tallies["records-merged"] += len(shaw_entries) - len(kept)
                if len(samples) < SAMPLE_LIMIT:
                    samples.append((shaw_entries, kept))
            else:
                tallies[reason] += len(shaw_entries)
            for entry in kept:
                collapsed[output_bucket_key(entry)].append(entry)

    return {key: collapsed[key] for key in sorted(collapsed)}


def report(tallies, samples):
    print("\n=== identical-dialect collapse report ===")
    print(f"Groups collapsed:          {tallies['collapsed-groups']:,}")
    print(f"Records merged away:       {tallies['records-merged']:,}")
    print(f"Left (single dialect):     {tallies['single-dialect']:,}")
    print(f"Left (mergers differ):     {tallies['mergers-differ']:,}")

    print("\nSample collapsed (identical spelling across dialects -> "
          "relabel to highest, union source):")
    for shaw_entries, kept in samples:
        vars_seen = ", ".join(sorted(entry.get("var", "") for entry in shaw_entries))
        rep = kept[0]
        print(f"  {rep['Latn']} [{rep['pos']}] {rep['Shaw']}: "
              f"{{{vars_seen}}} -> {rep.get('var', '')} "
              f"source={rep.get('source', [])}")


def main():
    tallies = Counter()
    samples = []

    supplement = load_json(INPUT_PATH)
    collapsed = collapse_supplement(supplement, tallies, samples)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(collapsed, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in collapsed.values()):,} records")

    report(tallies, samples)


if __name__ == "__main__":
    main()
