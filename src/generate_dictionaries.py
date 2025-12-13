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


def format_word_entry(main_text, ipa, pos_code, lemma, lemma_ipa, var_code, show_variants, shavian_lookup=None):
    """
    Format a word entry with consistent styling across all dictionaries.

    Args:
        main_text: The main word to display (Latin, Shavian, or None for IPA-only)
        ipa: IPA transcription for this form
        pos_code: Part of speech code
        lemma: The lemma for this form
        lemma_ipa: IPA transcription of the lemma
        var_code: Variant code (RRP, GA, AU, etc.)
        show_variants: Whether to show variant labels
        shavian_lookup: Optional dict for translating labels to Shavian

    Returns:
        HTML string for the word entry
    """
    html = []
    html.append('      <div class="word-entry">\n')

    # Main word: "translation /ipa/" or just "/ipa/" if no translation
    main_parts = []
    if main_text:
        main_parts.append(escape(main_text))
    if ipa:
        main_parts.append(f' <span class="ipa">/{escape(ipa)}/</span>')

    html.append(f'        <div class="word-main">{"".join(main_parts)}</div>\n')

    # Grammatical label below
    gram_form = pos_to_grammatical_form(pos_code, lemma, lemma_ipa, shavian_lookup) if pos_code else ''
    if gram_form or (show_variants and var_code):
        label_parts = []
        if gram_form:
            label_parts.append(gram_form)
        if show_variants and var_code:
            var_label = variant_to_label(var_code)
            if label_parts:
                label_parts.append(f' <span class="variant">({escape(var_label)})</span>')
            else:
                label_parts.append(f'<span class="variant">({escape(var_label)})</span>')
        html.append(f'        <div class="word-label">{"".join(label_parts)}</div>\n')

    html.append('      </div>\n')
    return ''.join(html)


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


def generate_shavian_to_english(readlex_data, wordnet_defs, output_path):
    """Generate Shavian → English dictionary with definitions."""
    print("Generating Shavian → English dictionary...")

    # No Shavian lookup needed for this dictionary (English labels)

    # Collect entries by Shavian word, grouped by lemma
    # Structure: {shaw: {lemma: {'forms': [...], 'definitions': [...]}}}
    shavian_entries = defaultdict(lambda: defaultdict(lambda: {'forms': [], 'definitions': []}))

    for key, data in readlex_data.items():
        lemma = data['lemma']
        entries = data['entries']

        # Get definitions for this lemma
        word_defs = wordnet_defs.get(lemma, [])

        # Group by Shavian spelling
        for entry in entries:
            shaw = entry['Shaw']
            latn = entry['Latn']
            pos = entry.get('pos', '')
            ipa = entry.get('ipa', '')
            var = entry.get('var', '')

            # Add form to this lemma group
            form_info = {
                'latn': latn,
                'pos': pos,
                'ipa': ipa,
                'var': var
            }
            if form_info not in shavian_entries[shaw][lemma]['forms']:
                shavian_entries[shaw][lemma]['forms'].append(form_info)

            # Add definitions if not already added for this lemma
            if not shavian_entries[shaw][lemma]['definitions'] and word_defs:
                shavian_entries[shaw][lemma]['definitions'] = word_defs

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('Shavian–English', 'Shavian', 'English'))
        f.write(create_front_matter())
        f.flush()

        total = len(shavian_entries)
        for idx, shaw in enumerate(sorted(shavian_entries.keys()), 1):
            lemma_groups = shavian_entries[shaw]
            entry_id = f"shaw_{shaw}"

            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(shaw)}">\n')
            f.write(f'    <d:index d:value="{escape(shaw)}"/>\n')
            f.write(f'    <h1>{escape(shaw)}</h1>\n')

            # Iterate over each lemma group
            for lemma_idx, (lemma, lemma_data) in enumerate(sorted(lemma_groups.items())):
                # Add separator if not first lemma
                if lemma_idx > 0:
                    f.write('    <hr/>\n')

                # Get lemma IPA by looking up the lemma in readlex_data
                lemma_ipa = ''
                for key, data in readlex_data.items():
                    if data['lemma'] == lemma:
                        # Find an entry where the latn matches the lemma
                        for entry in data['entries']:
                            if entry['Latn'].lower() == lemma and entry.get('ipa'):
                                lemma_ipa = entry['ipa']
                                break
                        if lemma_ipa:
                            break

                # Check if we need to show variants (only if multiple different variants exist)
                unique_variants = set(form['var'] for form in lemma_data['forms'] if form['var'])
                show_variants = len(unique_variants) > 1

                # Forms for this lemma
                f.write('    <div class="forms">\n')
                for form in lemma_data['forms']:
                    f.write(format_word_entry(
                        main_text=form['latn'],
                        ipa=form['ipa'],
                        pos_code=form['pos'],
                        lemma=lemma,
                        lemma_ipa=lemma_ipa,
                        var_code=form['var'],
                        show_variants=show_variants
                    ))
                f.write('    </div>\n')

                # Definitions for this lemma
                if lemma_data['definitions']:
                    f.write('    <div class="definitions">\n')
                    for i, def_data in enumerate(lemma_data['definitions'][:5], 1):  # Limit to 5 definitions
                        f.write(f'      <div class="definition">\n')
                        f.write(f'        <p><b>{i}. </b><i>({escape(def_data["pos"])})</i> {escape(def_data["definition"])}</p>\n')
                        f.write('      </div>\n')
                    f.write('    </div>\n')
                else:
                    # No definitions for this lemma (e.g., "chuse")
                    f.write('    <div class="definitions">\n')
                    f.write('      <p><i>(No definitions available)</i></p>\n')
                    f.write('    </div>\n')

            f.write('  </d:entry>\n')

            # Flush every 1000 entries
            if idx % 1000 == 0:
                f.flush()
                print(f"  Writing: {idx}/{total} entries ({(idx/total)*100:.1f}%)")

        f.write(create_xml_footer())
        f.flush()

    print(f"Generated {len(shavian_entries)} Shavian entries → {output_path}")


def generate_english_to_shavian(readlex_data, shavian_def_cache, output_path, dialect='gb'):
    """Generate English → Shavian dictionary with transliterated definitions."""
    print(f"Generating English → Shavian dictionary ({dialect.upper()})...")

    # Build Shavian lookup for translating grammatical labels
    shavian_lookup = build_shavian_lookup(readlex_data)

    # Determine preferred variant code based on dialect
    preferred_var = 'RRP' if dialect == 'gb' else 'GA'
    dialect_label = 'GB' if dialect == 'gb' else 'US'

    # Collect entries by English word, grouped by lemma
    # Structure: {latn: {lemma: {'forms': [...], 'definitions': [...]}}}
    english_entries = defaultdict(lambda: defaultdict(lambda: {'forms': [], 'definitions': []}))

    for key, data in readlex_data.items():
        lemma = data['lemma']
        entries = data['entries']

        # Get transliterated definitions from cache
        lemma_trans = shavian_def_cache.get(lemma, [])

        # Group by English spelling (case-insensitive)
        # Separate preferred dialect forms from others
        preferred_forms = []
        other_forms = []

        for entry in entries:
            latn = entry['Latn']
            latn_lower = latn.lower()
            shaw = entry['Shaw']
            pos = entry.get('pos', '')
            ipa = entry.get('ipa', '')
            var = entry.get('var', '')

            form_info = {
                'shaw': shaw,
                'latn': latn,
                'pos': pos,
                'ipa': ipa,
                'var': var
            }

            # Prioritize preferred dialect
            if var == preferred_var:
                if form_info not in preferred_forms:
                    preferred_forms.append(form_info)
            else:
                if form_info not in other_forms:
                    other_forms.append(form_info)

        # Add forms to entry: preferred first, then others
        for form_info in preferred_forms + other_forms:
            latn_lower = form_info['latn'].lower()
            if form_info not in english_entries[latn_lower][lemma]['forms']:
                english_entries[latn_lower][lemma]['forms'].append(form_info)

            # Add transliterated definitions if not already added for this lemma
            if not english_entries[latn_lower][lemma]['definitions'] and lemma_trans:
                # Convert cached format to dictionary format
                resolved_defs = []
                for trans_def in lemma_trans:
                    resolved_defs.append({
                        'definition': trans_def['transliterated_definition'],
                        'pos': trans_def['pos'],  # Keep original POS for now
                        'examples': trans_def['transliterated_examples']
                    })
                english_entries[latn_lower][lemma]['definitions'] = resolved_defs

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('English–Shavian', 'English', 'Shavian'))
        f.write(create_front_matter())
        f.flush()

        total = len(english_entries)
        for idx, latn in enumerate(sorted(english_entries.keys()), 1):
            lemma_groups = english_entries[latn]
            entry_id = f"eng_{latn}"

            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(latn)}">\n')
            f.write(f'    <d:index d:value="{escape(latn)}"/>\n')
            f.write(f'    <h1>{escape(latn)}</h1>\n')

            # Iterate over each lemma group
            for lemma_idx, (lemma, lemma_data) in enumerate(sorted(lemma_groups.items())):
                # Add separator if not first lemma
                if lemma_idx > 0:
                    f.write('    <hr/>\n')

                # Get lemma IPA by looking up the lemma in readlex_data
                lemma_ipa = ''
                for key, data in readlex_data.items():
                    if data['lemma'] == lemma:
                        # Find an entry where the latn matches the lemma
                        for entry in data['entries']:
                            if entry['Latn'].lower() == lemma and entry.get('ipa'):
                                lemma_ipa = entry['ipa']
                                break
                        if lemma_ipa:
                            break

                # Check if we need to show variants (only if multiple different variants exist)
                unique_variants = set(form['var'] for form in lemma_data['forms'] if form['var'])
                show_variants = len(unique_variants) > 1

                # Forms for this lemma
                f.write('    <div class="forms">\n')
                for form in lemma_data['forms']:
                    f.write(format_word_entry(
                        main_text=form['shaw'],
                        ipa=form['ipa'],
                        pos_code=form['pos'],
                        lemma=lemma,
                        lemma_ipa=lemma_ipa,
                        var_code=form['var'],
                        show_variants=show_variants,
                        shavian_lookup=shavian_lookup
                    ))
                f.write('    </div>\n')

                # Definitions for this lemma (in Shavian)
                if lemma_data['definitions']:
                    f.write('    <div class="definitions">\n')
                    for i, def_data in enumerate(lemma_data['definitions'][:5], 1):
                        # Translate POS to Shavian
                        pos_translated = translate_to_shavian(def_data["pos"], shavian_lookup)
                        f.write(f'      <div class="definition">\n')
                        f.write(f'        <p><b>{i}. </b><i>({escape(pos_translated)})</i> {escape(def_data["definition"])}</p>\n')
                        f.write('      </div>\n')
                    f.write('    </div>\n')
                else:
                    # No definitions for this lemma
                    f.write('    <div class="definitions">\n')
                    f.write('      <p><i>(No definitions available)</i></p>\n')
                    f.write('    </div>\n')

            f.write('  </d:entry>\n')

            # Flush every 1000 entries
            if idx % 1000 == 0:
                f.flush()
                print(f"  Writing: {idx}/{total} entries ({(idx/total)*100:.1f}%)")

        f.write(create_xml_footer())
        f.flush()

    print(f"Generated {len(english_entries)} English entries → {output_path}")


def generate_shavian_to_shavian(readlex_data, shavian_def_cache, output_path, dialect='gb'):
    """Generate Shavian → Shavian dictionary (Shavian word with Shavian definitions)."""
    print(f"Generating Shavian → Shavian dictionary ({dialect.upper()})...")

    # Build Shavian lookup for translating grammatical labels
    shavian_lookup = build_shavian_lookup(readlex_data)

    # Determine preferred variant code based on dialect
    preferred_var = 'RRP' if dialect == 'gb' else 'GA'
    dialect_label = 'GB' if dialect == 'gb' else 'US'

    # Collect entries by Shavian word, grouped by lemma
    # Structure: {shaw: {lemma: {'forms': [...], 'definitions': [...]}}}
    shavian_entries = defaultdict(lambda: defaultdict(lambda: {'forms': [], 'definitions': []}))

    for key, data in readlex_data.items():
        lemma = data['lemma']
        entries = data['entries']

        # Get transliterated definitions from cache
        lemma_trans = shavian_def_cache.get(lemma, [])

        # Group by Shavian spelling
        # Separate preferred dialect forms from others
        preferred_forms = []
        other_forms = []

        for entry in entries:
            shaw = entry['Shaw']
            latn = entry['Latn']
            pos = entry.get('pos', '')
            ipa = entry.get('ipa', '')
            var = entry.get('var', '')

            form_info = {
                'shaw': shaw,
                'latn': latn,
                'pos': pos,
                'ipa': ipa,
                'var': var
            }

            # Prioritize preferred dialect
            if var == preferred_var:
                if form_info not in preferred_forms:
                    preferred_forms.append(form_info)
            else:
                if form_info not in other_forms:
                    other_forms.append(form_info)

        # Add forms to entry: preferred first, then others
        for form_info in preferred_forms + other_forms:
            shaw = form_info['shaw']
            if form_info not in shavian_entries[shaw][lemma]['forms']:
                shavian_entries[shaw][lemma]['forms'].append(form_info)

            # Add transliterated definitions if not already added for this lemma
            if not shavian_entries[shaw][lemma]['definitions'] and lemma_trans:
                # Convert cached format to dictionary format
                resolved_defs = []
                for trans_def in lemma_trans:
                    resolved_defs.append({
                        'definition': trans_def['transliterated_definition'],
                        'pos': trans_def['transliterated_pos'],  # Use transliterated POS
                        'examples': trans_def['transliterated_examples']
                    })
                shavian_entries[shaw][lemma]['definitions'] = resolved_defs

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('Shavian', 'Shavian', 'Shavian'))
        f.write(create_front_matter())
        f.flush()

        total = len(shavian_entries)
        for idx, shaw in enumerate(sorted(shavian_entries.keys()), 1):
            lemma_groups = shavian_entries[shaw]
            entry_id = f"shavian_{shaw}"

            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(shaw)}">\n')
            f.write(f'    <d:index d:value="{escape(shaw)}"/>\n')
            f.write(f'    <h1>{escape(shaw)}</h1>\n')

            # Iterate over each lemma group
            for lemma_idx, (lemma, lemma_data) in enumerate(sorted(lemma_groups.items())):
                # Add separator if not first lemma
                if lemma_idx > 0:
                    f.write('    <hr/>\n')

                # Get lemma IPA by looking up the lemma in readlex_data
                lemma_ipa = ''
                for key, data in readlex_data.items():
                    if data['lemma'] == lemma:
                        # Find an entry where the latn matches the lemma
                        for entry in data['entries']:
                            if entry['Latn'].lower() == lemma and entry.get('ipa'):
                                lemma_ipa = entry['ipa']
                                break
                        if lemma_ipa:
                            break

                # Check if we need to show variants (only if multiple different variants exist)
                unique_variants = set(form['var'] for form in lemma_data['forms'] if form['var'])
                show_variants = len(unique_variants) > 1

                # Forms for this lemma (pronunciation info)
                if any(f['ipa'] for f in lemma_data['forms']):
                    f.write('    <div class="forms">\n')
                    for form in lemma_data['forms']:
                        if form['ipa']:
                            f.write(format_word_entry(
                                main_text=None,  # No translation in Shavian-Shavian
                                ipa=form['ipa'],
                                pos_code=form['pos'],
                                lemma=lemma,
                                lemma_ipa=lemma_ipa,
                                var_code=form['var'],
                                show_variants=show_variants,
                                shavian_lookup=shavian_lookup
                            ))
                    f.write('    </div>\n')

                # Definitions for this lemma (all in Shavian)
                if lemma_data['definitions']:
                    f.write('    <div class="definitions">\n')
                    for i, def_data in enumerate(lemma_data['definitions'][:5], 1):
                        # POS is already transliterated in cache for sha-sha
                        f.write(f'      <div class="definition">\n')
                        f.write(f'        <p><b>{i}. </b><i>({escape(def_data["pos"])})</i> {escape(def_data["definition"])}</p>\n')
                        f.write('      </div>\n')
                    f.write('    </div>\n')
                else:
                    # No definitions for this lemma
                    f.write('    <div class="definitions">\n')
                    f.write('      <p><i>(No definitions available)</i></p>\n')
                    f.write('    </div>\n')

            f.write('  </d:entry>\n')

            # Flush every 1000 entries
            if idx % 1000 == 0:
                f.flush()
                print(f"  Writing: {idx}/{total} entries ({(idx/total)*100:.1f}%)")

        f.write(create_xml_footer())
        f.flush()

    print(f"Generated {len(shavian_entries)} Shavian entries → {output_path}")


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
        generate_shavian_to_english(readlex_data, wordnet_defs, shavian_english_path)
        print()

    if 'english-shavian' in dictionaries:
        generate_english_to_shavian(readlex_data, shavian_def_cache, english_shavian_path, dialect)
        print()

    if 'shavian-shavian' in dictionaries:
        generate_shavian_to_shavian(readlex_data, shavian_def_cache, shavian_shavian_path, dialect)
        print()

    print(f"Dictionary generation complete ({dialect.upper()})!")
    for dict_name in dictionaries:
        dict_path = build_dir / f"{dict_name}-{dialect}.xml"
        print(f"  - {dict_path}")


if __name__ == '__main__':
    main()
