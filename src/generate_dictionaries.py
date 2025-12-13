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


def normalize_to_us_spelling(word):
    """
    Normalize GB spellings to US equivalents for grouping purposes.
    Returns the normalized (US) spelling.
    Handles hyphenated compounds by normalizing each part.
    """
    # Handle hyphenated words by normalizing each part
    if '-' in word:
        parts = word.split('-')
        normalized_parts = [_normalize_word_part(part) for part in parts]
        return '-'.join(normalized_parts)

    return _normalize_word_part(word)

def _normalize_word_part(word):
    """
    Normalize a single word (or word part) from GB to US spelling.
    """
    word_lower = word.lower()

    # Common GB -> US transformations
    # -our (GB) -> -or (US): colour -> color
    if word_lower.endswith('our'):
        if not word_lower.endswith(('pour', 'sour', 'tour', 'four', 'your')):
            base = word_lower[:-3]
            normalized = base + 'or'
            # Preserve original casing
            if word[0].isupper():
                return normalized.capitalize()
            return normalized

    # -re (GB) -> -er (US): centre -> center
    if word_lower.endswith('re'):
        if not word_lower.endswith(('are', 'ere', 'ire', 'ore', 'ure', 'acre', 'ogre')):
            base = word_lower[:-2]
            if len(base) >= 2:
                normalized = base + 'er'
                if word[0].isupper():
                    return normalized.capitalize()
                return normalized

    # -ogue (GB) -> -og (US): dialogue -> dialog
    if word_lower.endswith('ogue'):
        base = word_lower[:-3]
        normalized = base + 'og'
        if word[0].isupper():
            return normalized.capitalize()
        return normalized

    # -ence (GB) -> -ense (US): defence -> defense
    if word_lower.endswith('ence'):
        base = word_lower[:-4]
        if base in ('def', 'off', 'lic', 'pret'):
            normalized = base + 'ense'
            if word[0].isupper():
                return normalized.capitalize()
            return normalized

    # No transformation needed
    return word

def detect_spelling_variant(word):
    """
    Detect if a word uses US or GB spelling based on common patterns.
    Returns 'US', 'GB', or None if indeterminate.

    Note: Australian English generally follows British spelling patterns,
    so words detected as 'GB' likely apply to Australian as well.
    """
    word_lower = word.lower()

    # Try checking inflected forms by stripping common suffixes
    # and checking the root word
    inflection_suffixes = [
        ('ing', ''),      # coloring -> color
        ('ed', ''),       # colored -> color
        ('s', ''),        # colors -> color
        ('es', ''),       # defenses -> defense
        ('er', ''),       # colorer -> color
        ('est', ''),      # colorest -> color
        ('ly', ''),       # colorly -> color
        ('ness', ''),     # colorness -> color
    ]

    for suffix, _ in inflection_suffixes:
        if word_lower.endswith(suffix) and len(word_lower) > len(suffix) + 2:
            root = word_lower[:-len(suffix)]
            # Try root word first
            root_variant = _check_spelling_patterns(root)
            if root_variant:
                return root_variant
            # For -ed, also try with trailing 'e' (travelled -> travel)
            if suffix == 'ed' and len(root) > 2:
                root_variant = _check_spelling_patterns(root + 'e')
                if root_variant:
                    return root_variant

    # Check the word itself
    return _check_spelling_patterns(word_lower)


def _check_spelling_patterns(word_lower):
    """Check a word against US/GB spelling patterns."""
    # -our (GB) vs -or (US): colour/color, honour/honor, favour/favor
    if word_lower.endswith('our') and len(word_lower) > 3:
        # Check it's not a word that naturally ends in -our
        if not word_lower.endswith(('pour', 'sour', 'tour', 'four', 'your')):
            return 'GB'

    # Check for -or endings that likely have -our variant
    if word_lower.endswith('or') and len(word_lower) > 3:
        # Common -our words in base form
        our_words = ['col', 'hon', 'fav', 'flav', 'harb', 'hum', 'lab', 'neighb',
                     'rum', 'sav', 'vap', 'vig', 'splend', 'arb', 'clam']
        if any(word_lower[:-2].endswith(base) for base in our_words):
            return 'US'

    # -re (GB) vs -er (US): centre/center, theatre/theater, metre/meter
    if word_lower.endswith('tre') or word_lower.endswith('bre') or word_lower.endswith('pre'):
        if len(word_lower) > 4:
            return 'GB'
    if word_lower.endswith('ter') or word_lower.endswith('ber') or word_lower.endswith('per'):
        # Check if it's a -re word
        re_words = ['cen', 'thea', 'me', 'li', 'ti', 'lus', 'spec', 'som']
        if any(word_lower[:-3].endswith(base) for base in re_words):
            return 'US'

    # -ogue (GB) vs -og (US): catalogue/catalog, dialogue/dialog
    if word_lower.endswith('ogue'):
        return 'GB'
    if word_lower.endswith(('alog', 'ilog')) and not word_lower.endswith('olog'):
        return 'US'

    # -ence (GB) vs -ense (US): defence/defense, licence/license, offence/offense
    if word_lower.endswith('fence') or word_lower.endswith('tence'):
        if word_lower.startswith(('def', 'off')) or 'lic' in word_lower or 'pret' in word_lower:
            return 'GB'
    if word_lower.endswith('fense') or word_lower.endswith('tense'):
        if word_lower.startswith(('def', 'off')) or 'lic' in word_lower or 'pret' in word_lower:
            return 'US'

    return None


def extract_lemma_from_key(key):
    """Extract lemma from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if len(parts) >= 1:
        return parts[0].lower()
    return None


def process_readlex_with_lemmas(readlex_data):
    """
    Process readlex data to include lemma information.
    Returns: dict mapping readlex keys to (lemma, entries) tuples
    """
    print("Processing readlex with lemma information...")
    processed = {}

    for key, entries in readlex_data.items():
        # Extract lemma from key
        lemma = extract_lemma_from_key(key)
        if not lemma and entries:
            # Fallback to first entry's Latn field
            lemma = entries[0]['Latn'].lower()

        processed[key] = {
            'lemma': lemma,
            'entries': entries
        }

    print(f"Processed {len(processed)} lemma groups")
    return processed


def variant_to_label(var_code):
    """Convert variant codes to readable labels."""
    variant_map = {
        'RRP': 'RP',  # Received Pronunciation (British)
        'GA': 'Gen-Am',
        'AU': 'Gen-Au',
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


def generate_dictionary(readlex_data, definitions, output_path, dict_type, dialect='gb'):
    """
    Generate a dictionary with unified structure.

    Args:
        readlex_data: Processed readlex data with lemma information
        definitions: WordNet definitions or Shavian cache
        output_path: Output XML file path
        dict_type: 'shaw-eng', 'eng-shaw', or 'shaw-shaw'
        dialect: 'gb' or 'us' (for preferred variant)
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
    preferred_var = 'RRP' if dialect == 'gb' else 'GA'

    # Collect all forms for each lemma
    lemma_entries = defaultdict(lambda: {'forms': [], 'definitions': []})

    for key, data in readlex_data.items():
        lemma = data['lemma']
        # Normalize GB -> US spelling for grouping (colour -> color)
        # This merges US/GB spelling variants into one entry
        normalized_lemma = normalize_to_us_spelling(lemma)

        # Get definitions using normalized lemma (prefer US definitions)
        if config['use_shavian_cache']:
            lemma_defs_raw = definitions.get(normalized_lemma, [])
            # Convert cache format to standard format
            lemma_defs = []
            for trans_def in lemma_defs_raw:
                lemma_defs.append({
                    'definition': trans_def['transliterated_definition'],
                    'pos': trans_def['transliterated_pos'] if dict_type == 'shaw-shaw' else trans_def['pos'],
                    'examples': trans_def['transliterated_examples']
                })
        else:
            lemma_defs = definitions.get(normalized_lemma, [])

        # Process each form
        for entry in data['entries']:
            shaw = entry['Shaw']
            latn = entry['Latn']
            latn_lower = latn.lower()
            pos = entry.get('pos', '')
            ipa = entry.get('ipa', '')
            var = entry.get('var', '')

            # Detect spelling variant using heuristics
            detected_variant = detect_spelling_variant(latn)

            # Check if this is a lemma form (matches either original or normalized lemma)
            is_lemma_form = (latn_lower == lemma or latn_lower == normalized_lemma.lower())

            # Add form
            form_info = {
                'shaw': shaw,
                'latn': latn,
                'pos': pos,
                'ipa': ipa,
                'var': var,
                'spelling_variant': detected_variant,  # 'US', 'GB', or None
                'is_lemma': is_lemma_form,
                'is_preferred': (var == preferred_var)
            }
            # Use normalized lemma as key to merge colour/color
            if form_info not in lemma_entries[normalized_lemma]['forms']:
                lemma_entries[normalized_lemma]['forms'].append(form_info)

            # Add definitions if not already added
            if not lemma_entries[normalized_lemma]['definitions'] and lemma_defs:
                lemma_entries[normalized_lemma]['definitions'] = lemma_defs

    # Split lemmas that have multiple different Shavian forms (different pronunciation)
    # e.g., "lead" → 𐑤𐑧𐑛 /led/ and 𐑤𐑰𐑛 /liːd/, or "read" → 𐑮𐑰𐑛 /riːd/ and 𐑮𐑧𐑛 /red/
    # BUT: Don't split if the different Shavians are just due to GB vs US pronunciation variants
    # (e.g., "schedule" pronounced differently in GB vs US is still the same word sense)
    split_lemma_entries = {}
    for lemma, data in lemma_entries.items():
        # Find all distinct (Shavian, var) pairs for this lemma's lemma forms
        # We group by variant to avoid splitting on GB/US pronunciation differences
        lemma_form_groups = defaultdict(set)  # var → set of Shavian forms
        for f in data['forms']:
            if f['is_lemma']:
                var = f.get('var')
                lemma_form_groups[var].add(f['shaw'])

        if not lemma_form_groups:
            continue

        # Check if there are multiple distinct Shavians WITHIN any single variant
        # If so, these are true pronunciation differences (e.g., lead /led/ vs /liːd/)
        needs_split = False
        for var, shavians in lemma_form_groups.items():
            if len(shavians) > 1:
                needs_split = True
                break

        # If multiple distinct Shavian forms within a variant, split into separate entries
        if needs_split:
            # Collect all unique Shavian forms across all variants
            all_shavians = set()
            for shavians in lemma_form_groups.values():
                all_shavians.update(shavians)

            for shavian_form in all_shavians:
                # Create a split lemma key
                split_key = f"{lemma}__{shavian_form}"
                # Collect only forms that match this Shavian form
                split_forms = []
                for form in data['forms']:
                    if form['is_lemma']:
                        if form['shaw'] == shavian_form:
                            split_forms.append(form)
                    else:
                        # Include all derived forms
                        split_forms.append(form)

                if split_forms:
                    split_lemma_entries[split_key] = {
                        'forms': split_forms,
                        'definitions': data['definitions']
                    }
        else:
            # No split needed - keep all GB/US variants together
            split_lemma_entries[lemma] = data

    # Group split lemmas by their index word
    index_to_lemmas = defaultdict(list)
    for lemma_key, data in split_lemma_entries.items():
        lemma_forms = [f for f in data['forms'] if f['is_lemma']]
        if lemma_forms:
            index_word = (
                lemma_forms[0]['shaw'] if config['index_key'] == 'shaw'
                else lemma_forms[0]['latn'].lower()
            )
            index_to_lemmas[index_word].append(lemma_key)

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header(config['name'], config['from_lang'], config['to_lang']))
        f.write(create_front_matter())
        f.flush()

        written_entries = 0

        # Write entries - merge lemmas with same definitions, separate for different word senses
        for index_word in sorted(index_to_lemmas.keys()):
            lemmas_for_index = index_to_lemmas[index_word]

            # Group lemmas by their definitions to merge spelling variants (colour/color)
            # but keep separate word senses (dew/due)
            def_signature = lambda defs: tuple(sorted([d.get('definition', '') for d in (defs or [])[:5]]))

            merged_groups = []  # List of (merged_forms, definitions) tuples
            used_lemmas = set()

            for lemma_key in lemmas_for_index:
                if lemma_key in used_lemmas:
                    continue

                lemma_data = split_lemma_entries[lemma_key]
                current_sig = def_signature(lemma_data['definitions'])

                # Find all other lemmas with the same definition signature
                group_forms = list(lemma_data['forms'])
                group_defs = lemma_data['definitions']
                used_lemmas.add(lemma_key)

                for other_key in lemmas_for_index:
                    if other_key in used_lemmas:
                        continue
                    other_data = split_lemma_entries[other_key]
                    other_sig = def_signature(other_data['definitions'])

                    if current_sig == other_sig and current_sig:  # Same definitions
                        group_forms.extend(other_data['forms'])
                        used_lemmas.add(other_key)

                merged_groups.append((group_forms, group_defs))

            # Write separate entry for each merged group (each word sense)
            for group_idx, (group_forms, group_defs) in enumerate(merged_groups):
                lemma_data = {'forms': group_forms, 'definitions': group_defs}

                # Collect all index words for d:index tags (all forms from this lemma)
                lemma_forms_indices = set()
                for form in lemma_data['forms']:
                    form_index = form['shaw'] if config['index_key'] == 'shaw' else form['latn'].lower()
                    lemma_forms_indices.add(form_index)

                # Write entry for this group
                entry_id = f"{config['index_key']}_{index_word}_{group_idx}"
                f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(index_word)}">\n')

                # Add d:index for each form in this lemma
                for form_index in sorted(lemma_forms_indices):
                    f.write(f'    <d:index d:value="{escape(form_index)}"/>\n')

                f.write(f'    <h1>{escape(index_word)}</h1>\n')

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
                    base_word = normalize_to_us_spelling(form['latn'])
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
                    # Use the actual 'var' field from data (RRP=GB, GA=US), not heuristics
                    home_forms = []
                    alt_forms = []

                    for form in forms:
                        var = form.get('var')
                        # A form is "home" if it matches preferred variant OR has no variant specified
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

                        # Display the main text
                        f.write(escape(home_form[display_key]))
                        f.write(f' <span class="ipa">/{home_form["ipa"]}/</span>')

                        # Check for alternate forms
                        if alt_forms:
                            alt_form = alt_forms[0]
                            # Check if pronunciation is the same
                            if home_form['ipa'] == alt_form['ipa']:
                                # Same pronunciation - just show alternate spelling (colour vs color)
                                f.write(f' <span class="variant">({escape(alt_form[display_key])}, {alt_dialect})</span>')
                            else:
                                # Different pronunciation - show alternate with its IPA
                                f.write(f' <span class="variant">({escape(alt_form[display_key])}, {alt_dialect} /{alt_form["ipa"]}/)</span>')

                    elif alt_forms:
                        # Only alt form available
                        alt_form = alt_forms[0]

                        f.write(escape(alt_form[display_key]))
                        f.write(f' <span class="ipa">/{alt_form["ipa"]}/</span>')
                        f.write(f' <span class="variant">({alt_dialect})</span>')

                    f.write('</div>\n')

                f.write('    </div>\n')

                # Definitions for this lemma
                if lemma_data['definitions']:
                    pos_groups = group_definitions_by_pos(lemma_data['definitions'][:20])
                    f.write('    <div class="definitions">\n')
                    for pos, pos_defs in pos_groups:
                        f.write(f'      <div class="pos-group">\n')
                        f.write(f'        <h3><i>({escape(pos)})</i></h3>\n')
                        for i, def_data in enumerate(pos_defs[:5], 1):
                            f.write(f'        <p><b>{i}.</b> {escape(def_data["definition"])}</p>\n')
                        f.write('      </div>\n')
                    f.write('    </div>\n')
                else:
                    f.write('    <div class="definitions">\n')
                    f.write('      <p><i>(No definitions available)</i></p>\n')
                    f.write('    </div>\n')

                # Add separator between groups except for the last one
                if group_idx < len(merged_groups) - 1:
                    f.write('    <hr/>\n')

                f.write('  </d:entry>\n')
                written_entries += 1

            # Flush every 1000 entries
            if written_entries % 1000 == 0:
                f.flush()
                print(f"  Writing: {written_entries} entries")

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
    project_dir = script_dir.parent
    readlex_path = project_dir / '../shavian-info/readlex/readlex.json'
    wordnet_path = project_dir / 'build/wordnet-definitions.json'
    shavian_defs_path = project_dir / f'data/definitions-shavian-{dialect}.json'
    build_dir = project_dir / 'build'

    shavian_english_path = build_dir / f'shavian-english-{dialect}.xml'
    english_shavian_path = build_dir / f'english-shavian-{dialect}.xml'
    shavian_shavian_path = build_dir / f'shavian-shavian-{dialect}.xml'

    # Ensure directories exist
    build_dir.mkdir(exist_ok=True)

    # Load readlex data
    print("Loading readlex data...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_raw = json.load(f)
    print(f"Loaded {len(readlex_raw)} readlex entries")

    # Load WordNet definitions
    print("\nLoading WordNet definitions...")
    with open(wordnet_path, 'r', encoding='utf-8') as f:
        wordnet_defs = json.load(f)
    print(f"Loaded definitions for {len(wordnet_defs)} words")

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
        generate_dictionary(readlex_data, wordnet_defs, shavian_english_path, 'shaw-eng', dialect)
        print()

    if 'english-shavian' in dictionaries:
        generate_dictionary(readlex_data, shavian_def_cache, english_shavian_path, 'eng-shaw', dialect)
        print()

    if 'shavian-shavian' in dictionaries:
        generate_dictionary(readlex_data, shavian_def_cache, shavian_shavian_path, 'shaw-shaw', dialect)
        print()

    print(f"Dictionary generation complete ({dialect.upper()})!")
    for dict_name in dictionaries:
        dict_path = build_dir / f"{dict_name}-{dialect}.xml"
        print(f"  - {dict_path}")


if __name__ == '__main__':
    main()
