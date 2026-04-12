#!/usr/bin/env python3
"""
Rule-based IPA-to-Shavian converter for ReadLex-format IPA strings.

Handles ReadLex-specific conventions:
  - Capital R = linking/intrusive r (part of r-colored vowels)
  - Capital N/T/V/F/Ð = word signs for and/to/of/for/the
  - Uppercase Ə = schwa variant (in suffixes like -Əd, -Əz)
  - Uppercase Æ = TRAP-BATH short variant (maps to 𐑨)
  - Uppercase Ɑ = TRAP-BATH long variant (maps to 𐑭)
  - Uppercase I = weak vowel variant (maps to 𐑩)
  - + = affix/morpheme boundary (compound Shavian letters split here)
  - ʍ = voiceless w (maps to 𐑢)
  - ̩ = syllabic mark (ignored)

Usage:
    from ipa_to_shavian import ipa_to_shavian
    shaw = ipa_to_shavian("əˈbæk")  # Returns "𐑩𐑚𐑨𐑒"

    # Or run as script to validate against ReadLex:
    python3 ipa_to_shavian.py [--validate] [--verbose]
"""

import re
import sys
import json
from pathlib import Path


def normalize_ipa(ipa: str, word: str = "", source: str = "readlex") -> str:
    """Normalize IPA from various sources to ReadLex conventions.

    ReadLex uses a specific "Rhotic RP" dialect with conventions like:
      - lowercase 'r' (not ɹ) for the rhotic approximant
      - Capital 'R' for linking/intrusive r
      - 'e' (not ɛ) for the DRESS vowel
      - 'ə' + 'r' compounding into r-colored vowels (ər → 𐑼)
      - No syllabic marks (ən not n̩)

    Args:
        ipa: IPA string from the source
        word: Latin spelling of the word (needed for r-restoration)
        source: one of "readlex", "britfone", "wiktionary_rp", "wiktionary_gam"

    Returns:
        IPA string normalized to ReadLex conventions
    """
    if source == "readlex":
        return ipa  # already in ReadLex format

    # --- Common normalizations across all non-ReadLex sources ---

    # Strip IPA slashes/brackets
    ipa = ipa.strip("/[] ")

    # Remove syllable dots
    ipa = ipa.replace(".", "")

    # Remove tie bars
    ipa = ipa.replace("\u0361", "")  # combining double inverted breve
    ipa = ipa.replace("‿", "")

    # Remove non-syllabic diacritics (e.g. i̯)
    ipa = ipa.replace("\u032F", "")  # combining inverted breve below

    # Convert syllabic consonants: n̩ → ən, l̩ → əl, m̩ → əm
    ipa = ipa.replace("n\u0329", "ən")
    ipa = ipa.replace("l\u0329", "əl")
    ipa = ipa.replace("m\u0329", "əm")
    # Also handle standalone syllabic mark if it survived
    ipa = ipa.replace("\u0329", "")

    # Convert strict IPA symbols to ReadLex conventions
    ipa = ipa.replace("ɹ", "r")    # alveolar approximant → r
    ipa = ipa.replace("ɛː", "ɜː") # long open-e → NURSE (rare)

    # Handle ɛ carefully: ɛə should become eə (SQUARE), standalone ɛ → e (DRESS)
    # But ɛː is NURSE (already handled above)
    ipa = ipa.replace("ɛ", "e")

    # Britfone-specific: ɐ → ʌ (STRUT vowel)
    ipa = ipa.replace("ɐ", "ʌ")

    # Britfone uses ASCII g (U+0067), ReadLex uses IPA ɡ (U+0261)
    ipa = ipa.replace("g", "ɡ")

    # Wiktionary narrow transcription conventions → ReadLex broad
    ipa = ipa.replace("ɫ", "l")    # dark l → plain l
    ipa = ipa.replace("ɒʊ", "əʊ")  # GOAT: Wiktionary sometimes uses ɒʊ, ReadLex uses əʊ
    ipa = ipa.replace("ɪi", "iː")  # happy tensing narrow form → broad iː
    ipa = ipa.replace("i̯", "iː")  # another narrow happy form

    # Remove parenthesized optional segments like (ɹ)
    ipa = re.sub(r'\([^)]*\)', '', ipa)

    # --- GenAm-specific IPA symbols ---
    if source == "wiktionary_gam":
        ipa = _normalize_genam(ipa)

    # --- R-restoration for non-rhotic sources ---
    if source in ("britfone", "wiktionary_rp"):
        ipa = _restore_rhoticity(ipa, word)

    # --- Dialect normalization toward ReadLex conventions ---
    if source in ("britfone", "wiktionary_rp", "wiktionary_gam"):
        ipa = _normalize_to_readlex_dialect(ipa, word)

    return ipa


def _normalize_genam(ipa: str) -> str:
    """Normalize GenAm IPA symbols to ReadLex RRP conventions.

    GenAm IPA uses symbols that don't exist in ReadLex:
      ɚ  → əR  (r-colored schwa, e.g. "better")
      ɝ  → ɜːR (r-colored NURSE, e.g. "bird")
      ɾ  → t   (alveolar flap, e.g. "butter" — ReadLex writes 't')
      ɑɹ → ɑːR (START, e.g. "car" — GenAm has short ɑ+ɹ, ReadLex has ɑːR)
      ɔɹ → ɔːR (FORCE, e.g. "more")

    GenAm vowel mappings where they differ from RP:
      bare ɑ → ɒ  (LOT: GenAm merges LOT into ɑ, ReadLex uses ɒ)
      ɔ (without ː) → ɔː (THOUGHT: GenAm often drops the length mark)

    Note: Many GenAm words produce the SAME Shavian as RRP because
    ReadLex is designed as a universal compromise. GenAm entries in
    ReadLex only exist for genuine exceptions (yod-dropping, etc.).
    """
    # R-colored vowels (must come before bare ɚ/ɝ and before ɑ→ɒ)
    ipa = ipa.replace("ɝː", "ɜːR")   # long r-colored NURSE (rare variant)
    ipa = ipa.replace("ɝ", "ɜːR")    # r-colored NURSE: bird, her
    ipa = ipa.replace("ɚ", "əR")     # r-colored schwa: better, water

    # Flap
    ipa = ipa.replace("ɾ", "t")      # alveolar flap → t

    # GenAm ɑɹ → ɑːR (START) — must come before bare ɑ mapping
    ipa = ipa.replace("ɑɹ", "ɑːR")
    ipa = ipa.replace("ɑr", "ɑːR")

    # GenAm ɔɹ → ɔːR (FORCE)
    ipa = ipa.replace("ɔɹ", "ɔːR")
    ipa = ipa.replace("ɔr", "ɔːR")

    # GenAm bare ɑ → ɒ (LOT vowel)
    # But ɑː should stay as ɑː (PALM/BATH)
    # And ɑːR is already handled above
    ipa = re.sub(r'ɑ(?!ː)', 'ɒ', ipa)

    # GenAm bare ɔ (without length mark) before consonant → ɔː (THOUGHT)
    # But don't touch ɔː or ɔɪ
    ipa = re.sub(r'ɔ(?!ː|ɪ|ʊ|R|r)', 'ɔː', ipa)

    return ipa


def _restore_rhoticity(ipa: str, word: str) -> str:
    """Restore linking/intrusive R for non-rhotic IPA using spelling alignment.

    Non-rhotic dialects drop r after vowels except before another vowel.
    ReadLex's "Rhotic RP" convention adds capital R where the spelling has
    an 'r' but the non-rhotic transcription omits it.

    Strategy: align spelling to IPA to find where 'r' in spelling corresponds
    to a missing r in the IPA, then insert R at those positions.
    """
    if not word:
        return ipa

    word_lower = word.lower().replace("_", " ")
    if 'r' not in word_lower:
        return ipa

    # Strip stress marks for alignment
    stripped = re.sub('[ˈˌ]', '', ipa)

    # Build a simple spelling-to-IPA alignment using the r positions.
    # We scan both the spelling and IPA left-to-right, advancing through
    # both. When we hit 'r' in spelling and the IPA doesn't have 'r' at
    # the corresponding position, we insert R.

    # First: the high-confidence patterns.
    # NURSE: ɜː always gets R (it's always r-colored in the spelling)
    stripped = re.sub(r'ɜː(?!r|R)', 'ɜːR', stripped)

    # Word-final ə → əR when the word ends in 'r' or 're' or 'er' etc.
    if re.search(r'r[es]*$', word_lower):
        stripped = re.sub(r'ə$', 'əR', stripped)
        # Also handle ə before word-boundary space/hyphen
        stripped = re.sub(r'ə(?=[ -])', 'əR', stripped)

    # Inflected forms: word ends in Vr + inflectional suffix (s, ed, d, ly, ing).
    # Insert R after word-final ə that's followed by suffix consonant(s).
    # e.g., actors (Vr+s), filtered (Vr+ed), mastered, pictured,
    # fatherly, wandering, etc.
    # Only strip true inflectional endings to find the stem.
    stem = re.sub(r'(ed|ing|ly|s)$', '', word_lower)
    if re.search(r'[aeiouy]r[^aeiouy]*$', stem) and len(stem) > 1:
        stripped = re.sub(r'ə([pbtdkɡfvθðszʃʒhmnŋlwjʍ]+)$', r'əR\1', stripped)

    # Mid-word ə before consonant: check if spelling has 'r' at aligned position.
    # Handles words like yesterday (jestədeɪ), saturday (sætədeɪ), butterfly (bʌtəflaɪ).
    stripped = _restore_midword_schwa_r(stripped, word_lower)

    # Now handle the harder cases using a spelling-IPA alignment approach.
    # We extract the consonant/vowel skeleton of the spelling to find where
    # 'r' sits relative to other sounds, then match against IPA patterns.
    result = _align_and_insert_r(stripped, word_lower)
    return result


def _restore_midword_schwa_r(ipa: str, word: str) -> str:
    """Insert R after mid-word ə when the spelling has 'r' at the aligned position.

    Uses ratio-based position mapping: if ə is at position i in the IPA,
    look for 'r' near position i/len(ipa) * len(word) in the spelling.

    Only targets ə followed by a consonant (not word-final, not before a vowel,
    not already followed by R/r, and not part of eə/ɪə/ʊə diphthongs).
    """
    if 'r' not in word:
        return ipa

    ipa_vowels = set("ɪiɛeæɑɒɔəʊʌɐuaoyː")
    ipa_consonants = set("pbtdkɡgfvθðszʃʒhmnŋlwjʍ")

    result = list(ipa)
    ipa_len = len(result)
    word_len = len(word)
    insertions = []  # collect (index, 'R') to insert, applied right-to-left

    for i, ch in enumerate(result):
        if ch != 'ə':
            continue
        # Skip word-final ə (already handled)
        if i == ipa_len - 1:
            continue
        # Skip if already followed by R or r
        if result[i + 1] in ('R', 'r'):
            continue
        # Skip if followed by a vowel (linking position, not r-colored)
        if result[i + 1] in ipa_vowels:
            continue
        # Must be followed by a consonant
        if result[i + 1] not in ipa_consonants:
            continue
        # Skip if this ə is part of eə, ɪə, or ʊə diphthong
        if i >= 1 and result[i - 1] in ('e', 'ɪ', 'ʊ'):
            continue

        # Ratio-based alignment: where in the spelling does this ə sit?
        ratio = (i + 1) / ipa_len  # position just after the ə
        spelling_pos = int(ratio * word_len)

        # Search for 'r' in a window around the aligned position
        # Window size scales with word length but at least ±2
        window = max(2, word_len // 4)
        lo = max(0, spelling_pos - window)
        hi = min(word_len, spelling_pos + window + 1)
        spelling_slice = word[lo:hi]

        if 'r' in spelling_slice:
            # Extra guard: the 'r' in spelling should follow a vowel letter
            # (to avoid matching initial 'r' or 'r' in consonant clusters like 'str')
            r_idx = word.find('r', lo)
            if r_idx is not None and r_idx > 0 and word[r_idx - 1] in 'aeiouy':
                insertions.append(i + 1)

    # Apply insertions right-to-left to preserve indices
    for idx in reversed(insertions):
        result.insert(idx, 'R')

    return ''.join(result)


def _align_and_insert_r(ipa: str, word: str) -> str:
    """Align spelling to IPA and insert R where spelling has 'r' but IPA doesn't.

    Uses a greedy forward scan: walk through IPA and spelling simultaneously.
    When spelling has 'r' and IPA has no 'r' at the aligned position,
    check if we're after a vowel that could be r-colored.
    """
    # IPA vowel characters (the ones that can precede linking R)
    ipa_vowels = set("ɪiɛeæɑɒɔəʊʌɐuaoyː")
    ipa_consonants = set("pbtdkɡgfvθðszʃʒhmnŋlrwjʍ")

    # Build a list of 'r' positions in the spelling, relative to vowel/consonant
    # structure. We care about r's that come after vowels in the spelling.
    # We'll just check: for each long vowel pattern in the IPA (ɑː, ɔː, eə, ɪə, ʊə)
    # that doesn't already have R/r after it, if the word spelling suggests
    # there should be an r there, add R.

    # Pattern approach: scan for specific vowel+consonant sequences where
    # a missing 'r' would be expected

    result = list(ipa)
    i = len(result) - 1

    # Process right-to-left to not invalidate indices
    while i >= 0:
        # ɑː before consonant (START: car, far, park)
        if i >= 1 and ''.join(result[i-1:i+1]) == "ɑː":
            if i+1 >= len(result) or result[i+1] not in ('r', 'R') and result[i+1] not in set("ɑɒɔəeɪʊiuaoyː"):
                # Check if word has 'r' — use a simple heuristic:
                # START words almost always have 'r' in spelling
                if 'r' in word and _r_likely_after_vowel(word, 'ar', 'or', 'our', 'oor'):
                    result.insert(i+1, 'R')
        # ɔː before consonant (FORCE/NORTH: for, more, port)
        elif i >= 1 and ''.join(result[i-1:i+1]) == "ɔː":
            if i+1 >= len(result) or result[i+1] not in ('r', 'R') and result[i+1] not in set("ɑɒɔəeɪʊiuaoyː"):
                if 'r' in word and _r_likely_after_vowel(word, 'or', 'our', 'oor', 'oar', 'ore', 'ar', 'aur'):
                    result.insert(i+1, 'R')
        # eə (SQUARE: air, care, there)
        elif i >= 1 and ''.join(result[i-1:i+1]) == "eə":
            if i+1 >= len(result) or result[i+1] not in ('r', 'R'):
                if 'r' in word:
                    result.insert(i+1, 'R')
        # ɪə (NEAR: here, dear, beer)
        elif i >= 1 and ''.join(result[i-1:i+1]) == "ɪə":
            if i+1 >= len(result) or result[i+1] not in ('r', 'R'):
                if 'r' in word and _r_likely_after_vowel(word, 'ear', 'eer', 'ere', 'ier', 'eir'):
                    result.insert(i+1, 'R')
        # ʊə (CURE: poor, sure, tour)
        elif i >= 1 and ''.join(result[i-1:i+1]) == "ʊə":
            if i+1 >= len(result) or result[i+1] not in ('r', 'R'):
                if 'r' in word:
                    result.insert(i+1, 'R')

        i -= 1

    return ''.join(result)


def _normalize_to_readlex_dialect(ipa: str, word: str) -> str:
    """Apply ReadLex-specific dialect preferences to normalized IPA.

    ReadLex makes specific editorial choices that differ from standard SSB:
    1. Uses uppercase Ə for grammatical suffixes (-Əd, -Əz)
    2. Prefers ə over ʊ after j in unstressed syllables
    """
    # --- Suffix conventions: ReadLex uses uppercase Ə for -ed/-es suffixes ---
    # Require a consonant before ɪ to avoid matching diphthongs (aɪd, eɪz).
    cons = r'[pbtdkɡfvθðszʃʒhmnŋlrwjʍR]'
    ipa = re.sub(r'(' + cons + r')ɪd$', r'\1Əd', ipa)
    ipa = re.sub(r'(' + cons + r')ɪz$', r'\1Əz', ipa)
    ipa = re.sub(r'(' + cons + r')ɪdli$', r'\1Ədli', ipa)

    # --- Unstressed jʊ → jə ---
    # ReadLex prefers ə where modern pronunciation has reduced ʊ after j
    result = list(ipa)
    i = 0
    while i < len(result) - 1:
        if result[i] == 'j' and result[i + 1] == 'ʊ':
            stressed = False
            for j in range(i - 1, max(i - 3, -1), -1):
                if result[j] == 'ˈ':
                    stressed = True
                    break
                elif result[j] not in ('ˈ', 'ˌ'):
                    break
            if not stressed:
                result[i + 1] = 'ə'
        i += 1
    ipa = ''.join(result)

    return ipa


def _r_likely_after_vowel(word: str, *patterns: str) -> bool:
    """Check if word contains any of the given spelling patterns with 'r'."""
    word_lower = word.lower()
    for pat in patterns:
        if pat in word_lower:
            return True
    return False


# IPA-to-Shavian mapping rules, ordered longest-first for greedy matching.
# R-colored vowels and diphthongs (with capital R = ReadLex linking r)
# These must come before their component parts.
PHONEME_MAP = [
    # Word signs (uppercase single chars)
    ("N", "𐑯"),   # "and"
    ("T", "𐑑"),   # "to"
    ("V", "𐑝"),   # "of"
    ("F", "𐑓"),   # "for"
    ("Ð", "𐑞"),   # "the"

    # ReadLex uppercase variants
    ("Ə", "𐑩"),   # uppercase schwa (suffix variant)
    ("Æ", "𐑨"),   # TRAP-BATH short variant
    ("Ɑː", "𐑭"), # TRAP-BATH long variant (with length)
    ("Ɑ", "𐑭"),   # TRAP-BATH long variant (without length)
    ("I", "𐑩"),   # weak vowel variant (maps to schwa in Shavian)
    ("L", "𐑤"),   # voiceless lateral (Welsh ll, approximated)

    # Yew ligature (must come before j and uː)
    ("juː", "𐑿"),  # YEW ligature: you, use, new

    # R-colored long vowels/diphthongs (with capital R)
    ("ɜːR", "𐑻"),  # NURSE (stressed): bird, err
    ("ɑːR", "𐑸"),  # START: far, car
    ("ɔːR", "𐑹"),  # NORTH/FORCE: for, more
    ("eəR", "𐑺"),  # SQUARE: air, Mary
    ("ɪəR", "𐑽"),  # NEAR: dear, here
    ("ʊəR", "𐑫𐑼"), # CURE: poor, sure

    # R-colored long vowels/diphthongs (with lowercase r)
    ("ɜːr", "𐑻"),  # NURSE: bird (lowercase r variant)
    ("ɑːr", "𐑸"),  # START: far (lowercase r variant)
    ("ɔːr", "𐑹"),  # NORTH/FORCE: for (lowercase r variant)
    ("eər", "𐑺"),  # SQUARE: air (lowercase r variant)
    ("ɪər", "𐑽"),  # NEAR: dear (lowercase r variant)
    ("ʊər", "𐑫𐑼"), # CURE: poor (lowercase r variant)

    # R-colored short vowels (with capital R or lowercase r)
    ("əR", "𐑼"),   # lettER (unstressed): better
    ("ər", "𐑼"),   # lettER (lowercase r variant)

    # Standalone capital R after other vowels
    ("R", "𐑮"),    # linking r (general case)

    # Diphthongs (standard IPA)
    ("eɪ", "𐑱"),   # FACE: say, make
    ("aɪ", "𐑲"),   # PRICE: my, time
    ("ɔɪ", "𐑶"),   # CHOICE: boy, joy
    ("aʊ", "𐑬"),   # MOUTH: now, out
    ("əʊ", "𐑴"),   # GOAT: go, no
    ("oʊ", "𐑴"),   # GOAT (GenAm variant)
    ("ɪə", "𐑾"),   # NEAR (without R): idea, area
    ("eə", "𐑺"),   # SQUARE (without R, rare in ReadLex)
    ("ʊə", "𐑫𐑼"), # CURE (without R)

    # Long vowels
    ("iː", "𐑰"),   # FLEECE: be, see
    ("ɑː", "𐑭"),   # BATH/PALM: father
    ("ɔː", "𐑷"),   # THOUGHT: caught, all
    ("uː", "𐑵"),   # GOOSE: too, blue
    ("ɜː", "𐑻"),   # NURSE without R (rare in ReadLex)
    ("ɛː", "𐑻"),   # NURSE variant (tradesperson etc.)

    # Affricates (must come before component stops/fricatives)
    ("tʃ", "𐑗"),   # CHURCH: chop
    ("dʒ", "𐑡"),   # JUDGE: jug

    # Short vowels
    ("æ", "𐑨"),    # TRAP: cat
    ("ɛ", "𐑧"),    # DRESS variant (strict IPA)
    ("e", "𐑧"),    # DRESS: pet, bed
    ("ɪ", "𐑦"),    # KIT: it, bit
    ("ɒ", "𐑪"),    # LOT: not, got
    ("ʌ", "𐑳"),    # STRUT: but, cup
    ("ʊ", "𐑫"),    # FOOT: good, book
    ("ɔ", "𐑷"),    # (rare without length mark)
    ("ə", "𐑩"),    # commA: about
    ("ɐ", "𐑳"),    # STRUT (Britfone variant)

    # Consonants
    ("ŋ", "𐑙"),    # RING
    ("θ", "𐑔"),    # THIN
    ("ð", "𐑞"),    # THIS
    ("ʃ", "𐑖"),    # SHIP
    ("ʒ", "𐑠"),    # MEASURE
    ("ʍ", "𐑢"),    # voiceless W (whine) - maps to 𐑢 per ReadLex
    ("j", "𐑘"),    # YES
    ("ɡ", "𐑜"),    # GOT (IPA g)
    ("ɹ", "𐑮"),    # (Britfone r variant)

    # Simple consonants (ASCII)
    ("p", "𐑐"),
    ("b", "𐑚"),
    ("t", "𐑑"),
    ("d", "𐑛"),
    ("k", "𐑒"),
    ("g", "𐑜"),    # ASCII g
    ("f", "𐑓"),
    ("v", "𐑝"),
    ("s", "𐑕"),
    ("z", "𐑟"),
    ("h", "𐑣"),
    ("m", "𐑥"),
    ("n", "𐑯"),
    ("l", "𐑤"),
    ("r", "𐑮"),
    ("w", "𐑢"),
    ("i", "𐑦"),    # allophonic short i (happy tensing)
    ("u", "𐑫"),    # allophonic weak u (ReadLex convention: bare u = 𐑫)
    ("y", "𐑘"),    # rare: used in some foreign words
    ("a", "𐑨"),    # rare standalone
    ("o", "𐑪"),    # rare standalone
]

# Characters to skip/pass through
PASSTHROUGH = set(" -.'̩")
SKIP = set("ˈˌ")  # stress marks only; ː is part of phoneme patterns


def ipa_to_shavian(ipa: str) -> str:
    """Convert a ReadLex-format IPA string to Shavian script.

    Handles affix boundaries (+) by converting each segment separately,
    preventing compound Shavian letters from spanning morpheme boundaries.

    Args:
        ipa: IPA string using ReadLex conventions (capital R, word signs, etc.)

    Returns:
        Shavian string
    """
    # Split on affix boundaries, convert each segment, rejoin
    if '+' in ipa:
        segments = ipa.split('+')
        return ''.join(_convert_segment(seg) for seg in segments)
    return _convert_segment(ipa)


def _convert_segment(ipa: str) -> str:
    """Convert a single IPA segment (no affix boundaries) to Shavian.

    Strips stress marks and length marks before matching so that compound
    phonemes like ər are not broken by intervening ˈ or ˌ.
    """
    # Strip stress marks and length marks — they don't affect Shavian output
    stripped = ''
    for ch in ipa:
        if ch not in SKIP:
            stripped += ch
    return _convert_stripped(stripped)


def _convert_stripped(ipa: str) -> str:
    """Convert a stress-mark-free IPA string to Shavian."""
    result = []
    pos = 0
    length = len(ipa)

    while pos < length:
        char = ipa[pos]

        # Pass through spaces, hyphens, dots, apostrophes, syllabic marks
        if char in PASSTHROUGH:
            result.append(char)
            pos += 1
            continue

        # Try greedy longest-first match
        matched = False
        for phoneme, shavian in PHONEME_MAP:
            plen = len(phoneme)
            if ipa[pos:pos + plen] == phoneme:
                result.append(shavian)
                pos += plen
                matched = True
                break

        if not matched:
            # Unknown character — pass through
            result.append(char)
            pos += 1

    return "".join(result)


# All Shavian letters that contain an 'r' sound
SHAVIAN_R_LETTERS = set("𐑮𐑼𐑻𐑺𐑽𐑸𐑹")


def check_missing_r(word: str, shaw: str) -> str | None:
    """Check if a word has 'r' in its Latin spelling but no r-sound in Shavian.

    Returns a warning string if there's a likely missing r, or None if OK.
    This is a confidence penalty signal, not a fix.
    """
    word_lower = word.lower()
    if 'r' not in word_lower:
        return None

    has_shavian_r = bool(set(shaw) & SHAVIAN_R_LETTERS)
    if has_shavian_r:
        return None

    # Word has 'r' in spelling but zero r-sounds in Shavian output
    return f"missing_r:spelling_has_r_but_shaw_has_none"


def validate_against_readlex(readlex_path: str, verbose: bool = False) -> dict:
    """Validate the converter against all ReadLex entries.

    Returns dict with counts: total, correct, incorrect, and list of mismatches.
    """
    with open(readlex_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total = 0
    correct = 0
    mismatches = []

    for key, entries in data.items():
        for entry in entries:
            ipa = entry['ipa']
            expected = entry['Shaw']
            predicted = ipa_to_shavian(ipa)

            total += 1
            if predicted == expected:
                correct += 1
            else:
                mismatches.append({
                    'word': entry['Latn'],
                    'ipa': ipa,
                    'expected': expected,
                    'predicted': predicted,
                    'pos': entry.get('pos', ''),
                })

    accuracy = correct / total * 100 if total else 0
    result = {
        'total': total,
        'correct': correct,
        'incorrect': len(mismatches),
        'accuracy': accuracy,
        'mismatches': mismatches,
    }

    if verbose:
        print(f"Total entries: {total}")
        print(f"Correct:       {correct} ({accuracy:.2f}%)")
        print(f"Mismatches:    {len(mismatches)}")
        print()
        # Show first 50 mismatches
        for m in mismatches[:50]:
            print(f"  {m['word']:25s} ipa={m['ipa']:35s}")
            print(f"    expected:  {m['expected']}")
            print(f"    predicted: {m['predicted']}")
            print()

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IPA-to-Shavian converter")
    parser.add_argument("--validate", action="store_true",
                        help="Validate against ReadLex")
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed mismatches")
    parser.add_argument("--ipa", type=str,
                        help="Convert a single IPA string")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    readlex_path = project_root / "external" / "readlex" / "readlex.json"

    if args.ipa:
        print(ipa_to_shavian(args.ipa))
    elif args.validate:
        result = validate_against_readlex(str(readlex_path), verbose=args.verbose)
        print(f"\nAccuracy: {result['accuracy']:.2f}% ({result['correct']}/{result['total']})")
        if not args.verbose and result['mismatches']:
            print(f"Run with --verbose to see mismatches")
    else:
        parser.print_help()
