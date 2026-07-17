#!/usr/bin/env python3
"""
Prune sum-of-parts multi-word phrases out of the supplement set before they
reach the editorial basis.

A multi-word candidate whose pronunciation is just its component words glued
together ("outer space", "false friend") carries no lexical information a
dictionary needs — it is concatenation noise. detect_phrase_divergence
classifies each phrase as:

  divergent  — pronunciation genuinely differs from sum-of-parts  → KEEP
  matches    — same as sum-of-parts                               → DROP
  unknown    — a component word could not be resolved             → KEEP

Only `matches` phrases are dropped; `divergent` and `unknown` stay (an
unresolvable component is not evidence of redundancy). Single-word candidates
are outside the phrase classifier's scope and always pass through. A candidate a
patch already anchors to has left the review surface and is exempt — dropping it
would orphan the patch's anchor (apply_patches.py fails loud on that).

This is the last pass of supplement candidate pruning, chained after the
duplicate filter and the merger classifier: reliable -> deduped -> classified ->
here (filtered) -> basis. Records pass through verbatim (only `matches` phrases
are dropped), so each candidate's `mergers` annotation survives to the basis. The
classification logic is reused wholesale from detect_phrase_divergence; this
module only decides drop/keep and rewrites files.

Inputs:  data/supplement-{wordnet,wiktionary}-classified.json  (the merger
         classifier's output).
Outputs: data/supplement-{wordnet,wiktionary}-filtered.json  — the basis reads
         these (see src/tools/basis.py). The -classified.json files are left
         untouched.

Usage:
    python3 src/tools/filter_supplement_phrases.py
"""

import json
from collections import Counter
from pathlib import Path

from basis import anchor_of
from detect_phrase_divergence import (
    MATCHES, PROJECT_ROOT, build_label_classifier, is_phrase_record,
)
from filter_supplement_duplicates import anchored_keys, load_patches

# (classified input, filtered output) per supplement source.
SUPPLEMENTS = [
    (PROJECT_ROOT / "data" / "supplement-wordnet-classified.json",
     PROJECT_ROOT / "data" / "supplement-wordnet-filtered.json"),
    (PROJECT_ROOT / "data" / "supplement-wiktionary-classified.json",
     PROJECT_ROOT / "data" / "supplement-wiktionary-filtered.json"),
]

SAMPLE_LIMIT = 8


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prune_supplement(supplement, label_of, exempt_keys, dropped_samples,
                     kept_samples):
    """A copy of a supplement dict with `matches` phrases removed. Single-word
    candidates and divergent/unknown phrases are kept, as is any candidate a
    patch anchors to. Collects samples and returns (pruned, dropped_count)."""
    pruned = {}
    dropped = 0
    for key, entries in supplement.items():
        kept_entries = []
        for entry in entries:
            if not is_phrase_record(entry):
                kept_entries.append(entry)
                continue
            label = label_of(entry)
            if label == MATCHES and anchor_of(entry) not in exempt_keys:
                dropped += 1
                if len(dropped_samples) < SAMPLE_LIMIT:
                    dropped_samples.append(entry)
                continue
            if len(kept_samples) < SAMPLE_LIMIT:
                kept_samples.append((entry, label))
            kept_entries.append(entry)
        if kept_entries:
            pruned[key] = kept_entries
    return pruned, dropped


def format_entry(entry):
    return (f"{entry['Latn']!r} shaw={entry['Shaw']} "
            f"pos={entry.get('pos', '')} var={entry.get('var', '')}")


def report(total_phrases, dropped, dropped_samples, kept_samples):
    print(f"\n=== phrase pruning report ===")
    print(f"Multi-word phrases seen: {total_phrases:,}")
    print(f"Dropped (matches):       {dropped:,}")
    print(f"Kept (divergent/unknown):{total_phrases - dropped:,}")

    print(f"\nSample dropped (sum-of-parts glue):")
    for entry in dropped_samples:
        print(f"  {format_entry(entry)}")

    print(f"\nSample kept:")
    for entry, label in kept_samples:
        print(f"  [{label}] {format_entry(entry)}")


def main():
    label_of = build_label_classifier()
    exempt_keys = anchored_keys(load_patches())

    dropped_samples = []
    kept_samples = []
    total_phrases = 0
    total_dropped = 0

    for classified_path, filtered_path in SUPPLEMENTS:
        supplement = load_json(classified_path)
        total_phrases += sum(
            1 for entries in supplement.values()
            for entry in entries if is_phrase_record(entry))
        pruned, dropped = prune_supplement(
            supplement, label_of, exempt_keys, dropped_samples, kept_samples)
        total_dropped += dropped
        with open(filtered_path, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False, indent=4)
        print(f"Wrote {filtered_path.relative_to(PROJECT_ROOT)}: "
              f"{sum(len(v) for v in pruned.values()):,} candidates kept")

    report(total_phrases, total_dropped, dropped_samples, kept_samples)


if __name__ == "__main__":
    main()
