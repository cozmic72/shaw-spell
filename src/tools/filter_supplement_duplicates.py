#!/usr/bin/env python3
"""
Filter redundant candidates out of the supplement set before they reach the
editorial basis.

A supplement candidate is a DUPLICATE — and is removed — when an already
established entry would resolve to the same Shavian spelling for the candidate's
scope. "Established" is upstream ReadLex ONLY — read off the POOL's own core
records (collated in at combine under the `readlex` source label; no separate
readlex.json load). An upstream record itself is NEVER
a drop candidate: it would match its own scope in the established index and
self-annihilate, and core must ride the chain untouched (basis.is_upstream).
Resolution is
grounded in the dialect/POS specificity lattice: a candidate is redundant iff
some established entry with the SAME word (case-insensitive) and SAME Shaw has a
(var, pos) scope that is the same as, or BROADER than, the candidate's on BOTH
axes.

  var axis   RRP is the wildcard (covers every dialect when nothing more
             specific exists). Established RRP is broader than any specific
             candidate var; a different specific var is incomparable.
  pos axis   UNC is broadest; NN0 (number-neutral) is broader than NN1/NN2.
             Compound "+tags" (e.g. DT0+VBZ) are atomic — they only self-match.

A candidate that is BROADER than every same-spelling established entry (e.g.
candidate UNC over an established NN1) makes a wider claim and is KEPT.

The filter never reads patches: it is a pure function of the candidate pool
(upstream core rides in it). If a drop orphans a patch's anchor, apply_patches
soft-fails downstream — the orphan is logged, retained and surfaced in the
editor's 'orphaned' filter.

This is the first pruning pass over the source-combined candidate pool (see
combine_supplements.py, then definition-annotated by annotate_definitions.py);
the merger classifier reads the -deduped.json output next. Kept candidates are
copied verbatim, so each record's `source` list and `has_definition` flag ride
through untouched.

Inputs:  data/supplement-combined-defs.json (the combined, definition-annotated
         candidate pool, core included).
Outputs: data/supplement-combined-deduped.json  — the merger classifier reads
         this. The combined-defs file is left untouched; the removed candidates
         are regenerable machine output.

Usage:
    python3 src/tools/filter_supplement_duplicates.py
"""

import json
from collections import Counter

from basis import PROJECT_ROOT, anchor_key, is_upstream

PATCHES_PATH = PROJECT_ROOT / "data" / "patches" / "patches.jsonl"

# (combined+annotated input, deduped output) — one combined pool.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-defs.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-deduped.json"

# The var wildcard: an established RRP entry covers every dialect, so it is
# broader than any specific candidate var.
VAR_WILDCARD = "RRP"

# POS broadening: value -> the set of narrower POS tags it also covers. UNC is
# unknown (broadest); NN0 is number-neutral over the singular/plural nouns.
# Anything not listed broadens nothing beyond itself. Compound "+tags" are
# atomic and never appear here — they only ever self-match.
POS_BROADENS = {
    "UNC": {"NN0", "NN1", "NN2", "AJ0", "VVI", "AV0", "NP0", "ITJ", "PRP",
            "PNP", "DT0", "CJC", "CRD"},
    "NN0": {"NN1", "NN2"},
}

# Report tuning. KEPT_CLOSE_KINDS are the near-miss keeps (a same-word+same-shaw
# established entry that did NOT cover the candidate) the owner most wants to
# eyeball for over-filtering. SAMPLE_LIMIT caps each sampled list.
KEPT_CLOSE_KINDS = ("different-specific-var", "incomparable-pos")
SAMPLE_LIMIT = 8


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def var_covers(established_var, candidate_var):
    """Whether an established var's scope is the same as or broader than a
    candidate's on the dialect axis."""
    if established_var == candidate_var:
        return True
    return established_var == VAR_WILDCARD


def pos_covers(established_pos, candidate_pos):
    """Whether an established POS's scope is the same as or broader than a
    candidate's. Compound tags fall through to the exact-equal check only."""
    if established_pos == candidate_pos:
        return True
    return candidate_pos in POS_BROADENS.get(established_pos, ())


def build_established_index(pool):
    """(word_lower, shaw) -> list of (var, pos) established scopes, drawn from
    the POOL's own upstream ReadLex records ONLY (no separate readlex.json
    load — core rides in the pool since combine; never patches, so the build
    stays a pure function of its sources). Keyed on
    word+shaw because a candidate is only ever a duplicate of a same-spelling
    established entry; the var/pos comparison is the lattice test done at filter
    time.

    A core record carrying a `mergers` or `variant` flag is NOT registered: the
    dialect-model reinterpretation gave it var=RRP, but it is the merged
    exception form (TrapBath) or a free-variation alternate (RRPVar), not the
    canonical claim — registering it would wrongly turn an exception spelling
    into the RRP wildcard that covers every dialect. (The old raw readlex.json
    load registered their literal TrapBath/RRPVar vars, which covered nothing;
    excluding them here keeps that behaviour.) A candidate exactly matching such
    a record's full anchor was already merged into it at combine, so nothing is
    lost."""
    index = {}

    def register(word, shaw, var, pos):
        index.setdefault((word.lower(), shaw), []).append((var, pos))

    for entries in pool.values():
        for entry in entries:
            if not is_upstream(entry):
                continue
            if entry.get("mergers") or entry.get("variant"):
                continue
            register(entry["Latn"], entry["Shaw"], entry.get("var", ""),
                     entry.get("pos", ""))

    return index


def duplicate_reason(candidate, established_index):
    """The reason a candidate is a duplicate, or None if it is kept. Returns the
    first established scope that is same-or-broader on both axes, classified for
    the report: 'exact-var', 'rrp-wildcard' or 'pos-broadening'."""
    word = candidate["Latn"]
    shaw = candidate["Shaw"]
    cand_var = candidate.get("var", "")
    cand_pos = candidate.get("pos", "")

    for est_var, est_pos in established_index.get((word.lower(), shaw), ()):
        if not var_covers(est_var, cand_var):
            continue
        if not pos_covers(est_pos, cand_pos):
            continue
        if est_var == VAR_WILDCARD and cand_var != VAR_WILDCARD:
            return "rrp-wildcard"
        if est_pos != cand_pos:
            return "pos-broadening"
        return "exact-var"
    return None


# The pruning chain itself NEVER reads patches (see module docstring). These two
# helpers remain solely for fix_near_syllable_dots.py, an upstream pre-processor
# outside the pruning chain.
def load_patches():
    patches = []
    with open(PATCHES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def anchored_keys(patches):
    """The natural keys a patch's anchor resolves against — the candidates
    already under review."""
    return {anchor_key(patch["anchor"])
            for patch in patches if patch["anchor"] is not None}


def filter_supplement(supplement, established_index, reasons,
                      removed_samples, kept_close_samples):
    """Return a copy of a supplement dict with duplicate candidates removed,
    tallying reasons and collecting samples for the report. An upstream ReadLex
    record is always kept — it IS the established data and must never be dropped
    (it would self-annihilate against its own scope in the index)."""
    kept = {}
    for key, entries in supplement.items():
        kept_entries = []
        for entry in entries:
            if is_upstream(entry):
                kept_entries.append(entry)
                continue
            reason = duplicate_reason(entry, established_index)
            if reason is None:
                _collect_kept_close(entry, established_index, kept_close_samples)
                kept_entries.append(entry)
            else:
                reasons[reason] += 1
                if len(removed_samples[reason]) < SAMPLE_LIMIT:
                    removed_samples[reason].append(entry)
        if kept_entries:
            kept[key] = kept_entries
    return kept


def _collect_kept_close(candidate, established_index, kept_close_samples):
    """Classify a KEPT candidate that shares word+shaw with an established entry
    but was not covered, so the owner can confirm the keep is correct."""
    established = established_index.get(
        (candidate["Latn"].lower(), candidate["Shaw"]))
    if not established:
        return
    cand_var = candidate.get("var", "")
    cand_pos = candidate.get("pos", "")
    for est_var, est_pos in established:
        if not var_covers(est_var, cand_var):
            kind = "different-specific-var"
        elif not pos_covers(est_pos, cand_pos):
            kind = "incomparable-pos"
        else:
            continue
        if len(kept_close_samples[kind]) < SAMPLE_LIMIT:
            kept_close_samples[kind].append((candidate, est_var, est_pos))
        return


def format_entry(entry):
    return (f"{entry['Latn']!r} shaw={entry['Shaw']} "
            f"pos={entry.get('pos', '')} var={entry.get('var', '')}")


def report(total, removed_by_reason, removed_samples, kept_close_samples):
    removed = sum(removed_by_reason.values())
    print(f"\n=== duplicate filter report ===")
    print(f"Total candidates: {total:,}")
    print(f"Removed:          {removed:,}")
    print(f"Kept:             {total - removed:,}")
    print(f"\nRemoved by reason:")
    for reason in ("exact-var", "rrp-wildcard", "pos-broadening"):
        print(f"  {reason:16s} {removed_by_reason[reason]:,}")

    print(f"\nSample removed:")
    for reason in ("exact-var", "rrp-wildcard", "pos-broadening"):
        for entry in removed_samples[reason]:
            print(f"  [{reason}] {format_entry(entry)}")

    print(f"\nSample kept-but-close (shares word+shaw with an established entry):")
    for kind in KEPT_CLOSE_KINDS:
        for candidate, est_var, est_pos in kept_close_samples[kind]:
            print(f"  [{kind}] candidate {format_entry(candidate)} "
                  f"vs established var={est_var} pos={est_pos}")


def main():
    removed_by_reason = Counter()
    removed_samples = {r: [] for r in ("exact-var", "rrp-wildcard", "pos-broadening")}
    kept_close_samples = {kind: [] for kind in KEPT_CLOSE_KINDS}

    supplement = load_json(INPUT_PATH)
    established_index = build_established_index(supplement)
    total = sum(len(entries) for entries in supplement.values())
    filtered = filter_supplement(supplement, established_index,
                                 removed_by_reason, removed_samples,
                                 kept_close_samples)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in filtered.values()):,} candidates kept")

    report(total, removed_by_reason, removed_samples, kept_close_samples)


if __name__ == "__main__":
    main()
