#!/usr/bin/env python3
"""
Filter redundant candidates out of the supplement set before they reach the
editorial basis.

A supplement candidate is a DUPLICATE — and is removed — when an already
established entry would resolve to the same Shavian spelling for the candidate's
scope. "Established" is upstream ReadLex plus sanctioned patches. Resolution is
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

The filter trims only the UNREVIEWED review surface: a candidate a patch already
anchors to has left that surface, so it is exempt. Removing it would serve no
purpose and would orphan the patch's anchor (see apply_patches.py).

This is the first pass of supplement candidate pruning; the phrase-pruning pass
(filter_supplement_phrases.py) reads the -deduped.json output next and produces
the -filtered.json the basis consumes.

Inputs:  data/supplement-wordnet-reliable.json (the generator's output) and
         data/supplement-wiktionary-rescued.json (generator output augmented with
         rescued proper nouns), external/readlex/readlex.json,
         data/patches/patches.jsonl.
Outputs: data/supplement-{wordnet,wiktionary}-deduped.json  — the phrase filter
         reads these. The -reliable.json files are left untouched; the removed
         candidates are regenerable machine output.

Usage:
    python3 src/tools/filter_supplement_duplicates.py
"""

import json
from collections import Counter
from pathlib import Path

from basis import PROJECT_ROOT, anchor_key, anchor_of

UPSTREAM_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
PATCHES_PATH = PROJECT_ROOT / "data" / "patches" / "patches.jsonl"

# (reliable input, deduped output) per supplement source.
SUPPLEMENTS = [
    (PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json",
     PROJECT_ROOT / "data" / "supplement-wordnet-deduped.json"),
    (PROJECT_ROOT / "data" / "supplement-wiktionary-rescued.json",
     PROJECT_ROOT / "data" / "supplement-wiktionary-deduped.json"),
]

# An established entry counts only if the owner has sanctioned it; other patch
# states are still under review and do not establish anything.
SANCTIONED_STATUS = "sanctioned"

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


def build_established_index(upstream, patches):
    """(word_lower, shaw) -> list of (var, pos) established scopes, drawn from
    upstream ReadLex and sanctioned patches. Keyed on word+shaw because a
    candidate is only ever a duplicate of a same-spelling established entry; the
    var/pos comparison is the lattice test done at filter time."""
    index = {}

    def register(word, shaw, var, pos):
        index.setdefault((word.lower(), shaw), []).append((var, pos))

    for entries in upstream.values():
        for entry in entries:
            register(entry["Latn"], entry["Shaw"], entry.get("var", ""),
                     entry.get("pos", ""))

    for patch in patches:
        record = patch.get("record")
        if record is None or record.get("status") != SANCTIONED_STATUS:
            continue
        register(record["word"], record["shaw"], record.get("var", ""),
                 record.get("pos", ""))

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
    already under review, exempt from filtering."""
    return {anchor_key(patch["anchor"])
            for patch in patches if patch["anchor"] is not None}


def filter_supplement(supplement, established_index, exempt_keys, reasons,
                      removed_samples, kept_close_samples):
    """Return a copy of a supplement dict with duplicate candidates removed,
    tallying reasons and collecting samples for the report. A candidate whose
    natural key is in exempt_keys (a patch anchors to it) is always kept."""
    kept = {}
    for key, entries in supplement.items():
        kept_entries = []
        for entry in entries:
            if anchor_of(entry) in exempt_keys:
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


def report(total, removed_by_reason, removed_samples, kept_close_samples,
           dirty_vars):
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

    if dirty_vars:
        print(f"\nWARNING: non-canonical upstream var values seen (treated "
              f"literally, NOT as the RRP wildcard):")
        for var, count in sorted(dirty_vars.items()):
            print(f"  {var!r}: {count:,}")


def main():
    upstream = load_json(UPSTREAM_PATH)
    patches = load_patches()
    established_index = build_established_index(upstream, patches)
    exempt_keys = anchored_keys(patches)

    dirty_vars = Counter()
    canonical_vars = {VAR_WILDCARD, "GenAm", "TrapBath", "GenAus", "RSSB"}
    for entries in upstream.values():
        for entry in entries:
            var = entry.get("var", "")
            if var and var not in canonical_vars:
                dirty_vars[var] += 1

    removed_by_reason = Counter()
    removed_samples = {r: [] for r in ("exact-var", "rrp-wildcard", "pos-broadening")}
    kept_close_samples = {kind: [] for kind in KEPT_CLOSE_KINDS}

    total = 0
    for reliable_path, filtered_path in SUPPLEMENTS:
        supplement = load_json(reliable_path)
        total += sum(len(entries) for entries in supplement.values())
        filtered = filter_supplement(supplement, established_index, exempt_keys,
                                     removed_by_reason, removed_samples,
                                     kept_close_samples)
        with open(filtered_path, "w", encoding="utf-8") as f:
            json.dump(filtered, f, ensure_ascii=False, indent=4)
        print(f"Wrote {filtered_path.relative_to(PROJECT_ROOT)}: "
              f"{sum(len(v) for v in filtered.values()):,} candidates kept")

    report(total, removed_by_reason, removed_samples, kept_close_samples,
           dirty_vars)


if __name__ == "__main__":
    main()
