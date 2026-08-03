#!/usr/bin/env python3
"""
The vowel-merger vocabulary and detection shared across the dialect model.

The dialect model separates a record's BASE accent (the `var` label) from the
within-accent vowel MERGERS its spelling reflects (the additive `mergers` list).
A merger is a single-vowel flattening: the merged spelling is the non-merged one
with one-or-more positions swapped from the distinguished vowel to the merged
vowel, and NOTHING else changed.

  trap-bath   PALM 𐑭 -> TRAP 𐑨   (BATH words spelt with the short TRAP vowel)
  cot-caught  LOT 𐑪 -> THOUGHT 𐑷 (merged spelling shows THOUGHT: dog 𐑛𐑪𐑜/𐑛𐑷𐑜)
  lot-palm    LOT 𐑪 -> PALM 𐑭   (father-bother: GenAm flattens LOT onto PALM)

All are directional: the tagged record is the merged (flattened) form, the
distinguished form stays canonical. A record is tagged only when its spelling
is an exact swap of a non-merged sibling — see classify_dialect_mergers.py
(supplements) and basis.py (ReadLex's TrapBath var).
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
# every differing position from the first onto the second. MERGER_ENABLED below
# gates which mergers are active.
_MERGER_SWAPS_ALL = {
    MERGER_TRAP_BATH: (PALM, TRAP),
    MERGER_COT_CAUGHT: (LOT, THOUGHT),
    MERGER_LOT_PALM: (LOT, PALM),
}

# merger name -> the accents that HAVE the merger (owner ruling, 2026-08-03). A
# flag names variation WITHIN a variety, so an accent without the merger can
# never carry it — GenAus/NZ ɔ-for-LOT transcriptions are a source convention,
# not cot-caught. cot-caught and lot-palm (father-bother) are North American.
# Flat BATH is native across North America and general in Ireland, and
# lexically variable in Australia (dance/graph/castle commonly TRAP); NZ and
# South Africa hold a firm split, so a TRAP spelling there is not the merger.
MERGER_ACCENTS = {
    MERGER_TRAP_BATH: frozenset({"GenAm", "GenCan", "IrEng", "GenAus"}),
    MERGER_COT_CAUGHT: frozenset({"GenAm", "GenCan"}),
    MERGER_LOT_PALM: frozenset({"GenAm", "GenCan"}),
}

# Display labels (en dash), the SINGLE source for every UI that names a merger —
# the editor's filter chips and its detail-panel Variations toggles both read
# this off the daemon rather than hand-authoring their own copy.
MERGER_LABELS = {
    MERGER_TRAP_BATH: "TRAP–BATH",
    MERGER_COT_CAUGHT: "COT–CAUGHT",
    MERGER_LOT_PALM: "LOT–PALM",
}

# Per-merger enable flags, each overridable via env
# (SHAW_SPELL_MERGER_<NAME>=1/0) without a code edit.
def _merger_enabled(name, default):
    env = os.environ.get(f"SHAW_SPELL_MERGER_{name.upper().replace('-', '_')}")
    if env is None:
        return default
    return env.strip().lower() in ("1", "true", "yes", "on")

MERGER_ENABLED = {
    MERGER_TRAP_BATH: _merger_enabled(MERGER_TRAP_BATH, True),
    MERGER_COT_CAUGHT: _merger_enabled(MERGER_COT_CAUGHT, True),
    MERGER_LOT_PALM: _merger_enabled(MERGER_LOT_PALM, True),
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
