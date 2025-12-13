#!/usr/bin/env python3
"""
Generate macOS dictionaries for Shavian-English translation.
Reads from ../shavian-info/readlex/readlex.json and generates:
- shavian-english.xml (Shavian → English)
- english-shavian.xml (English → Shavian)
"""

import json
import os
from pathlib import Path
from html import escape


def load_readlex_data(json_path):
    """Load the readlex.json data."""
    print(f"Loading data from {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} entries")
    return data


def create_xml_header(dict_name, from_lang, to_lang):
    """Create the XML header for a dictionary."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<d:dictionary xmlns="http://www.w3.org/1999/xhtml" xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rdf">
<!-- {dict_name}: {from_lang} to {to_lang} -->
'''


def create_xml_footer():
    """Create the XML footer."""
    return '</d:dictionary>\n'


def generate_shavian_to_english(data, output_path):
    """Generate Shavian → English dictionary."""
    print(f"Generating Shavian → English dictionary...")

    # Collect entries by Shavian word
    shavian_entries = {}
    for key, entries in data.items():
        for entry in entries:
            shaw = entry['Shaw']
            latn = entry['Latn']
            pos = entry.get('pos', '')

            if shaw not in shavian_entries:
                shavian_entries[shaw] = []
            shavian_entries[shaw].append((latn, pos))

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('Shavian-English', 'Shavian', 'English'))

        for shaw in sorted(shavian_entries.keys()):
            translations = shavian_entries[shaw]
            entry_id = f"shaw_{shaw}"

            # Start entry
            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(shaw)}">\n')
            f.write(f'    <d:index d:value="{escape(shaw)}"/>\n')
            f.write(f'    <h1>{escape(shaw)}</h1>\n')

            # Add translations
            f.write('    <ul>\n')
            for latn, pos in translations:
                pos_label = f" ({pos})" if pos else ""
                f.write(f'      <li><b>{escape(latn)}</b>{escape(pos_label)}</li>\n')
            f.write('    </ul>\n')

            f.write('  </d:entry>\n')

        f.write(create_xml_footer())

    print(f"Generated {len(shavian_entries)} Shavian entries → {output_path}")


def generate_english_to_shavian(data, output_path):
    """Generate English → Shavian dictionary."""
    print(f"Generating English → Shavian dictionary...")

    # Collect entries by English word
    english_entries = {}
    for key, entries in data.items():
        for entry in entries:
            latn = entry['Latn']
            shaw = entry['Shaw']
            pos = entry.get('pos', '')

            if latn not in english_entries:
                english_entries[latn] = []
            english_entries[latn].append((shaw, pos))

    # Write XML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(create_xml_header('English-Shavian', 'English', 'Shavian'))

        for latn in sorted(english_entries.keys()):
            translations = english_entries[latn]
            entry_id = f"eng_{latn}"

            # Start entry
            f.write(f'  <d:entry id="{escape(entry_id)}" d:title="{escape(latn)}">\n')
            f.write(f'    <d:index d:value="{escape(latn)}"/>\n')
            f.write(f'    <h1>{escape(latn)}</h1>\n')

            # Add translations
            f.write('    <ul>\n')
            for shaw, pos in translations:
                pos_label = f" ({pos})" if pos else ""
                f.write(f'      <li><b>{escape(shaw)}</b>{escape(pos_label)}</li>\n')
            f.write('    </ul>\n')

            f.write('  </d:entry>\n')

        f.write(create_xml_footer())

    print(f"Generated {len(english_entries)} English entries → {output_path}")


def main():
    """Main function."""
    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    readlex_path = project_dir / '../shavian-info/readlex/readlex.json'
    build_dir = project_dir / 'build'
    shavian_english_path = build_dir / 'shavian-english.xml'
    english_shavian_path = build_dir / 'english-shavian.xml'

    # Ensure build directory exists
    build_dir.mkdir(exist_ok=True)

    # Load data
    data = load_readlex_data(readlex_path)

    # Generate dictionaries
    generate_shavian_to_english(data, shavian_english_path)
    generate_english_to_shavian(data, english_shavian_path)

    print("\nDictionary generation complete!")
    print(f"  - {shavian_english_path}")
    print(f"  - {english_shavian_path}")


if __name__ == '__main__':
    main()
