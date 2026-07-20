#!/usr/bin/env python3
"""
Apply the editorial patch store to the computed basis, producing data/readlex.json.

This replaces generate_merged_readlex.py. The model (see
docs/editorial-overlay-design.md, "The patch record (settled model)"):

  - The BASIS is the combined supplement pool, computed on-demand. Upstream
    ReadLex (external/readlex/readlex.json) rides IN the pool — collated at
    combine time under the `readlex` source label, carried through the pruning
    chain untouched — so the pool is the basis's single union point and every
    upstream anchor appears exactly once. Every candidate, including the
    unreviewed supplemental ones, is a record in the basis. Nothing is frozen.

  - A PATCH (data/patches/patches.jsonl) is {anchor, op, changes, meta}:
      anchor   the natural key {word, pos, shaw, var} of the ONE basis record it
               reviews, or null for authorship. Immutable identity — never changed
               when the record is edited.
      op       accept (sanction the anchored basis record) / drop (remove it) /
               flag (production no-op). Authorship has no op.
      changes  the intrinsic edits {word, shaw, pos, ipa, var, mergers, variant}
               an accept lays over the LIVE basis record (empty = accept as-is);
               or, for authorship, the whole self-contained record.

  - The OUTPUT starts as upstream ReadLex (an unreviewed candidate has no patch,
    so it never enters the output) and is mutated patch by patch. Each patch is
    resolved over the LIVE basis (basis.resolve_patch): an accept removes the
    anchored source record and re-emits it sanctioned with `changes` laid over
    it; a drop removes it; a flag leaves it untouched. Authorship (anchor null)
    emits `changes` as a standalone record.

  - SOFT-FAIL on an orphaned decision: an anchor that resolves against NOTHING in
    the basis (upstream drifted since the decision was made) is LOGGED and SKIPPED
    (it contributes nothing to the output), but the build still succeeds. The
    patch is RETAINED in the store (this applicator never rewrites it) and surfaced
    in the editor via the `orphaned` filter, where the owner re-anchors or discards
    it. An orphan is a recoverable, visible state — never a fatal error, and never
    a silent lost verdict.

Determinism: patches are applied in a total order over their anchor identity and
id, so identical inputs yield an identical readlex.json.

Usage:
    python3 src/tools/apply_patches.py
"""

import json
import os
import sys
from pathlib import Path

from basis import (
    PATCH_NOOP,
    PATCH_ORPHAN,
    PROJECT_ROOT,
    anchor_key,
    anchor_of,
    build_basis,
    load_upstream,
    reanchor_index,
    reanchor_patch,
    resolve_patch,
)

DEFAULT_PATCHES_PATH = PROJECT_ROOT / "data" / "patches" / "patches.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "data" / "readlex.json"


def patches_path():
    """The patch store to apply — the SHAW_SPELL_PATCH_STORE env var if set, else
    the live store. Resolved at call time so a migrated scratchpad store can be
    applied without touching the live one (mirrors patchstore._store_path)."""
    env = os.environ.get("SHAW_SPELL_PATCH_STORE")
    return Path(env) if env else DEFAULT_PATCHES_PATH

# Valid Shavian chars — a record whose Shaw contains anything else (e.g. an
# unconverted IPA fragment) is skipped, matching the legacy applicator.
KNOWN_SHAW = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘"
                 "𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")


def load_patches():
    patches = []
    with open(patches_path(), "r", encoding="utf-8") as f:
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
    authorship patch (anchor null) is ordered by its record's natural key, which
    for authorship IS its `changes`."""
    anchor = patch["anchor"] or patch["changes"]
    return (*anchor_key(anchor), patch["id"])


def apply_patches(output, basis_index, basis_source, patches):
    stats = {"authorship": 0, "update": 0, "removal": 0, "flag": 0, "orphaned": 0,
             "reanchored": 0, "skipped_numeral": 0, "skipped_shaw": 0}
    orphans = []

    # The auto-re-anchor lookup: an OLD natural key a key-moving transform rewrote
    # -> the CURRENT key of the record now carrying it (via orig_*). Built once so
    # the FIRST resort for an orphaned anchor is to follow the record to its new
    # key, ahead of the soft-fail below. Empty (and free) when no basis record
    # carries orig_* — the pre-convention behaviour.
    reanchor_map = reanchor_index(basis_index)

    for patch in sorted(patches, key=patch_order_key):
        entry = resolve_patch(patch, basis_index, basis_source)

        # A flag carries no editorial change ("looked at, no verdict yet"): it is
        # a pure no-op for production. The record leaves the output exactly as
        # upstream had it — no removal, no re-emit.
        if entry is PATCH_NOOP:
            stats["flag"] += 1
            continue

        # The anchor no longer resolves against the basis. FIRST resort: a key-
        # moving transform (var relabel / respell) may have rewritten the record
        # but preserved its old key in orig_*. If so, follow the record to its new
        # key and apply the decision there — the verdict is preserved automatically,
        # no manual migration. Only if no orig_* record covers the anchor does it
        # fall through to the soft-fail below.
        if entry is PATCH_ORPHAN:
            moved = reanchor_patch(patch, reanchor_map)
            reresolved = (resolve_patch(moved, basis_index, basis_source)
                          if moved is not None else None)
            if moved is None or reresolved is PATCH_ORPHAN:
                # Still orphaned: upstream drifted and no orig_* pre-image covers
                # it. Collect to log below and skip — it contributes nothing to the
                # output. The patch stays in the store (this applicator never
                # rewrites it) and is surfaced via the editor's `orphaned` filter.
                orphans.append(patch)
                stats["orphaned"] += 1
                continue
            # Auto-re-anchored: apply against the record's current key. The removal
            # below must target the CURRENT anchor (where the record now lives), so
            # carry the moved patch forward.
            patch, entry = moved, reresolved
            stats["reanchored"] += 1

        if patch["anchor"] is None:
            # Authorship: a standalone record no source attests.
            if is_emittable(entry["Latn"], entry["Shaw"], stats):
                insert_entry(output, entry)
                stats["authorship"] += 1
            continue

        # Accept or drop: the anchored source record leaves the output first.
        remove_anchored(output, anchor_key(patch["anchor"]))

        if entry is None:
            stats["removal"] += 1
            continue

        if is_emittable(entry["Latn"], entry["Shaw"], stats):
            insert_entry(output, entry)
        stats["update"] += 1

    return stats, orphans


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Apply the patch store to produce merged readlex")
    ap.add_argument("--out", dest="out_path", default=str(OUTPUT_PATH),
                    help="where to write the merged readlex (default: data/readlex.json)")
    out_path = Path(ap.parse_args().out_path)

    output = load_upstream()
    print(f"Upstream: {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")

    basis_index, basis_source = build_basis()
    print(f"Basis:    {len(basis_index):,} records "
          f"(the combined pool; ReadLex core rides in it as upstream records)")

    patches = load_patches()
    print(f"Patches:  {len(patches):,}")

    stats, orphans = apply_patches(output, basis_index, basis_source, patches)

    # Soft-fail on orphaned decisions: an anchor that no longer resolves means
    # upstream drifted out from under an editorial decision. LOG each one (so it is
    # never silently lost) and SKIP it (it applied nothing above), but still write
    # the output and exit 0 — an orphan is a recoverable, surfaced state, not a
    # blocked build. The patch stays in the store (this applicator never rewrites
    # it); the owner finds and fixes it via the editor's `orphaned` filter.
    if orphans:
        print(f"WARNING: {len(orphans)} orphaned decision(s) skipped — an anchor no "
              f"longer resolves against the basis (upstream drifted). Retained in the "
              f"store; surface via the editor 'orphaned' filter to re-anchor or drop.",
              file=sys.stderr)
        for patch in orphans:
            anchor = patch["anchor"]
            print(f"    {anchor['word']!r} pos={anchor['pos']} shaw={anchor['shaw']} "
                  f"var={anchor['var']} (id={patch['id']})", file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"\nMerged:   {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")
    print(f"  authorship (added):  {stats['authorship']:,}")
    print(f"  update/respell:      {stats['update']:,}")
    print(f"  removal:             {stats['removal']:,}")
    print(f"  flag (no-op):        {stats['flag']:,}")
    print(f"  auto-re-anchored:    {stats['reanchored']:,}"
          + ("  — orphaned anchor followed to its transformed record via orig_*"
             if stats['reanchored'] else ""))
    print(f"  orphaned (skipped):  {stats['orphaned']:,}"
          + ("  — see log above; retained in store, surface via editor 'orphaned' filter"
             if stats['orphaned'] else ""))
    print(f"  skipped (numeral):   {stats['skipped_numeral']:,}")
    print(f"  skipped (bad shaw):  {stats['skipped_shaw']:,}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
