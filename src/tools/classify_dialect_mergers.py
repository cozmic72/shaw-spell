#!/usr/bin/env python3
"""
Classify each supplement candidate's within-accent vowel mergers, annotating it
with a `mergers` list before it reaches the editorial basis.

The supplement candidates carry a scalar base-accent `var` (a multi-spelling
group pairs a merged GenAm form against a non-merged RSSB/RRP form). This stage
layers the merger axis on top: a GenAm spelling that is an exact vowel-merger
swap (trap-bath 𐑭->𐑨, cot-caught 𐑷->𐑪, or lot-palm 𐑪->𐑭) of a non-merged
sibling in the same (word, pos) group is tagged with that merger. Its base `var`
is unchanged — the flag is additive.

  RSSB/RRP record                  -> non-merged base, no merger
  GenAm = merger swap of a sibling -> base GenAm, mergers=[<that merger>]
  GenAm differing otherwise        -> base GenAm, no merger (just base accent)
  single spelling for the group    -> no merger

This runs BEFORE the RRP reclassifier (reclassify_rrp.py): the reclassifier must
see the `mergers` flag so it can HOLD BACK a merged form (spelt differently from
its RRP sibling) from canonicalization, rather than collapsing it to RRP and
erasing the merger relationship this stage detected.

The non-merged sibling may sit ANYWHERE in the candidate's dialect ancestry
(owner ruling, 2026-08-03): an upstream ReadLex entry or a fellow pool
candidate, at the candidate's own accent level (a peer) or at any ancestor up
the dialect hierarchy (collapse_identical_dialects.PARENT), with the British
bases RRP/RSSB eligible for every candidate. A pool source publishing multiple
spellings of one word is exactly the signal being mined, so an unreviewed
candidate MAY attest another — every flag is a review candidate and the
editorial process is the net. The correctness guards stay: an attester must
carry no merger flag and must not be a record this stage itself flags (a merged
mutant is no witness for the distinguished form), a descendant or lateral
accent never attests, POS must match, and the swap must be an exact
single-vowel merger swap (which keeps foreign broad-A loanword vowel choices
out). A candidate is only flaggable with a merger its own accent HAS
(dialect_mergers.MERGER_ACCENTS): a flag names variation within a variety, so
e.g. GenAus/NZ can never carry cot-caught. A candidate with no eligible
counterpart for its (word, pos) is never flagged.

A record's `mergers` is emitted only when non-empty, keeping the field additive:
absent means the empty list. See dialect_mergers.py for the swap detection and
docs/dialect-mergers.md for the model.

This is a pruning-chain stage between the duplicate filter and the RRP
reclassifier over the source-combined pool: combined-deduped -> HERE
(classified) -> reclassified -> collapsed -> decontaminated -> filtered ->
basis. Downstream stages pass records through verbatim, so the `mergers`
annotation survives to the basis. Only the annotation is added; no candidate is
dropped or reshaped, and the per-record `source` list is preserved by the dict
copy.

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

from basis import PROJECT_ROOT, is_upstream, load_upstream
from collapse_identical_dialects import PARENT
from dialect_mergers import MERGER_ACCENTS, MERGER_SWAPS, merger_of

# (deduped input, classified output) — one combined pool.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-deduped.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-classified.json"

# The non-merged British base vars: eligible to attest EVERY candidate (RRP is
# the hierarchy root; RSSB is the unresolved-British bucket alongside it), and a
# candidate carrying one is itself never tagged.
BASE_NON_MERGED = ("RSSB", "RRP")

# Attestation provenance, in precedence order.
ATTEST_TIERS = ("upstream-ancestor", "upstream-peer", "pool-ancestor",
                "pool-peer")

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def attesting_vars(candidate_var):
    """The accents allowed to attest a candidate: its own level, every ancestor
    up the dialect hierarchy, and the British bases. Descendant and lateral
    accents are excluded — attestation flows down the hierarchy, never up or
    across."""
    eligible = set(BASE_NON_MERGED)
    eligible.add(candidate_var)
    ancestor = PARENT.get(candidate_var)
    while ancestor is not None and ancestor not in eligible:
        eligible.add(ancestor)
        ancestor = PARENT.get(ancestor)
    return eligible


def _tier(attester_var, candidate_var, pool_record):
    """ATTEST_TIERS index of one attester relative to one candidate."""
    provenance = "upstream" if pool_record is None else "pool"
    relation = "peer" if attester_var == candidate_var else "ancestor"
    return ATTEST_TIERS.index(f"{provenance}-{relation}")


class AttestationIndex:
    """Per-(word, pos) index of every record eligible to attest a merger swap:
    unflagged upstream ReadLex entries and unflagged pool candidates alike.
    Accent eligibility is judged per candidate in merger_for; a pool attester is
    additionally rejected when this stage would flag IT (_flaggable) — a record
    judged a merged mutant cannot witness the distinguished form. An upstream
    attester is never so judged: core is pre-accepted reference data
    (basis.is_upstream) carrying only the flags ReadLex itself asserts."""

    def __init__(self, upstream, supplement):
        self._attesters = defaultdict(list)  # (word, pos) -> [(shaw, var, pool record | None)]
        self._flaggable_memo = {}
        self._judging = set()
        for entries in upstream.values():
            for entry in entries:
                self._add(entry, None)
        for entries in supplement.values():
            for entry in entries:
                if not is_upstream(entry):
                    self._add(entry, entry)

    def _add(self, entry, pool_record):
        if entry.get("mergers"):
            return
        key = (entry["Latn"].lower(), entry["pos"])
        self._attesters[key].append(
            (entry["Shaw"], entry.get("var", ""), pool_record))

    def merger_for(self, entry):
        """The (merger, non_merged_sibling, tier) `entry` is tagged with, or
        (None, None, None). Only a spelling that is an exact merger swap of some
        eligible sibling for its (word, pos) is tagged; RSSB/RRP (and unmatched)
        forms carry none.

        A single (sibling, entry) pair is never ambiguous — merger_of returns at
        most one merger. But a word can carry SEVERAL eligible siblings, and one
        merged spelling can be a valid swap of different siblings under
        different mergers. The competing tags resolve by MERGER declaration
        precedence first — so a newly-added merger can only claim records that
        matched NOTHING before — then by attestation tier, then by (shaw, var).
        Deterministic, and which sibling is the "true" one stays a data question
        the tag doesn't settle: every tagged record is a review candidate."""
        candidate_var = entry.get("var", "")
        if candidate_var in BASE_NON_MERGED:
            return None, None, None
        eligible = attesting_vars(candidate_var)
        ranked = [(_tier(var, candidate_var, record), shaw, var, record)
                  for shaw, var, record in
                  self._attesters.get((entry["Latn"].lower(), entry["pos"]), ())
                  if var in eligible]
        ranked.sort(key=lambda attester: attester[:3])
        shaw = entry["Shaw"]
        for merger_name in MERGER_SWAPS:
            if candidate_var not in MERGER_ACCENTS[merger_name]:
                continue
            for tier, sibling, _var, record in ranked:
                if merger_of(sibling, shaw) != merger_name:
                    continue
                if record is not None and self._flaggable(record):
                    continue
                return merger_name, sibling, ATTEST_TIERS[tier]
        return None, None, None

    def _flaggable(self, record):
        """Whether this stage itself would flag `record` — the pool half of the
        no-merger-flag guard, judged by the same rule that assigns the output
        flags. Recursion bottoms out because the vowel swap graph is acyclic; a
        future swap table breaking that fails loud here instead of looping."""
        key = (record["Latn"].lower(), record["pos"], record["Shaw"],
               record.get("var", ""))
        if key not in self._flaggable_memo:
            if key in self._judging:
                raise SystemExit(
                    f"classify_dialect_mergers: attestation cycle at {key} — "
                    f"the merger swap table no longer precludes swap cycles")
            self._judging.add(key)
            merger, _, _ = self.merger_for(record)
            self._judging.discard(key)
            self._flaggable_memo[key] = merger is not None
        return self._flaggable_memo[key]


def classify_supplement(supplement, tallies, samples, upstream=None):
    """A copy of a supplement dict with each record's `mergers` set. The field is
    written only when non-empty (additive: absent == empty). An upstream ReadLex
    record in the pool passes through VERBATIM — its `mergers` (the reinterpreted
    TrapBath flag) is ReadLex's own data and is neither stripped nor added to
    (basis.is_upstream: never flag-mutate core). `upstream` (the reinterpreted
    ReadLex) is threaded in by the orchestrator; None loads it."""
    if upstream is None:
        upstream = load_upstream()
    index = AttestationIndex(upstream, supplement)
    classified = {}
    for key, entries in supplement.items():
        annotated = []
        for entry in entries:
            record = dict(entry)
            if is_upstream(entry):
                tallies["upstream"] += 1
                annotated.append(record)
                continue
            merger, sibling, tier = index.merger_for(entry)
            if merger is not None:
                record["mergers"] = [merger]
                tallies[merger] += 1
                tallies[f"{merger}:{tier}"] += 1
                if len(samples[merger]) < SAMPLE_LIMIT:
                    samples[merger].append((entry, sibling, tier))
            else:
                record.pop("mergers", None)
                tallies["none"] += 1
            annotated.append(record)
        classified[key] = annotated
    return classified


def report(tallies, samples):
    tagged = sum(tallies[m] for m in MERGER_SWAPS)
    total = tagged + tallies["none"]
    print("\n=== dialect merger classification report ===")
    print(f"Records classified: {total:,}")
    for merger in MERGER_SWAPS:
        print(f"  {merger} tagged: {tallies[merger]:,}")
        for tier in ATTEST_TIERS:
            if tallies[f"{merger}:{tier}"]:
                print(f"    via {tier}: {tallies[f'{merger}:{tier}']:,}")
    print(f"  no merger:        {tallies['none']:,}")
    print(f"  upstream (passed through verbatim): {tallies['upstream']:,}")

    for merger in MERGER_SWAPS:
        print(f"\nSample [{merger}]:")
        for entry, sibling, tier in samples[merger]:
            print(f"  {entry['Latn']} [{entry['pos']}]: "
                  f"non-merged {sibling} ({tier}) -> "
                  f"{entry.get('var', '')} {entry['Shaw']}")


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
