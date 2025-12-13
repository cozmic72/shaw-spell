#!/usr/bin/env python3
"""
CLI tool for testing dictionary lookups.

Tests the generated dictionary XML files to verify entries are correct
without needing to compile and install them in Dictionary.app.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import argparse


def load_dictionary(xml_path):
    """
    Load dictionary XML and build lookup index.

    Returns:
        dict: Mapping from index words to list of entry elements
    """
    print(f"Loading dictionary from {xml_path}...")

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"ERROR: Failed to load XML: {e}")
        return {}

    # Define namespace
    ns = {'d': 'http://www.apple.com/DTDs/DictionaryService-1.0.rdf'}

    # Build index: word -> list of entries
    index = {}
    entry_count = 0

    for entry in root.findall('.//d:entry', ns):
        entry_count += 1

        # Get all d:index values for this entry
        for index_elem in entry.findall('d:index', ns):
            index_word = index_elem.get(f'{{{ns["d"]}}}value')
            if index_word:
                if index_word not in index:
                    index[index_word] = []
                index[index_word].append(entry)

    print(f"Loaded {entry_count} entries with {len(index)} unique index words")
    return index, ns


def format_entry(entry, ns):
    """
    Format an entry element for display.

    Returns:
        str: Formatted entry text
    """
    lines = []

    # Get h1 title
    h1 = entry.find('h1')
    if h1 is not None and h1.text:
        lines.append(f"\n{'='*60}")
        lines.append(f"  {h1.text}")
        lines.append(f"{'='*60}")

    # Get forms section
    forms_div = entry.find(".//div[@class='forms']")
    if forms_div is not None:
        lines.append("\nForms:")
        for form_div in forms_div.findall('div'):
            # Get all text from the form div, including nested spans
            form_text = ''.join(form_div.itertext()).strip()
            class_name = form_div.get('class', '')
            indent = '  ' if class_name == 'lemma-form' else '    '
            lines.append(f"{indent}{form_text}")

    # Get definitions section
    defs_div = entry.find(".//div[@class='definitions']")
    if defs_div is not None:
        lines.append("\nDefinitions:")
        for pos_group in defs_div.findall(".//div[@class='pos-group']"):
            # Get part of speech from h3
            pos_h3 = pos_group.find('h3')
            if pos_h3 is not None:
                pos_text = ''.join(pos_h3.itertext()).strip()
                lines.append(f"  {pos_text}")

            # Get definitions from paragraphs
            for p in pos_group.findall('p'):
                def_text = ''.join(p.itertext()).strip()
                lines.append(f"    {def_text}")

    return '\n'.join(lines)


def interactive_lookup(index, ns):
    """Run interactive lookup loop."""
    print("\nInteractive mode. Enter a word to look up, or 'quit' to exit.")
    print("You can also use 'list <prefix>' to see all words starting with a prefix.\n")

    while True:
        try:
            query = input("lookup> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not query:
            continue

        if query.lower() in ('quit', 'exit', 'q'):
            print("Exiting.")
            break

        # Handle list command
        if query.lower().startswith('list '):
            prefix = query[5:].strip().lower()
            matches = [word for word in index.keys() if word.lower().startswith(prefix)]
            matches.sort()

            if not matches:
                print(f"No words found starting with '{prefix}'")
            else:
                print(f"\nFound {len(matches)} words starting with '{prefix}':")
                for i, word in enumerate(matches[:50], 1):  # Limit to 50
                    print(f"  {word}")
                if len(matches) > 50:
                    print(f"  ... and {len(matches) - 50} more")
            print()
            continue

        # Normal lookup
        query_lower = query.lower()

        if query_lower in index:
            entries = index[query_lower]
            print(f"\nFound {len(entries)} entry/entries for '{query}':")

            for i, entry in enumerate(entries, 1):
                if len(entries) > 1:
                    print(f"\n--- Entry {i}/{len(entries)} ---")
                print(format_entry(entry, ns))
        else:
            print(f"\nNo entry found for '{query}'")

            # Suggest similar words
            similar = [word for word in index.keys()
                      if word.lower().startswith(query_lower[:3]) and len(query) >= 3]
            if similar:
                similar.sort()
                print(f"\nDid you mean one of these?")
                for word in similar[:10]:  # Show up to 10 suggestions
                    print(f"  {word}")

        print()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Test dictionary lookups')
    parser.add_argument('dictionary', choices=['shaw-eng', 'eng-shaw', 'shaw-shaw'],
                       help='Which dictionary to test')
    parser.add_argument('--dialect', choices=['gb', 'us'], default='gb',
                       help='Dialect version (gb or us)')
    parser.add_argument('--word', '-w', type=str,
                       help='Look up a specific word and exit (non-interactive)')

    args = parser.parse_args()

    # Map dictionary names to filenames
    dict_map = {
        'shaw-eng': 'shavian-english',
        'eng-shaw': 'english-shavian',
        'shaw-shaw': 'shavian-shavian'
    }

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    build_dir = project_dir / 'build'

    dict_filename = f"{dict_map[args.dictionary]}-{args.dialect}.xml"
    xml_path = build_dir / dict_filename

    if not xml_path.exists():
        print(f"ERROR: Dictionary file not found: {xml_path}")
        print("Please run: ./build.sh to generate dictionaries")
        sys.exit(1)

    # Load dictionary
    index, ns = load_dictionary(xml_path)

    if not index:
        print("ERROR: Failed to load dictionary or dictionary is empty")
        sys.exit(1)

    # Single word lookup or interactive mode
    if args.word:
        query = args.word.lower()
        if query in index:
            entries = index[query]
            for entry in entries:
                print(format_entry(entry, ns))
        else:
            print(f"No entry found for '{args.word}'")
            sys.exit(1)
    else:
        interactive_lookup(index, ns)


if __name__ == '__main__':
    main()
