#!/usr/bin/env python3
"""
Repair authored-orphan patch pairs in data/patches/patches.jsonl.

A now-fixed editor bug re-decided an AUTHORED entry (a word no source attests,
carried only by an anchor-null authorship patch) by writing a SECOND patch with a
NON-null anchor — as if a basis record existed. It does not, so that anchored
patch resolves to nothing and apply_patches.py fails the build on the orphan.

This repair merges each such pair back into one authorship patch:

  - An orphaned anchored patch is one whose anchor resolves to NO basis record.
  - If its natural key (word, pos, shaw, var) matches an existing authorship
    patch (anchor null) for the same word, the human's verdict recorded on the
    orphan (its record — e.g. sanctioned status — and any meta.flag) is merged
    INTO the authorship patch, keeping anchor null, and the orphan is dropped.

The merged patch carries a NEW content-derived id (its record changed), matching
how the fixed editor now writes authored re-decisions.

Genuine orphans — anchored patches that resolve to no basis record AND match no
authorship patch — are NOT this bug (upstream drifted out from under a real
decision). They are reported and the repair FAILS, since the store still will not
build; re-anchor or remove them separately.

Idempotent: a store with no authored orphans is left byte-for-byte unchanged.
Deterministic and reversible — it only rewrites patches.jsonl, which git tracks.

The owner runs this with the editor daemon QUIESCED (it writes the same file):

    python3 src/tools/repair_authored_orphans.py

Add --dry-run to report the repairs without writing.
"""

import argparse
import sys
from pathlib import Path

# patchstore lives in src/editor; basis in this dir (src/tools). Put the editor
# dir on the path so `import patchstore` resolves (basis is already importable).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "editor"))

from basis import anchor_key, build_basis_index  # noqa: E402
from patchstore import PATCHES_PATH, load_patches, make_patch, write_patches  # noqa: E402


def _authored_by_key(patches):
    """Index of authorship patches (anchor null) by their record's natural key.
    Fails loud on two authorship patches sharing a key — an ambiguous merge
    target the repair must not guess at."""
    index = {}
    for patch in patches:
        if patch["anchor"] is None:
            key = anchor_key(patch["record"])
            if key in index:
                raise ValueError(f"two authorship patches share natural key {key}")
            index[key] = patch
    return index


def _merged_authored_patch(orphan, authored):
    """The authorship patch that folds the orphan's verdict in: anchor null, the
    orphan's decided record, and its meta (carrying meta.flag if the orphan was a
    flag). Keeps the authorship author/origin so provenance stays authored."""
    meta = dict(authored["meta"])
    if orphan["meta"].get("flag"):
        meta["flag"] = True
    else:
        meta.pop("flag", None)
    return make_patch(None, orphan["record"], meta)


def repair(patches, basis_index):
    """Return (repaired_patches, merges, genuine_orphans). Each merge replaces an
    authorship patch in place and drops the paired orphan; genuine orphans are
    anchored patches resolving to no basis record with no authorship match."""
    authored = _authored_by_key(patches)
    merges = []
    genuine_orphans = []
    drop_ids = set()
    replacements = {}

    for patch in patches:
        anchor = patch["anchor"]
        if anchor is None or anchor_key(anchor) in basis_index:
            continue
        key = anchor_key(anchor)
        target = authored.get(key)
        if target is None:
            genuine_orphans.append(patch)
            continue
        merged = _merged_authored_patch(patch, target)
        replacements[target["id"]] = merged
        drop_ids.add(patch["id"])
        merges.append((patch, target, merged))

    repaired = [replacements.get(p["id"], p) for p in patches if p["id"] not in drop_ids]
    return repaired, merges, genuine_orphans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report repairs without writing")
    parser.add_argument("--path", default=str(PATCHES_PATH),
                        help="patch store to repair (default: the live store)")
    args = parser.parse_args()

    path = Path(args.path)
    patches = load_patches(path)
    basis_index = build_basis_index()

    repaired, merges, genuine_orphans = repair(patches, basis_index)

    for orphan, target, merged in merges:
        anchor = orphan["anchor"]
        verdict = "flag" if merged["meta"].get("flag") else merged["record"].get("status")
        print(f"merge {orphan['id']} -> {target['id']} "
              f"({anchor['word']!r} {anchor['pos']}, {verdict}) => {merged['id']}")

    if not merges:
        print("no authored orphans to repair")

    if genuine_orphans:
        print(f"\nFATAL: {len(genuine_orphans)} orphaned decision(s) resolve to no "
              f"basis record AND match no authored entry — not this bug. "
              f"Re-anchor or remove them:", file=sys.stderr)
        for patch in genuine_orphans:
            anchor = patch["anchor"]
            print(f"    {anchor['word']!r} pos={anchor['pos']} shaw={anchor['shaw']} "
                  f"var={anchor['var']} (id={patch['id']})", file=sys.stderr)
        raise SystemExit(1)

    if args.dry_run:
        print(f"\n[dry-run] would merge {len(merges)}, leaving {len(repaired)} patches")
        return
    if merges:
        write_patches(repaired, path)
        print(f"\nwrote {len(repaired)} patches to {path}")


if __name__ == "__main__":
    main()
