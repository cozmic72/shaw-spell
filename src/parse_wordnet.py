#!/usr/bin/env python3
"""
Parse Open English WordNet XML file to extract definitions.
Creates a JSON file mapping words to their definitions.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict


def parse_wordnet_xml(xml_path):
    """Parse WordNet XML and extract word definitions."""
    print(f"Parsing WordNet XML from {xml_path}...")
    print("This may take a minute...")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Build synset definitions mapping
    print("Extracting synsets...")
    synsets = {}
    for synset in root.findall('.//Synset'):
        synset_id = synset.get('id')
        definitions = []
        examples = []

        for definition in synset.findall('Definition'):
            if definition.text:
                definitions.append(definition.text)

        for example in synset.findall('Example'):
            if example.text:
                examples.append(example.text)

        if definitions:
            synsets[synset_id] = {
                'definitions': definitions,
                'examples': examples[:2]  # Limit to 2 examples
            }

    print(f"Loaded {len(synsets)} synsets with definitions")

    # Extract word -> definition mappings
    print("Extracting word definitions...")
    word_definitions = defaultdict(list)

    for lexicon in root.findall('Lexicon'):
        for lex_entry in lexicon.findall('LexicalEntry'):
            lemma = lex_entry.find('Lemma')
            if lemma is None:
                continue

            written_form = lemma.get('writtenForm', '').lower()
            pos = lemma.get('partOfSpeech', '')

            # Map POS abbreviations to full names
            pos_map = {
                'n': 'noun',
                'v': 'verb',
                'a': 'adjective',
                's': 'adjective',  # satellite adjective
                'r': 'adverb'
            }
            pos_full = pos_map.get(pos, pos)

            # Get all senses for this word
            for sense in lex_entry.findall('Sense'):
                synset_id = sense.get('synset')
                if synset_id and synset_id in synsets:
                    synset_data = synsets[synset_id]

                    for definition in synset_data['definitions']:
                        def_entry = {
                            'definition': definition,
                            'pos': pos_full,
                            'examples': synset_data['examples']
                        }

                        # Avoid exact duplicates
                        if def_entry not in word_definitions[written_form]:
                            word_definitions[written_form].append(def_entry)

    print(f"Extracted definitions for {len(word_definitions)} words")
    return dict(word_definitions)


def main():
    """Main function."""
    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    wordnet_xml_path = project_dir / 'external/english-wordnet-2024.xml'
    output_path = project_dir / 'build/wordnet-definitions.json'

    if not wordnet_xml_path.exists():
        print(f"Error: WordNet XML file not found: {wordnet_xml_path}")
        print("Please download it first with:")
        print("  curl -L -o external/english-wordnet-2024.xml.gz https://en-word.net/static/english-wordnet-2024.xml.gz")
        print("  gunzip external/english-wordnet-2024.xml.gz")
        return 1

    # Parse WordNet XML
    definitions = parse_wordnet_xml(wordnet_xml_path)

    # Save to JSON
    print(f"\nSaving definitions to {output_path}...")
    project_dir.joinpath('build').mkdir(exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(definitions, f, indent=2, ensure_ascii=False)

    print(f"Done! Definitions saved to {output_path}")
    print(f"Total words with definitions: {len(definitions)}")

    return 0


if __name__ == '__main__':
    exit(main())
