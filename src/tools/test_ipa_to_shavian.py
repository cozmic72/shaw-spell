#!/usr/bin/env python3
"""Unit tests for the IPA-to-Shavian converter.

Focus: the three converter bugs fixed in the editorial-overlay branch, plus
regression guards proving the fixes don't disturb neighbouring cases.

Run:
    python3 src/tools/test_ipa_to_shavian.py
"""

import unittest

from ipa_to_shavian import ipa_to_shavian, normalize_ipa


def norm_rp(ipa: str, word: str) -> str:
    """Normalize as a non-rhotic wiktionary/SSB source, then convert."""
    return ipa_to_shavian(normalize_ipa(ipa, word, "wiktionary_rp"))


class Bug1SquareVowel(unittest.TestCase):
    """ɛː is the SQUARE vowel (eə → 𐑺) in modern SSB, not NURSE (𐑻)."""

    def test_aerial_is_square(self):
        # ˈɛːrɪəl must give the SQUARE glyph 𐑺, not NURSE 𐑻.
        self.assertEqual(norm_rp("ˈɛːrɪəl", "aerial"), "𐑺𐑾𐑤")

    def test_air_is_square(self):
        self.assertEqual(norm_rp("ɛː", "air"), "𐑺")

    def test_matches_explicit_ee_schwa_form(self):
        # ɛː-input and the already-SQUARE eə-input converge on the same glyph.
        self.assertEqual(norm_rp("ˈɛːrɪəl", "aerial"), ipa_to_shavian("ˈeərɪəl"))

    def test_readlex_source_nurse_case_preserved(self):
        # tradesperson's ɛː arrives via source="readlex" (early return), so the
        # SQUARE rewrite never touches it — it stays NURSE 𐑻.
        self.assertIn("𐑻", ipa_to_shavian("ˈtreɪdzpɛːRsən"))


class Bug2AudioGoat(unittest.TestCase):
    """iəʊ is weak-i + GOAT (𐑦𐑴), not NEAR (𐑾) + stranded ʊ."""

    def test_audio(self):
        self.assertEqual(ipa_to_shavian("ˈɔːdiəʊ"), "𐑷𐑛𐑦𐑴")

    def test_radio_video_adagio(self):
        self.assertEqual(ipa_to_shavian("ˈreɪdiəʊ"), "𐑮𐑱𐑛𐑦𐑴")
        self.assertEqual(ipa_to_shavian("ˈvɪdiəʊ"), "𐑝𐑦𐑛𐑦𐑴")
        self.assertEqual(ipa_to_shavian("əˈdɑːdʒiəʊ"), "𐑩𐑛𐑭𐑡𐑦𐑴")

    def test_stress_separated_iəʊ(self):
        # iˈəʊ (stress mark between i and əʊ) is stripped then treated as iəʊ.
        self.assertEqual(ipa_to_shavian("ˌkæriˈəʊki"), "𐑒𐑨𐑮𐑦𐑴𐑒𐑦")

    # --- Regression guards: genuine NEAR / diphthong+əʊ must be untouched ---

    def test_near_words_unaffected(self):
        self.assertEqual(ipa_to_shavian("məˈtɪəriəl"), "𐑥𐑩𐑑𐑽𐑾𐑤")  # material
        self.assertEqual(ipa_to_shavian("aɪˈdɪə"), "𐑲𐑛𐑾")            # idea
        self.assertEqual(ipa_to_shavian("dɪəR"), "𐑛𐑽")               # dear

    def test_diphthong_plus_goat_unaffected(self):
        self.assertEqual(ipa_to_shavian("ˈbeɪəʊbæb"), "𐑚𐑱𐑴𐑚𐑨𐑚")  # baobab: eɪ+əʊ
        self.assertEqual(ipa_to_shavian("ˈkriːəʊl"), "𐑒𐑮𐑰𐑴𐑤")     # creole: iː+əʊ
        self.assertEqual(ipa_to_shavian("ˈbaɪəʊ"), "𐑚𐑲𐑴")          # bio: aɪ+əʊ


class Bug3IdempotentR(unittest.TestCase):
    """R-restoration must not double an R that already exists."""

    def test_abuser_existing_r_not_doubled(self):
        # Input already carries the linking R; result keeps a single 𐑼.
        self.assertEqual(norm_rp("əˈbjuːzəR", "abuser"), "𐑩𐑚𐑿𐑟𐑼")

    def test_abuser_missing_r_restored_once(self):
        # Input lacks the R; exactly one is restored — still a single 𐑼.
        self.assertEqual(norm_rp("əˈbjuːzə", "abuser"), "𐑩𐑚𐑿𐑟𐑼")

    def test_common_rhotic_words_single_r(self):
        for ipa, word, expected in [
            ("ˈmʌðəR", "mother", "𐑥𐑳𐑞𐑼"),
            ("ˈnevəR", "never", "𐑯𐑧𐑝𐑼"),
            ("hɪəR", "here", "𐑣𐑽"),
        ]:
            with self.subTest(word=word):
                self.assertEqual(norm_rp(ipa, word), expected)


class Determinism(unittest.TestCase):
    """The converter is pure: same input → same output."""

    def test_repeatable(self):
        for ipa in ["ˈɔːdiəʊ", "ˈɛːrɪəl", "məˈtɪəriəl"]:
            self.assertEqual(ipa_to_shavian(ipa), ipa_to_shavian(ipa))

    def test_normalize_repeatable(self):
        self.assertEqual(
            norm_rp("əˈbjuːzəR", "abuser"),
            norm_rp("əˈbjuːzəR", "abuser"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
