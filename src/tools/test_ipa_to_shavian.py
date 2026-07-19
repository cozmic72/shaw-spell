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


class Bug4CureNotReduced(unittest.TestCase):
    """The unstressed jʊ→jə reduction must not mangle CURE (jʊə → 𐑫𐑼) or a
    long jʊː. Ground truth (the Guide / ReadLex): cure 𐑒𐑘𐑫𐑼, pure 𐑐𐑘𐑫𐑼 —
    yod + CURE, never 𐑘𐑩𐑼."""

    def test_cure_diphthong_notation(self):
        self.assertEqual(norm_rp("kjʊə", "cure"), "𐑒𐑘𐑫𐑼")

    def test_cure_ssb_monophthong_notations(self):
        # Lindsey-style CURE: kjəː and kjɵː both land on 𐑒𐑘𐑫𐑼.
        self.assertEqual(norm_rp("kjəː", "cure"), "𐑒𐑘𐑫𐑼")
        self.assertEqual(norm_rp("kjɵː", "cure"), "𐑒𐑘𐑫𐑼")

    def test_cure_words(self):
        self.assertEqual(norm_rp("ˌɪnsɪkjʊə", "insecure"), "𐑦𐑯𐑕𐑦𐑒𐑘𐑫𐑼")
        self.assertEqual(norm_rp("ˈdʒænjʊəɹi", "January"), "𐑡𐑨𐑯𐑘𐑫𐑼𐑦")

    def test_weak_yod_u_still_reduced(self):
        # regular's jʊ is the weak yod-u — the reduction must still apply.
        self.assertEqual(norm_rp("ˈreɡjʊlə", "regular"), "𐑮𐑧𐑜𐑘𐑩𐑤𐑼")


class Bug5SsbLongMonophthongs(unittest.TestCase):
    """SSB/CUBE long-monophthong notations must map onto the ReadLex vowels,
    not leak through as base-letter + stripped length mark."""

    def test_nurse_stressed(self):
        self.assertEqual(norm_rp("wəːk", "work"), "𐑢𐑻𐑒")
        self.assertEqual(norm_rp("ˈəːskɪn", "Erskine"), "𐑻𐑕𐑒𐑦𐑯")

    def test_nurse_unstressed_is_letter(self):
        # ReadLex's own editorial choice for -burn/-ford names (goulburn 𐑚𐑼𐑯).
        self.assertEqual(norm_rp("ˈblækbəːn", "Blackburn"), "𐑚𐑤𐑨𐑒𐑚𐑼𐑯")
        self.assertEqual(norm_rp("ˈsænfəːd", "Sandford"), "𐑕𐑨𐑯𐑓𐑼𐑛")

    def test_force_thought(self):
        self.assertEqual(norm_rp("foː", "four"), "𐑓𐑹")
        self.assertEqual(norm_rp("oːl", "all"), "𐑷𐑤")

    def test_near(self):
        self.assertEqual(norm_rp("ˈpɪːɪdʒ", "peerage"), "𐑐𐑽𐑦𐑡")

    def test_palm(self):
        self.assertEqual(norm_rp("ˈfaːðə", "father"), "𐑓𐑭𐑞𐑼")

    def test_stray_length_on_diphthong_harmless(self):
        # deɪː / beəːr: the length mark is dropped, the diphthong survives.
        self.assertEqual(norm_rp("deɪː", "day"), "𐑛𐑱")
        self.assertEqual(norm_rp("beəːr", "bear"), "𐑚𐑺")

    def test_converter_backstops(self):
        # Stored/upstream IPA hits the converter without normalization.
        self.assertEqual(ipa_to_shavian("ˈɡəʊlbəːRn"), "𐑜𐑴𐑤𐑚𐑼𐑯")   # goulburn
        self.assertEqual(ipa_to_shavian("ˈsaːbɑː"), "𐑕𐑭𐑚𐑭")          # sabah
        self.assertEqual(ipa_to_shavian("ˈbɑRnbɜːRnɪŋ"), "𐑚𐑸𐑯𐑚𐑻𐑯𐑦𐑙")  # barnburning
        self.assertEqual(ipa_to_shavian("ˈhɑdləR"), "𐑣𐑪𐑛𐑤𐑼")        # hodler


class Bug6BareUaHiatus(unittest.TestCase):
    """ʊə with no r is the ʊ+ə hiatus (𐑫𐑩), not CURE-with-r (𐑫𐑼): the old
    mapping invented an r-sound in r-less words."""

    def test_hiatus_words(self):
        self.assertEqual(ipa_to_shavian("ˌsɪsˈsekʃʊəl"), "𐑕𐑦𐑕𐑕𐑧𐑒𐑖𐑫𐑩𐑤")  # cissexual
        self.assertEqual(norm_rp("ˈdʒʊəl", "jewel"), "𐑡𐑫𐑩𐑤")
        self.assertEqual(norm_rp("ˈakʃʊəli", "actually"), "𐑨𐑒𐑖𐑫𐑩𐑤𐑦")

    def test_cure_with_r_untouched(self):
        self.assertEqual(ipa_to_shavian("pʊəR"), "𐑐𐑫𐑼")   # poor
        self.assertEqual(ipa_to_shavian("bjʊəˈret"), "𐑚𐑘𐑫𐑼𐑧𐑑")  # burette (ʊə+r)


class ScorerRGroups(unittest.TestCase):
    """r_gap counts spelling r GROUPS: a doubled rr is one phoneme."""

    def test_double_r_not_a_gap(self):
        from ipa_to_shavian import score_confidence
        pct, notes = score_confidence("carrion", "ˈkærɪən", "𐑒𐑨𐑮𐑾𐑯")
        self.assertFalse(any(n.startswith("r_gap") for n in notes))

    def test_genuine_gap_still_flagged(self):
        from ipa_to_shavian import score_confidence
        pct, notes = score_confidence("charged", "tʃɑːdʒd", "𐑗𐑭𐑡𐑛")
        self.assertTrue(any(n.startswith("r_gap") for n in notes))


class ScorerShaveOptions(unittest.TestCase):
    """A bracketed shave option list containing our spelling is agreement."""

    def test_membership_is_agreement(self):
        from ipa_to_shavian import upgrade_confidence_shave
        pct, notes, override = upgrade_confidence_shave(
            5, [], "𐑛𐑪𐑜𐑚𐑼𐑦", "[𐑛𐑪𐑜𐑚𐑼𐑦 / 𐑛𐑪𐑜𐑚𐑧𐑮𐑦]", None)
        self.assertGreaterEqual(pct, 95)
        self.assertIsNone(override)
        self.assertIn("shave_agrees", notes)

    def test_ml_membership_is_consensus_with_concrete_override(self):
        from ipa_to_shavian import upgrade_confidence_shave
        pct, notes, override = upgrade_confidence_shave(
            5, [], "𐑛𐑪𐑜𐑚𐑧𐑮𐑦", "[𐑛𐑪𐑜𐑚𐑼𐑦 / 𐑛𐑪𐑜𐑚𐑼𐑮𐑦]", "𐑛𐑪𐑜𐑚𐑼𐑦")
        self.assertEqual(pct, 99)
        self.assertEqual(override, "𐑛𐑪𐑜𐑚𐑼𐑦")   # never the bracket string

    def test_non_member_still_disagrees(self):
        from ipa_to_shavian import upgrade_confidence_shave
        pct, notes, override = upgrade_confidence_shave(
            5, [], "𐑨", "[𐑚 / 𐑜]", None)
        self.assertEqual(pct, 5)
        self.assertIsNone(override)


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
