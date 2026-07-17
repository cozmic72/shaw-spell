#!/usr/bin/env python3
"""
The vowel-merger vocabulary and detection shared across the dialect model.

The dialect model separates a record's BASE accent (the `var` label) from the
within-accent vowel MERGERS its spelling reflects (the additive `mergers` list).
A merger is a single-vowel flattening: the merged spelling is the non-merged one
with one-or-more positions swapped from the distinguished vowel to the merged
vowel, and NOTHING else changed.

  trap-bath   PALM 𐑭 -> TRAP 𐑨   (BATH words spelt with the short TRAP vowel)
  cot-caught  THOUGHT 𐑷 -> LOT 𐑪  (GenAm flattens THOUGHT onto LOT)

Both are directional: GenAm is the merged accent, RSSB/RRP the non-merged base.
A record is tagged only when its spelling is an exact swap of a non-merged
sibling — see classify_dialect_mergers.py (supplements) and basis.py (ReadLex's
TrapBath var).
"""

PALM = "𐑭"
TRAP = "𐑨"
THOUGHT = "𐑷"
LOT = "𐑪"

MERGER_TRAP_BATH = "trap-bath"
MERGER_COT_CAUGHT = "cot-caught"

# merger name -> (non-merged vowel, merged vowel). The merged spelling swaps
# every differing position from the first onto the second.
MERGER_SWAPS = {
    MERGER_TRAP_BATH: (PALM, TRAP),
    MERGER_COT_CAUGHT: (THOUGHT, LOT),
}


def _diff_positions(non_merged, merged):
    """Indices where two equal-length spellings differ; None if lengths differ
    (an insertion/deletion is never a clean single-vowel merger)."""
    if len(non_merged) != len(merged):
        return None
    return [i for i in range(len(non_merged)) if non_merged[i] != merged[i]]


def _is_swap(non_merged, merged, distinguished_vowel, merged_vowel):
    """Whether `merged` is `non_merged` with 1+ positions swapped exactly
    distinguished_vowel -> merged_vowel and no other difference."""
    positions = _diff_positions(non_merged, merged)
    if not positions:
        return False
    return all(
        non_merged[i] == distinguished_vowel and merged[i] == merged_vowel
        for i in positions
    )


def merger_of(non_merged, merged):
    """The merger name that turns `non_merged` into `merged`, or None if the
    difference is not exactly one known merger. Directional: `merged` must be the
    flattened form."""
    for name, (distinguished, flattened) in MERGER_SWAPS.items():
        if _is_swap(non_merged, merged, distinguished, flattened):
            return name
    return None
