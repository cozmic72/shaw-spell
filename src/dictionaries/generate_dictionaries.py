#!/usr/bin/env python3
"""
Generate Shavian dictionary XML files for macOS Dictionary.app

Uses readlex.json for word data and pre-built definition caches.

Prerequisites:
  - Run src/build_definition_caches.py first to generate the Shavian cache
  - Or use existing cache at data/definitions-shavian.json

Generates:
  - shavian-english.xml (Shavian → English with definitions)
  - english-shavian.xml (English → Shavian with transliterated definitions)
  - shavian-shavian.xml (Shavian → Shavian definitions)
"""

import json
import sys
import subprocess
from pathlib import Path
from html import escape
from collections import defaultdict
from build_definition_caches import POS_TO_ENGLISH, POS_TO_SHAVIAN

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from dialect_display import (
    var_label, is_british, is_american, variations_label, rssb_role,
    BRITISH_BASE_VAR,
)
from inflection_rules import derive_noun_index_pairs
# Dialect detection now uses comprehensive cache only


# Cache for normalized words to avoid repeated lookups
_normalize_us_cache = {}
_normalize_gb_cache = {}


class ShyphenateSession:
    """
    Shavian hyphenation using the shyphenate tool.

    Uses batch mode (communicate) since shyphenate reads all input
    before producing output, so interactive line-by-line mode does not work.
    Batches multiple texts per subprocess invocation for efficiency.
    """
    BATCH_SIZE = 500  # Number of texts to batch per subprocess call

    def __init__(self):
        self.available = True
        self._cache = {}
        self._pending = []  # Texts waiting to be hyphenated
        self._pending_set = set()  # For dedup
        # Check if shyphenate is available
        try:
            subprocess.run(['shyphenate', '--version'], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("Warning: shyphenate not found on PATH", file=sys.stderr)
            self.available = False

    def _flush_batch(self):
        """Process all pending texts through shyphenate in one batch."""
        if not self._pending:
            return

        batch = self._pending
        self._pending = []
        self._pending_set = set()

        try:
            input_text = '\n'.join(batch) + '\n'
            proc = subprocess.run(
                ['shyphenate'],
                input=input_text,
                capture_output=True,
                text=True,
                timeout=30
            )
            results = proc.stdout.rstrip('\n').split('\n')
            for text, result in zip(batch, results):
                self._cache[text] = result
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"Warning: shyphenate batch failed: {e}", file=sys.stderr)
            # Cache original texts as fallback
            for text in batch:
                self._cache[text] = text

    def enqueue(self, text):
        """Add a text to the pending batch. Call flush_batch() before reading results."""
        if not self.available or text in self._cache or text in self._pending_set:
            return
        self._pending.append(text)
        self._pending_set.add(text)
        if len(self._pending) >= self.BATCH_SIZE:
            self._flush_batch()

    def hyphenate(self, text):
        """
        Hyphenate a single text.

        Args:
            text: String to hyphenate

        Returns:
            Hyphenated text, or original if shyphenate isn't available
        """
        if not self.available:
            return text

        if text not in self._cache:
            self.enqueue(text)
            self._flush_batch()

        return self._cache.get(text, text)

    def close(self):
        """Flush any remaining batch."""
        self._flush_batch()

def normalize_to_us_with_cache(word, wordnet_cache):
    """
    Normalize word to US spelling using comprehensive WordNet cache.
    Returns US spelling if available in cache, otherwise returns word unchanged.
    Handles hyphenated compounds by normalizing each part.
    """
    # Check memo cache first
    if word in _normalize_us_cache:
        return _normalize_us_cache[word]

    # Handle hyphenated words by normalizing each part
    if '-' in word:
        parts = word.split('-')
        normalized_parts = [normalize_to_us_with_cache(part, wordnet_cache) for part in parts]
        result = '-'.join(normalized_parts)
        _normalize_us_cache[word] = result
        return result

    # Pre-compute lowercase to avoid multiple calls
    word_lower = word.lower()

    # Return unchanged if no cache or word not in cache
    if not wordnet_cache or word_lower not in wordnet_cache:
        _normalize_us_cache[word] = word
        return word

    # Get US variants from cache (aggregate from all senses across all POS)
    entry = wordnet_cache[word_lower]
    us_variants = []
    for pos_data in entry.get('pos_entries', {}).values():
        for sense in pos_data.get('sense_variants', []):
            sense_variants = sense.get('variants', {}).get('US', [])
            for v in sense_variants:
                if v not in us_variants:
                    us_variants.append(v)

    if us_variants:
        # Pick first variant and preserve original casing
        us_variant = us_variants[0]
        if word and word[0].isupper():
            result = us_variant.capitalize()
        else:
            result = us_variant
        _normalize_us_cache[word] = result
        return result

    _normalize_us_cache[word] = word
    return word


def normalize_to_gb_with_cache(word, wordnet_cache):
    """
    Normalize word to GB spelling using comprehensive WordNet cache.
    Returns GB spelling if available in cache, otherwise returns word unchanged.
    Handles hyphenated compounds by normalizing each part.
    """
    # Check memo cache first
    if word in _normalize_gb_cache:
        return _normalize_gb_cache[word]

    # Handle hyphenated words by normalizing each part
    if '-' in word:
        parts = word.split('-')
        normalized_parts = [normalize_to_gb_with_cache(part, wordnet_cache) for part in parts]
        result = '-'.join(normalized_parts)
        _normalize_gb_cache[word] = result
        return result

    # Pre-compute lowercase to avoid multiple calls
    word_lower = word.lower()

    # Return unchanged if no cache or word not in cache
    if not wordnet_cache or word_lower not in wordnet_cache:
        _normalize_gb_cache[word] = word
        return word

    # Get GB variants from cache (aggregate from all senses across all POS)
    entry = wordnet_cache[word_lower]
    gb_variants = []
    for pos_data in entry.get('pos_entries', {}).values():
        for sense in pos_data.get('sense_variants', []):
            sense_variants = sense.get('variants', {}).get('GB', [])
            for v in sense_variants:
                if v not in gb_variants:
                    gb_variants.append(v)

    if gb_variants:
        # Pick first variant and preserve original casing
        gb_variant = gb_variants[0]
        if word and word[0].isupper():
            result = gb_variant.capitalize()
        else:
            result = gb_variant
        _normalize_gb_cache[word] = result
        return result

    _normalize_gb_cache[word] = word
    return word


# Cache for spelling variant detection
_spelling_variant_cache = {}

def detect_spelling_variant_with_cache(word, wordnet_cache):
    """
    Detect word dialect using comprehensive WordNet cache.
    Returns 'US', 'GB', 'CA', 'AU', or None if not in cache.
    """
    # Check memo cache first
    if word in _spelling_variant_cache:
        return _spelling_variant_cache[word]

    # Pre-compute lowercase to avoid multiple calls
    word_lower = word.lower()

    # Return None if no cache or word not in cache
    if not wordnet_cache or word_lower not in wordnet_cache:
        _spelling_variant_cache[word] = None
        return None

    # Get dialect from cache
    entry = wordnet_cache[word_lower]
    result = entry.get('dialect')
    _spelling_variant_cache[word] = result
    return result


def get_all_spelling_variants(word, dialect, wordnet_cache):
    """
    Get all spelling variants for a word in a specific dialect.

    Args:
        word: The word to look up
        dialect: Target dialect code ('GB' or 'US')
        wordnet_cache: Comprehensive WordNet cache

    Returns:
        List of variant spellings (excluding the input word), or empty list if none

    Example:
        get_all_spelling_variants('color', 'GB', cache) → ['colour']
        get_all_spelling_variants('honour', 'GB', cache) → ['honor'] (if multiple GB variants exist)
    """
    # Pre-compute lowercase to avoid multiple calls
    word_lower = word.lower()

    if not wordnet_cache or word_lower not in wordnet_cache:
        return []

    entry = wordnet_cache[word_lower]

    # Aggregate variants from all senses across all POS
    dialect_variants = []
    for pos_data in entry.get('pos_entries', {}).values():
        for sense in pos_data.get('sense_variants', []):
            sense_variants = sense.get('variants', {}).get(dialect, [])
            for v in sense_variants:
                if v not in dialect_variants:
                    dialect_variants.append(v)

    # Return variants that aren't the same as the input word
    return [v for v in dialect_variants if v != word_lower]


def normalize_readlex_ipa(ipa, dialect='gb'):
    """
    Normalize Readlex IPA transcription for display.

    Decodes ReadLex IPA shorthands into standard IPA, with dialect-aware
    rendering for GB (RP) vs US (GenAm).

    Args:
        ipa: IPA transcription string from Readlex
        dialect: 'gb' or 'us'

    Returns:
        Normalized IPA string suitable for display
    """
    if not ipa:
        return ipa

    # Remove affix boundary marker
    ipa = ipa.replace('+', '')

    # Dialect-aware TRAP-BATH split: Ɑː and Ɑ before Æ (Ɑː is more specific)
    if dialect == 'gb':
        ipa = ipa.replace('Ɑː', 'ɑː')
        ipa = ipa.replace('Ɑ', 'ɑː')
        ipa = ipa.replace('Æ', 'ɑː')
    else:
        ipa = ipa.replace('Ɑː', 'æ')
        ipa = ipa.replace('Ɑ', 'æ')
        ipa = ipa.replace('Æ', 'æ')

    # Dialect-aware linking R
    if dialect == 'gb':
        ipa = ipa.replace('R', '(r)')
    else:
        ipa = ipa.replace('R', 'r')

    # Simple lowercase mappings (not dialect-dependent)
    ipa = ipa.replace('Ə', 'ə')
    ipa = ipa.replace('I', 'ɪ')
    ipa = ipa.replace('L', 'l')

    return ipa


def extract_lemma_from_key(key):
    """Extract lemma from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if len(parts) >= 1:
        return parts[0].lower()
    return None


def extract_lemma_shavian_from_key(key):
    """Extract the canonical Shavian lemma form from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if len(parts) >= 3:
        return parts[2]  # The Shavian part
    return None


def is_proper_noun(pos_code):
    """
    Check if a POS tag indicates a proper noun.

    Args:
        pos_code: CLAWS POS tag (e.g., 'NP0', 'NN1', etc.)

    Returns:
        True if the POS tag indicates a proper noun
    """
    if not pos_code:
        return False

    # CLAWS tag NP0 = proper noun
    # Also check for combined tags like 'NP0+NN1'
    return 'NP0' in pos_code


def capitalize_if_proper_noun(text, pos_code):
    """
    Capitalize text if it's a proper noun.

    Args:
        text: The text to potentially capitalize (Latin/English)
        pos_code: CLAWS POS tag

    Returns:
        Capitalized text if proper noun, otherwise original text
    """
    if is_proper_noun(pos_code):
        return text.capitalize()
    return text


def add_namer_dot_if_proper_noun(text, pos_code):
    """
    Add namer dot (·) prefix if text is a proper noun.

    Args:
        text: The Shavian text to potentially prefix
        pos_code: CLAWS POS tag

    Returns:
        Text with namer dot prefix if proper noun, otherwise original text
    """
    namer_dot = '·'  # U+00B7 MIDDLE DOT

    if is_proper_noun(pos_code):
        if not text.startswith(namer_dot):
            return namer_dot + text
    return text


def form_index_pairs(form, index_key, plural_slot_open):
    """
    (value, twin) d:index pairs for one form: the base index value plus
    namer-dot / capitalization variants and derived noun inflections
    (see inflection_rules), each paired with its counterpart-script twin.
    """
    latin = form['latn']
    shaw = form['shaw']
    pos = form['pos']
    if not latin or not shaw:
        raise ValueError(
            f"form lacks a counterpart script for d:twin: "
            f"latn={latin!r} pos={pos!r}"
        )

    pairs = []
    if index_key == 'shaw':
        # Bare and namer-dotted stems both seed indices so the entry is
        # findable from either spelling convention; the Latin twin is the
        # stored Latin either way.
        stems = [shaw]
        dotted = add_namer_dot_if_proper_noun(shaw, pos)
        if dotted != shaw:
            stems.append(dotted)
        for stem in stems:
            pairs.append((stem, latin))
            for derived_latin, derived_shaw in derive_noun_index_pairs(
                    latin, stem, pos, plural_slot_open):
                pairs.append((derived_shaw, derived_latin))
    else:
        # Lowercase plus capitalized for proper nouns; the Shavian twin is
        # the same either way (capitalization is a Latin-only marker).
        # Derivation uses the Shavian as a phonemic oracle for the sibilant
        # decision, so 'box' (𐑚𐑪𐑒𐑕) → 'boxes' lands correctly.
        value = latin.lower()
        pairs.append((value, shaw))
        if is_proper_noun(pos):
            pairs.append((value.capitalize(), shaw))
        for derived_latin, derived_shaw in derive_noun_index_pairs(
                value, shaw, pos, plural_slot_open):
            pairs.append((derived_latin, derived_shaw))
            if is_proper_noun(pos):
                pairs.append((derived_latin.capitalize(), derived_shaw))
    return pairs


def process_readlex_with_lemmas(readlex_data):
    """
    Process readlex data to include lemma information.
    Returns: dict mapping readlex keys to (lemma, canonical_shavian, entries) tuples
    """
    print("Processing readlex with lemma information...")
    processed = {}

    for key, entries in readlex_data.items():
        # Supplement entries are single dicts; wrap them in a list
        if isinstance(entries, dict):
            entries = [entries]

        # Extract lemma from key
        lemma = extract_lemma_from_key(key)
        if not lemma and entries:
            # Fallback to first entry's Latn field
            lemma = entries[0]['Latn'].lower()

        # Extract canonical Shavian from key (the lemma form)
        canonical_shavian = extract_lemma_shavian_from_key(key)
        if not canonical_shavian and entries:
            # Fallback to first entry's Shaw field
            canonical_shavian = entries[0]['Shaw']

        processed[key] = {
            'lemma': lemma,
            'canonical_shavian': canonical_shavian,
            'entries': entries
        }

    print(f"Processed {len(processed)} lemma groups")
    return processed


def variant_to_label(var_code):
    """Convert a var code to its user-facing presentation dialect tag (GB / US /
    AU / …). Delegates to the shared dialect_display model so the dictionaries,
    spell-checker and any other product label a var identically."""
    return var_label(var_code)


def form_variant_label(form, lemma_has_rrp):
    """The user-facing dialect/variation label for one form, or "" when the form
    needs no label. Combines the var's presentation tag (GB / US / AU / …) with
    its variations (mergers / variant flag), and applies the owner's RSSB rule:
    an RSSB form is presented as a British variant (label "GB variant") when an
    RRP form of the same word exists, but as THE British form ("GB") when it is
    the word's only British attestation.
    """
    var = form.get('var', '')
    role = rssb_role(var, lemma_has_rrp)
    if role == 'variant':
        base = var_label(var) + ' variant'
    elif role == 'sole':
        base = var_label(var)
    else:
        base = var_label(var)

    extra = variations_label(form.get('mergers'), form.get('variant'))
    if base and extra:
        return f'{base}, {extra}'
    return base or extra


def build_shavian_lookup(readlex_data):
    """
    Build a lookup table for English → Shavian translations.
    Returns dict mapping lowercase English words to their Shavian spellings.
    """
    lookup = {}
    for key, data in readlex_data.items():
        for entry in data['entries']:
            latn = entry['Latn'].lower()
            shaw = entry['Shaw']
            # Use first occurrence (usually the most common variant)
            if latn not in lookup:
                lookup[latn] = shaw
    return lookup


def translate_to_shavian(text, shavian_lookup):
    """
    Translate English text to Shavian using lookup table.
    Falls back to original text if translation not found.
    """
    if not text:
        return text

    # Try direct lookup
    text_lower = text.lower()
    if text_lower in shavian_lookup:
        return shavian_lookup[text_lower]

    # For phrases like "plural of", translate word by word
    words = text.split()
    translated_words = []
    for word in words:
        word_lower = word.lower()
        if word_lower in shavian_lookup:
            translated_words.append(shavian_lookup[word_lower])
        else:
            # Keep original word if not found (e.g., lemma references)
            translated_words.append(word)

    return ' '.join(translated_words) if translated_words else text


def get_irregular_forms(lemma, wordnet_cache):
    """
    Extract irregular forms for a lemma from the comprehensive cache.

    Args:
        lemma: The lemma to look up (normalized to lowercase)
        wordnet_cache: The comprehensive WordNet cache

    Returns:
        Dict mapping POS to list of irregular forms, e.g., {'v': ['woke', 'woken'], 'a': ['better', 'best']}
    """
    if not wordnet_cache or lemma.lower() not in wordnet_cache:
        return {}

    entry = wordnet_cache[lemma.lower()]
    irregular_forms = {}

    for pos, pos_data in entry.get('pos_entries', {}).items():
        forms = pos_data.get('forms', [])
        if forms:
            irregular_forms[pos] = forms

    return irregular_forms


def is_foreign_dialect_lemma(lemma, synset_id, home_dialect, wordnet_cache):
    """
    Check if a lemma should be excluded because it belongs to a foreign dialect.

    For example, in a GB dictionary, "color" should be excluded if "colour" exists
    as the GB variant in the same synset.

    Args:
        lemma: The word to check
        synset_id: The synset ID
        home_dialect: 'US' or 'GB'
        wordnet_cache: WordNet comprehensive cache

    Returns:
        True if this lemma should be filtered out (it's foreign), False otherwise
    """
    if not wordnet_cache or not synset_id:
        return False

    lemma_lower = lemma.lower()

    # Check if this lemma exists in the cache
    if lemma_lower not in wordnet_cache:
        return False

    entry = wordnet_cache[lemma_lower]

    # Look through all senses to find this synset
    for pos_data in entry.get('pos_entries', {}).values():
        for sense in pos_data.get('sense_variants', []):
            if sense.get('synset') == synset_id:
                # Found the sense - check variants
                variants = sense.get('variants', {})

                # If this word is marked as a foreign dialect variant, exclude it
                # Check if there's a home-dialect variant available
                if home_dialect in variants:
                    home_variants = variants[home_dialect]
                    # If the lemma is NOT in the home dialect variants, it's foreign
                    if lemma_lower not in home_variants:
                        return True

    return False


def get_synsets_from_cache(lemma, pos_filter, wordnet_cache):
    """
    Extract synset IDs for a lemma with a specific POS from the comprehensive cache.

    Args:
        lemma: The lemma to look up (normalized to lowercase)
        pos_filter: POS code to filter (e.g., 'n', 'v', 'a', 'r')
        wordnet_cache: The comprehensive WordNet cache

    Returns:
        List of synset IDs for this lemma+POS, e.g., ['07582704-n', '04963771-n']
    """
    if not wordnet_cache or lemma.lower() not in wordnet_cache:
        return []

    entry = wordnet_cache[lemma.lower()]
    synsets = []

    # Look for matching POS entry
    pos_data = entry.get('pos_entries', {}).get(pos_filter, {})

    # Extract synset IDs from sense_variants
    for sense in pos_data.get('sense_variants', []):
        synset_id = sense.get('synset')
        if synset_id:
            synsets.append(synset_id)

    return synsets


def pos_to_readable(pos_code):
    """Convert CLAWS POS tags to readable forms."""
    if '+' in pos_code:
        parts = pos_code.split('+')
        return ', '.join(pos_to_readable(p) for p in parts)

    pos_map = {
        'AJ0': 'adjective', 'AJC': 'adjective (comparative)', 'AJS': 'adjective (superlative)',
        'AT0': 'article',
        'AV0': 'adverb', 'AVP': 'adverb', 'AVQ': 'adverb',
        'CJC': 'conjunction', 'CJS': 'subordinating conjunction', 'CJT': 'conjunction',
        'CRD': 'cardinal number',
        'DPS': 'possessive (e.g., "my", "your")', 'DT0': 'determiner', 'DTQ': 'determiner',
        'EX0': 'existential',
        'ITJ': 'interjection',
        'NN0': 'noun', 'NN1': 'noun (singular)', 'NN2': 'noun (plural)',
        'NP0': 'proper noun',
        'ORD': 'ordinal number',
        'PNI': 'pronoun (indefinite)', 'PNP': 'pronoun (personal)', 'PNQ': 'pronoun', 'PNX': 'pronoun',
        'PRE': 'prefix', 'PRF': 'prefix', 'PRP': 'preposition',
        'TO0': 'infinitive marker',
        'UNC': '',
        'VBB': 'verb (base form of "be")', 'VBD': 'verb (past tense of "be")',
        'VBG': 'verb (present participle of "be")', 'VBI': 'verb (infinitive of "be")',
        'VBN': 'verb (past participle of "be")', 'VBZ': 'verb ("is")',
        'VDB': 'verb (base form of "do")', 'VDD': 'verb (past tense of "do")',
        'VDG': 'verb (present participle of "do")', 'VDI': 'verb (infinitive of "do")',
        'VDN': 'verb (past participle of "do")', 'VDZ': 'verb ("does")',
        'VHB': 'verb (base form of "have")', 'VHD': 'verb (past tense of "have")',
        'VHG': 'verb (present participle of "have")', 'VHI': 'verb (infinitive of "have")',
        'VHN': 'verb (past participle of "have")', 'VHZ': 'verb ("has")',
        'VM0': 'modal verb',
        'VVB': 'verb (base form)', 'VVD': 'verb (past tense)',
        'VVG': 'verb (present participle)', 'VVI': 'verb (infinitive)',
        'VVN': 'verb (past participle)', 'VVZ': 'verb (third person singular)',
        'XX0': 'negation',
        'ZZ0': 'letter of the alphabet',
        'POS': 'possessive',
    }
    return pos_map.get(pos_code, pos_code)


# Shavian translations for grammar terms that aren't single-word entries in the
# Latin→Shavian lookup. Used by translate_grammar_term().
GRAMMAR_TERM_SHAVIAN = {
    'past tense': '𐑐𐑭𐑕𐑑 𐑑𐑧𐑯𐑕',
    'present participle': '𐑐𐑮𐑧𐑟𐑩𐑯𐑑 𐑐𐑸𐑑𐑦𐑕𐑦𐑐𐑩𐑤',
    'past participle': '𐑐𐑭𐑕𐑑 𐑐𐑸𐑑𐑦𐑕𐑦𐑐𐑩𐑤',
    'third person singular': '𐑔𐑻𐑛 𐑐𐑻𐑕𐑩𐑯 𐑕𐑦𐑙𐑜𐑘𐑫𐑤𐑼',
    'plural': '𐑐𐑤𐑫𐑼𐑩𐑤',
    'comparative': '𐑒𐑩𐑥𐑐𐑨𐑮𐑩𐑑𐑦𐑝',
    'superlative': '𐑕𐑵𐑐𐑻𐑤𐑩𐑑𐑦𐑝',
}


def translate_grammar_term(term, shavian_lookup):
    """Translate a grammar-form label to Shavian.

    Tries the hard-coded GRAMMAR_TERM_SHAVIAN map first (handles multi-word
    terms like 'past tense' whose individual words may not translate cleanly),
    then falls back to the main lookup.
    """
    if not term:
        return term
    if term in GRAMMAR_TERM_SHAVIAN:
        return GRAMMAR_TERM_SHAVIAN[term]
    return translate_to_shavian(term, shavian_lookup)


def pos_to_form_label(pos_code):
    """POS-derived sub-label for a derived-form line.

    Returns only the grammatical specialisation (e.g. 'past tense', 'plural') —
    not the top-level part of speech, which is already shown in the definitions
    heading. Returns empty string for lemma-like tags (infinitive / base form /
    bare singular), since those add no information over the headword.
    """
    if not pos_code:
        return ''
    if '+' in pos_code:
        # Composite tag — pick the first meaningful sub-label
        for p in pos_code.split('+'):
            label = pos_to_form_label(p)
            if label:
                return label
        return ''

    form_map = {
        # Verbs — main verb
        'VVD': 'past tense',
        'VVG': 'present participle',
        'VVN': 'past participle',
        'VVZ': 'third person singular',
        # Nouns
        'NN2': 'plural',
        # Adjectives
        'AJC': 'comparative',
        'AJS': 'superlative',
    }
    return form_map.get(pos_code, '')


def wordnet_pos_to_label(pos_code):
    """Convert WordNet-style single-letter POS code to readable label."""
    pos_labels = {
        'v': 'verb',
        'n': 'noun',
        'a': 'adjective',
        'r': 'adverb',
        'p': 'preposition',
        'i': 'interjection',
        'c': 'conjunction',
    }
    return pos_labels.get(pos_code, pos_code)


def pos_to_grammatical_form(pos_code, lemma, lemma_ipa='', shavian_lookup=None):
    """Convert POS tag to grammatical form description (e.g., 'plural of choose /tʃuːz/')."""
    # Build lemma reference with IPA if available
    lemma_ref = lemma
    if lemma_ipa:
        lemma_ref = f'{lemma} <span class="ipa">/{escape(lemma_ipa)}/</span>'

    # Helper to translate if Shavian lookup is provided
    def t(text):
        return translate_to_shavian(text, shavian_lookup) if shavian_lookup else text

    # Verbs
    if pos_code == 'VVI':
        return t('infinitive')
    elif pos_code == 'VVB':
        return t('base form')
    elif pos_code == 'VVZ':
        return f'{t("third person singular of")} {lemma_ref}'
    elif pos_code == 'VVD':
        return f'{t("past tense of")} {lemma_ref}'
    elif pos_code == 'VVN':
        return f'{t("past participle of")} {lemma_ref}'
    elif pos_code == 'VVG':
        return f'{t("present participle of")} {lemma_ref}'
    # Be verb
    elif pos_code in ('VBB', 'VBD', 'VBG', 'VBI', 'VBN', 'VBZ'):
        return f'{t("form of")} {t("be")}'
    # Do verb
    elif pos_code in ('VDB', 'VDD', 'VDG', 'VDI', 'VDN', 'VDZ'):
        return f'{t("form of")} {t("do")}'
    # Have verb
    elif pos_code in ('VHB', 'VHD', 'VHG', 'VHI', 'VHN', 'VHZ'):
        return f'{t("form of")} {t("have")}'
    # Nouns
    elif pos_code == 'NN1':
        return t('singular')
    elif pos_code == 'NN2':
        return f'{t("plural of")} {lemma_ref}'
    # Adjectives
    elif pos_code == 'AJ0':
        return t('base form')
    elif pos_code == 'AJC':
        return f'{t("comparative of")} {lemma_ref}'
    elif pos_code == 'AJS':
        return f'{t("superlative of")} {lemma_ref}'
    # Default: return empty string (no label)
    else:
        return ''


def format_word_form(main_text, ipa, var_code, show_variants, indent=False):
    """
    Format a word form with IPA (no grammatical labels).

    Args:
        main_text: The word to display (Latin, Shavian, or None for IPA-only)
        ipa: IPA transcription
        var_code: Variant code (RRP, GA, AU, etc.)
        show_variants: Whether to show variant labels
        indent: Whether to indent this form (for derived forms)

    Returns:
        HTML string for the word form
    """
    # Build the form display: "word /ipa/" or just "/ipa/"
    parts = []
    if main_text:
        parts.append(escape(main_text))
    if ipa:
        parts.append(f' <span class="ipa">/{escape(ipa)}/</span>')
    if show_variants and var_code:
        var_label = variant_to_label(var_code)
        parts.append(f' <span class="variant">({escape(var_label)})</span>')

    form_text = ''.join(parts)

    if indent:
        return f'      <div class="derived-form">{form_text}</div>\n'
    else:
        return f'      <div class="lemma-form">{form_text}</div>\n'


def group_definitions_by_pos(definitions):
    """
    Group definitions by part of speech.
    Returns list of (pos, definitions) tuples, preserving order.
    """
    from collections import OrderedDict
    pos_groups = OrderedDict()

    for def_data in definitions:
        pos = def_data['pos']
        if pos not in pos_groups:
            pos_groups[pos] = []
        pos_groups[pos].append(def_data)

    return list(pos_groups.items())


def create_xml_header(dict_name, from_lang, to_lang):
    """Create XML header."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<d:dictionary xmlns="http://www.w3.org/1999/xhtml" xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rdf">
<!-- {dict_name}: {from_lang} to {to_lang} -->
'''


def create_front_matter():
    """Create front matter entry with dictionary description."""
    # Load description from HTML snippet file
    description_path = Path(__file__).parent / 'dictionary-description.html'
    try:
        with open(description_path, 'r', encoding='utf-8') as f:
            description_html = f.read().strip()
    except FileNotFoundError:
        description_html = '<p>Shavian dictionary for macOS.</p>'

    return f'''  <d:entry id="front_back_matter" d:title="About This Dictionary">
    <h1>About This Dictionary</h1>
    {description_html}
  </d:entry>

'''


def create_xml_footer():
    """Create XML footer."""
    return '</d:dictionary>\n'


def generate_dictionary(readlex_data, definitions, output_path, dict_type, dialect='gb', wordnet_cache=None):
    """
    Generate a dictionary with unified structure.

    Args:
        readlex_data: Processed readlex data with lemma information
        definitions: WordNet definitions or Shavian cache
        output_path: Output XML file path
        dict_type: 'shaw-eng', 'eng-shaw', or 'shaw-shaw'
        dialect: 'gb' or 'us' (for preferred variant)
        wordnet_cache: Comprehensive WordNet cache (required for dialect detection)
    """
    # Initialize hyphenation session for Shavian dictionaries
    shyphenate_session = None
    # Configuration based on dictionary type
    config = {
        'shaw-eng': {
            'name': 'Shavian–English',
            'from_lang': 'Shavian',
            'to_lang': 'English',
            'index_key': 'shaw',        # Index by Shavian
            'display_text': 'latn',      # Display English text
            'translate_labels': False,   # Don't translate labels
            'use_shavian_cache': False,  # Read English gloss from Latin source
            'msg': 'Generating Shavian → English dictionary...'
        },
        'eng-shaw': {
            'name': 'English–Shavian',
            'from_lang': 'English',
            'to_lang': 'Shavian',
            'index_key': 'latn',         # Index by English
            'display_text': 'shaw',      # Display Shavian text
            'translate_labels': True,    # Translate labels to Shavian
            'use_shavian_cache': True,   # Use Shavian cache
            'msg': f'Generating English → Shavian dictionary ({dialect.upper()})...'
        },
        'shaw-shaw': {
            'name': 'Shavian',
            'from_lang': 'Shavian',
            'to_lang': 'Shavian',
            'index_key': 'shaw',         # Index by Shavian
            'display_text': None,        # No translation, just IPA
            'translate_labels': True,    # Translate labels to Shavian
            'use_shavian_cache': True,   # Use Shavian cache
            'msg': f'Generating Shavian → Shavian dictionary ({dialect.upper()})...'
        }
    }[dict_type]

    print(config['msg'])

    # Build Shavian lookup if needed
    shavian_lookup = build_shavian_lookup(readlex_data) if config['translate_labels'] else None

    # Determine preferred variant
    preferred_var = 'RRP' if dialect == 'gb' else 'GenAm'

    # Process each readlex key as a separate entry
    # Each readlex key represents a distinct word sense (lemma + POS + canonical pronunciation)
    readlex_entries = {}

    for key, data in readlex_data.items():
        lemma = data['lemma']
        canonical_shavian = data['canonical_shavian']

        # Get definitions using (lemma, synset_id) key for Shavian cache
        # The transliteration cache is keyed by "lemma|synset_id" strings
        if config['use_shavian_cache']:
            # First, determine POS to get synset
            key_pos_set = set()
            for entry in data['entries']:
                pos_code = entry.get('pos', '')
                if pos_code.startswith('V'):
                    key_pos_set.add('v')
                elif pos_code.startswith('N') and not is_proper_noun(pos_code):
                    key_pos_set.add('n')
                elif pos_code.startswith('AJ'):
                    key_pos_set.add('a')
                elif pos_code.startswith('AV'):
                    key_pos_set.add('r')

            # Get synsets for this lemma/POS
            synsets = []
            if wordnet_cache and key_pos_set:
                first_pos = sorted(key_pos_set)[0]
                synsets = get_synsets_from_cache(lemma, first_pos, wordnet_cache)

            # Look up definitions using (lemma, synset_id) key for ALL synsets
            lemma_defs = []
            if synsets:
                for synset_id in synsets:
                    cache_key = f"{lemma}|{synset_id}"
                    trans_def = definitions.get(cache_key)
                    if trans_def:
                        lemma_defs.append({
                            'definition': trans_def['transliterated_definition'],
                            'pos': trans_def['transliterated_pos'] if dict_type in ('shaw-shaw', 'eng-shaw') else trans_def['pos'],
                            'examples': trans_def['transliterated_examples']
                        })
        else:
            # Shavian → English: read the ENGLISH gloss from the `lemma|synset`-keyed
            # Latin definitions source (`definitions`), joined by the SAME synset key
            # the Shavian branch uses. This is the source-of-truth split off from the
            # merged corpus — one gloss per synset, so no POS-filtering is needed.
            key_pos_set = set()
            for entry in data['entries']:
                pos_code = entry.get('pos', '')
                if pos_code.startswith('V'):
                    key_pos_set.add('v')
                elif pos_code.startswith('N') and not is_proper_noun(pos_code):
                    key_pos_set.add('n')
                elif pos_code.startswith('AJ'):
                    key_pos_set.add('a')
                elif pos_code.startswith('AV'):
                    key_pos_set.add('r')

            synsets = []
            if wordnet_cache and key_pos_set:
                first_pos = sorted(key_pos_set)[0]
                synsets = get_synsets_from_cache(lemma, first_pos, wordnet_cache)

            lemma_defs = []
            for synset_id in synsets:
                latin_def = definitions.get(f"{lemma}|{synset_id}")
                if latin_def:
                    lemma_defs.append({
                        'definition': latin_def['definition'],
                        'pos': latin_def['pos'],
                        'examples': latin_def.get('examples', []),
                    })

        # Both branches are synset-specific already — no POS filtering needed.
        filtered_defs = lemma_defs

        # Process each form in this readlex key
        forms = []
        for entry in data['entries']:
            shaw = entry['Shaw']
            latn = entry['Latn']
            pos = entry.get('pos', '')
            ipa = normalize_readlex_ipa(entry.get('ipa', ''), dialect=dialect)
            var = entry.get('var', '')

            # Detect spelling variant using comprehensive cache
            detected_variant = detect_spelling_variant_with_cache(latn, wordnet_cache)

            # A form is the "lemma form" if its Shavian matches the canonical one from the key
            is_lemma_form = (shaw == canonical_shavian)

            # Add form
            form_info = {
                'shaw': shaw,
                'latn': latn,
                'pos': pos,
                'ipa': ipa,
                'var': var,
                'mergers': entry.get('mergers', []),
                'variant': entry.get('variant', False),
                'spelling_variant': detected_variant,
                'is_lemma': is_lemma_form,
                'is_preferred': (var == preferred_var)
            }
            forms.append(form_info)

        # Store this readlex key as an entry
        readlex_entries[key] = {
            'forms': forms,
            'definitions': filtered_defs,
            'canonical_shavian': canonical_shavian
        }

    # Merge entries with same meaning and POS
    # Signature is based on (lemma, synset) to group morphological variants
    # while keeping separate:
    # - Different lemmas (color vs colour, color vs tinge)
    # - Different senses (color noun vs color verb)
    entry_signatures = {}
    entry_pos = {}  # Store POS tuple for each entry

    # Debug: track signature creation for specific words and Shavian forms
    debug_words = {'dew', 'dews', 'due', 'dues', 'color', 'colour', 'colors', 'colours', 'tinge', 'tinges',
                   'coloring', 'colouring', 'colorings', 'colourings', 'colored', 'coloured'}
    debug_shavian = {'𐑛𐑿', '𐑛𐑵', '𐑒𐑳𐑤𐑼', '𐑛𐑵'}

    for key, data in readlex_entries.items():
        lemma = data.get('lemma', key.split('_')[0])

        # Determine POS for this entry
        # Map CLAWS POS codes to single-letter codes
        pos_set = set()
        for form in data['forms']:
            pos_code = form.get('pos', '')
            if pos_code.startswith('V'):
                pos_set.add('v')  # verb
            elif pos_code.startswith('N') and not is_proper_noun(pos_code):
                pos_set.add('n')  # noun
            elif pos_code.startswith('AJ'):
                pos_set.add('a')  # adjective
            elif pos_code.startswith('AV'):
                pos_set.add('r')  # adverb
            elif pos_code.startswith('PRP'):
                pos_set.add('p')  # preposition
            elif pos_code.startswith('ITJ'):
                pos_set.add('i')  # interjection
            elif pos_code.startswith('CJ'):
                pos_set.add('c')  # conjunction
            # Note: Other POS codes (pronouns, determiners, numbers, etc.) are not mapped
            # and will result in empty pos_set, which we handle below
        pos_tuple = tuple(sorted(pos_set))
        entry_pos[key] = pos_tuple  # Store for later use

        # Create signature based on synset ID (if available) or readlex key (fallback)
        # Synset ID uniquely identifies a word sense and groups:
        # - Spelling variants: color/colour (same synset)
        # - Different words: dew/due (different synsets even with same Shavian)
        # - Keeps synonyms separate: color/hue (actually they're in same synset, so they WILL merge - see below)
        #
        # For entries without WordNet data (pronouns, determiners), use readlex key

        synsets = []
        if wordnet_cache and pos_tuple:
            # Get first POS from tuple for lookup
            first_pos = pos_tuple[0] if pos_tuple else None
            if first_pos:
                synsets = get_synsets_from_cache(lemma, first_pos, wordnet_cache)

        # Check for foreign dialect lemmas
        # E.g., in GB dictionary, "color" is foreign if "colour" exists in the synset
        home_dialect = 'GB' if preferred_var == 'RRP' else 'US'
        is_foreign = synsets and is_foreign_dialect_lemma(lemma, synsets[0], home_dialect, wordnet_cache)

        if is_foreign:
            # Mark as foreign - we'll add index entries but not full definitions
            if lemma in debug_words:
                print(f"DEBUG FOREIGN: {key} (foreign dialect - will add as index only)")
            entry_signatures[key] = ('foreign', lemma, synsets[0])
        elif synsets:
            # Use (lemma, synset) as signature to group:
            # - Morphological variants: color/colors/colored (same lemma "color", same synset)
            # - Keep separate: color vs colour (different lemmas, even if same synset)
            # - Keep separate: color vs tinge (different lemmas, even if same synset as synonyms)
            # - Keep separate: color noun vs color verb (different synsets)
            entry_signatures[key] = ('synset', lemma, synsets[0])
        else:
            # No WordNet data - use readlex key to keep separate
            entry_signatures[key] = ('readlex', key)

        # Debug output for specific words or Shavian forms
        if lemma in debug_words or data['canonical_shavian'] in debug_shavian:
            print(f"DEBUG: {key} -> lemma={lemma}, pos={pos_tuple}, shaw={data['canonical_shavian']}, signature={entry_signatures[key]}")

    # Now merge entries with the same signature
    # When merging, prefer the normalized (US) spelling for the canonical entry
    merged_entries = {}
    variant_map = {}  # Maps original keys to merged keys
    signature_to_key = {}  # Maps signatures to the canonical key with that signature
    foreign_to_home = {}  # Maps foreign dialect entries to their home dialect equivalent

    # Debug: count merges
    merge_count = 0

    for key, data in readlex_entries.items():
        # Skip entries that were filtered out (foreign dialect)
        if key not in entry_signatures:
            continue

        entry_signature = entry_signatures[key]
        lemma = data.get('lemma', key.split('_')[0])

        # Handle foreign dialect entries - track them but don't create full entries
        if entry_signature[0] == 'foreign':
            # Find the home dialect entry with same synset
            # Signature is ('foreign', lemma, synset_id)
            synset_id = entry_signature[2]
            home_signature = None

            # Look for a home dialect entry with this synset
            for other_key, other_sig in entry_signatures.items():
                if other_sig[0] == 'synset' and other_sig[2] == synset_id:
                    # Found a home dialect entry with same synset
                    home_signature = other_sig
                    break

            if home_signature and home_signature in signature_to_key:
                home_key = signature_to_key[home_signature]
                foreign_to_home[key] = home_key
                if lemma in debug_words:
                    print(f"DEBUG FOREIGN MAP: {key} -> {home_key}")
            continue

        # Check if we already have an entry with this signature
        if entry_signature in signature_to_key:
            # Merge with existing entry
            existing_key = signature_to_key[entry_signature]
            merge_count += 1

            # Debug output for specific words
            if lemma in debug_words or existing_key.split('_')[0] in debug_words:
                print(f"DEBUG MERGE: {key} merged into {existing_key} (signature={entry_signature})")

            # Keep existing as canonical, just add forms
            merged_entries[existing_key]['forms'].extend(data['forms'])
            variant_map[key] = existing_key
        else:
            # This is a new unique entry
            merged_entries[key] = data
            variant_map[key] = key
            signature_to_key[entry_signature] = key

    print(f"DEBUG: Merged {merge_count} entries, resulted in {len(merged_entries)} unique entries")

    # Group merged entries by their index word for display
    # For example, looking up 𐑮𐑧𐑛 should show both "read" (verb) and "red" (color)
    index_to_entries = defaultdict(list)
    for key, data in merged_entries.items():
        # Skip entries that were merged into other entries
        # variant_map[key] points to the canonical key for this entry
        if variant_map.get(key) != key:
            continue

        if config['index_key'] == 'shaw':
            # For Shavian dictionaries, only create entries for LEMMA forms
            # Inflected forms (dews, dues) should not get separate entries
            # They will be searchable via d:index tags within the lemma entry
            lemma_forms = [f for f in data['forms'] if f['is_lemma']]
            lemma_shavian_forms = set(f['shaw'] for f in lemma_forms)

            # Create an entry for each unique lemma Shavian form
            # This handles homophones like "dew" and "due" which both have lemma form 𐑛𐑿
            for shaw in lemma_shavian_forms:
                if key not in index_to_entries[shaw]:
                    index_to_entries[shaw].append(key)
        else:
            # For Latin dictionaries, use the first lemma form
            lemma_forms = [f for f in data['forms'] if f['is_lemma']]
            if lemma_forms:
                index_word = lemma_forms[0]['latn'].lower()
                if key not in index_to_entries[index_word]:
                    index_to_entries[index_word].append(key)

    # Initialize hyphenation session if needed and pre-hyphenate all definitions
    if config.get('use_shavian_cache', False):
        shyphenate_session = ShyphenateSession()
        if shyphenate_session.available:
            print("Pre-collecting definition texts for batch hyphenation...")
            for data in merged_entries.values():
                for def_data in data.get('definitions', [])[:20]:
                    shyphenate_session.enqueue(def_data['definition'])
            shyphenate_session._flush_batch()
            print(f"Pre-hyphenated {len(shyphenate_session._cache)} unique definition texts")

    # Write XML
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(create_xml_header(config['name'], config['from_lang'], config['to_lang']))
            f.write(create_front_matter())
            f.flush()

            written_entries = 0

            # Write entries - each readlex entry is a separate word sense
            # Sort index words, stripping namer dots so ·𐑛𐑵 sorts with 𐑛𐑵
            def index_sort_key(word):
                return word.lstrip('·')

            for index_word in sorted(index_to_entries.keys(), key=index_sort_key):
                entry_keys = index_to_entries[index_word]

                # Sort entries: direct matches first, then by lemma, then by POS
                def sort_entries(entry_key):
                    entry_data = merged_entries[entry_key]

                    # Check if this is a direct match (index_word matches ANY form - lemma or derived)
                    is_direct_match = False
                    lemma_text = None
                    for form in entry_data['forms']:
                        form_index = form['shaw'] if config['index_key'] == 'shaw' else form['latn'].lower()
                        if form_index == index_word:
                            is_direct_match = True
                        if lemma_text is None and form['is_lemma']:
                            lemma_text = form['latn'].lower()

                    # Get POS for sorting
                    pos = entry_pos.get(entry_key, ())
                    pos_str = ''.join(sorted(pos)) if pos else 'zzz'  # Put entries without POS at end

                    # Sort key: (not is_direct_match, lemma, pos)
                    # not is_direct_match: False (direct) comes before True (indirect)
                    return (not is_direct_match, lemma_text or '', pos_str)

                entry_keys = sorted(entry_keys, key=sort_entries)

                # Debug: check for dew entries
                if index_word in debug_shavian:
                    print(f"DEBUG INDEX: {index_word} has {len(entry_keys)} entries:")
                    for ek in entry_keys:
                        sort_key = sort_entries(ek)
                        ed = merged_entries[ek]
                        lemma_form = next((f['latn'] for f in ed['forms'] if f['is_lemma']), 'unknown')
                        print(f"  {ek}: sort_key={sort_key}, lemma={lemma_form}")

                # Write separate entry for each merged entry (each word sense)
                for entry_idx, entry_key in enumerate(entry_keys):
                    entry_data = merged_entries[entry_key]
                    lemma_data = {'forms': entry_data['forms'], 'definitions': entry_data['definitions']}

                    # Collect all index forms for d:index tags: this lemma's
                    # own forms plus foreign-dialect cross-refs (e.g. in the
                    # GB dictionary, "color" indices point to the "colour"
                    # entry). Each index value maps to its counterpart-script
                    # d:twin.
                    indexed_forms = list(lemma_data['forms'])
                    for foreign_key, home_key in foreign_to_home.items():
                        if home_key == entry_key:
                            indexed_forms.extend(readlex_entries[foreign_key]['forms'])

                    # Explicit-slot gate: derive a default plural only when no
                    # explicit plural record (NN2) occupies this lemma's slot
                    # and the lemma is not invariant (NN0 closes the slot) —
                    # dog has a real "dogs" record, sheep takes no plural.
                    plural_slot_open = not any(
                        form['pos'] in ('NN0', 'NN2') for form in indexed_forms
                    )

                    # First twin wins on duplicate index values (homographic
                    # forms within one entry); form order is deterministic.
                    lemma_forms_indices = {}
                    for form in indexed_forms:
                        for value, twin in form_index_pairs(
                                form, config['index_key'], plural_slot_open):
                            lemma_forms_indices.setdefault(value, twin)

                    # Write entry for this readlex key
                    entry_id = f"{config['index_key']}_{index_word}_{entry_idx}"
                    f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(index_word)}">\n')

                    # Add d:index for each form in this lemma, with its
                    # counterpart-script transliteration as d:twin
                    for value in sorted(lemma_forms_indices):
                        twin = lemma_forms_indices[value]
                        f.write(f'    <d:index d:value="{escape(value)}" d:twin="{escape(twin)}"/>\n')

                    # Apply proper noun formatting to h1 title based on first lemma form's POS
                    lemma_forms = [f for f in lemma_data['forms'] if f['is_lemma']]
                    first_pos = lemma_forms[0]['pos'] if lemma_forms else ''

                    # Determine which text to display in h1 based on dictionary type
                    # Use the canonical form from the readlex entry
                    if config['index_key'] == 'shaw':
                        # For Shavian dictionaries, use the canonical Shavian from readlex key
                        h1_text = entry_data['canonical_shavian']
                        h1_text = add_namer_dot_if_proper_noun(h1_text, first_pos)
                    else:
                        # For Latin dictionaries, use the first lemma form's Latin text
                        if lemma_forms:
                            h1_text = lemma_forms[0]['latn']
                            h1_text = capitalize_if_proper_noun(h1_text, first_pos)
                        else:
                            h1_text = index_word

                    f.write(f'    <h1>{escape(h1_text)}</h1>\n')

                    # Check if we need to show variants
                    unique_variants = set(form['var'] for form in lemma_data['forms'] if form['var'])
                    show_variants = len(unique_variants) > 1

                    # Whether ANY form of this lemma carries the British base var
                    # (RRP). Drives the owner's rule for presenting RSSB: an RSSB
                    # form is "a variant of British" when an RRP form for the word
                    # exists, but stands as THE British form when it is the only
                    # British attestation (see rssb_role).
                    lemma_has_rrp = any(form['var'] == BRITISH_BASE_VAR
                                        for form in lemma_data['forms'])

                    # Determine home dialect spelling for this dictionary
                    home_dialect = 'GB' if preferred_var == 'RRP' else 'US'

                    # Group forms by normalized English word to find all variants together
                    # This groups spelling variants (colour/color) AND pronunciation variants
                    # (due /djuː/ GB vs /duː/ US) under one word
                    word_groups = defaultdict(list)
                    is_eng_to_shaw = (config['index_key'] == 'latn')

                    for form in lemma_data['forms']:
                        # ALL dictionaries: Group by normalized English spelling
                        # This merges colour/color and also groups due /djuː/ with due /duː/
                        base_word = normalize_to_us_with_cache(form['latn'], wordnet_cache)
                        key = (base_word, form['is_lemma'])
                        word_groups[key].append(form)

                    # Display forms for this lemma
                    f.write('    <div class="forms">\n')

                    # Sort: lemmas first, then derived forms
                    def sort_key(k):
                        base_word, is_lemma = k
                        return (not is_lemma, base_word)

                    sorted_words = sorted(word_groups.keys(), key=sort_key)

                    for word_key in sorted_words:
                        base_word, is_lemma = word_key
                        forms = word_groups[word_key]

                        # Separate forms by variant (home vs alt)
                        # For spelling variants (color/colour), use spelling_variant field
                        # For pronunciation variants (due /djuː/ vs /duː/), use var field
                        home_forms = []
                        alt_forms = []

                        for form in forms:
                            # Check spelling variant first (US/GB spelling like color/colour)
                            spelling_var = form.get('spelling_variant')
                            if spelling_var:
                                # Use spelling variant to determine home vs alt
                                is_home = (spelling_var == home_dialect)
                            else:
                                # Fall back to pronunciation variant (var field):
                                # a form is HOME when its var belongs to this
                                # dictionary's accent family. British family (RRP,
                                # RSSB, the southern-hemisphere accents, legacy SSB)
                                # is home in the GB dict; American family (GenAm,
                                # Canadian, Irish) is home in the US dict. trap-bath
                                # is a `mergers` flag on an RRP record, so those
                                # forms are British-home (shown as "also").
                                var = form.get('var')
                                if dialect == 'us':
                                    is_home = is_american(var) or not var
                                else:
                                    is_home = is_british(var)

                            if is_home:
                                home_forms.append(form)
                            else:
                                alt_forms.append(form)

                        # Determine style
                        div_class = 'lemma-form' if is_lemma else 'derived-form'
                        f.write(f'      <div class="{div_class}">')

                        alt_dialect = 'US' if home_dialect == 'GB' else 'GB'

                        # Determine which field to display based on dictionary type
                        # shaw->eng: display English (latn)
                        # eng->shaw and shaw->shaw: display Shavian (shaw)
                        display_key = 'shaw' if is_eng_to_shaw or config['display_text'] is None else 'latn'

                        # Get the home form to display
                        if home_forms:
                            home_form = home_forms[0]

                            # Apply proper noun formatting to displayed text
                            home_display_text = home_form[display_key]
                            if display_key == 'shaw':
                                home_display_text = add_namer_dot_if_proper_noun(home_display_text, home_form['pos'])
                            else:
                                home_display_text = capitalize_if_proper_noun(home_display_text, home_form['pos'])

                            # Display the main text
                            f.write(escape(home_display_text))
                            f.write(f' <span class="ipa">/{home_form["ipa"]}/</span>')

                            # Display grammatical form sub-label (e.g. "past tense",
                            # "plural"). Empty for lemma-like POS tags so the main
                            # headword isn't cluttered with "singular"/"infinitive".
                            form_label_text = pos_to_form_label(home_form.get('pos', ''))
                            if form_label_text:
                                if config['translate_labels']:
                                    form_label_text = translate_grammar_term(form_label_text, shavian_lookup)
                                f.write(f' <span class="form-label">{escape(form_label_text)}</span>')

                            # Look up alternate dialect spellings from WordNet cache
                            # E.g., in GB dict for "colour", find "color" from cache variants
                            lemma_latn = home_form.get('latn', '')
                            alt_spellings = []  # List of (spelling, dialect, ipa) tuples

                            if wordnet_cache and lemma_latn.lower() in wordnet_cache and is_lemma:
                                # Get the synset for this entry
                                entry_sig = entry_signatures.get(entry_key)
                                if entry_sig and entry_sig[0] == 'synset':
                                    synset_id = entry_sig[2]

                                    # Look up variants in the cache for this synset
                                    cache_entry = wordnet_cache[lemma_latn.lower()]
                                    for pos_data in cache_entry.get('pos_entries', {}).values():
                                        for sense in pos_data.get('sense_variants', []):
                                            if sense.get('synset') == synset_id:
                                                variants = sense.get('variants', {})
                                                # Check each dialect
                                                for dialect, variant_words in variants.items():
                                                    if dialect != home_dialect:
                                                        # This is a foreign dialect
                                                        for variant_word in variant_words:
                                                            if variant_word.lower() != lemma_latn.lower():
                                                                # Different spelling - try to find pronunciation from WordNet cache
                                                                variant_ipa = None
                                                                if variant_word.lower() in wordnet_cache:
                                                                    variant_cache = wordnet_cache[variant_word.lower()]
                                                                    # Look for this synset in the variant's cache entry
                                                                    for v_pos_data in variant_cache.get('pos_entries', {}).values():
                                                                        for v_sense in v_pos_data.get('sense_variants', []):
                                                                            if v_sense.get('synset') == synset_id:
                                                                                # Found the right sense - get pronunciation
                                                                                prons = v_sense.get('pronunciations', {})
                                                                                # Prefer the dialect-specific pronunciation
                                                                                variant_ipa = prons.get(dialect) or prons.get('default') or prons.get('US') or prons.get('GB')
                                                                                break
                                                                alt_spellings.append((variant_word, dialect, variant_ipa))

                            # Check for additional pronunciations in home_forms (e.g., due /djuː/ and /duː/)
                            for additional_form in home_forms[1:]:
                                if additional_form['ipa'] != home_form['ipa']:
                                    # Different pronunciation - show it with its friendly
                                    # dialect/variation label (broad-A merger, national
                                    # accent, RSSB-variant …). No distinguishing label →
                                    # a plain "also".
                                    variant_label = form_variant_label(additional_form, lemma_has_rrp)
                                    if variant_label:
                                        f.write(f' <span class="variant">({escape(home_display_text)}, {escape(variant_label)} /{additional_form["ipa"]}/)</span>')
                                    else:
                                        f.write(f' <span class="variant">(also /{additional_form["ipa"]}/)</span>')

                            # Display alternate spellings (only if actually different)
                            # For shaw-shaw dictionary, skip Latin alphabet variants
                            if alt_spellings and dict_type != 'shaw-shaw':
                                for alt_spelling, alt_dialect, alt_ipa in alt_spellings:
                                    # Only show if spelling is different OR pronunciation is different
                                    spelling_differs = alt_spelling.lower() != home_form.get('latn', '').lower()
                                    pronunciation_differs = alt_ipa and alt_ipa != home_form['ipa']

                                    if not spelling_differs and not pronunciation_differs:
                                        # Nothing different - skip this variant
                                        continue

                                    if pronunciation_differs:
                                        # Different pronunciation - show both spelling and IPA
                                        f.write(f' <span class="variant">({escape(alt_spelling)}, {alt_dialect} /{alt_ipa}/)</span>')
                                    elif spelling_differs:
                                        # Only spelling differs (same or no pronunciation)
                                        f.write(f' <span class="variant">({escape(alt_spelling)}, {alt_dialect})</span>')

                            # Check for additional spelling variants in the same dialect from the actual forms
                            # Only show variants that exist in THIS entry (not from cache lookup)
                            # e.g., if we have both "colour" and "colourise" in home_forms, show them
                            displayed_latn_normalized = normalize_to_us_with_cache(home_form.get('latn', ''), wordnet_cache)
                            additional_home_forms = []
                            for additional_form in home_forms[1:]:  # Skip the first one we already displayed
                                # Only include if it's a different word (not just different POS)
                                form_normalized = normalize_to_us_with_cache(additional_form.get('latn', ''), wordnet_cache)
                                if form_normalized != displayed_latn_normalized:
                                    additional_home_forms.append(additional_form['latn'])

                            if additional_home_forms:
                                variants_text = ', '.join(additional_home_forms)
                                f.write(f' <span class="variant">(also: {escape(variants_text)})</span>')

                            # Check for alternate forms (a form of the OTHER accent
                            # family, e.g. GenAm in the GB dictionary)
                            if alt_forms:
                                alt_form = alt_forms[0]

                                # Apply proper noun formatting to alternate form
                                alt_display_text = alt_form[display_key]
                                if display_key == 'shaw':
                                    alt_display_text = add_namer_dot_if_proper_noun(alt_display_text, alt_form['pos'])
                                else:
                                    alt_display_text = capitalize_if_proper_noun(alt_display_text, alt_form['pos'])

                                # The friendly accent/variation label for this alt form
                                # (General American, broad A, an RSSB variant …), falling
                                # back to the coarse home/alt dialect name.
                                alt_label = form_variant_label(alt_form, lemma_has_rrp) or alt_dialect

                                if home_form['ipa'] == alt_form['ipa']:
                                    # Same pronunciation - just show alternate spelling (colour vs color)
                                    f.write(f' <span class="variant">({escape(alt_display_text)}, {escape(alt_label)})</span>')
                                else:
                                    # Different pronunciation - show alternate with its IPA
                                    f.write(f' <span class="variant">({escape(alt_display_text)}, {escape(alt_label)} /{alt_form["ipa"]}/)</span>')

                        elif alt_forms:
                            # Only alt form available
                            alt_form = alt_forms[0]

                            # Apply proper noun formatting
                            alt_display_text = alt_form[display_key]
                            if display_key == 'shaw':
                                alt_display_text = add_namer_dot_if_proper_noun(alt_display_text, alt_form['pos'])
                            else:
                                alt_display_text = capitalize_if_proper_noun(alt_display_text, alt_form['pos'])

                            f.write(escape(alt_display_text))
                            f.write(f' <span class="ipa">/{alt_form["ipa"]}/</span>')

                            # Display grammatical form sub-label (see home-form branch above)
                            form_label_text = pos_to_form_label(alt_form.get('pos', ''))
                            if form_label_text:
                                if config['translate_labels']:
                                    form_label_text = translate_grammar_term(form_label_text, shavian_lookup)
                                f.write(f' <span class="form-label">{escape(form_label_text)}</span>')

                            only_alt_label = form_variant_label(alt_form, lemma_has_rrp) or alt_dialect
                            f.write(f' <span class="variant">({escape(only_alt_label)})</span>')

                        f.write('</div>\n')

                    f.write('    </div>\n')

                    # Irregular forms (if any)
                    # Get the first lemma form to determine which lemma to look up
                    if lemma_forms:
                        first_lemma_latn = lemma_forms[0]['latn']
                        irregular_forms = get_irregular_forms(first_lemma_latn, wordnet_cache)

                        if irregular_forms:
                            f.write('    <div class="irregular-forms">\n')
                            for pos, forms in irregular_forms.items():
                                # Map WordNet POS to readable forms
                                pos_label = POS_TO_ENGLISH.get(pos, pos)

                                # Translate forms list if needed
                                if config['translate_labels']:
                                    forms_display = ', '.join([translate_to_shavian(form, shavian_lookup) for form in forms])
                                    label_text = translate_to_shavian(f'Irregular {pos_label} forms', shavian_lookup)
                                else:
                                    forms_display = ', '.join(forms)
                                    label_text = f'Irregular {pos_label} forms'

                                f.write(f'      <p><i>{escape(label_text)}:</i> {escape(forms_display)}</p>\n')
                            f.write('    </div>\n')

                    # Definitions for this lemma
                    if lemma_data['definitions']:
                        pos_groups = group_definitions_by_pos(lemma_data['definitions'][:20])
                        f.write('    <div class="definitions">\n')
                        for pos, pos_defs in pos_groups:
                            # Convert single-letter POS code to readable label
                            pos_label = wordnet_pos_to_label(pos)
                            # Translate to Shavian if needed
                            if config['translate_labels']:
                                pos_label = translate_to_shavian(pos_label, shavian_lookup)

                            f.write(f'      <div class="pos-group">\n')
                            f.write(f'        <h3><i>{escape(pos_label)}</i></h3>\n')
                            f.write('        <ol class="definition-list">\n')
                            for i, def_data in enumerate(pos_defs[:5], 1):
                                definition_text = def_data["definition"]
                                # Hyphenate Shavian definitions using persistent session
                                if shyphenate_session:
                                    definition_text = shyphenate_session.hyphenate(definition_text)
                                f.write(f'          <li class="definition">{escape(definition_text)}</li>\n')
                            f.write('        </ol>\n')
                            f.write('      </div>\n')
                        f.write('    </div>\n')
                    else:
                        # No WordNet definitions - show POS from readlex with no defs message
                        readlex_pos_tuple = entry_pos.get(entry_key)

                        f.write('    <div class="definitions">\n')
                        if readlex_pos_tuple:
                            # Show each POS with no definitions message
                            for pos in readlex_pos_tuple:
                                pos_label = wordnet_pos_to_label(pos)
                                if config['translate_labels']:
                                    pos_label = translate_to_shavian(pos_label, shavian_lookup)
                                    no_defs_msg = '(𐑯𐑴 𐑛𐑧𐑓𐑦𐑯𐑦𐑖𐑩𐑯𐑟 𐑩𐑝𐑱𐑤𐑩𐑚𐑩𐑤)'
                                else:
                                    no_defs_msg = '(No definitions available)'

                                f.write(f'      <div class="pos-group">\n')
                                f.write(f'        <h3><i>{escape(pos_label)}</i></h3>\n')
                                f.write(f'        <p><i>{escape(no_defs_msg)}</i></p>\n')
                                f.write('      </div>\n')
                        else:
                            # Can't determine POS
                            if config['translate_labels']:
                                no_defs_msg = '(𐑯𐑴 𐑛𐑧𐑓𐑦𐑯𐑦𐑖𐑩𐑯𐑟 𐑩𐑝𐑱𐑤𐑩𐑚𐑩𐑤)'
                            else:
                                no_defs_msg = '(No definitions available)'
                            f.write(f'      <p><i>{escape(no_defs_msg)}</i></p>\n')
                        f.write('    </div>\n')

                    # Add separator between entries except for the last one
                    if entry_idx < len(entry_keys) - 1:
                        f.write('    <hr/>\n')

                    f.write('  </d:entry>\n')
                    written_entries += 1

                # Flush every 1000 entries
                if written_entries % 1000 == 0:
                    f.flush()

            f.write(create_xml_footer())
            f.flush()

        print(f"Generated {written_entries} entries → {output_path}")
    finally:
        # Close hyphenation session if it was created
        if shyphenate_session:
            shyphenate_session.close()


def main():
    """Main function."""
    # Parse --dict arguments
    dictionaries = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--dict' and i + 1 < len(sys.argv):
            dictionaries.append(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    # Parse dialect argument
    dialect = 'gb'  # default
    if '--dialect=us' in sys.argv or '--us' in sys.argv:
        dialect = 'us'
    elif '--dialect=gb' in sys.argv or '--gb' in sys.argv:
        dialect = 'gb'

    # Default to all dictionaries if none specified
    if not dictionaries:
        dictionaries = ['shavian-english', 'english-shavian', 'shavian-shavian']

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent
    readlex_path = project_dir / 'data/readlex.json'
    latin_defs_path = project_dir / f'data/definitions-latin-{dialect}.json'
    wordnet_cache_path = project_dir / 'data/wordnet-comprehensive.json'
    shavian_defs_path = project_dir / f'data/definitions-shavian-{dialect}.json'
    build_dir = project_dir / 'build'
    xml_dir = build_dir / 'dictionaries' / 'xml'

    shavian_english_path = xml_dir / f'shavian-english-{dialect}.xml'
    english_shavian_path = xml_dir / f'english-shavian-{dialect}.xml'
    shavian_shavian_path = xml_dir / f'shavian-shavian-{dialect}.xml'

    # Ensure directories exist
    xml_dir.mkdir(parents=True, exist_ok=True)

    # Load readlex data
    print("Loading readlex data...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_raw = json.load(f)
    print(f"Loaded {len(readlex_raw)} readlex entries")

    # Load the Latin definitions source (`lemma|synset`-keyed English glosses) for the
    # shavian-english dictionary. This is the source-of-truth split off from the merged
    # Shavian corpus (src/tools/split_definition_corpus.py).
    latin_defs = {}
    if latin_defs_path.exists():
        print(f"\nLoading {dialect.upper()} Latin definitions...")
        with open(latin_defs_path, 'r', encoding='utf-8') as f:
            latin_defs = json.load(f)
        print(f"Loaded definitions for {len(latin_defs)} senses")
    else:
        print(f"\nNote: Latin definitions not found at {latin_defs_path}")
        print("The shavian-english dictionary will have no glosses.")

    # Load comprehensive WordNet cache (required for dialect detection)
    wordnet_cache = {}
    if wordnet_cache_path.exists():
        print("\nLoading comprehensive WordNet cache...")
        with open(wordnet_cache_path, 'r', encoding='utf-8') as f:
            wordnet_cache = json.load(f)
        print(f"Loaded cache with {len(wordnet_cache)} lemmas")
    else:
        print(f"\nERROR: Comprehensive cache not found at {wordnet_cache_path}")
        print("Please run 'make wordnet-cache' first")
        sys.exit(1)
    print()

    # Load Shavian definition cache (if needed)
    shavian_def_cache = {}
    needs_shavian_cache = 'english-shavian' in dictionaries or 'shavian-shavian' in dictionaries
    if needs_shavian_cache:
        if not shavian_defs_path.exists():
            print(f"\nERROR: Shavian definition cache not found at {shavian_defs_path}")
            print("Please run: ./src/build_definition_caches.py")
            sys.exit(1)

        print("\nLoading Shavian definition cache...")
        with open(shavian_defs_path, 'r', encoding='utf-8') as f:
            shavian_def_cache = json.load(f)
        print(f"Loaded Shavian definitions for {len(shavian_def_cache)} lemmas")

    # Process readlex with lemma information
    readlex_data = process_readlex_with_lemmas(readlex_raw)

    print(f"\nGenerating dictionaries: {', '.join(dictionaries)}\n")

    # Generate requested dictionaries
    if 'shavian-english' in dictionaries:
        generate_dictionary(readlex_data, latin_defs, shavian_english_path, 'shaw-eng', dialect, wordnet_cache)
        print()

    if 'english-shavian' in dictionaries:
        generate_dictionary(readlex_data, shavian_def_cache, english_shavian_path, 'eng-shaw', dialect, wordnet_cache)
        print()

    if 'shavian-shavian' in dictionaries:
        generate_dictionary(readlex_data, shavian_def_cache, shavian_shavian_path, 'shaw-shaw', dialect, wordnet_cache)
        print()

    print(f"Dictionary generation complete ({dialect.upper()})!")
    for dict_name in dictionaries:
        dict_path = build_dir / f"{dict_name}-{dialect}.xml"
        print(f"  - {dict_path}")


if __name__ == '__main__':
    main()
