#!/usr/bin/env python3
"""
Classify each supplement candidate's within-accent vowel mergers, annotating it
with a `mergers` list before it reaches the editorial basis.

The supplement candidates carry a scalar base-accent `var` (a multi-spelling
group pairs a merged GenAm form against a non-merged RSSB/RRP form). This stage
layers the merger axis on top: a GenAm spelling that is an exact vowel-merger
swap (trap-bath 𐑭->𐑨, cot-caught 𐑷->𐑪, or lot-palm 𐑭->𐑪) of a non-merged
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

The non-merged sibling is drawn from TWO attestations (see non_merged_spellings):
an RSSB spelling within the supplement pool, OR a non-merged ReadLex/RRP spelling
for the same (word, pos). The ReadLex attestation is what lets a GenAm candidate
be flagged trap-bath even when its own supplement group has no RSSB sibling — the
common case for names / GenAm-sourced imports. A candidate with no non-merged
sibling in EITHER source is the sole (canonical) spelling of its (word, pos): the
pairing cannot fire, so an isolated form is never flagged.

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
from dialect_mergers import MERGER_SWAPS, merger_of

# (deduped input, classified output) — one combined pool.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-deduped.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-classified.json"

# The non-merged base spellings a GenAm merger swap is measured against, and
# which are themselves never tagged. RSSB is the non-merged British standard; a
# supplement RRP form (e.g. an IPA-rescued copied-homograph, or — should the RRP
# reclassifier ever precede this stage — a canonicalized sibling) is equally a
# non-merged base. Including both is directional-safe: merger_of only ever treats
# an RSSB/RRP form as the non-merged SIBLING, never as the merged target (the
# merged form is GenAm). Verified net-neutral vs the RSSB-only pool on live data.
BASE_NON_MERGED = ("RSSB", "RRP")

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def non_merged_spellings(supplement, upstream=None):
    """(word_lower, pos) -> the set of non-merged spellings attesting it. These are
    the canonical forms a candidate's merger swap is measured against.

    The attestation pool is the union of two sources:

      1. RSSB siblings WITHIN the supplement pool — the original within-supplement
         pairing (an {RSSB, GenAm} group's non-merged British spelling).
      2. Non-merged ReadLex/RRP spellings for the same (word, pos) — every ReadLex
         entry NOT already carrying a merger flag (see reinterpret_upstream: a
         `TrapBath` record is the MERGED 𐑨 form and is excluded here, so it can
         never masquerade as the non-merged attestation it is measured against).

    This index is merger-agnostic: it holds the non-merged spellings, and
    merger_for/merger_of decide per-candidate which known merger (if any) the swap
    is — so the ReadLex attestation feeds BOTH trap-bath (𐑭→𐑨) and cot-caught
    (𐑷→𐑪) uniformly, no merger is privileged.

    Adding (2) lets a supplement candidate be flagged off an attested ReadLex
    sibling (a 𐑭 form for trap-bath, a 𐑷 form for cot-caught) even when its own
    supplement group has no RSSB sibling — the common case for names / GenAm-sourced
    imports. It is still a pure PAIRING claim against an attested sibling; a
    candidate with no non-merged sibling in EITHER source is the sole (canonical)
    spelling of its (word, pos) and is never flagged."""
    index = defaultdict(set)
    for entries in supplement.values():
        for entry in entries:
            if entry.get("var") in BASE_NON_MERGED and not entry.get("mergers"):
                index[(entry["Latn"].lower(), entry["pos"])].add(entry["Shaw"])
    if upstream is None:
        upstream = load_upstream()
    for entries in upstream.values():
        for entry in entries:
            # Only NON-merged ReadLex forms attest: a reinterpreted TrapBath entry
            # already carries mergers=[trap-bath] and is itself a merged 𐑨 form.
            if entry.get("mergers"):
                continue
            key = (entry.get("Latn", "").lower(), entry.get("pos", ""))
            index[key].add(entry.get("Shaw", ""))
    return index


def merger_for(entry, non_merged_index):
    """The (merger, non_merged_sibling) `entry` is tagged with, or (None, None).
    Only a merged spelling that is an exact merger swap of some non-merged sibling
    (an RSSB supplement sibling OR a non-merged ReadLex/RRP form) in its (word, pos)
    group is tagged; RSSB (and unmatched) forms carry none.

    A single (sibling, entry) pair is never ambiguous — merger_of returns at most
    one merger. But a word can carry SEVERAL non-merged siblings, and a merged 𐑪
    form can be a cot-caught swap of a 𐑷 sibling AND a lot-palm swap of a 𐑭 sibling
    (e.g. `vase`: 𐑝𐑷𐑟 and 𐑝𐑭𐑟 both attested, GenAm 𐑝𐑪𐑟). The two candidate
    tags then compete. We resolve by MERGER declaration precedence, not by sibling
    sort order: try each merger over the whole sibling set in MERGER_SWAPS order
    and take the first that fires. This is deterministic and keeps the pre-existing
    mergers' tags stable when a later merger is added (a newly-added merger can only
    claim records that matched NOTHING before). Which sibling is the "true" one is a
    data question the tag doesn't settle — every tagged record is a review
    candidate — so a stable, documented precedence is the honest resolution."""
    if entry.get("var") in BASE_NON_MERGED:
        return None, None
    siblings = non_merged_index.get((entry["Latn"].lower(), entry["pos"]))
    if not siblings:
        return None, None
    shaw = entry["Shaw"]
    # Sorted siblings keep the REPORTED sibling deterministic within a merger;
    # the outer loop is merger-precedence so an earlier merger wins a multi-sibling
    # tie (see docstring).
    for merger_name in MERGER_SWAPS:
        for sibling in sorted(siblings):
            if merger_of(sibling, shaw) == merger_name:
                return merger_name, sibling
    return None, None


def classify_supplement(supplement, tallies, samples, upstream=None):
    """A copy of a supplement dict with each record's `mergers` set. The field is
    written only when non-empty (additive: absent == empty). An upstream ReadLex
    record in the pool passes through VERBATIM — its `mergers` (the reinterpreted
    TrapBath flag) is ReadLex's own data and is neither stripped nor added to
    (basis.is_upstream: never flag-mutate core). `upstream` (the reinterpreted
    ReadLex) is threaded in by the orchestrator; None loads it."""
    non_merged_index = non_merged_spellings(supplement, upstream)
    classified = {}
    for key, entries in supplement.items():
        annotated = []
        for entry in entries:
            record = dict(entry)
            if is_upstream(entry):
                tallies["upstream"] += 1
                annotated.append(record)
                continue
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
    tagged = sum(tallies[m] for m in MERGER_SWAPS)
    total = tagged + tallies["none"]
    print("\n=== dialect merger classification report ===")
    print(f"Records classified: {total:,}")
    for merger in MERGER_SWAPS:
        print(f"  {merger} tagged: {tallies[merger]:,}")
    print(f"  no merger:        {tallies['none']:,}")
    print(f"  upstream (passed through verbatim): {tallies['upstream']:,}")

    for merger in MERGER_SWAPS:
        print(f"\nSample [{merger}]:")
        for entry, sibling in samples[merger]:
            # The sibling may be an RSSB supplement form OR a non-merged ReadLex/RRP
            # form — both attest — so it is labelled generically, not "RSSB".
            print(f"  {entry['Latn']} [{entry['pos']}]: "
                  f"non-merged {sibling} -> {entry.get('var', '')} {entry['Shaw']}")


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
