#!/usr/bin/env python3
"""
The DEFINITION patch store: read and write data/patches/definition-patches.jsonl,
the persisted ledger of Shavian-transliteration corrections over the read-only
Shavian definitions corpus (definitions.py).

This is a SEPARATE ledger from the word patch store (patchstore.py /
data/patches/patches.jsonl) — a definition correction has a different natural key
and lifecycle, so mixing it into the sacred word-decisions file would muddy that
file's commit/attribution. Same MECHANISM (minimal-diff patch, upsert-by-anchor,
total-order apply, soft-fail-on-orphan), separate FILE. The word store is NEVER
touched by this module.

A definition patch is {id, anchor, changes, meta} — a minimal diff over the live
definitions corpus (docs/definitions-editor-design.md §5c):

  id       deterministic, content-derived (dp_ + sha256 of {anchor, changes}), so
           a re-decision that resolves to the same correction collides rather than
           duplicates.
  anchor   the per-sense natural key {word, synset, dialect} of the ONE corpus
           sense it corrects — word LOWERCASED, synset the WordNet offset, dialect
           "gb" | "us". Immutable identity; never changed when the sense is
           re-corrected.
  changes  the edited field(s). v1 corrects the Shavian transliteration only:
           {"shaw": "…"}. The English gloss + synset are stable identity, never
           edited. (No drop/remove op — removing poor generated glosses is a
           future data-cleanup, not a UI feature. Owner decision, 2026-07-19.)
  meta     {author, origin, ts, note?}

All definitions are CANONICAL BY DEFAULT (owner, 2026-07-19): a correction is an
EDIT, not an accept/sanction — there is no accept/flag/drop lifecycle here, only
the correction and its removal (unpatch). The owner's edit wins silently over the
machine transliteration when the corpus is overlaid for the viewer.

gb/us (design §6 Q1, lean (c)): a correction targets ONE dialect's transliteration
(the anchor carries the dialect). When gb == us the viewer shows a single line and
the daemon writes ONE patch per dialect the caller names — the caller decides
whether an edit covers both dialects or one (the daemon does not silently fan a
gb edit onto us). See editord.handle_definition_patch for the applied policy.

SOFT-FAIL on an orphaned correction: an anchor whose (word, synset, dialect) no
longer resolves against the corpus (the corpus drifted — a sense was removed or
re-keyed since the correction was made) is LOGGED and RETAINED, never a hard
failure. Mirrors the word applicator's discipline (apply_patches.py docstring).
overlay_corpus() collects such orphans and returns them for surfacing rather than
dropping them silently.

Redirecting the store (tests/agents): every read/write resolves its path at CALL
time from _store_path() — the SHAW_SPELL_DEFINITION_PATCH_STORE env var if set,
else DEFINITION_PATCHES_PATH — so an isolated test never touches the live store
(mirrors patchstore._store_path). Passing path= overrides a single call.
"""

import hashlib
import json
import os
from pathlib import Path

from basis import DATA_ROOT

DEFINITION_PATCHES_PATH = DATA_ROOT / "patches" / "definition-patches.jsonl"

# The anchor fields, in a fixed order — the per-sense natural key. word is stored
# LOWERCASED (the corpus headword case varies; the index lowercases too), synset is
# the WordNet offset, dialect is "gb" | "us".
ANCHOR_FIELDS = ("word", "synset", "dialect")
DIALECTS = ("gb", "us")

# The only field a v1 correction may edit: the Shavian transliteration of the
# sense's gloss. The gloss and synset are stable identity, never edited.
CHANGE_FIELDS = ("shaw",)


def _store_path():
    """The store path resolved at call time — the SHAW_SPELL_DEFINITION_PATCH_STORE
    env var if set, else DEFINITION_PATCHES_PATH. Resolved at call time (not bound
    as a def default) so setting the env var actually redirects every read/write.
    Callers pass path= to override a single call."""
    env = os.environ.get("SHAW_SPELL_DEFINITION_PATCH_STORE")
    return Path(env) if env else DEFINITION_PATCHES_PATH


def anchor_key(anchor):
    """The hashable, order-fixed identity tuple of a def-patch anchor — the total
    order key and the upsert identity. Fails loud on a missing field rather than
    keying on None."""
    missing = [f for f in ANCHOR_FIELDS if not anchor.get(f)]
    if missing:
        raise ValueError(f"definition anchor missing {', '.join(missing)}: {anchor!r}")
    return tuple(anchor[f] for f in ANCHOR_FIELDS)


def patch_id(anchor, changes):
    """Content-derived id over the patch's identity (anchor + changes), so a
    re-correction resolving to the same diff collides rather than duplicates. meta
    (author/ts/note) is excluded — not part of identity."""
    payload = json.dumps({"anchor": anchor, "changes": changes},
                         ensure_ascii=False, sort_keys=True)
    return "dp_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_patch(anchor, changes, meta):
    return {"id": patch_id(anchor, changes), "anchor": anchor,
            "changes": changes, "meta": meta}


def load_patches(path=None):
    """Read the store. A MISSING store is an empty store (no corrections yet) — a
    benign first-run condition, not a fallback around a precondition: the ledger is
    created on the first write. A malformed line fails loud."""
    if path is None:
        path = _store_path()
    if not Path(path).exists():
        return []
    patches = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def write_patches(patches, path=None):
    """Persist the store atomically: write a sibling temp file, then rename."""
    if path is None:
        path = _store_path()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for patch in patches:
            f.write(json.dumps(patch, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_patch(patch, path=None):
    """Append the patch, or replace the existing patch on the same anchor (a
    re-correction of the same sense never duplicates). Returns ("replaced",
    old_patch) or ("appended", None)."""
    if path is None:
        path = _store_path()
    patches = load_patches(path)
    at = _index_of_anchor(patches, anchor_key(patch["anchor"]))
    if at is None:
        patches.append(patch)
        write_patches(patches, path)
        return ("appended", None)
    previous = patches[at]
    patches[at] = patch
    write_patches(patches, path)
    return ("replaced", previous)


def delete_patch(anchor, path=None):
    """Remove the correction on the given anchor, reverting the sense to its
    machine transliteration (undo). Fails loud if no patch holds that anchor — the
    caller asked to delete something that is not there. Returns the removed patch."""
    if path is None:
        path = _store_path()
    patches = load_patches(path)
    at = _index_of_anchor(patches, anchor_key(anchor))
    if at is None:
        raise KeyError(f"no definition patch on anchor: {anchor}")
    removed = patches.pop(at)
    write_patches(patches, path)
    return removed


def _index_of_anchor(patches, target):
    for i, patch in enumerate(patches):
        if anchor_key(patch["anchor"]) == target:
            return i
    return None


def patch_order_key(patch):
    """Total, deterministic apply order over anchor identity then id, so identical
    inputs overlay identically."""
    return (*anchor_key(patch["anchor"]), patch["id"])


def overlay_corpus(index, patches):
    """Overlay the corrections onto the definitions index IN PLACE, so the viewer
    shows the corrected Shavian (the owner's edit wins silently over the machine
    transliteration). Returns the list of ORPHANED patches — those whose anchor no
    longer resolves against a corpus sense — for surfacing. Orphans are never
    applied and never dropped: the applied set changes the corpus, the orphan set
    is reported, and the store itself is left untouched (this never rewrites it).

    `index` is a DefinitionsIndex (definitions.py); it exposes correct(anchor,
    changes) which applies one correction to the matching sense and returns True,
    or False when the anchor resolves to nothing (an orphan). Corrections are
    applied in total order so the overlay is deterministic.
    """
    orphans = []
    for patch in sorted(patches, key=patch_order_key):
        if not index.correct(patch["anchor"], patch["changes"]):
            orphans.append(patch)
    return orphans
