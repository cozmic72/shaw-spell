#!/usr/bin/env python3
"""
Lemma carrying through the RRP reclassifier's respell path.

A PASS_RESPELL moves a record's (word, pos, shaw) identity — the slot lemmas
resolve by. Two obligations follow (see reclassify_rrp):

  - a SELF-referenced lemma moves with its record (reclassify_record);
  - a record filed UNDER the respelled identity is re-pointed at the new one,
    unless a sibling record still carries the old identity
    (repoint_dependent_lemmas).

Pure in-memory tests. Run:

    python3 src/tools/test_reclassify_lemmas.py
"""

import unittest
from collections import Counter, defaultdict

from basis import LEMMA_FIELD
from reclassify_rrp import reclassify_record, repoint_dependent_lemmas
from rrp_classifier import Judgment


def entry(latn, pos, shaw, var, lemma=None, **extra):
    e = {"Latn": latn, "pos": pos, "Shaw": shaw, "var": var}
    e[LEMMA_FIELD] = lemma or {"Latn": latn, "pos": pos, "Shaw": shaw}
    e.update(extra)
    return e


def respell(record, new_shaw):
    """reclassify_record applying a PASS_RESPELL to `record`."""
    judgment = Judgment(outcome="PASS_RESPELL", tier="C", respell=new_shaw)
    return reclassify_record(record, judgment, lane_blocked=False, held=None,
                             tallies=Counter(), samples=defaultdict(list))


class SelfLemmaFollowsRespell(unittest.TestCase):

    def test_self_referenced_lemma_moves_with_the_record(self):
        out = respell(entry("colour", "NN1", "𐑒𐑳𐑤𐑼", "RSSB"), "𐑒𐑳𐑤𐑻")
        self.assertEqual(out["Shaw"], "𐑒𐑳𐑤𐑻")
        self.assertEqual(out[LEMMA_FIELD],
                         {"Latn": "colour", "pos": "NN1", "Shaw": "𐑒𐑳𐑤𐑻"})

    def test_foreign_lemma_is_left_alone(self):
        lemma = {"Latn": "color", "pos": "NN1", "Shaw": "𐑒𐑳𐑤𐑼"}
        out = respell(entry("colours", "NN2", "𐑒𐑳𐑤𐑼𐑟", "RSSB", lemma=lemma),
                      "𐑒𐑳𐑤𐑻𐑟")
        self.assertEqual(out[LEMMA_FIELD], lemma)


class RepointDependents(unittest.TestCase):

    def repoint(self, records):
        reclassified = {"all": records}
        tallies = Counter()
        repoint_dependent_lemmas(reclassified, tallies)
        return tallies

    def test_dependent_of_a_respelled_lemma_is_repointed(self):
        target = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "RSSB"), "𐑮𐑳𐑯𐑻")
        dependent = entry("runs", "VVZ", "𐑮𐑳𐑯𐑟", "RRP",
                          lemma={"Latn": "run", "pos": "VVB", "Shaw": "𐑮𐑳𐑯𐑼"})
        tallies = self.repoint([target, dependent])
        self.assertEqual(dependent[LEMMA_FIELD],
                         {"Latn": "run", "pos": "VVB", "Shaw": "𐑮𐑳𐑯𐑻"})
        self.assertEqual(tallies["lemma-repointed"], 1)

    def test_surviving_sibling_keeps_the_dependent_resolving(self):
        target = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "RSSB"), "𐑮𐑳𐑯𐑻")
        sibling = entry("run", "VVB", "𐑮𐑳𐑯𐑼", "GenAm")
        old_lemma = {"Latn": "run", "pos": "VVB", "Shaw": "𐑮𐑳𐑯𐑼"}
        dependent = entry("runs", "VVZ", "𐑮𐑳𐑯𐑟", "RRP", lemma=dict(old_lemma))
        tallies = self.repoint([target, sibling, dependent])
        self.assertEqual(dependent[LEMMA_FIELD], old_lemma)
        self.assertEqual(tallies["lemma-repointed"], 0)

    def test_ambiguous_respell_fails_loud(self):
        a = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "RSSB"), "𐑮𐑳𐑯𐑻")
        b = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "GenAm"), "𐑮𐑳𐑯𐑩")
        dependent = entry("runs", "VVZ", "𐑮𐑳𐑯𐑟", "RRP",
                          lemma={"Latn": "run", "pos": "VVB", "Shaw": "𐑮𐑳𐑯𐑼"})
        with self.assertRaises(SystemExit):
            self.repoint([a, b, dependent])

    def test_ambiguous_respell_without_dependents_is_harmless(self):
        a = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "RSSB"), "𐑮𐑳𐑯𐑻")
        b = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "GenAm"), "𐑮𐑳𐑯𐑩")
        self.assertEqual(self.repoint([a, b])["lemma-repointed"], 0)

    def test_converging_respells_are_unambiguous(self):
        a = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "RSSB"), "𐑮𐑳𐑯𐑻")
        b = respell(entry("run", "VVB", "𐑮𐑳𐑯𐑼", "GenAm"), "𐑮𐑳𐑯𐑻")
        dependent = entry("runs", "VVZ", "𐑮𐑳𐑯𐑟", "RRP",
                          lemma={"Latn": "run", "pos": "VVB", "Shaw": "𐑮𐑳𐑯𐑼"})
        tallies = self.repoint([a, b, dependent])
        self.assertEqual(dependent[LEMMA_FIELD]["Shaw"], "𐑮𐑳𐑯𐑻")
        self.assertEqual(tallies["lemma-repointed"], 1)

    def test_baseline_orphan_is_left_alone(self):
        # A lemma dangling for reasons OTHER than a respell (upstream's own
        # quirks) is not this pass's to touch — the chain-end guard's baseline
        # comparison owns it.
        orphan_lemma = {"Latn": "gone", "pos": "VVB", "Shaw": "𐑜𐑪𐑯"}
        dependent = entry("runs", "VVZ", "𐑮𐑳𐑯𐑟", "RRP",
                          lemma=dict(orphan_lemma))
        tallies = self.repoint([dependent])
        self.assertEqual(dependent[LEMMA_FIELD], orphan_lemma)
        self.assertEqual(tallies["lemma-repointed"], 0)

    def test_lemma_latn_casing_matches_via_slot(self):
        target = respell(entry("boston", "NP0", "𐑚𐑪𐑕𐑑𐑩𐑯", "RSSB"), "𐑚𐑪𐑕𐑑𐑭𐑯")
        dependent = entry("bostons", "NP0", "𐑚𐑪𐑕𐑑𐑩𐑯𐑟", "RRP",
                          lemma={"Latn": "Boston", "pos": "NP0",
                                 "Shaw": "𐑚𐑪𐑕𐑑𐑩𐑯"})
        tallies = self.repoint([target, dependent])
        self.assertEqual(dependent[LEMMA_FIELD],
                         {"Latn": "boston", "pos": "NP0", "Shaw": "𐑚𐑪𐑕𐑑𐑭𐑯"})
        self.assertEqual(tallies["lemma-repointed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
