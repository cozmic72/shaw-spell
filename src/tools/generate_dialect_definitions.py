#!/usr/bin/env python3
"""
Generate dialect-specific definition files (US/GB) from WordNet definitions.

This script takes WordNet definitions (which are predominantly in American English)
and creates two versions:
- definitions-latin-us.json: American English spelling
- definitions-latin-gb.json: British English spelling

It uses the US/GB variant mappings from the WordNet comprehensive cache to
intelligently replace American spellings with British ones (or vice versa).

Usage:
    ./src/tools/generate_dialect_definitions.py [--output-dir PATH]
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, Set, Tuple


def build_spelling_maps(wordnet_cache: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Build US→GB and GB→US spelling conversion dictionaries from WordNet cache.

    Returns:
        Tuple of (us_to_gb, gb_to_us) dictionaries
    """
    print("Building spelling conversion maps from WordNet...")

    us_to_gb = {}
    gb_to_us = {}

    for lemma, entry in wordnet_cache.items():
        for pos, pos_data in entry.get('pos_entries', {}).items():
            for sense in pos_data.get('sense_variants', []):
                variants = sense.get('variants', {})

                if 'US' not in variants or 'GB' not in variants:
                    continue

                us_variants = variants['US']
                gb_variants = variants['GB']

                # Map each US variant to each GB variant and vice versa
                for us_word in us_variants:
                    for gb_word in gb_variants:
                        if us_word != gb_word:
                            # Store mappings (prefer first occurrence)
                            if us_word.lower() not in us_to_gb:
                                us_to_gb[us_word.lower()] = gb_word.lower()
                            if gb_word.lower() not in gb_to_us:
                                gb_to_us[gb_word.lower()] = us_word.lower()

    print(f"  Found {len(us_to_gb)} US→GB spelling pairs")
    print(f"  Found {len(gb_to_us)} GB→US spelling pairs")

    return us_to_gb, gb_to_us


def convert_text_to_dialect(text: str, spelling_map: Dict[str, str]) -> str:
    """
    Convert text to a different dialect using spelling map.

    Handles:
    - Whole word replacement with case preservation
    - Words at start of sentences (capitalized)
    - Hyphenated compounds

    Args:
        text: The text to convert
        spelling_map: Dictionary mapping source spellings to target spellings

    Returns:
        Converted text
    """
    if not text:
        return text

    # Use word boundaries to match whole words only
    # This regex matches words (including hyphenated compounds)
    def replace_word(match):
        word = match.group(0)
        word_lower = word.lower()

        # Handle hyphenated compounds by converting each part
        if '-' in word:
            parts = word.split('-')
            converted_parts = []
            for part in parts:
                part_lower = part.lower()
                if part_lower in spelling_map:
                    # Preserve case
                    if part[0].isupper():
                        converted_parts.append(spelling_map[part_lower].capitalize())
                    else:
                        converted_parts.append(spelling_map[part_lower])
                else:
                    converted_parts.append(part)
            return '-'.join(converted_parts)

        # Simple word replacement
        if word_lower in spelling_map:
            replacement = spelling_map[word_lower]
            # Preserve case
            if word[0].isupper():
                return replacement.capitalize()
            else:
                return replacement

        return word

    # Match words (including hyphenated compounds)
    # Word boundary \b doesn't work well with hyphens, so use a more explicit pattern
    pattern = r'\b[a-zA-Z]+(?:-[a-zA-Z]+)*\b'
    result = re.sub(pattern, replace_word, text)

    return result


def convert_definitions_to_dialect(
    wordnet_defs: Dict,
    spelling_map: Dict[str, str],
    dialect_name: str
) -> Dict:
    """
    Convert all definitions to target dialect.

    Args:
        wordnet_defs: Dictionary of {lemma: [{definition, pos, examples, source}]}
        spelling_map: Spelling conversion map
        dialect_name: Name of target dialect (for logging)

    Returns:
        New dictionary with converted definitions
    """
    print(f"Converting definitions to {dialect_name}...")

    converted = {}
    total_defs = 0
    converted_count = 0

    for lemma, definitions in wordnet_defs.items():
        converted_lemma_defs = []

        for def_entry in definitions:
            # Convert definition text
            orig_definition = def_entry.get('definition', '')
            new_definition = convert_text_to_dialect(orig_definition, spelling_map)

            # Convert examples if present
            orig_examples = def_entry.get('examples', [])
            new_examples = [convert_text_to_dialect(ex, spelling_map) for ex in orig_examples]

            # Track if anything changed
            if new_definition != orig_definition or new_examples != orig_examples:
                converted_count += 1

            total_defs += 1

            entry = {
                'definition': new_definition,
                'pos': def_entry.get('pos', ''),
                'examples': new_examples
            }
            # Preserve source attribution
            if 'source' in def_entry:
                entry['source'] = def_entry['source']

            converted_lemma_defs.append(entry)

        converted[lemma] = converted_lemma_defs

    print(f"  Converted {converted_count}/{total_defs} definitions")
    return converted


def extract_lemma_from_readlex_key(key: str) -> str:
    """Extract lemma from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if parts:
        return parts[0].lower()
    return ''


def extract_definitions_from_wordnet(wordnet_cache: Dict, readlex_lemmas: Set[str]) -> Dict:
    """
    Extract definitions from WordNet comprehensive cache for all readlex lemmas.

    Args:
        wordnet_cache: The comprehensive WordNet cache
        readlex_lemmas: Set of lowercased lemmas from readlex

    Returns:
        Dictionary of {lemma: [{definition, pos, examples, source}]}
    """
    print("Extracting definitions from WordNet comprehensive cache...")

    wordnet_defs = {}
    matched_lemmas = 0

    for wn_lemma, entry in wordnet_cache.items():
        # Match case-insensitively against readlex lemmas
        if wn_lemma.lower() not in readlex_lemmas:
            continue

        matched_lemmas += 1
        lemma_key = wn_lemma.lower()

        if lemma_key not in wordnet_defs:
            wordnet_defs[lemma_key] = []

        for pos, pos_data in entry.get('pos_entries', {}).items():
            for sense in pos_data.get('sense_variants', []):
                sense_defs = sense.get('definitions', [])
                for def_text in sense_defs:
                    wordnet_defs[lemma_key].append({
                        'definition': def_text,
                        'pos': pos,
                        'examples': [],
                        'source': 'WordNet'
                    })

    print(f"  Matched {matched_lemmas} WordNet entries to readlex lemmas")
    total_defs = sum(len(v) for v in wordnet_defs.values())
    print(f"  Extracted {total_defs} definitions for {len(wordnet_defs)} unique lemmas")

    return wordnet_defs


def main():
    """Main function."""
    # Parse arguments
    output_dir = None
    for i, arg in enumerate(sys.argv):
        if arg == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = Path(sys.argv[i + 1])

    # Set up paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent

    wordnet_cache_path = project_dir / 'data/wordnet-comprehensive.json'
    readlex_path = project_dir / 'data/readlex.json'

    if output_dir is None:
        output_dir = project_dir / 'data'

    us_output_path = output_dir / 'definitions-latin-us.json'
    gb_output_path = output_dir / 'definitions-latin-gb.json'

    # Load WordNet comprehensive cache
    print("Loading WordNet comprehensive cache...")
    if not wordnet_cache_path.exists():
        print(f"ERROR: WordNet cache not found at {wordnet_cache_path}")
        print("Please run: make wordnet-cache")
        sys.exit(1)

    with open(wordnet_cache_path, 'r', encoding='utf-8') as f:
        wordnet_cache = json.load(f)
    print(f"Loaded {len(wordnet_cache)} entries\n")

    # Load readlex to get lemma set
    print("Loading readlex...")
    if not readlex_path.exists():
        print(f"ERROR: readlex not found at {readlex_path}")
        sys.exit(1)

    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_raw = json.load(f)

    readlex_lemmas = set()
    for key in readlex_raw:
        lemma = extract_lemma_from_readlex_key(key)
        if lemma:
            readlex_lemmas.add(lemma)
    print(f"Found {len(readlex_lemmas)} unique readlex lemmas\n")

    # Extract definitions directly from WordNet comprehensive cache
    # (previously this read from the Shavian cache, limiting coverage)
    wordnet_defs = extract_definitions_from_wordnet(wordnet_cache, readlex_lemmas)
    print()

    # Merge Wiktionary definitions if available
    wiktionary_defs_path = project_dir / 'data/definitions-wiktionary.json'
    if wiktionary_defs_path.exists():
        print("Loading Wiktionary definitions...")
        with open(wiktionary_defs_path, 'r', encoding='utf-8') as f:
            wikt_defs = json.load(f)
        print(f"  Loaded {len(wikt_defs)} Wiktionary definition entries")

        # Merge: Wiktionary entries use keys like "word|wikt-N"
        # Add them directly to the definitions dict
        for key, defs_list in wikt_defs.items():
            wordnet_defs[key] = defs_list

        wikt_words = set(k.split('|')[0] for k in wikt_defs)
        print(f"  Added definitions for {len(wikt_words)} words from Wiktionary")
        print()

    # Build spelling conversion maps
    us_to_gb, gb_to_us = build_spelling_maps(wordnet_cache)
    print()

    # Generate US version (convert any GB spellings to US)
    # Most definitions are already in US English, so this mainly normalizes
    us_definitions = convert_definitions_to_dialect(wordnet_defs, gb_to_us, "US English")

    # Generate GB version (convert US spellings to GB)
    gb_definitions = convert_definitions_to_dialect(wordnet_defs, us_to_gb, "GB English")

    print()

    # Write output files
    print(f"Writing US definitions to {us_output_path}...")
    with open(us_output_path, 'w', encoding='utf-8') as f:
        json.dump(us_definitions, f, ensure_ascii=False, indent=2)

    print(f"Writing GB definitions to {gb_output_path}...")
    with open(gb_output_path, 'w', encoding='utf-8') as f:
        json.dump(gb_definitions, f, ensure_ascii=False, indent=2)

    total_us = sum(len(v) for v in us_definitions.values())
    total_gb = sum(len(v) for v in gb_definitions.values())

    print("\nDone!")
    print(f"Generated:")
    print(f"  - {us_output_path}: {len(us_definitions)} lemmas, {total_us} definitions")
    print(f"  - {gb_output_path}: {len(gb_definitions)} lemmas, {total_gb} definitions")


if __name__ == '__main__':
    main()
