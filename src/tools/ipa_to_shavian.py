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

    # Route the [iɪ].ə syllable break through the affix boundary (+) so
    # ipa_to_shavian keeps it two syllables (𐑦𐑼) instead of collapsing it to
    # NEAR (𐑽) — e.g. happier /hæp.i.ə/ → 𐑣𐑨𐑐𐑦𐑼, not 𐑣𐑨𐑐𐑽. Genuine NEAR
    # (here /hɪə/, no dot) is untouched. Must run before the dot strip below.
    # NOTE: the GenAm .ɚ/.ɹ sibling has the same latent bug but is out of scope.
    ipa = re.sub(r'([iɪ])\.(ə)', r'\1+\2', ipa)

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

    # Strip narrow phonetic diacritics that don't affect Shavian spelling
    # Combining diacritics
    for cp in ("\u0303", "\u0308", "\u0325", "\u031E", "\u031A", "\u0320",
               "\u031D", "\u031F", "\u032A", "\u0306", "\u032C", "\u030A"):
        ipa = ipa.replace(cp, "")
    # Modifier letters and allophonic symbols
    ipa = ipa.replace("ʰ", "")      # aspiration
    ipa = ipa.replace("ʷ", "")      # labialization
    ipa = ipa.replace("ʔ", "")      # glottal stop (allophonic in English)
    ipa = ipa.replace("ˑ", "")      # half-long
    ipa = ipa.replace("˔", "")      # raised modifier
    ipa = ipa.replace("~", "")      # nasalization (ASCII tilde variant)
    ipa = ipa.replace("ᵊ", "")      # superscript schwa

    # Narrow vowel allophones → broad equivalents
    ipa = ipa.replace("ə˞", "əR")   # rhotacized schwa → schwa + R
    ipa = ipa.replace("˞", "")       # any remaining rhoticity hook
    ipa = ipa.replace("ʉ", "uː")    # close central rounded → GOOSE
    ipa = ipa.replace("ɵ", "ʊ")     # close-mid central rounded → FOOT
    ipa = ipa.replace("ɨ", "ɪ")     # close central unrounded → KIT
    ipa = ipa.replace("ᵻ", "ɪ")     # superscript barred i → KIT
    ipa = ipa.replace("ɘ", "ə")     # close-mid central → schwa
    ipa = ipa.replace("ɱ", "m")     # labiodental nasal → m
    ipa = ipa.replace("ɻ", "r")     # retroflex approximant → r
    ipa = ipa.replace("ç", "h")     # voiceless palatal fricative → h (anglicized)
    ipa = ipa.replace("ä", "a")     # centralized a → a
    ipa = ipa.replace("ã", "a")     # nasalized a → a
    ipa = ipa.replace("ĩ", "i")     # nasalized i → i
    ipa = ipa.replace("õ", "o")     # nasalized o → o

    # R-colored vowels that may appear in any source (not just GenAm)
    ipa = ipa.replace("ɝː", "ɜːR")  # long r-colored NURSE
    ipa = ipa.replace("ɝ", "ɜːR")   # r-colored NURSE
    ipa = ipa.replace("ɚ", "əR")    # r-colored schwa
    ipa = ipa.replace("ɜr", "ɜːR")  # NURSE without length mark (GenAm style)
    ipa = ipa.replace("ɑr", "ɑːR")  # START: bare ɑr → ɑːR (any source)

    # Bare ɑ without length mark → ɑː (PALM) for non-GenAm sources
    # (GenAm bare ɑ is handled separately in _normalize_genam as LOT)
    if source not in ("wiktionary_gam",):
        ipa = re.sub(r'ɑ(?!ː|R|r)', 'ɑː', ipa)

    # Bare ɜ without length mark → ɜː (NURSE)
    ipa = re.sub(r'ɜ(?!ː)', 'ɜː', ipa)

    # Voiceless velar fricative → 𐑒 (anglicized)
    # But only IPA x (which is ASCII), not when it's part of a word
    # This is handled by leaving it for the PHONEME_MAP; add mapping there

    # Remove parenthesized optional segments like (ɹ)
    ipa = re.sub(r'\([^)]*\)', '', ipa)

    # --- GenAm-specific IPA symbols ---
    if source == "wiktionary_gam":
        ipa = _normalize_genam(ipa)

    # --- R-restoration for non-rhotic sources ---
    # Apply per-word for phrases so alignment works correctly
    if source in ("britfone", "wiktionary_rp"):
        if " " in word and " " in ipa:
            ipa_words = ipa.split(" ")
            latin_words = word.split(" ")
            if len(ipa_words) == len(latin_words):
                ipa = " ".join(
                    _restore_rhoticity_ml(iw, lw)
                    for iw, lw in zip(ipa_words, latin_words)
                )
            else:
                ipa = _restore_rhoticity_ml(ipa, word)
        else:
            ipa = _restore_rhoticity_ml(ipa, word)

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
    # R-colored vowels and bare ɜ now handled in common normalize_ipa() section.

    # Flap
    ipa = ipa.replace("ɾ", "t")      # alveolar flap → t

    # GenAm ɑr → ɑːR (START) — must come before bare ɑ mapping
    # (ɹ→r already done by normalize_ipa before this function is called)
    ipa = ipa.replace("ɑr", "ɑːR")

    # GenAm ɔr → ɔːR (FORCE)
    ipa = ipa.replace("ɔr", "ɔːR")

    # GenAm bare ɑ → ɒ (LOT vowel)
    # But ɑː should stay as ɑː (PALM/BATH)
    # And ɑːR is already handled above
    ipa = re.sub(r'ɑ(?!ː)', 'ɒ', ipa)

    # GenAm bare ɔ (without length mark, not in diphthongs) → ɒ (LOT)
    # GenAm IPA from Wiktionary uses ɔ for the merged cot-caught vowel;
    # ReadLex canonical form is LOT (𐑪), not THOUGHT (𐑷).
    # Don't touch ɔː (explicit THOUGHT) or ɔɪ/ɔʊ (diphthongs) or ɔR/ɔr (FORCE).
    ipa = re.sub(r'ɔ(?!ː|ɪ|ʊ|R|r)', 'ɒ', ipa)

    return ipa


def _restore_rhoticity_ml(ipa: str, word: str) -> str:
    """Restore linking/intrusive R for non-rhotic IPA using a trained classifier.

    Non-rhotic dialects drop r after vowels except before another vowel.
    ReadLex's "Rhotic RP" convention adds capital R where the spelling has
    an 'r' but the non-rhotic transcription omits it.

    Uses a gradient-boosted classifier trained on ReadLex to predict which
    vowel positions need R insertion, based on IPA context and spelling alignment.
    """
    if not word:
        return ipa

    word_lower = word.lower().replace("_", " ")
    if 'r' not in word_lower:
        return ipa

    # Strip stress marks for processing
    stripped = re.sub('[ˈˌ]', '', ipa)

    # Load model (cached after first call)
    model_data = _load_rhoticity_model()
    if model_data is None:
        # Fallback: just return as-is if model not available
        return ipa

    model = model_data['model']
    char_vocab = model_data['char_vocab']
    r_vowels = model_data['r_vowels']

    # Find all vowel sites that could potentially take R
    sites = _find_r_sites(stripped, r_vowels)
    if not sites:
        return ipa

    # Predict for each site
    import numpy as np
    insertions = []
    for site_pos, vowel in sites:
        features = _extract_r_features(stripped, word, site_pos, vowel, r_vowels)
        vec = _features_to_vector(features, char_vocab, r_vowels).reshape(1, -1)
        pred = model.predict(vec)[0]
        insert_pos = site_pos + len(vowel)
        if pred:
            insertions.append(insert_pos)

    # Insert R at predicted positions (reverse order to preserve indices)
    result = list(stripped)
    for pos in sorted(insertions, reverse=True):
        result.insert(pos, 'R')

    return ''.join(result)


_rhoticity_model_cache = None


def _load_rhoticity_model():
    """Load the rhoticity model, caching after first call."""
    global _rhoticity_model_cache
    if _rhoticity_model_cache is not None:
        return _rhoticity_model_cache

    import pickle
    model_path = Path(__file__).parent.parent.parent / "data" / "rhoticity-model.pkl"
    if not model_path.exists():
        print(f"Warning: rhoticity model not found at {model_path}", file=sys.stderr)
        return None

    with open(model_path, 'rb') as f:
        _rhoticity_model_cache = pickle.load(f)
    return _rhoticity_model_cache


def _find_r_sites(ipa: str, r_vowels: list) -> list:
    """Find all vowel positions in IPA that could potentially take R."""
    sites = []
    i = 0
    while i < len(ipa):
        matched = False
        for vowel in r_vowels:
            vlen = len(vowel)
            if ipa[i:i + vlen] == vowel:
                next_pos = i + vlen
                # Skip əʊ diphthong
                if vowel == 'ə' and next_pos < len(ipa) and ipa[next_pos] == 'ʊ':
                    i += 1
                    matched = True
                    break
                sites.append((i, vowel))
                i += vlen
                matched = True
                break
        if not matched:
            i += 1
    return sites


def _extract_r_features(ipa: str, word: str, site_pos: int, vowel: str, r_vowels: list) -> dict:
    """Extract features for a vowel position that may need R insertion."""
    word_lower = word.lower()
    ipa_len = len(ipa)
    word_len = len(word_lower)
    vlen = len(vowel)
    after_pos = site_pos + vlen

    ctx_before = ipa[max(0, site_pos - 3):site_pos].rjust(3, '_')
    ctx_after = ipa[after_pos:after_pos + 3].ljust(3, '_')
    next_char = ipa[after_pos] if after_pos < ipa_len else '_'
    prev_char = ipa[site_pos - 1] if site_pos > 0 else '_'

    norm_pos = site_pos / max(ipa_len - 1, 1)
    is_final = after_pos >= ipa_len

    aligned_pos = int(norm_pos * (word_len - 1)) if word_len > 1 else 0
    aligned_pos = min(aligned_pos, word_len - 1)

    spell_at = word_lower[aligned_pos] if aligned_pos < word_len else '_'

    r_positions = [i for i, c in enumerate(word_lower) if c == 'r']
    if r_positions:
        min_r_dist = min(abs(aligned_pos - rp) for rp in r_positions)
        nearest_r_pos = min(r_positions, key=lambda rp: abs(aligned_pos - rp))
        r_before = nearest_r_pos < aligned_pos
        r_after = nearest_r_pos >= aligned_pos
    else:
        min_r_dist = 99
        r_before = False
        r_after = False

    r_at_aligned = spell_at == 'r'
    r_near_aligned = 'r' in word_lower[max(0, aligned_pos - 1):aligned_pos + 2]

    consonants = set('pbtdkɡfvθðszʃʒhmnŋlrwjʍ')
    ipa_vowels_set = set('iɪeɛæɑɒɔʊuəʌɜaɐoɵʉɨ')

    return {
        'prev_char': prev_char,
        'next_char': next_char,
        'spell_at': spell_at,
        'ctx_before_1': ctx_before[-1],
        'ctx_before_2': ctx_before[-2] if len(ctx_before) >= 2 else '_',
        'ctx_after_1': ctx_after[0],
        'ctx_after_2': ctx_after[1] if len(ctx_after) >= 2 else '_',
        'norm_pos': norm_pos,
        'is_final': is_final,
        'r_at_aligned': r_at_aligned,
        'r_near_aligned': r_near_aligned,
        'min_r_dist': min_r_dist,
        'r_before': r_before,
        'r_after': r_after,
        'ends_er': word_lower[-2:] in ('er', 're'),
        'ends_or': word_lower[-2:] == 'or',
        'ends_ar': word_lower[-2:] == 'ar',
        'ends_r': word_lower.endswith('r'),
        'ends_re': word_lower.endswith('re'),
        'r_count': word_lower.count('r'),
        'word_len': word_len,
        'ipa_len': ipa_len,
        'next_is_consonant': next_char in consonants,
        'next_is_vowel': next_char in ipa_vowels_set,
        'vowel_type': r_vowels.index(vowel) if vowel in r_vowels else -1,
        'syllable_index': sum(1 for c in ipa[:site_pos] if c in ipa_vowels_set),
        'vowel_count': sum(1 for c in ipa if c in ipa_vowels_set),
    }


def _features_to_vector(features: dict, char_vocab: dict, r_vowels: list):
    """Convert feature dict to numpy vector for the rhoticity model."""
    import numpy as np

    def ci(c):
        return char_vocab.get(c, 0)

    vec = [
        ci(features['prev_char']),
        ci(features['next_char']),
        ci(features['spell_at']),
        ci(features['ctx_before_1']),
        ci(features['ctx_before_2']),
        ci(features['ctx_after_1']),
        ci(features['ctx_after_2']),
        features['norm_pos'],
        float(features['is_final']),
        float(features['r_at_aligned']),
        float(features['r_near_aligned']),
        min(features['min_r_dist'], 20) / 20.0,
        float(features['r_before']),
        float(features['r_after']),
        float(features['ends_er']),
        float(features['ends_or']),
        float(features['ends_ar']),
        float(features['ends_r']),
        float(features['ends_re']),
        features['r_count'] / 5.0,
        features['word_len'] / 20.0,
        features['ipa_len'] / 20.0,
        float(features['next_is_consonant']),
        float(features['next_is_vowel']),
        features['vowel_type'] / len(r_vowels),
        features['syllable_index'] / 5.0,
        features['vowel_count'] / 8.0,
    ]
    return np.array(vec, dtype=np.float32)


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

    # --- Grammatical suffix ɪ → ə ---
    # ReadLex uses ə (not ɪ) specifically in grammatical suffixes.
    # These are ONLY the inflectional/derivational endings, NOT all word-final
    # -ɪt/-ɪs/-ɪn patterns (those could be stressed or lexical).
    # We rely on spelling patterns to identify grammatical suffixes.
    word_lower = word.lower()

    # -ness → -nəs (always grammatical)
    if word_lower.endswith('ness') or word_lower.endswith('nesses'):
        ipa = re.sub(r'nɪs$', 'nəs', ipa)
        ipa = re.sub(r'nɪsɪz$', 'nəsɪz', ipa)
    # -ment → -mənt (always grammatical)
    if word_lower.endswith('ment') or word_lower.endswith('ments'):
        ipa = re.sub(r'mɪnt$', 'mənt', ipa)
        ipa = re.sub(r'mɪnts$', 'mənts', ipa)
    # -less → -ləs (always grammatical)
    if word_lower.endswith('less'):
        ipa = re.sub(r'lɪs$', 'ləs', ipa)
    # -ble/-bly (derivational suffix)
    if word_lower.endswith('ble') or word_lower.endswith('bly'):
        ipa = re.sub(r'bɪl$', 'bəl', ipa)
        ipa = re.sub(r'blɪ$', 'bli', ipa)  # -bly keeps ɪ→i actually

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
    ("iəR", "𐑽"),  # NEAR: weak /i/ + schwa + linking r, e.g. material-ly
    ("ʊəR", "𐑫𐑼"), # CURE: poor, sure

    # R-colored long vowels/diphthongs (with lowercase r)
    ("ɜːr", "𐑻"),  # NURSE: bird (lowercase r variant)
    ("ɑːr", "𐑸"),  # START: far (lowercase r variant)
    ("ɔːr", "𐑹"),  # NORTH/FORCE: for (lowercase r variant)
    ("eər", "𐑺"),  # SQUARE: air (lowercase r variant)
    ("ɪər", "𐑽"),  # NEAR: dear (lowercase r variant)
    ("iər", "𐑽"),  # NEAR: weak /i/ + schwa (lowercase r variant)
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
    ("iə", "𐑾"),   # NEAR: weak /i/ + schwa, e.g. material, editorial, coaxial
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
    ("x", "𐑒"),    # voiceless velar fricative → anglicized as k (loch, Bach)
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
            # Skip orphaned length marks (ː consumed by vowel+ː patterns,
            # but left over when the vowel was matched without it)
            if char == 'ː':
                pos += 1
                continue
            # Unknown character — pass through
            result.append(char)
            pos += 1

    return "".join(result)


# All Shavian letters that contain an 'r' sound
SHAVIAN_R_LETTERS = set("𐑮𐑼𐑻𐑺𐑽𐑸𐑹")

# Known acceptable Shavian alternation pairs (either direction).
# These represent genuine dialect/editorial differences that are valid
# alternative spellings, not errors.
ACCEPTABLE_ALTERNATIONS = {
    ('𐑦', '𐑩'),  # kit/schwa: RP speakers may use either in weak syllables
    ('𐑨', '𐑩'),  # trap/schwa: unstressed initial syllables
    ('𐑫', '𐑩'),  # foot/schwa: modern pronunciation shift
    ('𐑼', '𐑩'),  # schwa-r/schwa: r-related alternation
    ('𐑼', '𐑦'),  # schwa-r/kit: r-related alternation
}
# Make bidirectional
ACCEPTABLE_ALTERNATIONS |= {(b, a) for a, b in ACCEPTABLE_ALTERNATIONS}


def classify_shaw_difference(our_shaw: str, readlex_shaw: str) -> str:
    """Classify the difference between our Shavian and ReadLex's.

    Returns:
        "match" — identical
        "acceptable_alternation" — differs only in known acceptable vowel alternations
        "different" — substantive difference
    """
    if our_shaw == readlex_shaw:
        return "match"

    if len(our_shaw) != len(readlex_shaw):
        return "different"

    for i in range(len(our_shaw)):
        if our_shaw[i] != readlex_shaw[i]:
            if (our_shaw[i], readlex_shaw[i]) not in ACCEPTABLE_ALTERNATIONS:
                return "different"

    return "acceptable_alternation"

# Valid Shavian characters (for unknown-char detection)
KNOWN_SHAVIAN = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")


def score_confidence(word: str, ipa: str, shaw: str,
                     ml_shaw: str | None = None) -> tuple[int, list[str]]:
    """Score conversion confidence as a percentage (0-99) with explanatory notes.

    Empirically calibrated against ReadLex overlap data:
      Clean (no flags):              89% accuracy → confidence 89
      shave+ML consensus override:  ~99% accuracy → confidence 99
      r_gap + shave agrees:          97% accuracy → confidence 95
      ML disagrees + shave agrees:   67% accuracy → confidence 65
      r_gap only:                    30% accuracy → confidence 30
      ML disagrees only:              5% accuracy → confidence 5
      missing_r or unknown_chars:     0% accuracy → confidence 1

    Args:
        word: Latin spelling
        ipa: Normalized IPA string
        shaw: Shavian output from converter
        ml_shaw: Shavian from ML model (None if unavailable)

    Returns:
        (confidence_pct, notes) where confidence_pct is 0-99
    """
    notes = []
    penalties = []

    # Check ML disagreement
    if ml_shaw is not None and ml_shaw != shaw:
        notes.append(f"ml_disagrees:{ml_shaw}")
        penalties.append("ml_disagrees")

    # Check r-gap (spelling has more r's than IPA)
    word_lower = word.lower()
    if 'r' in word_lower:
        spelling_r = word_lower.count('r')
        ipa_r = ipa.count('r') + ipa.count('R')
        if spelling_r > ipa_r:
            notes.append(f"r_gap:spelling={spelling_r},ipa={ipa_r}")
            penalties.append("r_gap")

    # Check missing r entirely
    missing_r = check_missing_r(word, shaw)
    if missing_r:
        notes.append(missing_r)
        penalties.append("missing_r")

    # Check unknown characters
    unknown = set(shaw) - KNOWN_SHAVIAN
    if unknown:
        notes.append(f"unknown_chars:{''.join(unknown)}")
        penalties.append("unknown_chars")

    # Check numeral in word
    if word and word[0].isdigit():
        notes.append("numeral")
        penalties.append("numeral")

    # Compute confidence percentage from penalty combination
    p = set(penalties)
    if not p:
        pct = 89
    elif "unknown_chars" in p:
        pct = 1
    elif "missing_r" in p and "r_gap" in p:
        pct = 1
    elif "missing_r" in p:
        pct = 5
    elif "numeral" in p:
        pct = 10
    elif "ml_disagrees" in p and "r_gap" in p:
        pct = 3
    elif "ml_disagrees" in p:
        pct = 5
    elif "r_gap" in p:
        pct = 30
    else:
        pct = 50  # unknown combination

    return pct, notes


WSD_OVERRIDE_THRESHOLD = 70  # shave's WSD must be this confident to override IPA-derived spelling


def upgrade_confidence_shave(pct: int, notes: list[str],
                             shaw: str, shave_shaw: str,
                             ml_shaw: str | None,
                             wsd_confidence: int | None = None,
                             ) -> tuple[int, list[str], str | None]:
    """Upgrade confidence based on shave tool agreement.

    When wsd_confidence is provided and below WSD_OVERRIDE_THRESHOLD, any
    shave-proposed override is refused — shave was unsure which sense of a
    homograph was meant, so its spelling guess should not trump the
    IPA-derived one. The WSD value is logged in notes for traceability.

    Returns (new_pct, updated_notes, override_shaw_or_None).
    """
    # Strip Shavian naming dot (·) — shave adds it for proper nouns,
    # but ReadLex stores spellings without it.
    shave_shaw = shave_shaw.lstrip("·")

    if shave_shaw == shaw:
        # Shave agrees with rules
        new_pct = max(pct, 95) if pct < 89 else max(pct, 97)
        notes.append("shave_agrees")
        return new_pct, notes, None
    elif ml_shaw and shave_shaw == ml_shaw:
        # Shave + ML consensus would normally override — but refuse if shave
        # flagged this word as WSD-ambiguous below threshold.
        if wsd_confidence is not None and wsd_confidence < WSD_OVERRIDE_THRESHOLD:
            notes.append(f"wsd_ambiguous:{wsd_confidence}%; shave_says:{shave_shaw}")
            return pct, notes, None
        suffix = f"; wsd={wsd_confidence}%" if wsd_confidence is not None else ""
        notes.append(f"overridden:was={shaw}; shave+ml_consensus{suffix}")
        return 99, notes, shave_shaw
    else:
        # Shave disagrees with both
        notes.append(f"shave_says:{shave_shaw}")
        return pct, notes, None


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
