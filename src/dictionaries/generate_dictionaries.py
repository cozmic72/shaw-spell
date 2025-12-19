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
from pathlib import Path
from html import escape
from collections import defaultdict
from build_definition_caches import POS_TO_ENGLISH, POS_TO_SHAVIAN
# Dialect detection now uses comprehensive cache only


# Cache for normalized words to avoid repeated lookups
_normalize_us_cache = {}
_normalize_gb_cache = {}

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


def normalize_readlex_ipa(ipa):
    """
    Normalize Readlex IPA transcription.
    Readlex uses 'R' to denote '(r)' (optional r in non-rhotic accents).

    Args:
        ipa: IPA transcription string from Readlex

    Returns:
        Normalized IPA string with R replaced by (r)
    """
    if not ipa:
        return ipa
    return ipa.replace('R', '(r)')


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


def process_readlex_with_lemmas(readlex_data):
    """
    Process readlex data to include lemma information.
    Returns: dict mapping readlex keys to (lemma, canonical_shavian, entries) tuples
    """
    print("Processing readlex with lemma information...")
    processed = {}

    for key, entries in readlex_data.items():
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
    """Convert variant codes to readable labels."""
    variant_map = {
        'RRP': 'RP',  # Received Pronunciation (British)
        'GenAm': 'Gen-Am',
        'GB': 'GB'
    }
    return variant_map.get(var_code, var_code)


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


def get_definitions_from_cache(lemma, wordnet_cache):
    """
    Extract definitions for a lemma from the comprehensive cache.

    Args:
        lemma: The lemma to look up (normalized to lowercase)
        wordnet_cache: The comprehensive WordNet cache

    Returns:
        List of definition dicts compatible with wordnet-definitions.json format:
        [{'definition': str, 'pos': str, 'examples': [str, ...]}, ...]
    """
    if not wordnet_cache or lemma.lower() not in wordnet_cache:
        return []

    entry = wordnet_cache[lemma.lower()]
    all_definitions = []

    # Extract definitions from all POS entries and their senses
    for pos, pos_data in entry.get('pos_entries', {}).items():
        # Get definitions from sense_variants
        for sense in pos_data.get('sense_variants', []):
            sense_defs = sense.get('definitions', [])
            for def_text in sense_defs:
                all_definitions.append({
                    'definition': def_text,
                    'pos': pos
                })

    return all_definitions


def pos_to_readable(pos_code):
    """Convert CLAWS POS tags to readable forms."""
    if '+' in pos_code:
        parts = pos_code.split('+')
        return ', '.join(pos_to_readable(p) for p in parts)

    pos_map = {
        'AJ0': 'adjective', 'AJC': 'adjective (comparative)', 'AJS': 'adjective (superlative)',
        'AT0': 'article',
        'AV0': 'adverb', 'AVP': 'adverb', 'AVQ': 'adverb',
        'CJC': 'conjunction', 'CJS': 'conjunction', 'CJT': 'conjunction',
        'CRD': 'cardinal number',
        'DPS': 'determiner', 'DT0': 'determiner', 'DTQ': 'determiner',
        'EX0': 'existential',
        'ITJ': 'interjection',
        'NN0': 'noun', 'NN1': 'noun', 'NN2': 'noun (plural)',
        'NP0': 'proper noun',
        'ORD': 'ordinal',
        'PNI': 'pronoun', 'PNP': 'pronoun', 'PNQ': 'pronoun', 'PNX': 'pronoun',
        'PRE': 'prefix', 'PRF': 'prefix', 'PRP': 'preposition',
        'TO0': 'infinitive marker',
        'UNC': '',
        'VBB': 'verb', 'VBD': 'verb', 'VBG': 'verb', 'VBI': 'verb', 'VBN': 'verb', 'VBZ': 'verb',
        'VDB': 'verb', 'VDD': 'verb', 'VDG': 'verb', 'VDI': 'verb', 'VDN': 'verb', 'VDZ': 'verb',
        'VHB': 'verb', 'VHD': 'verb', 'VHG': 'verb', 'VHI': 'verb', 'VHN': 'verb', 'VHZ': 'verb',
        'VM0': 'modal verb',
        'VVB': 'verb', 'VVD': 'verb', 'VVG': 'verb', 'VVI': 'verb', 'VVN': 'verb', 'VVZ': 'verb',
        'XX0': 'negation',
        'ZZ0': 'letter',
        'POS': 'possessive',
    }
    return pos_map.get(pos_code, pos_code)


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
        return f'{t("3rd person singular of")} {lemma_ref}'
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
    # Configuration based on dictionary type
    config = {
        'shaw-eng': {
            'name': 'Shavian–English',
            'from_lang': 'Shavian',
            'to_lang': 'English',
            'index_key': 'shaw',        # Index by Shavian
            'display_text': 'latn',      # Display English text
            'translate_labels': False,   # Don't translate labels
            'use_shavian_cache': False,  # Use WordNet
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
            # For non-Shavian dictionaries, use old lemma-based lookup
            if wordnet_cache:
                lemma_defs = get_definitions_from_cache(lemma, wordnet_cache)
            else:
                lemma_defs = []

            # Fall back to passed definitions if cache didn't have any
            if not lemma_defs:
                lemma_defs = definitions.get(lemma, [])

            # Determine POS for this readlex key to filter definitions
            key_pos_set = set()
            for entry in data['entries']:
                pos_code = entry.get('pos', '')
                # Map CLAWS POS to WordNet POS (v, n, a, r)
                if pos_code.startswith('V'):
                    key_pos_set.add('v')
                elif pos_code.startswith('N') and not is_proper_noun(pos_code):
                    key_pos_set.add('n')
                elif pos_code.startswith('AJ'):
                    key_pos_set.add('a')
                elif pos_code.startswith('AV'):
                    key_pos_set.add('r')

            # Filter definitions to match the POS of this readlex key
            filtered_defs = []
            for def_data in lemma_defs:
                if def_data.get('pos') in key_pos_set:
                    filtered_defs.append(def_data)

            # Don't use fallback - if we can't find definitions for this POS,
            # leave filtered_defs empty and we'll show "no definition found"

        # For Shavian cache, no filtering needed (already synset-specific)
        if config['use_shavian_cache']:
            filtered_defs = lemma_defs

        # Process each form in this readlex key
        forms = []
        for entry in data['entries']:
            shaw = entry['Shaw']
            latn = entry['Latn']
            pos = entry.get('pos', '')
            ipa = normalize_readlex_ipa(entry.get('ipa', ''))
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

    # Write XML
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

                # Collect all index words for d:index tags (all forms from this lemma)
                lemma_forms_indices = set()
                for form in lemma_data['forms']:
                    form_index = form['shaw'] if config['index_key'] == 'shaw' else form['latn'].lower()

                    # Apply proper noun formatting to index values
                    if config['index_key'] == 'shaw':
                        # Add namer dot version for proper nouns
                        if is_proper_noun(form['pos']):
                            # Add both with and without namer dot for flexibility
                            lemma_forms_indices.add(form_index)
                            lemma_forms_indices.add(add_namer_dot_if_proper_noun(form_index, form['pos']))
                        else:
                            lemma_forms_indices.add(form_index)
                    else:
                        # For Latin, add both lowercase and capitalized versions for proper nouns
                        lemma_forms_indices.add(form_index)  # lowercase version
                        if is_proper_noun(form['pos']):
                            lemma_forms_indices.add(form_index.capitalize())

                # Add foreign dialect forms as cross-references
                # E.g., in GB dictionary, add "color" indices pointing to "colour" entry
                for foreign_key, home_key in foreign_to_home.items():
                    if home_key == entry_key:
                        # This home entry has foreign variants - add their forms as indices
                        foreign_data = readlex_entries[foreign_key]
                        for form in foreign_data['forms']:
                            form_index = form['shaw'] if config['index_key'] == 'shaw' else form['latn'].lower()
                            if config['index_key'] == 'shaw':
                                if is_proper_noun(form['pos']):
                                    lemma_forms_indices.add(form_index)
                                    lemma_forms_indices.add(add_namer_dot_if_proper_noun(form_index, form['pos']))
                                else:
                                    lemma_forms_indices.add(form_index)
                            else:
                                lemma_forms_indices.add(form_index)
                                if is_proper_noun(form['pos']):
                                    lemma_forms_indices.add(form_index.capitalize())

                # Write entry for this readlex key
                entry_id = f"{config['index_key']}_{index_word}_{entry_idx}"
                f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(index_word)}">\n')

                # Add d:index for each form in this lemma
                for form_index in sorted(lemma_forms_indices):
                    f.write(f'    <d:index d:value="{escape(form_index)}"/>\n')

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
                            # Fall back to pronunciation variant (var field)
                            var = form.get('var')
                            is_home = (var == preferred_var or var is None)

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
                                # Different pronunciation - show it
                                variant_label = additional_form.get('var')
                                if variant_label == 'GenAm':
                                    variant_label = 'US'
                                elif variant_label == 'RRP':
                                    variant_label = 'GB'

                                if variant_label and variant_label != home_dialect:
                                    f.write(f' <span class="variant">({escape(home_display_text)}, {variant_label} /{additional_form["ipa"]}/)</span>')
                                else:
                                    f.write(f' <span class="variant">({escape(home_display_text)} /{additional_form["ipa"]}/)</span>')

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

                        # Check for alternate forms
                        if alt_forms:
                            alt_form = alt_forms[0]

                            # Apply proper noun formatting to alternate form
                            alt_display_text = alt_form[display_key]
                            if display_key == 'shaw':
                                alt_display_text = add_namer_dot_if_proper_noun(alt_display_text, alt_form['pos'])
                            else:
                                alt_display_text = capitalize_if_proper_noun(alt_display_text, alt_form['pos'])

                            # Check if pronunciation is the same
                            if home_form['ipa'] == alt_form['ipa']:
                                # Same pronunciation - just show alternate spelling (colour vs color)
                                f.write(f' <span class="variant">({escape(alt_display_text)}, {alt_dialect})</span>')
                            else:
                                # Different pronunciation - show alternate with its IPA
                                f.write(f' <span class="variant">({escape(alt_display_text)}, {alt_dialect} /{alt_form["ipa"]}/)</span>')

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
                        f.write(f' <span class="variant">({alt_dialect})</span>')

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
                            f.write(f'          <li class="definition">{escape(def_data["definition"])}</li>\n')
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
    readlex_path = project_dir / 'external/readlex/readlex.json'
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

    # Load dialect-specific Latin definitions for shavian-english dictionary
    latin_defs = {}
    if latin_defs_path.exists():
        print(f"\nLoading {dialect.upper()} Latin definitions...")
        with open(latin_defs_path, 'r', encoding='utf-8') as f:
            latin_defs = json.load(f)
        print(f"Loaded definitions for {len(latin_defs)} words")
    else:
        print(f"\nNote: Latin definitions not found at {latin_defs_path}")
        print(f"Please run: ./src/tools/generate_dialect_definitions.py")
        print("Will use comprehensive cache if available")

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
