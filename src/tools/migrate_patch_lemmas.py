#!/usr/bin/env python3
"""
Stamp every anchored patch's anchor with the lemma of the record it reviews —
the one-off store migration for the lemma-in-the-anchor identity change.

WHY THIS EXISTS
---------------
The natural key gained a lemma slot (basis.anchor_of / anchor_key): two records
can share (word, pos, shaw, var) yet belong to different lemmas (`axes` VVZ
under both `ax` and `axe` upstream), so identity now carries the stated lemma.
Every patch in data/patches/patches.jsonl predates that and anchors by the bare
4-part key; once the basis carries lemmas, a lemma-less anchor no longer
resolves and the whole store orphans. This tool rewrites each anchor to carry
the structured lemma sub-object its record will have.

WHAT GETS STAMPED
-----------------
For each anchored patch, the (word_lower, pos, shaw, var) it holds resolves to:

  upstream   the 4-key matches upstream ReadLex entries stating exactly ONE
             distinct lemma (their bucket key) — stamp that lemma.
  basis      no raw-upstream match, but the 4-key is in the basis pool — stamp
             the basis record's OWN stated lemma (falling back to the
             self-reference on a not-yet-regenerated pool). The stored lemma,
             not a computed self-reference: a var-relabelled upstream
             inflection resolves here, and its stated lemma is not itself.
  ambiguous  the 4-key resolves to MORE THAN ONE distinct lemma. Which one the
             owner reviewed is unrecoverable: NEVER guessed. Reported; --write
             REFUSES while any exist.
  unresolved neither upstream nor the basis holds the 4-key — the patch was
             already orphaned before this migration. Left byte-identical
             (surfaced via the editor's `orphaned` filter as before).

A patch whose anchor ALREADY carries a lemma is verified against the same
resolution: matching → untouched; differing → a CONFLICT, left byte-identical
for the owner to adjudicate — and --write refuses while any exist.

ORDERING (why this is run together with the artifact rebuild)
-------------------------------------------------------------
The committed basis artifact and this store must move together: a regenerated
basis carries lemmas, so un-migrated patches orphan against it; migrated
patches orphan against an un-regenerated basis. Regenerate the pool
(build_supplement) and run this --write in the same sitting, then apply_patches
to confirm every decision resolves.

SAFETY (this rewrites the owner's editorial decisions — sacred)
---------------------------------------------------------------
  - DRY-RUN by default; rewriting requires the explicit --write flag.
  - --write BACKS UP the store first (timestamped sibling copy, via
    repair_patches.backup_store) and writes atomically (patchstore).
  - Only the anchor gains a `lemma` sub-object; op / changes / id / meta of
    every patch are left byte-for-byte as loaded, in original order.
  - Point it at a TEMP COPY via SHAW_SPELL_PATCH_STORE for development. It must
    NEVER be run --write against the live store without the owner's explicit go.

Usage:
    python3 src/tools/migrate_patch_lemmas.py             # dry-run report
    python3 src/tools/migrate_patch_lemmas.py --write     # back up + rewrite
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "editor"))

from basis import (                                              # noqa: E402
    LEMMA_FIELD,
    anchor_key,
    anchor_of,
    build_basis_index,
    lemma_slot,
    load_upstream,
    self_lemma,
)
from repair_patches import backup_store                          # noqa: E402
import patchstore                                                # noqa: E402

KIND_UPSTREAM = "upstream"
KIND_BASIS = "basis"
KIND_AMBIGUOUS = "ambiguous"
KIND_UNRESOLVED = "unresolved"


def upstream_lemma_map():
    """(word_lower, pos, shaw, var) -> the DISTINCT lemma dicts upstream ReadLex
    states for entries with that wordform (distinct by lemma_slot; the 36 dual-
    filed inflections yield two)."""
    lemmas_by_wordform = {}
    for entries in load_upstream().values():
        for entry in entries:
            known = lemmas_by_wordform.setdefault(anchor_of(entry)[:4], {})
            lemma = entry[LEMMA_FIELD]
            known.setdefault(lemma_slot(lemma), lemma)
    return {wordform: list(known.values())
            for wordform, known in lemmas_by_wordform.items()}


def basis_wordform_map(basis_index):
    """(word_lower, pos, shaw, var) -> the basis entries carrying it (the basis
    key's first four slots; today's un-regenerated artifact has one per)."""
    by_wordform = {}
    for key, entry in basis_index.items():
        by_wordform.setdefault(key[:4], []).append(entry)
    return by_wordform


def _basis_lemma(entry):
    """The lemma a basis record states for itself — its stored LEMMA_FIELD, or
    the self-reference on a pre-lemma artifact (a regenerated pool always
    stores one; combine self-references anything arriving without)."""
    return entry.get(LEMMA_FIELD) or self_lemma(entry)


def resolve_lemma(wordform, upstream_map, basis_map):
    """(kind, lemma) for one anchored wordform — see the module doc's four
    resolution classes. `lemma` is the dict to stamp for upstream/basis, the
    candidate list for ambiguous, None for unresolved."""
    upstream = upstream_map.get(wordform)
    if upstream is not None:
        if len(upstream) == 1:
            return (KIND_UPSTREAM, upstream[0])
        return (KIND_AMBIGUOUS, upstream)
    basis_entries = basis_map.get(wordform)
    if basis_entries is None:
        return (KIND_UNRESOLVED, None)
    if len(basis_entries) > 1:
        return (KIND_AMBIGUOUS, [_basis_lemma(e) for e in basis_entries])
    return (KIND_BASIS, _basis_lemma(basis_entries[0]))


def plan_migration(patches, upstream_map, basis_map):
    """Partition the store into the write plan, without mutating `patches`.

    Returns (stamps, ambiguous, unresolved, conflicts, counts) where
      stamps     [(index, patch, kind, lemma)]  anchors to rewrite
      ambiguous  [(index, patch, lemmas)]       NEVER written; blocks --write
      unresolved [(index, patch)]               pre-existing orphans, untouched
      conflicts  [(index, patch, lemma)]        stored lemma differs, untouched
      counts     {manual, already} untouched-and-fine tallies
    """
    stamps, ambiguous, unresolved, conflicts = [], [], [], []
    counts = {"manual": 0, "already": 0}

    for i, patch in enumerate(patches):
        anchor = patch["anchor"]
        if anchor is None:
            counts["manual"] += 1
            continue

        wordform = anchor_key(anchor)[:4]
        kind, lemma = resolve_lemma(wordform, upstream_map, basis_map)
        stored = anchor.get("lemma")

        if stored is not None:
            if kind in (KIND_UPSTREAM, KIND_BASIS) \
                    and lemma_slot(stored) != lemma_slot(lemma):
                conflicts.append((i, patch, lemma))
            else:
                counts["already"] += 1
        elif kind == KIND_AMBIGUOUS:
            ambiguous.append((i, patch, lemma))
        elif kind == KIND_UNRESOLVED:
            unresolved.append((i, patch))
        else:
            stamps.append((i, patch, kind, lemma))

    return stamps, ambiguous, unresolved, conflicts, counts


def stamped_patch(patch, lemma):
    """A copy of `patch` whose anchor gains the `lemma` sub-object — op /
    changes / id / meta and the anchor's own fields byte-identical."""
    return {**patch, "anchor": {**patch["anchor"], "lemma": lemma}}


def _anchor_str(anchor):
    return (f"word={anchor['word']!r} pos={anchor['pos']} "
            f"shaw={anchor['shaw']} var={anchor['var']}")


def _lemma_str(lemma):
    return f"{lemma['Latn']!r} {lemma['pos']} {lemma['Shaw']}"


def report(store_path, total, stamps, ambiguous, unresolved, conflicts, counts):
    n_upstream = sum(1 for _i, _p, kind, _l in stamps if kind == KIND_UPSTREAM)
    n_basis = sum(1 for _i, _p, kind, _l in stamps if kind == KIND_BASIS)
    print(f"Patch store: {store_path}")
    print(f"  patches:              {total:,}")
    print(f"  manual (no anchor):    {counts['manual']:,}")
    print(f"  already stamped:      {counts['already']:,}")
    print(f"  to stamp — upstream:  {n_upstream:,}  (bucket lemma, unique)")
    print(f"  to stamp — basis:     {n_basis:,}  (the basis record's stated lemma)")
    print(f"  ambiguous:            {len(ambiguous):,}  (multiple lemmas — NEVER guessed; blocks --write)")
    print(f"  unresolved:           {len(unresolved):,}  (already orphaned — untouched)")
    print(f"  lemma conflicts:      {len(conflicts):,}  (stored lemma differs — untouched)")

    if ambiguous:
        print("\nAMBIGUOUS (which lemma the owner reviewed is unrecoverable):",
              file=sys.stderr)
        for _i, patch, lemmas in ambiguous:
            options = "; ".join(_lemma_str(lemma) for lemma in lemmas)
            print(f"  [{patch['id']}] {_anchor_str(patch['anchor'])}"
                  f" — candidates: {options}", file=sys.stderr)

    if conflicts:
        print("\nLEMMA CONFLICTS (stored vs resolved — left untouched):",
              file=sys.stderr)
        for _i, patch, lemma in conflicts:
            print(f"  [{patch['id']}] {_anchor_str(patch['anchor'])}"
                  f" stored={_lemma_str(patch['anchor']['lemma'])}"
                  f" resolved={_lemma_str(lemma)}", file=sys.stderr)

    if unresolved:
        print("\nUNRESOLVED (pre-existing orphans — left untouched):")
        for _i, patch in unresolved:
            print(f"  [{patch['id']}] {_anchor_str(patch['anchor'])}")

    upstream_stamps = [s for s in stamps if s[2] == KIND_UPSTREAM]
    if upstream_stamps:
        print("\nUPSTREAM-LEMMA STAMPS (the non-self rewrites --write would make):")
        for _i, patch, _kind, lemma in upstream_stamps:
            print(f"  [{patch['id']}] {_anchor_str(patch['anchor'])}"
                  f" -> lemma {_lemma_str(lemma)}")


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Stamp anchored patches with their record's lemma (the "
                    "lemma-in-the-anchor migration). DRY-RUN by default; "
                    "--write to rewrite in place.")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the stamped anchors in place (backs up first). "
                         "Without this, only report what would change.")
    args = ap.parse_args()

    store_path = patchstore._store_path()
    patches = patchstore.load_patches()
    upstream_map = upstream_lemma_map()
    basis_map = basis_wordform_map(build_basis_index())

    stamps, ambiguous, unresolved, conflicts, counts = plan_migration(
        patches, upstream_map, basis_map)
    report(store_path, len(patches), stamps, ambiguous, unresolved, conflicts,
           counts)

    if not args.write:
        print("\nDRY-RUN: nothing written. Re-run with --write to stamp the "
              "anchors (regenerate the basis pool in the same sitting).")
        return

    if ambiguous or conflicts:
        raise SystemExit(
            f"\n--write REFUSED: {len(ambiguous)} ambiguous and {len(conflicts)} "
            f"conflicted patch(es) — a lemma is never guessed and a stored one "
            f"never overwritten. Resolve them (see the listing above) and re-run.")
    if not stamps:
        print("\n--write: no changes to make; store left byte-identical.")
        return

    rewritten = list(patches)
    for i, patch, _kind, lemma in stamps:
        rewritten[i] = stamped_patch(patch, lemma)

    backup = backup_store(store_path)
    print(f"\nBacked up store -> {backup}")
    patchstore.write_patches(rewritten)
    print(f"Wrote {len(rewritten):,} patch(es) to {store_path} "
          f"({len(stamps):,} stamped).")
    print("Re-run apply_patches to confirm these decisions now resolve.")


if __name__ == "__main__":
    main()
