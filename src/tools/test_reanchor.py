#!/usr/bin/env python3
"""
Unit + end-to-end demonstration of the orig_* provenance convention and the
applicator's auto-re-anchor (see basis.mark_original / reanchor_index /
reanchor_patch and apply_patches.apply_patches).

The natural key is (word, pos, shaw, var). A pipeline transform that rewrites a
record's `var` or `shaw` moves its key and orphans every patch anchored to the old
key. The orig_* convention preserves the pre-image on the transformed record, so
the applicator can auto-re-anchor an orphaned patch to where the record lives now.

These tests never touch the live basis or the live patch store: they build small
synthetic basis dicts in memory, and the end-to-end case redirects the store via
SHAW_SPELL_PATCH_STORE to a scratch file (patchstore/apply_patches both resolve
the store path at call time). Run:

    python3 src/tools/test_reanchor.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import apply_patches
import basis
from basis import anchor_of, mark_original, reanchor_index


def entry(latn, pos, shaw, var, **extra):
    """A canonical basis entry (the Latn/Shaw/... on-disk shape)."""
    e = {"Latn": latn, "pos": pos, "Shaw": shaw, "ipa": extra.pop("ipa", ""),
         "freq": extra.pop("freq", 0), "var": var}
    e.update(extra)
    return e


def accept_patch(word, pos, shaw, var, pid, changes=None):
    """An accept patch anchored to (word, pos, shaw, var)."""
    return {"id": pid, "anchor": {"word": word, "pos": pos, "shaw": shaw, "var": var},
            "op": "accept", "changes": changes or {}, "meta": {}}


def build_index(entries):
    """(index, source) over a list of canonical entries — the two structures
    apply_patches consumes, built the way basis.build_basis would."""
    index = {anchor_of(e): e for e in entries}
    source = {anchor_of(e): e.get("source", ["readlex"]) for e in entries}
    return index, source


class MarkOriginalTest(unittest.TestCase):
    def test_records_pre_image_on_change(self):
        e = entry("colour", "n", "𐑒𐑳𐑤𐑼", "GenAm")
        mark_original(e, "var", "RSSB")
        self.assertEqual(e["orig_var"], "RSSB")

    def test_set_once_first_pre_image_wins(self):
        # Two transforms change var in turn; orig_var must hold the FIRST pre-image
        # (RSSB), the value a patch was anchored against — not the intermediate.
        e = entry("x", "n", "𐑨", "GenAm")
        mark_original(e, "var", "RSSB")   # RSSB -> GenAm
        e["var"] = "RRP"
        mark_original(e, "var", "GenAm")  # GenAm -> RRP (later transform)
        self.assertEqual(e["orig_var"], "RSSB")

    def test_no_op_when_field_unchanged(self):
        # Additive: recording a no-change must not plant an orig_* (which would
        # falsely claim the key moved).
        e = entry("x", "n", "𐑨", "RRP")
        mark_original(e, "var", "RRP")
        self.assertNotIn("orig_var", e)

    def test_rejects_unknown_field(self):
        with self.assertRaises(ValueError):
            mark_original(entry("x", "n", "𐑨", "RRP"), "pos", "v")

    def test_orig_shaw_and_ipa(self):
        e = entry("x", "n", "𐑚", "RRP", ipa="b")
        mark_original(e, "shaw", "𐑚𐑚")
        mark_original(e, "ipa", "bb")
        self.assertEqual(e["orig_shaw"], "𐑚𐑚")
        self.assertEqual(e["orig_ipa"], "bb")


class ReanchorIndexTest(unittest.TestCase):
    def test_maps_old_key_to_current(self):
        # A record relabelled RSSB -> RRP carries orig_var=RSSB; its old key must
        # map to its current key.
        e = entry("shed", "n", "𐑖𐑧𐑛", "RRP", orig_var="RSSB")
        index, _ = build_index([e])
        rmap = reanchor_index(index)
        old_key = ("shed", "n", "𐑖𐑧𐑛", "RSSB")
        self.assertEqual(rmap[old_key], ("shed", "n", "𐑖𐑧𐑛", "RRP"))

    def test_respell_axis(self):
        e = entry("x", "n", "𐑚𐑦", "RRP", orig_shaw="𐑚𐑰")
        index, _ = build_index([e])
        rmap = reanchor_index(index)
        self.assertEqual(rmap[("x", "n", "𐑚𐑰", "RRP")], ("x", "n", "𐑚𐑦", "RRP"))

    def test_untouched_record_absent(self):
        e = entry("x", "n", "𐑚", "RRP")  # no orig_*
        index, _ = build_index([e])
        self.assertEqual(reanchor_index(index), {})

    def test_orig_ipa_alone_is_not_a_key_redirect(self):
        # ipa is not in the anchor key: an orig_ipa-only record moved no key, so it
        # contributes no redirect.
        e = entry("x", "n", "𐑚", "RRP", orig_ipa="old")
        index, _ = build_index([e])
        self.assertEqual(reanchor_index(index), {})

    def test_collision_dropped(self):
        # Two records both claiming the same old key can't resolve to one target;
        # the ambiguous old key is dropped (patch stays orphaned, never mis-applied).
        a = entry("x", "n", "𐑚", "RRP", orig_var="RSSB")
        b = entry("x", "n", "𐑚", "GenAm", orig_var="RSSB")
        index, _ = build_index([a, b])
        self.assertNotIn(("x", "n", "𐑚", "RSSB"), reanchor_index(index))


class AutoReanchorApplyTest(unittest.TestCase):
    """The end-to-end guarantee: a patch anchored to a key a transform moved is
    applied against the record's new key, with 0 orphans where orig_* covers it,
    and a clean soft-fail where it does not."""

    def apply(self, entries, patches):
        index, source = build_index(entries)
        output = {}
        stats, _orphans = apply_patches.apply_patches(output, index, source, patches)
        return stats, output

    def test_auto_reanchor_preserves_verdict(self):
        # Basis: 'shed' relabelled RSSB -> RRP by a transform (orig_var=RSSB).
        # Patch: an accept anchored to the OLD RSSB key. It must auto-re-anchor and
        # emit the record under its CURRENT (RRP) key, 0 orphans.
        e = entry("shed", "n", "𐑖𐑧𐑛", "RRP", orig_var="RSSB", freq=5)
        patch = accept_patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_a")
        (stats, output) = self.apply([e], [patch])

        self.assertEqual(stats["reanchored"], 1)
        self.assertEqual(stats["orphaned"], 0)
        self.assertEqual(stats["update"], 1)
        emitted = [r for v in output.values() for r in v]
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["var"], "RRP")           # current key
        self.assertEqual(emitted[0]["orig_var"], "RSSB")     # provenance survives
        self.assertEqual(emitted[0]["status"], "sanctioned")

    def test_reanchored_edit_lays_over_current_record(self):
        # An accept-with-edits anchored to the old key still lays its edits over the
        # CURRENT record after re-anchoring.
        e = entry("shed", "n", "𐑖𐑧𐑛", "RRP", orig_var="RSSB")
        patch = accept_patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_e",
                             changes={"ipa": "ʃɛd"})
        (stats, output) = self.apply([e], [patch])
        emitted = [r for v in output.values() for r in v][0]
        self.assertEqual(stats["reanchored"], 1)
        self.assertEqual(emitted["var"], "RRP")
        self.assertEqual(emitted["ipa"], "ʃɛd")

    def test_soft_fail_when_no_orig_covers(self):
        # No basis record carries a matching orig_*, so the orphaned anchor cannot
        # re-anchor: it must fall through to the existing soft-fail (retained +
        # surfaced), never crash, and emit nothing.
        e = entry("other", "n", "𐑳", "RRP")
        patch = accept_patch("gone", "n", "𐑜𐑪𐑯", "RSSB", "p_o")
        (stats, output) = self.apply([e], [patch])
        self.assertEqual(stats["reanchored"], 0)
        self.assertEqual(stats["orphaned"], 1)
        self.assertEqual([r for v in output.values() for r in v], [])

    def test_mixed_batch(self):
        # One re-anchorable orphan + one un-re-anchorable orphan + one live accept.
        moved = entry("shed", "n", "𐑖𐑧𐑛", "RRP", orig_var="RSSB")
        live = entry("cat", "n", "𐑒𐑨𐑑", "RRP")
        patches = [
            accept_patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_moved"),   # re-anchors
            accept_patch("cat", "n", "𐑒𐑨𐑑", "RRP", "p_live"),      # resolves live
            accept_patch("ghost", "n", "𐑜𐑴𐑕𐑑", "GenAm", "p_dead"), # soft-fails
        ]
        (stats, output) = self.apply([moved, live], patches)
        self.assertEqual(stats["reanchored"], 1)
        self.assertEqual(stats["orphaned"], 1)
        self.assertEqual(stats["update"], 2)  # moved + live both emitted

    def test_backward_compatible_no_orig(self):
        # A basis with NO orig_* anywhere behaves exactly as before: a live anchor
        # applies, a drifted one soft-fails. reanchor_index is empty and inert.
        e = entry("cat", "n", "𐑒𐑨𐑑", "RRP")
        (stats, _o) = self.apply([e], [accept_patch("cat", "n", "𐑒𐑨𐑑", "RRP", "p")])
        self.assertEqual(stats["reanchored"], 0)
        self.assertEqual(stats["update"], 1)


class EndToEndTempStoreTest(unittest.TestCase):
    """Drive the WHOLE applicator (build patches on disk -> load -> apply) through a
    TEMP patch store, proving the real store is never touched and a transform's
    orig_* auto-re-anchors a decision the transform would otherwise orphan.

    A throwaway transform stands in for a real pipeline stage: it relabels a
    record's var and records orig_var via mark_original — exactly what a live stage
    (collapse_identical_dialects, a future RRP classifier) would do."""

    def throwaway_relabel_transform(self, entries, from_var, to_var):
        """Stand-in transform: relabel `from_var` -> `to_var`, preserving the
        pre-image on each changed record. Models a key-moving pipeline stage."""
        for e in entries:
            if e.get("var") == from_var:
                e["var"] = to_var
                mark_original(e, "var", from_var)  # record the pre-image post-change
        return entries

    def test_end_to_end_through_temp_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "patches.jsonl"

            # A decision made against the PRE-transform record (RSSB).
            covered = accept_patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_covered")
            # A decision against a record no transform touched and that no longer
            # exists — must soft-fail, not re-anchor.
            dangling = accept_patch("vanished", "n", "𐑝", "GenAm", "p_dangling")
            store.write_text(
                "\n".join(json.dumps(p) for p in (covered, dangling)) + "\n",
                encoding="utf-8")

            # The transform runs AFTER the decisions, moving shed RSSB -> RRP.
            basis_entries = [entry("shed", "n", "𐑖𐑧𐑛", "RSSB", freq=5)]
            self.throwaway_relabel_transform(basis_entries, "RSSB", "RRP")
            self.assertEqual(basis_entries[0]["orig_var"], "RSSB")

            index, source = build_index(basis_entries)

            # Load patches from the TEMP store via the real resolver, proving the
            # live store path is bypassed.
            os.environ["SHAW_SPELL_PATCH_STORE"] = str(store)
            try:
                loaded = apply_patches.load_patches()
            finally:
                del os.environ["SHAW_SPELL_PATCH_STORE"]
            self.assertEqual(len(loaded), 2)

            output = {}
            stats, orphans = apply_patches.apply_patches(
                output, index, source, loaded)

            # The covered decision auto-re-anchored onto the RRP record; the
            # dangling one soft-failed and is retained for surfacing.
            self.assertEqual(stats["reanchored"], 1)
            self.assertEqual(stats["orphaned"], 1)
            self.assertEqual(len(orphans), 1)
            self.assertEqual(orphans[0]["id"], "p_dangling")
            emitted = [r for v in output.values() for r in v]
            self.assertEqual(len(emitted), 1)
            self.assertEqual(emitted[0]["var"], "RRP")

            # The live store on disk is unchanged (we only ever wrote the temp one).
            self.assertTrue(
                (basis.PROJECT_ROOT / "data" / "patches" / "patches.jsonl").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
