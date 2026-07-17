#!/usr/bin/env python3
"""
The patch store: read and write data/patches/patches.jsonl, the only persisted
editorial artifact (see docs/editorial-overlay-design.md).

A patch is {anchor, record, meta}; its shape and id derivation match
src/tools/migrate_csv_to_patches.py exactly — one representation of the patch
format, not a parallel copy:

  id      deterministic, content-derived (p_ + sha256 of {anchor, record})
  anchor  natural key {word, pos, shaw, var} | null (null = authorship)
  record  the complete record {word, pos, shaw, var, ipa, freq, status, …}
          | null (drop)
  meta    {author, origin, ts, note?}

A patch's identity for upsert is its full anchor (word, pos, shaw, var) — the
immutable identity of the reviewed record. Writing a patch whose anchor already
has one REPLACES it, so a re-decision never duplicates. Authorship patches
(anchor null) have no anchor and are keyed by id.
"""

import hashlib
import json
from pathlib import Path

from basis import PROJECT_ROOT, anchor_key

PATCHES_PATH = PROJECT_ROOT / "data" / "patches" / "patches.jsonl"


def load_patches(path=PATCHES_PATH):
    patches = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def patch_id(anchor, record):
    """Content-derived id — identical derivation to migrate_csv_to_patches so a
    salvaged patch and a re-decided one collide rather than duplicate."""
    payload = json.dumps({"anchor": anchor, "record": record},
                         ensure_ascii=False, sort_keys=True)
    return "p_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_patch(anchor, record, meta):
    return {"id": patch_id(anchor, record), "anchor": anchor, "record": record, "meta": meta}


def write_patches(patches, path=PATCHES_PATH):
    """Persist the store atomically: write a sibling temp file, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for patch in patches:
            f.write(json.dumps(patch, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_patch(patch, path=PATCHES_PATH):
    """Append the patch, or replace the existing patch on the same anchor.

    An anchored patch (anchor present) replaces any patch with the same natural
    key (word, pos, shaw, var). An authorship patch (anchor null) replaces one
    with the same id. Returns ("replaced", old_patch) or ("appended", None).
    """
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


def delete_patch(anchor, path=PATCHES_PATH):
    """Remove the patch on the given anchor, reverting the record to its untouched
    source (undo / unflag). Fails loud if no patch holds that anchor — the caller
    asked to delete something that is not there. Returns the removed patch."""
    patches = load_patches(path)
    at = _index_of_anchor(patches, anchor_key(anchor))
    if at is None:
        raise KeyError(f"no patch on anchor: {anchor}")
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
