#!/usr/bin/env python3
"""Characterization tests for the patch store (patchstore.py) — the upsert-by-anchor
no-duplicate guarantee and the write→read round-trip.

Everything runs against a THROWAWAY store file, pointed at via
SHAW_SPELL_PATCH_STORE (the same tmp-redirect idiom test_patch_meta_filters.py and
test_commit_submodule.py use), so the live data/patches/patches.jsonl is never
touched. Fixtures are hand-built patch dicts — no basis, no build.

Covers:
  - the anchor-key derivation (word LOWERCASED; pos/shaw/var verbatim) — the
    identity two patches share for upsert
  - insert (first patch on an anchor) → ("appended", None), store grows by one
  - upsert-same-anchor REPLACES, not appends: a re-decision on the same anchor
    yields ("replaced", old) and leaves the store at ONE patch for that anchor
  - a DIFFERENT anchor appends a second patch (does not collide)
  - upsert keys on the FULL anchor incl. var — same word/pos/shaw under a
    different var are distinct records, both retained
  - manual patches (anchor null) upsert by id, not anchor
  - the store round-trips: write a set, read it back, get the same patches
  - patch_id is content-derived and stable (same anchor/op/changes → same id)

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import patchstore
from basis import anchor_key

SHAW_A = "\U00010450"
SHAW_B = "\U00010451"


def anchor(word, pos, shaw, var):
    return {"word": word, "pos": pos, "shaw": shaw, "var": var}


def accept(word, pos, shaw, var, changes=None, author="joro"):
    return patchstore.make_patch(anchor(word, pos, shaw, var), "accept",
                                 changes or {},
                                 {"author": author, "origin": "editor"})


def manual(record, author="joro"):
    return patchstore.make_patch(None, None, record,
                                 {"author": author, "origin": "editor"})


class _store:
    """A fresh temp store pointed at by SHAW_SPELL_PATCH_STORE for the block, so
    every patchstore read/write resolves to it — never the live store."""

    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        self._path = Path(self._dir.name) / "patches.jsonl"
        patchstore.write_patches([], path=self._path)
        self._prev = os.environ.get("SHAW_SPELL_PATCH_STORE")
        os.environ["SHAW_SPELL_PATCH_STORE"] = str(self._path)
        return self._path

    def __exit__(self, *_exc):
        if self._prev is None:
            os.environ.pop("SHAW_SPELL_PATCH_STORE", None)
        else:
            os.environ["SHAW_SPELL_PATCH_STORE"] = self._prev
        self._dir.cleanup()
        return False


# ---- anchor-key derivation ----

def test_anchor_key_lowercases_word_keeps_rest_verbatim():
    key = anchor_key(anchor("Cat", "NN", SHAW_A, "RRP"))
    assert key == ("cat", "NN", SHAW_A, "RRP", ()), key


def test_anchor_key_var_is_part_of_identity():
    rrp = anchor_key(anchor("cat", "NN", SHAW_A, "RRP"))
    genam = anchor_key(anchor("cat", "NN", SHAW_A, "GenAm"))
    assert rrp != genam


# ---- insert vs upsert-replace (the no-duplicate guarantee) ----

def test_first_patch_on_anchor_appends():
    with _store():
        outcome, previous = patchstore.upsert_patch(accept("cat", "NN", SHAW_A, "RRP"))
        assert outcome == "appended", outcome
        assert previous is None
        assert len(patchstore.load_patches()) == 1


def test_upsert_same_anchor_replaces_not_appends():
    with _store():
        first = accept("cat", "NN", SHAW_A, "RRP", changes={})
        patchstore.upsert_patch(first)
        # A re-decision on the SAME anchor with different changes.
        second = accept("cat", "NN", SHAW_A, "RRP", changes={"ipa": "kæt"})
        outcome, previous = patchstore.upsert_patch(second)

        assert outcome == "replaced", outcome
        assert previous["id"] == first["id"]
        stored = patchstore.load_patches()
        # The store holds ONE patch for the anchor — the replacement, not a second row.
        assert len(stored) == 1, stored
        assert stored[0]["id"] == second["id"]
        assert stored[0]["changes"] == {"ipa": "kæt"}


def test_upsert_replaces_across_different_op():
    # An accept then a drop on the same anchor: the drop REPLACES the accept (a
    # re-decision), never coexists with it.
    with _store():
        patchstore.upsert_patch(accept("cat", "NN", SHAW_A, "RRP"))
        drop = patchstore.make_patch(anchor("cat", "NN", SHAW_A, "RRP"), "drop", {},
                                     {"author": "joro", "origin": "editor"})
        outcome, _previous = patchstore.upsert_patch(drop)
        assert outcome == "replaced", outcome
        stored = patchstore.load_patches()
        assert len(stored) == 1 and stored[0]["op"] == "drop", stored


def test_different_anchor_appends_second_patch():
    with _store():
        patchstore.upsert_patch(accept("cat", "NN", SHAW_A, "RRP"))
        outcome, _previous = patchstore.upsert_patch(accept("dog", "NN", SHAW_B, "RRP"))
        assert outcome == "appended", outcome
        assert len(patchstore.load_patches()) == 2


def test_same_word_pos_shaw_different_var_are_distinct():
    # var is part of the anchor identity: two records identical but for var are
    # distinct facts, and BOTH must be retained (no false collision).
    with _store():
        patchstore.upsert_patch(accept("cat", "NN", SHAW_A, "RRP"))
        outcome, _previous = patchstore.upsert_patch(accept("cat", "NN", SHAW_A, "GenAm"))
        assert outcome == "appended", outcome
        assert len(patchstore.load_patches()) == 2


def test_word_case_folds_to_same_anchor():
    # The anchor lowercases the word, so "Cat" and "cat" upsert to the SAME record.
    with _store():
        patchstore.upsert_patch(accept("Cat", "NN", SHAW_A, "RRP"))
        outcome, _previous = patchstore.upsert_patch(accept("cat", "NN", SHAW_A, "RRP"))
        assert outcome == "replaced", outcome
        assert len(patchstore.load_patches()) == 1


# ---- manual patches upsert by id ----

def test_manual_patch_upserts_by_id_not_anchor():
    with _store():
        record = {"word": "newword", "shaw": SHAW_B, "pos": "NN", "var": "RRP"}
        patch = manual(record)
        outcome, _previous = patchstore.upsert_patch(patch)
        assert outcome == "appended", outcome
        # Re-upserting the identical manual patch (same id) replaces in place.
        outcome2, previous2 = patchstore.upsert_patch(patch)
        assert outcome2 == "replaced", outcome2
        assert previous2["id"] == patch["id"]
        assert len(patchstore.load_patches()) == 1


# ---- round-trip fidelity ----

def test_write_read_round_trips_faithfully():
    with _store():
        patches = [
            accept("cat", "NN", SHAW_A, "RRP", changes={"ipa": "kæt"}),
            accept("dog", "NN", SHAW_B, "GenAm"),
            manual({"word": "newword", "shaw": SHAW_B, "pos": "NN", "var": "RRP"}),
        ]
        patchstore.write_patches(patches)
        reread = patchstore.load_patches()
        assert reread == patches, reread


# ---- content-derived id stability ----

def test_patch_id_is_stable_for_same_content():
    a = patchstore.patch_id(anchor("cat", "NN", SHAW_A, "RRP"), "accept", {})
    b = patchstore.patch_id(anchor("cat", "NN", SHAW_A, "RRP"), "accept", {})
    assert a == b == patchstore.make_patch(
        anchor("cat", "NN", SHAW_A, "RRP"), "accept", {}, {})["id"]


def test_patch_id_differs_on_different_changes():
    a = patchstore.patch_id(anchor("cat", "NN", SHAW_A, "RRP"), "accept", {})
    b = patchstore.patch_id(anchor("cat", "NN", SHAW_A, "RRP"), "accept",
                            {"ipa": "kæt"})
    assert a != b


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
