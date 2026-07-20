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
  lot-palm    PALM 𐑭 -> LOT 𐑪    (father-bother: GenAm flattens PALM onto LOT)

All are directional: GenAm is the merged accent, RSSB/RRP the non-merged base.
A record is tagged only when its spelling is an exact swap of a non-merged
sibling — see classify_dialect_mergers.py (supplements) and basis.py (ReadLex's
TrapBath var).
"""

import os

PALM = "𐑭"
TRAP = "𐑨"
THOUGHT = "𐑷"
LOT = "𐑪"

MERGER_TRAP_BATH = "trap-bath"
MERGER_COT_CAUGHT = "cot-caught"
MERGER_LOT_PALM = "lot-palm"

# merger name -> (non-merged vowel, merged vowel). The merged spelling swaps
# every differing position from the first onto the second.
#
# Each entry is a DISTINCT ordered (distinguished, flattened) vowel-pair:
# 𐑭->𐑨, 𐑷->𐑪, 𐑭->𐑪. lot-palm and trap-bath share the distinguished vowel 𐑭 but
# flatten it to different targets (𐑪 vs 𐑨), so merger_of stays unambiguous: a
# single-vowel swap fixes both endpoints, and no two entries have the same
# ordered pair (see merger_of).
#
# lot-palm direction is empirically confirmed: in this dataset the merged (GenAm)
# form shows LOT 𐑪 where the non-merged RSSB/RRP sibling shows PALM 𐑭 by 543 to
# 230 over the reverse — foreign/broad-A words (Aachen, Abaza, Accra) that GenAm
# renders with the LOT vowel. Same convention as cot-caught: ReadLex canonical is
# LOT, so the merged target is 𐑪.
# The full vowel-swap table. Which mergers are ACTIVE is gated by MERGER_ENABLED
# below — a per-merger off-switch. cot-caught and lot-palm are disabled for now:
# their base-selection produces false flags on candidate-soup spellings (a
# candidate sibling is trusted as a non-merged base even when the flagged word's
# canonical vowel is already the flattened target — e.g. "lot" 𐑤𐑪𐑑 is LOT in every
# accent, no merger applies). The swap DIRECTION is correct; the base-selection bug
# is deferred. See scratchpad/merger-falseflag-investigation.md.
_MERGER_SWAPS_ALL = {
    MERGER_TRAP_BATH: (PALM, TRAP),
    MERGER_COT_CAUGHT: (THOUGHT, LOT),
    MERGER_LOT_PALM: (PALM, LOT),
}

# Per-merger enable flags. Default: trap-bath ON, cot-caught + lot-palm OFF. Each
# can be flipped via env (SHAW_SPELL_MERGER_<NAME>=1/0) without a code edit, so the
# owner can re-enable one for review once the base-selection fix lands.
def _merger_enabled(name, default):
    env = os.environ.get(f"SHAW_SPELL_MERGER_{name.upper().replace('-', '_')}")
    if env is None:
        return default
    return env.strip().lower() in ("1", "true", "yes", "on")

MERGER_ENABLED = {
    MERGER_TRAP_BATH: _merger_enabled(MERGER_TRAP_BATH, True),
    MERGER_COT_CAUGHT: _merger_enabled(MERGER_COT_CAUGHT, False),
    MERGER_LOT_PALM: _merger_enabled(MERGER_LOT_PALM, False),
}

# The active swap table: only enabled mergers. merger_of / classify iterate this,
# so a disabled merger is simply never detected or flagged.
MERGER_SWAPS = {
    name: pair for name, pair in _MERGER_SWAPS_ALL.items() if MERGER_ENABLED[name]
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
    flattened form.

    At most one merger ever matches: _is_swap fixes both the distinguished and the
    flattened vowel at every differing position, and MERGER_SWAPS holds distinct
    ordered (distinguished, flattened) pairs, so a pair matching two swaps would
    force those swaps to be identical. Iteration order is therefore irrelevant to
    the result."""
    for name, (distinguished, flattened) in MERGER_SWAPS.items():
        if _is_swap(non_merged, merged, distinguished, flattened):
            return name
    return None
