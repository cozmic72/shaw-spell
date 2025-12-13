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


def create_xml_header(dict_name, from_lang, to_lang):
    """Create XML header."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<d:dictionary xmlns="http://www.w3.org/1999/xhtml" xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rdf">
<!-- {dict_name}: {from_lang} to {to_lang} -->
'''


def create_xml_footer():
    """Create XML footer."""
    return '</d:dictionary>\n'


def generate_shavian_to_english(readlex_data, wordnet_defs, output_path):
    """Generate Shavian → English dictionary with definitions."""
    print("Generating Shavian → English dictionary...")

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
        f.write(create_xml_header('Shavian-English', 'Shavian', 'English'))
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

                # Forms for this lemma
                f.write('    <div class="forms">\n')
                for form in lemma_data['forms']:
                    parts = [f'<b>{escape(form["latn"])}</b>']
                    if form['ipa']:
                        parts.append(f' <span class="ipa">/{escape(form["ipa"])}/</span>')
                    if form['pos']:
                        pos_readable = pos_to_readable(form['pos'])
                        if pos_readable:
                            parts.append(f' <i>{escape(pos_readable)}</i>')
                    if form['var']:
                        var_label = variant_to_label(form['var'])
                        parts.append(f' <span class="variant">({escape(var_label)})</span>')
                    f.write(f'      <p>{"".join(parts)}</p>\n')
                f.write('    </div>\n')

                # Definitions for this lemma
                if lemma_data['definitions']:
                    f.write('    <div class="definitions">\n')
                    for i, def_data in enumerate(lemma_data['definitions'][:5], 1):  # Limit to 5 definitions
                        f.write(f'      <div class="definition">\n')
                        f.write(f'        <p><b>{i}.</b> <i>({escape(def_data["pos"])})</i> {escape(def_data["definition"])}</p>\n')
                        if def_data.get('examples'):
                            f.write('        <ul class="examples">\n')
                            for ex in def_data['examples'][:2]:
                                f.write(f'          <li>{escape(ex)}</li>\n')
                            f.write('        </ul>\n')
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


def generate_english_to_shavian(readlex_data, shavian_def_cache, output_path):
    """Generate English → Shavian dictionary with transliterated definitions."""
    print("Generating English → Shavian dictionary...")

    # Build entries structure using cached transliterations
    english_entries = defaultdict(lambda: {'forms': [], 'definitions': []})

    for key, data in readlex_data.items():
        lemma = data['lemma']
        entries = data['entries']

        # Get transliterated definitions from cache
        lemma_trans = shavian_def_cache.get(lemma, [])

        # Group by English spelling (case-insensitive)
        for entry in entries:
            latn = entry['Latn']
            latn_lower = latn.lower()
            shaw = entry['Shaw']
            pos = entry.get('pos', '')
            ipa = entry.get('ipa', '')
            var = entry.get('var', '')

            # Add form
            form_info = {
                'shaw': shaw,
                'pos': pos,
                'ipa': ipa,
                'var': var
            }
            if form_info not in english_entries[latn_lower]['forms']:
                english_entries[latn_lower]['forms'].append(form_info)

            # Add transliterated definitions if not already added
            if not english_entries[latn_lower]['definitions'] and lemma_trans:
                # Convert cached format to dictionary format
                resolved_defs = []
                for trans_def in lemma_trans:
                    resolved_defs.append({
                        'definition': trans_def['transliterated_definition'],
                        'pos': trans_def['pos'],  # Keep original POS for now
                        'examples': trans_def['transliterated_examples']
                    })
                english_entries[latn_lower]['definitions'] = resolved_defs

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('English-Shavian', 'English', 'Shavian'))
        f.flush()

        total = len(english_entries)
        for idx, latn in enumerate(sorted(english_entries.keys()), 1):
            entry_data = english_entries[latn]
            entry_id = f"eng_{latn}"

            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(latn)}">\n')
            f.write(f'    <d:index d:value="{escape(latn)}"/>\n')
            f.write(f'    <h1>{escape(latn)}</h1>\n')

            # Forms
            f.write('    <div class="forms">\n')
            for form in entry_data['forms']:
                parts = [f'<b>{escape(form["shaw"])}</b>']
                if form['ipa']:
                    parts.append(f' <span class="ipa">/{escape(form["ipa"])}/</span>')
                if form['pos']:
                    pos_readable = pos_to_readable(form['pos'])
                    if pos_readable:
                        parts.append(f' <i>{escape(pos_readable)}</i>')
                if form['var']:
                    var_label = variant_to_label(form['var'])
                    parts.append(f' <span class="variant">({escape(var_label)})</span>')
                f.write(f'      <p>{"".join(parts)}</p>\n')
            f.write('    </div>\n')

            # Definitions (in Shavian)
            if entry_data['definitions']:
                f.write('    <div class="definitions">\n')
                for i, def_data in enumerate(entry_data['definitions'][:5], 1):
                    f.write(f'      <div class="definition">\n')
                    f.write(f'        <p><b>{i}.</b> <i>({escape(def_data["pos"])})</i> {escape(def_data["definition"])}</p>\n')
                    if def_data.get('examples'):
                        f.write('        <ul class="examples">\n')
                        for ex in def_data['examples'][:2]:
                            f.write(f'          <li>{escape(ex)}</li>\n')
                        f.write('        </ul>\n')
                    f.write('      </div>\n')
                f.write('    </div>\n')

            f.write('  </d:entry>\n')

            # Flush every 1000 entries
            if idx % 1000 == 0:
                f.flush()
                print(f"  Writing: {idx}/{total} entries ({(idx/total)*100:.1f}%)")

        f.write(create_xml_footer())
        f.flush()

    print(f"Generated {len(english_entries)} English entries → {output_path}")


def generate_shavian_to_shavian(readlex_data, shavian_def_cache, output_path):
    """Generate Shavian → Shavian dictionary (Shavian word with Shavian definitions)."""
    print("Generating Shavian → Shavian dictionary...")

    # Build entries structure using cached transliterations
    shavian_entries = defaultdict(lambda: {'forms': [], 'definitions': []})

    for key, data in readlex_data.items():
        lemma = data['lemma']
        entries = data['entries']

        # Get transliterated definitions from cache
        lemma_trans = shavian_def_cache.get(lemma, [])

        # Group by Shavian spelling
        for entry in entries:
            shaw = entry['Shaw']
            pos = entry.get('pos', '')
            ipa = entry.get('ipa', '')
            var = entry.get('var', '')

            # Add form
            form_info = {
                'shaw': shaw,
                'pos': pos,
                'ipa': ipa,
                'var': var
            }
            if form_info not in shavian_entries[shaw]['forms']:
                shavian_entries[shaw]['forms'].append(form_info)

            # Add transliterated definitions if not already added
            if not shavian_entries[shaw]['definitions'] and lemma_trans:
                # Convert cached format to dictionary format
                resolved_defs = []
                for trans_def in lemma_trans:
                    resolved_defs.append({
                        'definition': trans_def['transliterated_definition'],
                        'pos': trans_def['transliterated_pos'],  # Use transliterated POS
                        'examples': trans_def['transliterated_examples']
                    })
                shavian_entries[shaw]['definitions'] = resolved_defs

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('Shavian-Shavian', 'Shavian', 'Shavian'))
        f.flush()

        total = len(shavian_entries)
        for idx, shaw in enumerate(sorted(shavian_entries.keys()), 1):
            entry_data = shavian_entries[shaw]
            entry_id = f"shavian_{shaw}"

            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(shaw)}">\n')
            f.write(f'    <d:index d:value="{escape(shaw)}"/>\n')
            f.write(f'    <h1>{escape(shaw)}</h1>\n')

            # Forms (pronunciation info)
            if any(f['ipa'] for f in entry_data['forms']):
                f.write('    <div class="forms">\n')
                for form in entry_data['forms']:
                    if form['ipa']:
                        parts = [f'<span class="ipa">/{escape(form["ipa"])}/</span>']
                        if form['var']:
                            var_label = variant_to_label(form['var'])
                            parts.append(f' <span class="variant">({escape(var_label)})</span>')
                        f.write(f'      <p>{"".join(parts)}</p>\n')
                f.write('    </div>\n')

            # Definitions (all in Shavian)
            if entry_data['definitions']:
                f.write('    <div class="definitions">\n')
                for i, def_data in enumerate(entry_data['definitions'][:5], 1):
                    f.write(f'      <div class="definition">\n')
                    f.write(f'        <p><b>{i}.</b> <i>({escape(def_data["pos"])})</i> {escape(def_data["definition"])}</p>\n')
                    if def_data.get('examples'):
                        f.write('        <ul class="examples">\n')
                        for ex in def_data['examples'][:2]:
                            f.write(f'          <li>{escape(ex)}</li>\n')
                        f.write('        </ul>\n')
                    f.write('      </div>\n')
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

    # Default to all dictionaries if none specified
    if not dictionaries:
        dictionaries = ['shavian-english', 'english-shavian', 'shavian-shavian']

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    readlex_path = project_dir / '../shavian-info/readlex/readlex.json'
    wordnet_path = project_dir / 'build/wordnet-definitions.json'
    shavian_defs_path = project_dir / 'data/definitions-shavian.json'
    build_dir = project_dir / 'build'

    shavian_english_path = build_dir / 'shavian-english.xml'
    english_shavian_path = build_dir / 'english-shavian.xml'
    shavian_shavian_path = build_dir / 'shavian-shavian.xml'

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
        generate_english_to_shavian(readlex_data, shavian_def_cache, english_shavian_path)
        print()

    if 'shavian-shavian' in dictionaries:
        generate_shavian_to_shavian(readlex_data, shavian_def_cache, shavian_shavian_path)
        print()

    print("Dictionary generation complete!")
    for dict_name in dictionaries:
        dict_path = build_dir / f"{dict_name}.xml"
        print(f"  - {dict_path}")


if __name__ == '__main__':
    main()
