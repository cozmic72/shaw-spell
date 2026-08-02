#!/usr/bin/env python3
"""
Persist the applicator's auto-re-anchor into the patch store — the ON-DEMAND,
BAKED counterpart to the in-memory re-anchoring apply_patches does every build.

WHY THIS EXISTS
---------------
The natural key of a patch is (word, pos, shaw, var, lemma). When a pipeline transform
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

COLLISIONS — DEDUP THE DUPLICATES, SKIP THE CONFLICTS
-----------------------------------------------------
Re-anchoring can land a patch on a key another patch already holds (two repaired
patches converging, a repaired patch meeting an un-repaired one, or a duplicate
pair that already shared a key in the store). The store is one-patch-per-anchor,
so each such key must resolve to ONE survivor. A collision is classified by the
DECISION its occupants carry — op + changes + final word/pos (id and meta are NOT
identity):

  DUPLICATE  every occupant is the SAME decision (e.g. the same word accepted
             twice, once per source, pre-dating the source merger). Nothing is
             lost by keeping one, so the tool DEDUPS: keep a single survivor
             (richest meta, then first-seen), drop the redundant others, and
             re-anchor the survivor. SAFE.
  CONFLICT   occupants carry DIFFERING decisions (differing op or changes). Not
             auto-resolvable, so the whole group is SKIPPED — left byte-identical
             for the owner to adjudicate in the editor.

The fail-safe default is CONFLICT: anything not a proven single-decision duplicate
is skipped, never deduped, so a distinct decision is never dropped.

SAFETY (this rewrites the owner's editorial decisions — sacred)
---------------------------------------------------------------
  - DRY-RUN by default. It reports what it WOULD change and writes nothing.
    Rewriting requires the explicit --write flag.
  - --write BACKS UP the store first (timestamped sibling copy) and prints the
    backup path, then writes atomically (temp + rename, via patchstore).
  - FAIL-LOUD: an internal inconsistency (a re-anchor target that does not
    resolve, a shaw actually changing under a var re-anchor, or a same-decision
    duplicate surviving planning) aborts rather than shipping a corrupted store.
    No DISTINCT decision is ever dropped — only proven duplicates are deduped.
  - It moves anchors of safe var-relabel orphans and drops proven-duplicate
    patches; op / changes / id / meta of every surviving patch and every
    untouched patch are left byte-for-byte as loaded, in original order.
  - Point it at a TEMP COPY via SHAW_SPELL_PATCH_STORE for development/testing.
    It must NEVER be run --write against the live store without the owner's
    explicit go — it is a tool left ready for the owner, not auto-run.

Usage:
    python3 src/tools/repair_patches.py            # dry-run report (default)
    python3 src/tools/repair_patches.py --write     # back up + rewrite in place

    SHAW_SPELL_PATCH_STORE=/tmp/copy.jsonl \\
        python3 src/tools/repair_patches.py [--write]   # against a temp copy
"""

import json
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
    _, _, old_shaw, _, _ = old_key
    _, _, current_shaw, _, _ = current_key
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


def _decision_of(patch, final_anchor):
    """The identifying DECISION a patch carries, once landed on its final anchor:
    (word_lower, pos, op, canonical(changes)). This is what makes two patches "the
    same decision" for dedup — the natural-key axes that survive the re-anchor plus
    the intrinsic edit. `id` (often a stale content hash) and `meta` (author / note /
    origin) are deliberately EXCLUDED: they do not change what the patch decides.

    word/pos are taken from the FINAL anchor (a repaired patch keeps its word/pos; a
    var-relabel never touches them), so a repaired and an un-repaired patch landing on
    one key are compared on equal footing."""
    return (
        final_anchor["word"].lower(),
        final_anchor["pos"],
        patch.get("op"),
        json.dumps(patch.get("changes"), ensure_ascii=False, sort_keys=True),
    )


def _meta_richness(patch):
    """A deterministic richness score for a patch's meta, used only to pick which of
    two SAME-DECISION duplicates to keep. Prefer the one that carries a human note
    (the informative annotation we must not lose), then the one with more meta
    fields. Purely a tie-preference; never distinguishes decisions."""
    meta = patch.get("meta") or {}
    has_note = 1 if meta.get("note") else 0
    return (has_note, len(meta))


def find_collisions(patches, repairs):
    """Every FINAL natural key that more than one patch would occupy once `repairs`
    are applied, classified as a DUPLICATE (all occupants carry the same decision) or
    a TRUE CONFLICT (occupants carry differing decisions). A re-anchor that lands two
    patches on one key breaks the store's one-patch-per-anchor identity (patchstore
    upserts by anchor), so every such key must resolve to exactly one survivor.

    Returns (duplicates, conflicts) where each is a list of collision groups:

      duplicates [{key, survivor_index, drop_indexes, occupants}]
          all occupants are the SAME decision (op + changes + final word/pos). Safe
          to DEDUP: keep `survivor_index`, drop `drop_indexes`; the survivor still
          re-anchors normally. Covers BOTH the re-anchor-created duplicate (two
          repaired patches, or a repaired + an un-repaired patch, landing on one key)
          AND a pre-existing duplicate already sharing a key in the loaded store.
      conflicts [{key, occupants}]
          occupants carry DIFFERING decisions — not auto-resolvable (which verdict
          wins?), so left untouched for editorial review.

    Each occupant is (index, patch, final_anchor) where final_anchor is the anchor
    the patch holds AFTER repairs (a repaired patch's new anchor; else its own).

    Survivor rule (deterministic): among same-decision duplicates keep the one with
    the richest meta (a human note, then most meta fields), breaking ties by FIRST
    position in the store (lowest index). Stable and independent of the unreliable
    `id`."""
    repaired_anchor_by_index = {i: new_anchor for i, _p, new_anchor in repairs}

    final_key_occupants = {}
    for i, patch in enumerate(patches):
        anchor = repaired_anchor_by_index.get(i, patch["anchor"])
        if anchor is None:  # authorship — no natural key, never collides
            continue
        final_key_occupants.setdefault(anchor_key(anchor), []).append(
            (i, patch, anchor))

    duplicates, conflicts = [], []
    for key, occupants in final_key_occupants.items():
        if len(occupants) < 2:
            continue

        decisions = {_decision_of(p, a) for _i, p, a in occupants}
        if len(decisions) != 1:
            # Differing decisions on one key — a genuine conflict. FAIL-SAFE default:
            # anything not a proven single-decision duplicate is treated as a conflict
            # (skipped), never deduped, so a distinct decision is never dropped.
            conflicts.append({"key": key, "occupants": occupants})
            continue

        # Same decision throughout: dedup. Keep the richest-meta occupant, lowest
        # index breaking ties; drop the rest.
        survivor = max(occupants, key=lambda o: (_meta_richness(o[1]), -o[0]))
        survivor_index = survivor[0]
        drop_indexes = [i for i, _p, _a in occupants if i != survivor_index]
        duplicates.append({
            "key": key,
            "survivor_index": survivor_index,
            "drop_indexes": drop_indexes,
            "occupants": occupants,
        })

    return duplicates, conflicts


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

    # Classify every key two-or-more patches would share after the repairs into
    # DUPLICATE (same decision → dedup, keep one) and TRUE CONFLICT (differing
    # decisions → skip for editorial review). See find_collisions.
    duplicates, conflicts = find_collisions(patches, repairs)
    report_collisions(duplicates, conflicts)

    rewritten, dropped_indexes, skipped_repair_ids = plan_write(
        patches, repairs, duplicates, conflicts, basis_index)

    n_reanchored = sum(
        1 for i, _p, _a in repairs
        if _p["id"] not in skipped_repair_ids and i not in dropped_indexes)
    n_dropped = len(dropped_indexes)
    n_conflict_skips = len(conflicts)

    print("\nWRITE PLAN (what --write would do):")
    print(f"  re-anchor (clean + duplicate survivors): {n_reanchored:,}")
    print(f"  duplicate patches dropped (deduped):     {n_dropped:,}")
    print(f"  true-conflict keys skipped (untouched):  {n_conflict_skips:,}")
    print(f"  resulting store size:                    {len(rewritten):,} "
          f"(was {len(patches):,})")

    if not args.write:
        print("\nDRY-RUN: nothing written. Re-run with --write to bake the "
              "re-anchors and dedup the duplicate collisions.")
        return

    if rewritten == patches:
        print("\n--write: no changes to make; store left byte-identical.")
        return

    backup = backup_store(store_path)
    print(f"\nBacked up store -> {backup}")
    patchstore.write_patches(rewritten)
    print(f"Wrote {len(rewritten):,} patch(es) to {store_path} "
          f"({n_reanchored:,} re-anchored, {n_dropped:,} deduped).")
    print("Re-run apply_patches to confirm these decisions now resolve.")


def report_collisions(duplicates, conflicts):
    """Report the two collision classes distinctly: duplicate keys (deduped) and
    true-conflict keys (skipped, listed for editorial review)."""
    n_dup_dropped = sum(len(g["drop_indexes"]) for g in duplicates)
    print(f"\n  duplicate-collision keys:{len(duplicates):,}  "
          f"({n_dup_dropped:,} redundant patch(es) would be deduped, survivor re-anchored)")
    print(f"  true-conflict keys:      {len(conflicts):,}  "
          f"(differing decisions — SKIPPED, left for editorial review)")

    if conflicts:
        print("\nTRUE CONFLICTS (differing decisions on one key — left untouched):",
              file=sys.stderr)
        for group in conflicts:
            word, pos, shaw, var, lemma = group["key"]
            print(f"  key: word={word!r} pos={pos} shaw={shaw} var={var}"
                  + (f" lemma={lemma}" if lemma else ""),
                  file=sys.stderr)
            for _i, patch, _a in group["occupants"]:
                print(f"    [{patch['id']}] op={patch.get('op')} "
                      f"changes={json.dumps(patch.get('changes'), ensure_ascii=False)}",
                      file=sys.stderr)


def plan_write(patches, repairs, duplicates, conflicts, basis_index):
    """Assemble the rewritten patch list for --write, without mutating `patches`.

      - Every clean var-relabel repair moves ONLY its anchor (rewrite_anchor).
      - Each DUPLICATE-collision group keeps its single survivor (re-anchored if the
        survivor is itself a repair) and DROPS the redundant others.
      - Each TRUE-CONFLICT group's repairs are SKIPPED (that patch left as loaded);
        the whole group stays for editorial review.
      - Everything else stays byte-identical, in original order.

    Guarantees exactly one patch per final natural key (asserted). Returns
    (rewritten, dropped_indexes, skipped_repair_ids)."""
    # Indexes to DROP: the redundant members of every duplicate group.
    dropped_indexes = set()
    for group in duplicates:
        dropped_indexes.update(group["drop_indexes"])

    # Repair ids to SKIP re-anchoring: any repair whose patch sits on a conflict key
    # (leave it exactly as loaded, orphaned, for the owner to adjudicate).
    conflict_indexes = {i for g in conflicts for i, _p, _a in g["occupants"]}
    skipped_repair_ids = {
        p["id"] for i, p, _a in repairs if i in conflict_indexes}

    # New anchor for each repair index that survives (not dropped, not conflict-skipped).
    repair_anchor_by_index = {
        i: a for i, p, a in repairs
        if i not in dropped_indexes and p["id"] not in skipped_repair_ids
        and i not in conflict_indexes}

    rewritten = []
    for i, patch in enumerate(patches):
        if i in dropped_indexes:
            continue  # redundant duplicate — dropped
        if i in repair_anchor_by_index:
            rewritten.append(rewrite_anchor(patch, repair_anchor_by_index[i], basis_index))
        else:
            rewritten.append(patch)

    _assert_one_patch_per_anchor(rewritten)
    return rewritten, dropped_indexes, skipped_repair_ids


def _assert_one_patch_per_anchor(patches):
    """Fail loud if the planned store would hold two patches on one natural key —
    the invariant the whole dedup exists to preserve. Conflict keys are the sole
    permitted exception (deliberately left for review); every other key must be
    unique. Authorship patches (anchor null) are keyed by id, not anchor, so they do
    not participate."""
    seen = {}
    for patch in patches:
        anchor = patch["anchor"]
        if anchor is None:
            continue
        key = anchor_key(anchor)
        seen.setdefault(key, []).append(patch)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    # A surviving multi-occupant key is only acceptable if it is a genuine conflict
    # (its patches carry differing decisions); a duplicate slipping through is a bug.
    for key, group in dupes.items():
        decisions = {_decision_of(p, p["anchor"]) for p in group}
        if len(decisions) == 1:
            raise RuntimeError(
                f"dedup invariant violated: {len(group)} identical patches remain on "
                f"{key} after planning — {[p['id'] for p in group]}")


if __name__ == "__main__":
    main()
