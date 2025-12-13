#!/usr/bin/env python3
"""
WordNet dialect information extractor.

Extracts authoritative dialect markers (American, British, Canadian, Australian)
from Open English WordNet XML files, replacing heuristic-based dialect detection.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, Optional, List


class WordNetDialectData:
    """
    Manages dialect information extracted from WordNet.

    Structure:
        word_dialects: word → set of dialects ('US', 'GB', 'CA', 'AU')
        word_synsets: word → set of synsets
        synset_variants: synset → {dialect → word}
    """

    def __init__(self):
        self.word_dialects: Dict[str, Set[str]] = defaultdict(set)
        self.word_synsets: Dict[str, Set[str]] = defaultdict(set)
        self.synset_variants: Dict[str, Dict[str, str]] = defaultdict(dict)

    def add_entry(self, word: str, synset: str, dialects: Set[str]):
        """Add a word entry with its synset and dialects."""
        word_lower = word.lower()

        # Record word → dialects
        self.word_dialects[word_lower].update(dialects)

        # Record word → synsets
        self.word_synsets[word_lower].add(synset)

        # Record synset → {dialect → word}
        for dialect in dialects:
            self.synset_variants[synset][dialect] = word_lower

    def get_dialects(self, word: str) -> Set[str]:
        """Get all dialects for a word (e.g., {'US'}, {'GB', 'CA', 'AU'})."""
        return self.word_dialects.get(word.lower(), set())

    def get_variant_for_dialect(self, word: str, target_dialect: str) -> Optional[str]:
        """
        Get the spelling variant of a word for a target dialect.

        For example:
            get_variant_for_dialect('color', 'GB') → 'colour'
            get_variant_for_dialect('colour', 'US') → 'color'

        Returns None if no variant exists for the target dialect.
        """
        word_lower = word.lower()

        # Get synsets for this word
        synsets = self.word_synsets.get(word_lower, set())

        # For each synset, check if there's a variant for the target dialect
        for synset in synsets:
            if synset in self.synset_variants:
                variants = self.synset_variants[synset]
                if target_dialect in variants:
                    variant = variants[target_dialect]
                    # Don't return the same word
                    if variant != word_lower:
                        return variant

        return None

    def get_all_variants(self, word: str) -> Dict[str, str]:
        """
        Get all spelling variants of a word across all dialects.

        Returns: dict mapping dialect → word (e.g., {'US': 'color', 'GB': 'colour'})
        """
        word_lower = word.lower()
        all_variants = {}

        # Get synsets for this word (sorted for deterministic iteration)
        synsets = sorted(self.word_synsets.get(word_lower, set()))

        # Collect all variants from all synsets
        for synset in synsets:
            if synset in self.synset_variants:
                all_variants.update(self.synset_variants[synset])

        return all_variants


def load_wordnet_dialect_data(wordnet_xml_path: Path) -> WordNetDialectData:
    """
    Load dialect information from WordNet XML file.

    Extracts words with dialect markers like:
        <SenseRelation relType="exemplifies" target="oewn-american_spelling__1.10.01.."/>
        <SenseRelation relType="exemplifies" target="oewn-british_spelling__1.10.01.."/>

    Returns:
        WordNetDialectData object with dialect lookups
    """
    print("Loading WordNet dialect data...")

    data = WordNetDialectData()

    # Dialect marker to code mapping
    dialect_markers = {
        'american_spelling': 'US',
        'british_spelling': 'GB',
        'canadian_spelling': 'CA',
        'australian_spelling': 'AU'
    }

    # Parse XML
    tree = ET.parse(wordnet_xml_path)
    root = tree.getroot()

    # Find all LexicalEntry elements
    for entry in root.findall('.//LexicalEntry'):
        lemma_elem = entry.find('Lemma')
        if lemma_elem is None:
            continue

        word = lemma_elem.get('writtenForm')
        if not word:
            continue

        # Check all senses for dialect markers
        for sense in entry.findall('.//Sense'):
            synset = sense.get('synset')
            if not synset:
                continue

            # Find dialect markers in sense relations
            dialects = set()
            for sense_rel in sense.findall('SenseRelation'):
                rel_type = sense_rel.get('relType')
                target = sense_rel.get('target', '')

                if rel_type == 'exemplifies':
                    # Extract dialect from target like "oewn-american_spelling__1.10.01.."
                    for marker, code in dialect_markers.items():
                        if marker in target:
                            dialects.add(code)

            # If this sense has dialect markers, record it
            if dialects:
                data.add_entry(word, synset, dialects)

    print(f"Loaded dialect data for {len(data.word_dialects)} words")
    print(f"  - US words: {sum(1 for d in data.word_dialects.values() if 'US' in d)}")
    print(f"  - GB words: {sum(1 for d in data.word_dialects.values() if 'GB' in d)}")
    print(f"  - Variant pairs: {len(data.synset_variants)}")

    return data


# Global cache for loaded dialect data
_dialect_data_cache: Optional[WordNetDialectData] = None
_cached_wordnet_path: Optional[Path] = None


def get_dialect_data(wordnet_xml_path: Path) -> WordNetDialectData:
    """Get dialect data, using cache if already loaded."""
    global _dialect_data_cache, _cached_wordnet_path

    if _dialect_data_cache is None or _cached_wordnet_path != wordnet_xml_path:
        _dialect_data_cache = load_wordnet_dialect_data(wordnet_xml_path)
        _cached_wordnet_path = wordnet_xml_path

    return _dialect_data_cache


def normalize_to_us_spelling_wordnet(word: str, dialect_data: WordNetDialectData) -> str:
    """
    Normalize word to US spelling using WordNet dialect data.

    Falls back to original word if no US variant exists.
    """
    # Check if word has a US variant
    us_variant = dialect_data.get_variant_for_dialect(word, 'US')
    if us_variant:
        # Preserve original casing
        if word[0].isupper():
            return us_variant.capitalize()
        return us_variant

    # No US variant found, return original
    return word


def normalize_to_gb_spelling_wordnet(word: str, dialect_data: WordNetDialectData) -> str:
    """
    Normalize word to GB spelling using WordNet dialect data.

    Falls back to original word if no GB variant exists.
    """
    # Check if word has a GB variant
    gb_variant = dialect_data.get_variant_for_dialect(word, 'GB')
    if gb_variant:
        # Preserve original casing
        if word[0].isupper():
            return gb_variant.capitalize()
        return gb_variant

    # No GB variant found, return original
    return word


def detect_spelling_variant_wordnet(word: str, dialect_data: WordNetDialectData) -> Optional[str]:
    """
    Detect if a word uses US, GB, CA, or AU spelling based on WordNet data.

    Returns:
        'US', 'GB', 'CA', 'AU', or None if not in WordNet dialect data

    Note: If a word is marked as both GB/CA/AU, returns 'GB' for consistency.
    """
    dialects = dialect_data.get_dialects(word)

    if not dialects:
        return None

    # Priority order: US, GB, CA, AU
    if 'US' in dialects:
        return 'US'
    if 'GB' in dialects:
        return 'GB'
    if 'CA' in dialects:
        return 'CA'
    if 'AU' in dialects:
        return 'AU'

    return None


if __name__ == '__main__':
    # Test the module
    import sys

    if len(sys.argv) > 1:
        wordnet_path = Path(sys.argv[1])
    else:
        # Default path
        wordnet_path = Path(__file__).parent.parent.parent / 'external/english-wordnet-2024.xml'

    if not wordnet_path.exists():
        print(f"ERROR: WordNet XML not found at {wordnet_path}")
        sys.exit(1)

    # Load data
    data = load_wordnet_dialect_data(wordnet_path)

    # Test examples
    print("\n=== Testing dialect detection ===")
    test_words = ['color', 'colour', 'center', 'centre', 'dialog', 'dialogue',
                  'defense', 'defence', 'realize', 'realise']

    for word in test_words:
        dialects = data.get_dialects(word)
        variant = detect_spelling_variant_wordnet(word, data)
        all_variants = data.get_all_variants(word)
        print(f"\n{word}:")
        print(f"  Dialects: {dialects}")
        print(f"  Detected as: {variant}")
        print(f"  All variants: {all_variants}")

    # Test normalization
    print("\n=== Testing normalization ===")
    print(f"colour → US: {normalize_to_us_spelling_wordnet('colour', data)}")
    print(f"color → GB: {normalize_to_gb_spelling_wordnet('color', data)}")
    print(f"centre → US: {normalize_to_us_spelling_wordnet('centre', data)}")
    print(f"center → GB: {normalize_to_gb_spelling_wordnet('center', data)}")
