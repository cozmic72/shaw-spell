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


def norm_gam(ipa: str, word: str = "") -> str:
    """Normalize as a GenAm wiktionary source, then convert."""
    return ipa_to_shavian(normalize_ipa(ipa, word, "wiktionary_gam"))


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


class Bug7PriceNarrowSsb(unittest.TestCase):
    """ʌɪ is the SSB/Lindsey narrow PRICE diphthong (price, my, I) → 𐑲, not a
    stranded ʌ+ɪ → 𐑳𐑦."""

    def test_adonai_price_ending(self):
        # normalize path (any non-readlex source) rewrites ʌɪ → aɪ → 𐑲
        self.assertTrue(norm_rp("ˌædɒˈnʌɪ", "adonai").endswith("𐑲"))

    def test_brooklynite_price_medial(self):
        self.assertEqual(norm_rp("ˈbrʊklɪnʌɪt", "brooklynite"), "𐑚𐑮𐑫𐑒𐑤𐑦𐑯𐑲𐑑")

    def test_converter_backstop_slider(self):
        # readlex-source entries bypass normalize_ipa: the PHONEME_MAP backstop
        # must render ʌɪ as PRICE 𐑲 directly (slider ˈslʌɪdəR).
        self.assertEqual(ipa_to_shavian("ˈslʌɪdəR"), "𐑕𐑤𐑲𐑛𐑼")

    def test_price_matches_ai(self):
        # ʌɪ and aɪ converge on the same PRICE glyph.
        self.assertEqual(ipa_to_shavian("ˈslʌɪd"), ipa_to_shavian("ˈslaɪd"))


class Bug8GenAmStressedFleece(unittest.TestCase):
    """GenAm bare i (no length mark) is FLEECE (𐑰) under STRESS, KIT/happY (𐑦)
    unstressed. The stressed-vs-unstressed distinction is the crux."""

    def test_three_monosyllable_fleece(self):
        self.assertEqual(norm_gam("ˈθri", "three"), "𐑔𐑮𐑰")

    def test_antique_stressed_fleece(self):
        self.assertEqual(norm_gam("ænˈtik", "antique"), "𐑨𐑯𐑑𐑰𐑒")

    def test_aegean_stressed_i_before_schwa(self):
        # Stressed i in an iə hiatus (no following r) → FLEECE + schwa.
        self.assertEqual(norm_gam("ɪˈdʒiən", "aegean"), "𐑦𐑡𐑰𐑩𐑯")

    def test_media_first_i_fleece_second_stays(self):
        # First (stressed) i → FLEECE; second (weak, in diə) stays.
        self.assertEqual(norm_gam("ˈmidiə", "media"), "𐑥𐑰𐑛𐑾")

    # --- happY guard: unstressed final/weak i must STAY 𐑦 (the key non-regression) ---

    def test_happy_word_stays_kit(self):
        self.assertEqual(norm_gam("ˈhæpi", "happy"), "𐑣𐑨𐑐𐑦")
        self.assertEqual(norm_gam("ˈsɪti", "city"), "𐑕𐑦𐑑𐑦")
        self.assertEqual(norm_gam("ˈkɔfi", "coffee"), "𐑒𐑪𐑓𐑦")

    def test_unstressed_i_after_uppercase_variant_stays_kit(self):
        # alexandria zÆndriə: the i is unstressed (Æ nucleus precedes it). The
        # onset-scan must see Æ as a nucleus, so the i stays weak (NEAR 𐑾),
        # NOT wrongly lengthened to FLEECE.
        self.assertEqual(norm_gam("ˌælɪɡˈzÆndriə", "alexandria"), "𐑨𐑤𐑦𐑜𐑟𐑨𐑯𐑛𐑮𐑾")

    def test_near_with_r_untouched(self):
        # here/beer/lear: iəR is the NEAR-with-r centering diphthong (𐑽), never
        # FLEECE+lettER. The rule must leave it alone even under stress.
        self.assertEqual(norm_gam("hiəR", "here"), "𐑣𐑽")
        self.assertEqual(norm_gam("ˈbiəR", "beer"), "𐑚𐑽")
        self.assertEqual(norm_gam("liəR", "lear"), "𐑤𐑽")


class Bug9IumSuffixFused(unittest.TestCase):
    """The -ium suffix fuses to the RP ending 𐑾𐑥 (valium 𐑝𐑨𐑤𐑾𐑥), not the
    two-syllable 𐑦𐑩𐑥. ReadLex is unanimous: 155 fused, 0 split. Regression:
    the happier fix (i.ə → i+ə) over-fired on i.əm/i+əm, whose + boundary
    blocked the iə → 𐑾 fusion. Scoped to iəm ONLY (not -iə, iəʊ, iən)."""

    def test_valium_all_boundary_forms(self):
        # Baked + form (wiktionary), dot form, and plain form all fuse.
        self.assertEqual(norm_rp("ˈvæli+əm", "valium"), "𐑝𐑨𐑤𐑾𐑥")
        self.assertEqual(norm_rp("ˈvæli.əm", "valium"), "𐑝𐑨𐑤𐑾𐑥")
        self.assertEqual(norm_rp("ˈvæliəm", "valium"), "𐑝𐑨𐑤𐑾𐑥")

    def test_sodium_medium(self):
        self.assertEqual(norm_rp("ˈsəʊdi.əm", "sodium"), "𐑕𐑴𐑛𐑾𐑥")
        self.assertEqual(norm_rp("ˈmiːdi.əm", "medium"), "𐑥𐑰𐑛𐑾𐑥")

    def test_byzantium_baked_plus(self):
        self.assertEqual(norm_rp("baɪˈzænti+əm", "byzantium"), "𐑚𐑲𐑟𐑨𐑯𐑑𐑾𐑥")

    def test_kit_vowel_iium_fuses(self):
        # KIT ɪ before the -ium suffix fuses like FLEECE i (both → 𐑾 in RP).
        self.assertEqual(norm_rp("reɪdɪ+əm", "radium"), "𐑮𐑱𐑛𐑾𐑥")
        self.assertEqual(norm_rp("pəˈləʊnɪ+əm", "polonium"), "𐑐𐑩𐑤𐑴𐑯𐑾𐑥")

    def test_plural_iums_fuses(self):
        self.assertEqual(norm_rp("ˈmiːdi.əmz", "mediums"), "𐑥𐑰𐑛𐑾𐑥𐑟")

    # --- CRITICAL guards: neighbouring iə contexts must be UNTOUCHED ---

    def test_happier_word_final_ia_unchanged(self):
        # Word-FINAL -iə (not followed by m): stays two-syllable 𐑦𐑼.
        self.assertEqual(norm_rp("ˈhæp.i.ə", "happier"), "𐑣𐑨𐑐𐑦𐑼")

    def test_radio_iau_unchanged(self):
        # iəʊ (different vowel after i): weak-i + GOAT, untouched.
        self.assertEqual(norm_rp("ˈreɪdi.əʊ", "radio"), "𐑮𐑱𐑛𐑦𐑴")

    def test_belgium_no_ia_sequence_unchanged(self):
        # -gium: i palatalised into dʒ, no iə vowel sequence → not our case.
        self.assertEqual(norm_rp("ˈbɛldʒəm", "belgium"), "𐑚𐑧𐑤𐑡𐑩𐑥")

    def test_nasturtium_no_ia_sequence_unchanged(self):
        # -tium: i palatalised into ʃ, no iə vowel sequence → not our case.
        self.assertEqual(norm_rp("nəˈstɜːʃəm", "nasturtium"), "𐑯𐑩𐑕𐑑𐑻𐑖𐑩𐑥")

    def test_ian_iən_unchanged(self):
        # iən (not iəm): out of scope, left exactly as-is.
        self.assertEqual(ipa_to_shavian("ˈiən"), "𐑾𐑯")


class Determinism(unittest.TestCase):
    """The converter is pure: same input → same output."""

    def test_repeatable(self):
        for ipa in ["ˈɔːdiəʊ", "ˈɛːrɪəl", "məˈtɪəriəl", "ˈslʌɪdəR"]:
            self.assertEqual(ipa_to_shavian(ipa), ipa_to_shavian(ipa))

    def test_genam_normalize_repeatable(self):
        self.assertEqual(norm_gam("ˈθri", "three"), norm_gam("ˈθri", "three"))

    def test_normalize_repeatable(self):
        self.assertEqual(
            norm_rp("əˈbjuːzəR", "abuser"),
            norm_rp("əˈbjuːzəR", "abuser"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
