#!/usr/bin/env python3
"""
Apply the editorial patch store to the computed basis, producing data/readlex.json.

This replaces generate_merged_readlex.py. The model (see
docs/editorial-overlay-design.md, "The patch record (settled model)"):

  - The BASIS is the raw combination of all upstream sources — upstream ReadLex
    (external/readlex/readlex.json) plus the wordnet and wiktionary supplement
    candidates — computed on-demand. Every candidate, including the ~85K
    unreviewed supplemental ones, is a record in the basis. Nothing is frozen.

  - A PATCH (data/patches/patches.jsonl) is {anchor, record, meta}:
      anchor  the natural key {word, pos, shaw, var} of the ONE basis record it
              reviews, or null for authorship. Immutable identity — never changed
              when the record is edited.
      record  the COMPLETE record you want {word, pos, shaw, var, ipa, freq,
              status, …}, emitted VERBATIM with no source+patch merge; or null to
              drop the anchored record.

  - The OUTPUT starts as upstream ReadLex (an unreviewed candidate has no patch,
    so it never enters the output) and is mutated patch by patch: the anchored
    source record is removed, then `record` (if non-null) is emitted verbatim.
    Authorship (anchor null) simply emits `record`.

  - FAIL LOUD on an orphaned decision: an anchor that resolves against NOTHING in
    the basis (upstream drifted since the decision was made) is surfaced, not
    silently dropped.

Determinism: patches are applied in a total order over their anchor identity and
id, so identical inputs yield an identical readlex.json.

Usage:
    python3 src/tools/apply_patches.py
"""

import json
import sys

from basis import (
    PROJECT_ROOT,
    SUPPLEMENT_PATHS,
    UPSTREAM_PATH,
    anchor_key,
    anchor_of,
    build_basis_index,
    load_json,
    record_to_output,
)

PATCHES_PATH = PROJECT_ROOT / "data" / "patches" / "patches.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "data" / "readlex.json"

# Valid Shavian chars — a record whose Shaw contains anything else (e.g. an
# unconverted IPA fragment) is skipped, matching the legacy applicator.
KNOWN_SHAW = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘"
                 "𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")


def load_patches():
    patches = []
    with open(PATCHES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def remove_anchored(output, key):
    """Remove from the output the single entry whose natural key matches."""
    for bucket_key in list(output.keys()):
        kept = [e for e in output[bucket_key] if anchor_of(e) != key]
        if len(kept) != len(output[bucket_key]):
            if kept:
                output[bucket_key] = kept
            else:
                del output[bucket_key]
            return


def insert_entry(output, entry):
    """Insert an output record under its ReadLex key, skipping an exact-identity
    duplicate already present (e.g. the same natural key from two sources)."""
    key = f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"
    bucket = output.setdefault(key, [])
    identity = anchor_of(entry)
    if any(anchor_of(existing) == identity for existing in bucket):
        return
    bucket.append(entry)


def is_emittable(word, shaw, stats):
    """Whether a record survives the numeral / bad-Shavian output filters,
    tallying the reason when it does not."""
    if word and word[0].isdigit():
        stats["skipped_numeral"] += 1
        return False
    if set(shaw) - KNOWN_SHAW:
        stats["skipped_shaw"] += 1
        return False
    return True


def patch_order_key(patch):
    """Total, deterministic apply order over anchor identity then patch id. An
    authorship patch (anchor null) is ordered by its record's natural key."""
    anchor = patch["anchor"] or patch["record"]
    return (*anchor_key(anchor), patch["id"])


def apply_patches(output, basis_index, patches):
    stats = {"authorship": 0, "update": 0, "removal": 0, "orphaned": 0,
             "skipped_numeral": 0, "skipped_shaw": 0}
    orphans = []

    for patch in sorted(patches, key=patch_order_key):
        anchor, record = patch["anchor"], patch["record"]

        if anchor is None:
            # Authorship: a standalone record no source attests.
            if is_emittable(record["word"], record["shaw"], stats):
                insert_entry(output, record_to_output(record))
                stats["authorship"] += 1
            continue

        # Resolve the anchor against the basis by its full natural key.
        if anchor_key(anchor) not in basis_index:
            # Upstream drifted: the record this decision was made against no
            # longer exists. Surface it loudly rather than dropping it.
            orphans.append(patch)
            stats["orphaned"] += 1
            continue

        remove_anchored(output, anchor_key(anchor))

        if record is None:
            stats["removal"] += 1
            continue

        entry = record_to_output(record)
        if is_emittable(entry["Latn"], entry["Shaw"], stats):
            insert_entry(output, entry)
        stats["update"] += 1

    return stats, orphans


def main():
    output = load_json(UPSTREAM_PATH)
    print(f"Upstream: {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")

    basis_index = build_basis_index()
    print(f"Basis:    {len(basis_index):,} records "
          f"(upstream + {len(SUPPLEMENT_PATHS)} supplements)")

    patches = load_patches()
    print(f"Patches:  {len(patches):,}")

    stats, orphans = apply_patches(output, basis_index, patches)

    # Fail loud on orphaned decisions BEFORE writing anything. An anchor that no
    # longer resolves means upstream drifted out from under an editorial
    # decision; shipping a dictionary that silently dropped it is the exact
    # "lost verdicts" failure this system exists to prevent. No output written.
    if orphans:
        print(f"FATAL: {len(orphans)} orphaned decision(s) — an anchor no longer "
              f"resolves against the basis. Re-anchor or remove them.",
              file=sys.stderr)
        for patch in orphans:
            anchor = patch["anchor"]
            print(f"    {anchor['word']!r} pos={anchor['pos']} shaw={anchor['shaw']} "
                  f"var={anchor['var']} (id={patch['id']})", file=sys.stderr)
        raise SystemExit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"\nMerged:   {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")
    print(f"  authorship (added):  {stats['authorship']:,}")
    print(f"  update/respell:      {stats['update']:,}")
    print(f"  removal:             {stats['removal']:,}")
    print(f"  skipped (numeral):   {stats['skipped_numeral']:,}")
    print(f"  skipped (bad shaw):  {stats['skipped_shaw']:,}")
    print(f"\nWrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
