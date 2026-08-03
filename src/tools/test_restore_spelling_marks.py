#!/usr/bin/env python3
"""
Latin spelling-mark restoration (restore_spelling_marks).

Pins the alignment rules — substitution on equal separator counts, unique
attested decomposition otherwise, hold on anything else — plus the stage-level
obligations: upstream pass-through, orig_shaw provenance, self-lemma moves,
dependent re-pointing, collision holds, re-bucketing.

Pure in-memory tests. Run:

    python3 src/tools/test_restore_spelling_marks.py
"""

import unittest
from collections import Counter, defaultdict

from basis import LEMMA_FIELD
from combine_supplements import output_bucket_key
from restore_spelling_marks import (
    ALREADY_CORRECT, HELD_AMBIGUOUS, HELD_COLLISION, HELD_EXTRA_SEPS,
    HELD_OVERSIZE, HELD_PARTIAL_CHUNK, HELD_SPACE_MISMATCH, HELD_UNPLACED,
    MAX_CHUNK_LETTERS, MAX_CHUNK_MARKS, RESTORED_ALIGNED,
    RESTORED_SUBSTITUTED, build_spelling_index, restore_marks,
    restore_supplement)

INDEX = {
    "e": {"𐑰"},
    "mail": {"𐑥𐑱𐑤"},
    "mails": {"𐑥𐑱𐑤𐑟"},
    "enter": {"𐑧𐑯𐑑𐑼"},
    "should": {"𐑖𐑫𐑛"},
    "jones": {"𐑡𐑴𐑯𐑟"},
    "a": {"𐑨"},
    "b": {"𐑚"},
    "ha": {"𐑨", "𐑨𐑨"},
}


def restore(latn, shaw):
    return restore_marks(latn, shaw, INDEX)


class RestoreMarks(unittest.TestCase):

    def test_markless_latin_is_out_of_scope(self):
        self.assertEqual(restore("plain", "𐑐𐑤𐑱𐑯"), (None, None))
        self.assertEqual(restore("two words", "𐑑𐑵 𐑢𐑻𐑛𐑟"), (None, None))

    def test_already_correct_is_recognised(self):
        self.assertEqual(restore("e-mail", "𐑰-𐑥𐑱𐑤"), (ALREADY_CORRECT, None))

    def test_hyphens_substitute_for_spaces(self):
        self.assertEqual(restore("1-2-3", "𐑢𐑳𐑯 𐑑𐑵 𐑔𐑮𐑰"),
                         (RESTORED_SUBSTITUTED, "𐑢𐑳𐑯-𐑑𐑵-𐑔𐑮𐑰"))

    def test_mixed_separators_substitute_in_order(self):
        self.assertEqual(restore("a-b c", "𐑨 𐑚 𐑒"),
                         (RESTORED_SUBSTITUTED, "𐑨-𐑚 𐑒"))

    def test_curly_apostrophe_is_normalised(self):
        self.assertEqual(restore("don't", "𐑛𐑴𐑯’𐑑"),
                         (RESTORED_SUBSTITUTED, "𐑛𐑴𐑯'𐑑"))

    def test_leading_mark_is_positional(self):
        self.assertEqual(restore("'bout", "𐑚𐑬𐑑"), (RESTORED_ALIGNED, "'𐑚𐑬𐑑"))

    def test_trailing_mark_is_positional(self):
        self.assertEqual(restore("runnin'", "𐑮𐑳𐑯𐑦𐑯"),
                         (RESTORED_ALIGNED, "𐑮𐑳𐑯𐑦𐑯'"))

    def test_fully_attested_decomposition(self):
        self.assertEqual(restore("e-mail", "𐑰𐑥𐑱𐑤"),
                         (RESTORED_ALIGNED, "𐑰-𐑥𐑱𐑤"))

    def test_one_unattested_remainder_is_anchored_by_the_attested_side(self):
        self.assertEqual(restore("re-enter", "𐑮𐑰𐑧𐑯𐑑𐑼"),
                         (RESTORED_ALIGNED, "𐑮𐑰-𐑧𐑯𐑑𐑼"))

    def test_contraction_tail_is_attested_phonetically(self):
        self.assertEqual(restore("should've", "𐑖𐑫𐑛𐑝"),
                         (RESTORED_ALIGNED, "𐑖𐑫𐑛'𐑝"))

    def test_fully_attested_split_outranks_one_free_splits(self):
        # suffix 𐑟 (head free) and suffix 𐑦𐑟 (head attested) both qualify;
        # the attested head decides.
        self.assertEqual(restore("Jones's", "𐑡𐑴𐑯𐑟𐑦𐑟"),
                         (RESTORED_ALIGNED, "𐑡𐑴𐑯𐑟'𐑦𐑟"))

    def test_tail_shapes_never_anchor_an_unattested_remainder(self):
        # unattested head + matching 𐑟/𐑦𐑟 tail renderings: no qualifying split
        self.assertEqual(restore("Better's", "𐑚𐑧𐑑𐑦𐑟"), (HELD_UNPLACED, None))

    def test_two_qualifying_splits_hold(self):
        # both lexicon spellings of the head match a prefix
        self.assertEqual(restore("ha-foo", "𐑨𐑨𐑨𐑒"), (HELD_AMBIGUOUS, None))

    def test_nothing_attested_holds(self):
        self.assertEqual(restore("1-800", "𐑢𐑳𐑯𐑱𐑑"), (HELD_UNPLACED, None))

    def test_a_mark_whose_sound_is_missing_holds(self):
        # possessive 's with no sibilant in the Shavian: no suffix matches
        self.assertEqual(restore("Jones's", "𐑡𐑴𐑯𐑟"), (HELD_UNPLACED, None))

    def test_more_shavian_separators_hold(self):
        self.assertEqual(restore("CD-RW", "𐑕𐑰 𐑛𐑰 𐑸 𐑛𐑳𐑚𐑩𐑤𐑘𐑫"),
                         (HELD_EXTRA_SEPS, None))

    def test_space_count_mismatch_holds(self):
        self.assertEqual(restore("Cetti's warbler", "𐑗𐑧𐑑𐑦𐑟"),
                         (HELD_SPACE_MISMATCH, None))

    def test_chunks_mix_passthrough_substitution_and_decomposition(self):
        # chunk 1 markless pass-through, chunk 2 per-chunk substitution
        # (its hyphen survived as an apostrophe), chunk 3 decomposed
        self.assertEqual(restore("cd a-b e-mail", "𐑒𐑛 𐑨'𐑚 𐑰𐑥𐑱𐑤"),
                         (RESTORED_ALIGNED, "𐑒𐑛 𐑨-𐑚 𐑰-𐑥𐑱𐑤"))

    def test_chunk_with_some_but_not_all_marks_holds(self):
        self.assertEqual(restore("cd a-b-mail", "𐑒𐑛 𐑨-𐑚𐑥𐑱𐑤"),
                         (HELD_PARTIAL_CHUNK, None))

    def test_oversize_chunk_holds(self):
        marks = "-".join("a" * (MAX_CHUNK_MARKS + 2))
        self.assertEqual(restore(marks, "𐑨" * (MAX_CHUNK_MARKS + 2)),
                         (HELD_OVERSIZE, None))
        letters = "𐑨" * (MAX_CHUNK_LETTERS + 1)
        self.assertEqual(restore("a-foo", letters), (HELD_OVERSIZE, None))

    def test_tail_only_edge_contraction(self):
        self.assertEqual(restore("'em", "𐑩𐑥"), (RESTORED_ALIGNED, "'𐑩𐑥"))

    def test_naming_dot_stays_chunk_initial(self):
        self.assertEqual(restore("'bout", "·𐑚𐑬𐑑"), (RESTORED_ALIGNED, "·'𐑚𐑬𐑑"))

    def test_restoration_is_idempotent(self):
        for latn, shaw in (("1-2-3", "𐑢𐑳𐑯 𐑑𐑵 𐑔𐑮𐑰"), ("e-mail", "𐑰𐑥𐑱𐑤"),
                           ("'bout", "𐑚𐑬𐑑")):
            _, restored = restore(latn, shaw)
            self.assertEqual(restore(latn, restored), (ALREADY_CORRECT, None))


class SpellingIndex(unittest.TestCase):

    def test_dots_stripped_and_separator_carrying_spellings_skipped(self):
        upstream = {"k": [
            {"Latn": "Aaron", "pos": "NP0", "Shaw": "·𐑺𐑩𐑯"},
            {"Latn": "e-mail", "pos": "NN1", "Shaw": "𐑰-𐑥𐑱𐑤"},
        ]}
        index = build_spelling_index(upstream)
        self.assertEqual(index["aaron"], {"𐑺𐑩𐑯"})
        self.assertNotIn("e-mail", index)


def record(latn, pos, shaw, var="RRP", lemma=None, **extra):
    entry = {"Latn": latn, "pos": pos, "Shaw": shaw, "var": var}
    entry[LEMMA_FIELD] = lemma or {"Latn": latn, "pos": pos, "Shaw": shaw}
    entry.update(extra)
    return entry


def run_stage(records):
    supplement = {output_bucket_key(r): [r] for r in records}
    upstream = {"k": [{"Latn": latn, "Shaw": shaw}
                     for latn, spellings in INDEX.items()
                     for shaw in spellings]}
    tallies, samples = Counter(), defaultdict(list)
    restored = restore_supplement(supplement, tallies, samples,
                                  upstream=upstream)
    return restored, tallies


class RestoreSupplement(unittest.TestCase):

    def test_restores_reprovenances_and_rebuckets(self):
        target = record("e-mail", "NN1", "𐑰𐑥𐑱𐑤")
        restored, tallies = run_stage([target])
        self.assertEqual(target["Shaw"], "𐑰-𐑥𐑱𐑤")
        self.assertEqual(target["orig_shaw"], "𐑰𐑥𐑱𐑤")
        self.assertEqual(target[LEMMA_FIELD]["Shaw"], "𐑰-𐑥𐑱𐑤")
        self.assertEqual(list(restored), ["e-mail_NN1_𐑰-𐑥𐑱𐑤"])
        self.assertEqual(tallies[RESTORED_ALIGNED], 1)

    def test_upstream_records_pass_through_verbatim(self):
        core = record("e-mail", "NN1", "𐑰𐑥𐑱𐑤", source=["readlex"])
        _, tallies = run_stage([core])
        self.assertEqual(core["Shaw"], "𐑰𐑥𐑱𐑤")
        self.assertEqual(sum(tallies.values()), 0)

    def test_occupied_identity_holds_the_restoration(self):
        core = record("e-mail", "NN1", "𐑰-𐑥𐑱𐑤", source=["readlex"])
        own = record("e-mail", "NN1", "𐑰𐑥𐑱𐑤")
        _, tallies = run_stage([core, own])
        self.assertEqual(own["Shaw"], "𐑰𐑥𐑱𐑤")
        self.assertNotIn("orig_shaw", own)
        self.assertEqual(tallies[HELD_COLLISION], 1)

    def test_converging_restorations_both_hold(self):
        one = record("a-b", "NN1", "𐑨𐑚")
        two = record("a-b", "NN1", "𐑨 𐑚")
        _, tallies = run_stage([one, two])
        self.assertEqual((one["Shaw"], two["Shaw"]), ("𐑨𐑚", "𐑨 𐑚"))
        self.assertEqual(tallies[HELD_COLLISION], 2)

    def test_dependent_lemma_follows_the_restored_target(self):
        target = record("e-mail", "NN1", "𐑰𐑥𐑱𐑤")
        dependent = record(
            "e-mails", "NN2", "𐑰𐑥𐑱𐑤𐑟",
            lemma={"Latn": "e-mail", "pos": "NN1", "Shaw": "𐑰𐑥𐑱𐑤"})
        _, tallies = run_stage([target, dependent])
        self.assertEqual(dependent["Shaw"], "𐑰-𐑥𐑱𐑤𐑟")
        self.assertEqual(dependent[LEMMA_FIELD]["Shaw"], "𐑰-𐑥𐑱𐑤")
        self.assertEqual(tallies["lemma-repointed"], 1)

    def test_count_is_preserved(self):
        records = [record("e-mail", "NN1", "𐑰𐑥𐑱𐑤"),
                   record("plain", "NN1", "𐑐𐑤𐑱𐑯"),
                   record("1-800", "NN1", "𐑢𐑳𐑯𐑱𐑑")]
        restored, _ = run_stage(records)
        self.assertEqual(sum(len(v) for v in restored.values()), len(records))


if __name__ == "__main__":
    unittest.main(verbosity=2)
