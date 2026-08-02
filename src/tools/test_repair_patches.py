#!/usr/bin/env python3
"""
Unit tests for repair_patches' planning: orphan classification (both re-anchor
resorts), collision dedup vs conflict-skip, and idempotency of the write plan.
All in-memory over synthetic basis dicts; the live store is never touched. Run:

    python3 src/tools/test_repair_patches.py
"""

import unittest

import repair_patches
from apply_patches import weak_reanchor_index
from basis import anchor_of, reanchor_index


def entry(latn, pos, shaw, var, **extra):
    e = {"Latn": latn, "pos": pos, "Shaw": shaw, "ipa": "", "freq": 0, "var": var}
    e.update(extra)
    return e


def patch(word, pos, shaw, var, pid, op="accept", changes=None, meta=None):
    return {"id": pid, "anchor": {"word": word, "pos": pos, "shaw": shaw, "var": var},
            "op": op, "changes": changes or {}, "meta": meta or {}}


def build_index(entries):
    return {anchor_of(e): e for e in entries}


def plan(entries, patches):
    """plan_repairs + find_collisions + plan_write over a synthetic basis."""
    index = build_index(entries)
    repairs, shaw_changed, ambiguous, gone, untouched = repair_patches.plan_repairs(
        patches, index)
    duplicates, conflicts = repair_patches.find_collisions(patches, repairs)
    rewritten, dropped, skipped = repair_patches.plan_write(
        patches, repairs, duplicates, conflicts, index)
    return {"repairs": repairs, "shaw_changed": shaw_changed,
            "ambiguous": ambiguous, "gone": gone, "untouched": untouched,
            "duplicates": duplicates, "conflicts": conflicts,
            "rewritten": rewritten, "dropped": dropped, "skipped": skipped}


class ClassifyOrphanTest(unittest.TestCase):
    def classify(self, entries, p):
        index = build_index(entries)
        return repair_patches.classify_orphan(
            p, reanchor_index(index), weak_reanchor_index(index))

    def test_orig_breadcrumb_first_resort(self):
        e = entry("shed", "n", "𐑖𐑧𐑛", "RRP", orig_var="RSSB")
        kind, new_anchor = self.classify([e], patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p"))
        self.assertEqual(kind, "var-relabel")
        self.assertEqual(new_anchor["var"], "RRP")

    def test_weak_second_resort_no_breadcrumb(self):
        # No orig_* anywhere (e.g. the RRP promotion narrowed between runs), but
        # exactly one live record carries the spelling: var-only drift, recover.
        e = entry("shed", "n", "𐑖𐑧𐑛", "RSSB")
        kind, new_anchor = self.classify([e], patch("shed", "n", "𐑖𐑧𐑛", "RRP", "p"))
        self.assertEqual(kind, "var-relabel")
        self.assertEqual(new_anchor["var"], "RSSB")
        self.assertEqual(new_anchor["shaw"], "𐑖𐑧𐑛")

    def test_shaw_changed_refused_even_with_breadcrumb(self):
        e = entry("x", "n", "𐑚𐑦", "RRP", orig_shaw="𐑚𐑰")
        kind, new_anchor = self.classify([e], patch("x", "n", "𐑚𐑰", "RRP", "p"))
        self.assertEqual((kind, new_anchor), ("shaw-changed", None))

    def test_ambiguous_multiple_vars(self):
        a = entry("i", "n", "𐑲", "RRP")
        b = entry("i", "n", "𐑲", "GenAm")
        kind, new_anchor = self.classify([a, b], patch("i", "n", "𐑲", "RSSB", "p"))
        self.assertEqual((kind, new_anchor), ("ambiguous", None))

    def test_gone_spelling_absent(self):
        e = entry("other", "n", "𐑳", "RRP")
        kind, new_anchor = self.classify([e], patch("gone", "n", "𐑜", "RRP", "p"))
        self.assertEqual((kind, new_anchor), ("gone", None))


class PlanWriteTest(unittest.TestCase):
    def test_clean_move_reanchored_only_anchor_changes(self):
        e = entry("shed", "n", "𐑖𐑧𐑛", "RSSB")
        p = patch("shed", "n", "𐑖𐑧𐑛", "RRP", "p1", changes={"ipa": "ʃɛd"},
                  meta={"note": "checked"})
        result = plan([e], [p])
        self.assertEqual(len(result["repairs"]), 1)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["duplicates"], [])
        [moved] = result["rewritten"]
        self.assertEqual(moved["anchor"]["var"], "RSSB")
        for field in ("id", "op", "changes", "meta"):
            self.assertEqual(moved[field], p[field])

    def test_same_decision_collision_dedups_to_one_survivor(self):
        e = entry("shed", "n", "𐑖𐑧𐑛", "RSSB")
        orphan = patch("shed", "n", "𐑖𐑧𐑛", "RRP", "p_orphan")
        survivor = patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_live",
                         meta={"note": "keep me"})
        result = plan([e], [orphan, survivor])
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(len(result["rewritten"]), 1)
        self.assertEqual(result["rewritten"][0]["id"], "p_live")

    def test_differing_op_collision_skipped_untouched(self):
        e = entry("shed", "n", "𐑖𐑧𐑛", "RSSB")
        orphan = patch("shed", "n", "𐑖𐑧𐑛", "RRP", "p_orphan", op="drop")
        live = patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_live", op="accept")
        result = plan([e], [orphan, live])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(result["rewritten"], [orphan, live])

    def test_ambiguous_and_gone_left_untouched(self):
        a = entry("i", "n", "𐑲", "RRP")
        b = entry("i", "n", "𐑲", "GenAm")
        patches = [patch("i", "n", "𐑲", "RSSB", "p_amb"),
                   patch("void", "n", "𐑝", "RRP", "p_gone")]
        result = plan([a, b], patches)
        self.assertEqual(len(result["ambiguous"]), 1)
        self.assertEqual(len(result["gone"]), 1)
        self.assertEqual(result["repairs"], [])
        self.assertEqual(result["rewritten"], patches)

    def test_write_plan_is_idempotent(self):
        entries = [entry("shed", "n", "𐑖𐑧𐑛", "RSSB"),
                   entry("i", "n", "𐑲", "RRP"),
                   entry("i", "n", "𐑲", "GenAm")]
        patches = [
            patch("shed", "n", "𐑖𐑧𐑛", "RRP", "p_move"),
            patch("shed", "n", "𐑖𐑧𐑛", "RSSB", "p_dup"),
            patch("i", "n", "𐑲", "RSSB", "p_amb"),
            patch("void", "n", "𐑝", "RRP", "p_gone"),
        ]
        first = plan(entries, patches)
        self.assertEqual(len(first["rewritten"]), 3)  # p_move/p_dup deduped to one

        second = plan(entries, first["rewritten"])
        self.assertEqual(second["repairs"], [])
        self.assertEqual(second["duplicates"], [])
        self.assertEqual(second["rewritten"], first["rewritten"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
