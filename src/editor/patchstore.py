#!/usr/bin/env python3
"""
The patch store: read and write data/patches/patches.jsonl, the only persisted
editorial artifact (see docs/editorial-overlay-design.md).

A patch is {anchor, op, changes, meta} — a minimal diff over the live basis:

  id       deterministic, content-derived (p_ + sha256 of {anchor, op, changes})
  anchor   natural key {word, pos, shaw, var, lemma?} | null (null = a MANUAL record)
  op       "accept" (sanction the anchored basis record) / "drop" (remove it) /
           "flag" (production no-op). Absent for a manual patch (anchor null).
  changes  the intrinsic edits {word, shaw, pos, ipa, var, mergers, variant} an
           accept lays over the basis record (empty = accept as-is); or, for
           a manual patch, the whole self-contained record.
  meta     {author, origin, ts, note?}

A patch's identity for upsert is its full anchor (word, pos, shaw, var, lemma) —
the immutable identity of the reviewed record. Writing a patch whose anchor already
has one REPLACES it, so a re-decision never duplicates. Manual patches
(anchor null) have no anchor and are keyed by id.

Redirecting the store (tests): every read/write resolves its path at CALL time
from _store_path(), so the live store is never touched by an isolated test.
Reassign the module attribute PATCHES_PATH, or set the SHAW_SPELL_PATCH_STORE
env var, to redirect all reads and writes; passing path= to any function still
overrides per call.
"""

import hashlib
import json
import os
from pathlib import Path

from basis import DATA_ROOT, anchor_key

PATCHES_PATH = DATA_ROOT / "patches" / "patches.jsonl"


def _store_path():
    """The store path resolved at call time — the SHAW_SPELL_PATCH_STORE env var
    if set, else the current PATCHES_PATH module attribute. Read at call time (not
    bound as a def default) so reassigning PATCHES_PATH or the env var actually
    redirects every read and write. Callers pass path= to override a single call."""
    env = os.environ.get("SHAW_SPELL_PATCH_STORE")
    return Path(env) if env else PATCHES_PATH


def load_patches(path=None):
    if path is None:
        path = _store_path()
    patches = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def patch_id(anchor, op, changes):
    """Content-derived id over the patch's identity fields (anchor, op, changes),
    so a re-decision that resolves to the same diff collides rather than
    duplicates. meta (author/ts/note) is excluded — it is not part of identity."""
    payload = json.dumps({"anchor": anchor, "op": op, "changes": changes},
                         ensure_ascii=False, sort_keys=True)
    return "p_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_patch(anchor, op, changes, meta):
    return {"id": patch_id(anchor, op, changes), "anchor": anchor,
            "op": op, "changes": changes, "meta": meta}


def write_patches(patches, path=None):
    """Persist the store atomically: write a sibling temp file, then rename."""
    if path is None:
        path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for patch in patches:
            f.write(json.dumps(patch, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_patch(patch, path=None):
    """Append the patch, or replace the existing patch on the same anchor.

    An anchored patch (anchor present) replaces any patch with the same natural
    key (word, pos, shaw, var, lemma). A manual patch (anchor null) replaces
    one with the same id. Returns ("replaced", old_patch) or ("appended", None).
    """
    if path is None:
        path = _store_path()
    patches = load_patches(path)
    anchor = patch["anchor"]

    if anchor is None:
        replaced_at = _index_of_id(patches, patch["id"])
    else:
        replaced_at = _index_of_anchor(patches, anchor_key(anchor))

    if replaced_at is None:
        patches.append(patch)
        write_patches(patches, path)
        return ("appended", None)

    previous = patches[replaced_at]
    patches[replaced_at] = patch
    write_patches(patches, path)
    return ("replaced", previous)


def replace_manual_patch(patch, prior_id, path=None):
    """Re-decide an existing manual entry: drop the patch with `prior_id` and
    write `patch` (anchor null) in its place, at the same position so the entry
    keeps its order. A re-decision changes the record (new status / flag / edited
    fields), so `patch` carries a NEW content-derived id — the prior patch cannot be
    found by the new id, which is why the caller names it explicitly.

    Fails loud if no manual patch carries `prior_id` (the re-decision named a
    prior patch that is not there) or if `patch` still carries an anchor (a
    manual re-decision must keep anchor null). Returns the replaced patch."""
    if patch["anchor"] is not None:
        raise ValueError(f"manual re-decision must have anchor null: {patch['anchor']}")
    if path is None:
        path = _store_path()
    patches = load_patches(path)
    at = _index_of_id(patches, prior_id)
    if at is None:
        raise KeyError(f"no manual patch with id: {prior_id}")
    if patches[at]["anchor"] is not None:
        raise ValueError(f"patch {prior_id} is not a manual patch: {patches[at]['anchor']}")
    previous = patches[at]
    patches[at] = patch
    write_patches(patches, path)
    return previous


def delete_patch(anchor, path=None):
    """Remove the patch on the given anchor, reverting the record to its untouched
    source (undo / unflag). Fails loud if no patch holds that anchor — the caller
    asked to delete something that is not there. Returns the removed patch."""
    if path is None:
        path = _store_path()
    patches = load_patches(path)
    at = _index_of_anchor(patches, anchor_key(anchor))
    if at is None:
        raise KeyError(f"no patch on anchor: {anchor}")
    return _pop_and_write(patches, at, path)


def delete_patch_by_id(patch_id, path=None):
    """Remove the patch with the given id — the deletion path for manual
    patches, whose stored anchor is null and so cannot be found by anchor. Fails
    loud if no patch carries that id. Returns the removed patch."""
    if path is None:
        path = _store_path()
    patches = load_patches(path)
    at = _index_of_id(patches, patch_id)
    if at is None:
        raise KeyError(f"no patch with id: {patch_id}")
    return _pop_and_write(patches, at, path)


def _pop_and_write(patches, at, path):
    removed = patches.pop(at)
    write_patches(patches, path)
    return removed


def _index_of_anchor(patches, target):
    for i, patch in enumerate(patches):
        anchor = patch["anchor"]
        if anchor is not None and anchor_key(anchor) == target:
            return i
    return None


def _index_of_id(patches, target_id):
    for i, patch in enumerate(patches):
        if patch["id"] == target_id:
            return i
    return None
