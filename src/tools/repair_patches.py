#!/usr/bin/env python3
"""
Persist the applicator's auto-re-anchor into the patch store — the ON-DEMAND,
BAKED counterpart to the in-memory re-anchoring apply_patches does every build.

WHY THIS EXISTS
---------------
The natural key of a patch is (word, pos, shaw, var). When a pipeline transform
relabels a record's `var` (the identical-dialect collapse, or a forthcoming RRP
classifier), the record's key MOVES and every editorial patch anchored to the OLD
key is ORPHANED. The transform preserves the pre-image on the moved record in
orig_* (see basis.mark_original), so the applicator ALREADY follows an orphaned
patch to the record's new key IN MEMORY every apply (basis.reanchor_index /
reanchor_patch, hooked into apply_patches ahead of its soft-fail). That repair is
recomputed on every build and never written down.

This script writes it down. Run it ONCE after a reclassification to REWRITE the
orphaned patches' anchors in data/patches/patches.jsonl to their new keys, so the
repair is baked into the committed store — visible and permanent — rather than
recomputed each build. It is also the fallback / bulk migration tool.

WHAT IT REPAIRS vs WHAT IT LEAVES ALONE (the owner's settled principle)
-----------------------------------------------------------------------
It re-anchors ONLY var-relabel orphans: a patch whose anchor no longer resolves,
which the orig_* breadcrumb path (reanchor_index) can follow to a record whose
SPELLING is unchanged. A changed SHAW is a different spelling and needs human
re-review, so shaw-change orphans are NEVER auto-rewritten — they are REPORTED
(and left byte-identical) as "needs re-review, not auto-repairable". An orphan
that no record's orig_* covers at all is REPORTED as "fully gone".

    NOTE — reanchor_index already discriminates: it swaps BOTH orig_var and
    orig_shaw back when reconstructing the old key. A patch that only re-anchors
    because a shaw changed would land via a record carrying orig_shaw. We detect
    that (the target record's shaw differs from the anchor's shaw) and REFUSE to
    rewrite it here, deferring to re-review — even though the applicator would
    follow it in memory. This script bakes only the safe, spelling-preserving
    var relabels; shaw moves stay in the recomputed-each-build regime.

SAFETY (this rewrites the owner's editorial decisions — sacred)
---------------------------------------------------------------
  - DRY-RUN by default. It reports what it WOULD change and writes nothing.
    Rewriting requires the explicit --write flag.
  - --write BACKS UP the store first (timestamped sibling copy) and prints the
    backup path, then writes atomically (temp + rename, via patchstore).
  - FAIL-LOUD: an internal inconsistency (a re-anchor target that does not
    resolve, a shaw actually changing under a var re-anchor) aborts rather than
    shipping a corrupted store. No decision is ever silently dropped.
  - It ONLY moves anchors of safe var-relabel orphans; op / changes / id / meta
    and every other patch are left byte-for-byte as loaded, in original order.
  - Point it at a TEMP COPY via SHAW_SPELL_PATCH_STORE for development/testing.
    It must NEVER be run --write against the live store without the owner's
    explicit go — it is a tool left ready for the owner, not auto-run.

Usage:
    python3 src/tools/repair_patches.py            # dry-run report (default)
    python3 src/tools/repair_patches.py --write     # back up + rewrite in place

    SHAW_SPELL_PATCH_STORE=/tmp/copy.jsonl \\
        python3 src/tools/repair_patches.py [--write]   # against a temp copy
"""

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# patchstore lives in src/editor; basis in this dir (src/tools). Put the editor dir
# on the path so `import patchstore` resolves (basis is already importable). Both
# resolve the store path at call time from SHAW_SPELL_PATCH_STORE, so a temp copy
# is applied without touching the live store.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "editor"))

from basis import (                                              # noqa: E402
    anchor_from_key,
    anchor_key,
    build_basis_index,
    reanchor_index,
)
import patchstore                                                # noqa: E402


def resolves(anchor, basis_index):
    """Whether a patch anchor resolves against a live basis record."""
    return anchor is not None and anchor_key(anchor) in basis_index


def classify_orphan(patch, basis_index, reanchor_map):
    """Classify an orphaned patch (anchor absent from the basis) and, when it is a
    safe var-relabel, the new anchor to rewrite it to.

    Returns one of:
      ("var-relabel", new_anchor)  the orig_* breadcrumb follows the record to a
                                   new key whose SHAW is UNCHANGED — safe to bake.
      ("shaw-changed", None)       a record carries the pre-image but its SHAW
                                   differs (a respell): needs re-review, not baked.
      ("gone", None)               no record's orig_* covers this anchor at all.
    """
    old_key = anchor_key(patch["anchor"])
    current_key = reanchor_map.get(old_key)
    if current_key is None:
        return ("gone", None)

    # reanchor_index reconstructs the old key by swapping BOTH orig_shaw and
    # orig_var back. If the shaw slot differs between the old (anchored) key and the
    # current key, the record was RESPELLED — a changed spelling needs re-review, so
    # we refuse to bake it and defer to the owner (the applicator still follows it in
    # memory, but this persistent tool does not).
    _, _, old_shaw, _ = old_key
    _, _, current_shaw, _ = current_key
    if old_shaw != current_shaw:
        return ("shaw-changed", None)

    return ("var-relabel", anchor_from_key(current_key))


def plan_repairs(patches, basis_index):
    """Partition the store into (repairs, shaw_changed, gone, untouched).

      repairs      [(index, patch, new_anchor)]  var-relabel orphans to rewrite
      shaw_changed [(index, patch)]              respell orphans — report, re-review
      gone         [(index, patch)]              no orig_* covers it — report
      untouched    count of patches whose anchor resolves (or authorship) — no-op

    Nothing is mutated here; the caller decides whether to write the repairs.
    """
    reanchor_map = reanchor_index(basis_index)
    repairs, shaw_changed, gone = [], [], []
    untouched = 0

    for i, patch in enumerate(patches):
        anchor = patch["anchor"]
        # Authorship (anchor null) has no basis anchor to orphan; a resolving anchor
        # is live. Either way there is nothing to re-anchor.
        if anchor is None or resolves(anchor, basis_index):
            untouched += 1
            continue

        kind, new_anchor = classify_orphan(patch, basis_index, reanchor_map)
        if kind == "var-relabel":
            repairs.append((i, patch, new_anchor))
        elif kind == "shaw-changed":
            shaw_changed.append((i, patch))
        else:
            gone.append((i, patch))

    return repairs, shaw_changed, gone, untouched


def find_collisions(patches, repairs):
    """The repairs whose new anchor collides with ANOTHER patch's anchor in the
    resulting store — a re-anchor that would leave two patches on one natural key,
    breaking the store's one-patch-per-anchor identity (patchstore upserts by
    anchor). Returns [(patch, new_anchor, other_id)].

    The colliding "other" is any patch (repaired or not) that ends up on the same
    key, excluding the repaired patch itself. A collision is NOT auto-resolvable
    (which verdict wins?), so the caller reports it and aborts the write rather than
    silently merging or dropping a decision.
    """
    # The anchor each patch holds AFTER repairs are applied: a repaired patch takes
    # its new anchor, every other keeps its own (authorship => no key).
    repaired_by_index = {i: new_anchor for i, _p, new_anchor in repairs}
    final_key_owners = {}
    for i, patch in enumerate(patches):
        anchor = repaired_by_index.get(i, patch["anchor"])
        if anchor is None:
            continue
        final_key_owners.setdefault(anchor_key(anchor), []).append(patch["id"])

    collisions = []
    for _i, patch, new_anchor in repairs:
        owners = final_key_owners[anchor_key(new_anchor)]
        other = [pid for pid in owners if pid != patch["id"]]
        if other:
            collisions.append((patch, new_anchor, other[0]))
    return collisions


def rewrite_anchor(patch, new_anchor, basis_index):
    """A copy of `patch` with ONLY its anchor moved to `new_anchor`, preserving
    op / changes / id / meta and key order. Fails loud if the new anchor does not
    resolve against the basis, or if the rewrite would change the shaw (a var
    re-anchor must never move spelling) — a corrupt re-anchor aborts, never ships.
    """
    if anchor_key(new_anchor) not in basis_index:
        raise RuntimeError(
            f"repair target does not resolve against basis: {new_anchor} "
            f"(patch id={patch['id']})")
    if new_anchor["shaw"] != patch["anchor"]["shaw"]:
        raise RuntimeError(
            f"var re-anchor would change shaw {patch['anchor']['shaw']!r} -> "
            f"{new_anchor['shaw']!r} (patch id={patch['id']}); refusing")
    moved = dict(patch)
    moved["anchor"] = new_anchor
    return moved


def _anchor_str(anchor):
    if anchor is None:
        return "<authorship>"
    return (f"word={anchor['word']!r} pos={anchor['pos']} "
            f"shaw={anchor['shaw']} var={anchor['var']}")


def report(store_path, total, repairs, shaw_changed, gone, untouched):
    print(f"Patch store: {store_path}")
    print(f"  patches:            {total:,}")
    print(f"  resolve / untouched:{untouched:,}")
    print(f"  var-relabel repairs:{len(repairs):,}  (re-anchorable, spelling unchanged)")
    print(f"  shaw-changed:       {len(shaw_changed):,}  (respelled — needs re-review, NOT auto-repaired)")
    print(f"  fully gone:         {len(gone):,}  (no orig_* covers the anchor — needs re-review)")

    if repairs:
        print("\nVAR-RELABEL RE-ANCHORS (var changes; would be rewritten with --write):")
        for _i, patch, new_anchor in repairs:
            old = patch["anchor"]
            print(f"  [{patch['id']}] {old['var']} -> {new_anchor['var']}   "
                  f"({old['word']!r} pos={old['pos']} shaw={old['shaw']})")

    if shaw_changed:
        print("\nSHAW-CHANGED ORPHANS (respelled — reported only, left untouched for re-review):")
        for _i, patch in shaw_changed:
            print(f"  [{patch['id']}] {_anchor_str(patch['anchor'])}")

    if gone:
        print("\nFULLY-GONE ORPHANS (no orig_* covers the anchor — reported only, for re-review):")
        for _i, patch in gone:
            print(f"  [{patch['id']}] {_anchor_str(patch['anchor'])}")


def backup_store(store_path):
    """Timestamped sibling backup of the store; returns the backup path. Fails loud
    if the store is missing — we never write repairs over a store we could not back
    up first."""
    if not store_path.exists():
        raise FileNotFoundError(f"patch store not found, refusing to write: {store_path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = store_path.with_name(f"{store_path.name}.bak-{stamp}")
    if backup.exists():
        raise FileExistsError(f"backup already exists, refusing to overwrite: {backup}")
    shutil.copy2(store_path, backup)
    return backup


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Bake the applicator's var-relabel re-anchoring into the patch "
                    "store. DRY-RUN by default; --write to rewrite in place.")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the re-anchored patches in place (backs up first). "
                         "Without this, only report what would change.")
    args = ap.parse_args()

    store_path = patchstore._store_path()
    patches = patchstore.load_patches()
    basis_index = build_basis_index()

    repairs, shaw_changed, gone, untouched = plan_repairs(patches, basis_index)
    report(store_path, len(patches), repairs, shaw_changed, gone, untouched)

    # A re-anchor that lands on a key another patch already holds would leave two
    # patches on one identity — surface it and refuse to write. Not auto-resolvable.
    collisions = find_collisions(patches, repairs)
    if collisions:
        print("\nCOLLISION: re-anchor target already held by another patch — cannot "
              "bake without losing a decision:", file=sys.stderr)
        for patch, new_anchor, other_id in collisions:
            print(f"  [{patch['id']}] -> {_anchor_str(new_anchor)}  "
                  f"already held by [{other_id}]", file=sys.stderr)

    if not args.write:
        print("\nDRY-RUN: nothing written. Re-run with --write to bake the "
              f"{len(repairs):,} var-relabel re-anchor(s) into the store.")
        return

    if collisions:
        raise RuntimeError(
            f"{len(collisions)} re-anchor collision(s) (see above); refusing to "
            f"write. Resolve the conflicting decisions in the editor first.")

    if not repairs:
        print("\n--write: no var-relabel repairs to make; store left byte-identical.")
        return

    # Build the rewritten patch list: repairs move only their anchor, everything
    # else stays exactly as loaded, in original order. rewrite_anchor fails loud on
    # any inconsistency, so a corrupt plan aborts before we touch the store.
    rewritten = list(patches)
    for i, patch, new_anchor in repairs:
        rewritten[i] = rewrite_anchor(patch, new_anchor, basis_index)

    backup = backup_store(store_path)
    print(f"\nBacked up store -> {backup}")
    patchstore.write_patches(rewritten)
    print(f"Rewrote {len(repairs):,} anchor(s) in {store_path}")
    print("Re-run apply_patches to confirm these decisions now resolve (0 orphans "
          "for the repaired patches).")


if __name__ == "__main__":
    main()
