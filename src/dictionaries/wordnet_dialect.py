#!/usr/bin/env python3
"""
WordNet dialect information extractor.

Extracts authoritative dialect markers (American, British, Canadian, Australian)
from Open English WordNet YAML files, replacing heuristic-based dialect detection.
"""

import yaml
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, Optional, List


class WordNetDialectData:
    """
    Manages dialect information extracted from WordNet.

    Structure:
        word_dialects: word → set of dialects ('US', 'GB', 'CA', 'AU')
        word_synsets: word → set of synsets
        synset_variants: synset → {dialect → list of words}
    """

    def __init__(self):
        self.word_dialects: Dict[str, Set[str]] = defaultdict(set)
        self.word_synsets: Dict[str, Set[str]] = defaultdict(set)
        self.synset_variants: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    def add_entry(self, word: str, synset: str, dialects: Set[str]):
        """Add a word entry with its synset and dialects."""
        word_lower = word.lower()

        # Record word → dialects
        self.word_dialects[word_lower].update(dialects)

        # Record word → synsets
        self.word_synsets[word_lower].add(synset)

        # Record synset → {dialect → list of words}
        for dialect in dialects:
            if word_lower not in self.synset_variants[synset][dialect]:
                self.synset_variants[synset][dialect].append(word_lower)

    def get_dialects(self, word: str) -> Set[str]:
        """Get all dialects for a word (e.g., {'US'}, {'GB', 'CA', 'AU'})."""
        return self.word_dialects.get(word.lower(), set())

    def get_variant_for_dialect(self, word: str, target_dialect: str) -> Optional[List[str]]:
        """
        Get the spelling variants of a word for a target dialect.

        For example:
            get_variant_for_dialect('color', 'GB') → ['colour']
            get_variant_for_dialect('colour', 'US') → ['color']

        Returns None if no variant exists for the target dialect, or an empty list
        if only the same word exists.
        """
        word_lower = word.lower()

        # Get synsets for this word (sorted for deterministic iteration)
        synsets = sorted(self.word_synsets.get(word_lower, set()))

        # Collect all variants for the target dialect
        all_variants = []
        for synset in synsets:
            if synset in self.synset_variants:
                variants_dict = self.synset_variants[synset]
                if target_dialect in variants_dict:
                    # Add variants that aren't the same as the input word
                    for variant in variants_dict[target_dialect]:
                        if variant != word_lower and variant not in all_variants:
                            all_variants.append(variant)

        return all_variants if all_variants else None

    def get_all_variants(self, word: str) -> Dict[str, List[str]]:
        """
        Get all spelling variants of a word across all dialects.

        Returns: dict mapping dialect → list of words
                 (e.g., {'US': ['color'], 'GB': ['colour', 'coloure']})
        """
        word_lower = word.lower()
        all_variants: Dict[str, List[str]] = defaultdict(list)

        # Get synsets for this word (sorted for deterministic iteration)
        synsets = sorted(self.word_synsets.get(word_lower, set()))

        # Collect all variants from all synsets
        for synset in synsets:
            if synset in self.synset_variants:
                for dialect, variants_list in self.synset_variants[synset].items():
                    for variant in variants_list:
                        if variant not in all_variants[dialect]:
                            all_variants[dialect].append(variant)

        return dict(all_variants)


def load_wordnet_dialect_data(wordnet_yaml_dir: Path) -> WordNetDialectData:
    """
    Load dialect information from WordNet YAML files.

    Extracts words with dialect markers in the 'exemplifies' field:
        exemplifies:
          - 'american_spelling%1:10:01::'
          - 'british_spelling%1:10:01::'

    Returns:
        WordNetDialectData object with dialect lookups
    """
    print("Loading WordNet dialect data from YAML...")

    data = WordNetDialectData()

    # Dialect marker to code mapping
    dialect_markers = {
        'american_spelling': 'US',
        'british_spelling': 'GB',
        'canadian_spelling': 'CA',
        'australian_spelling': 'AU'
    }

    # Find all entries-*.yaml files (where lemmas with dialect info are stored)
    yaml_files = sorted(wordnet_yaml_dir.glob('entries-*.yaml'))

    files_processed = 0
    for yaml_file in yaml_files:
        files_processed += 1

        with open(yaml_file, 'r', encoding='utf-8') as f:
            entries = yaml.safe_load(f)

        if not entries:
            continue

        # Each YAML file contains: {lemma: {pos: data}}
        for lemma, pos_dict in entries.items():
            if not isinstance(pos_dict, dict):
                continue

            for pos, pos_data in pos_dict.items():
                if not isinstance(pos_data, dict):
                    continue

                # Check all senses for dialect markers
                senses = pos_data.get('sense', [])
                if not isinstance(senses, list):
                    continue

                for sense in senses:
                    if not isinstance(sense, dict):
                        continue

                    synset = sense.get('synset')
                    if not synset:
                        continue

                    # Find dialect markers in 'exemplifies' field
                    exemplifies = sense.get('exemplifies', [])
                    if not exemplifies:
                        continue

                    dialects = set()
                    for exemplify in exemplifies:
                        # Extract dialect from strings like 'american_spelling%1:10:01::'
                        for marker, code in dialect_markers.items():
                            if marker in exemplify:
                                dialects.add(code)

                    # If this sense has dialect markers, record it
                    if dialects:
                        data.add_entry(lemma, synset, dialects)

    print(f"Loaded dialect data from {files_processed} YAML files")
    print(f"  - Total words: {len(data.word_dialects)}")
    print(f"  - US words: {sum(1 for d in data.word_dialects.values() if 'US' in d)}")
    print(f"  - GB words: {sum(1 for d in data.word_dialects.values() if 'GB' in d)}")
    print(f"  - Variant pairs: {len(data.synset_variants)}")

    return data


# Global cache for loaded dialect data
_dialect_data_cache: Optional[WordNetDialectData] = None
_cached_yaml_dir: Optional[Path] = None


def get_dialect_data(wordnet_yaml_dir: Path) -> WordNetDialectData:
    """Get dialect data, using cache if already loaded."""
    global _dialect_data_cache, _cached_yaml_dir

    if _dialect_data_cache is None or _cached_yaml_dir != wordnet_yaml_dir:
        _dialect_data_cache = load_wordnet_dialect_data(wordnet_yaml_dir)
        _cached_yaml_dir = wordnet_yaml_dir

    return _dialect_data_cache


def normalize_to_us_spelling_wordnet(word: str, dialect_data: WordNetDialectData) -> str:
    """
    Normalize word to US spelling using WordNet dialect data.

    Falls back to original word if no US variant exists.
    If multiple US variants exist, returns the first one.
    """
    # Check if word has US variants
    us_variants = dialect_data.get_variant_for_dialect(word, 'US')
    if us_variants:
        # Pick first variant
        us_variant = us_variants[0]
        # Preserve original casing
        if word and word[0].isupper():
            return us_variant.capitalize()
        return us_variant

    # No US variant found, return original
    return word


def normalize_to_gb_spelling_wordnet(word: str, dialect_data: WordNetDialectData) -> str:
    """
    Normalize word to GB spelling using WordNet dialect data.

    Falls back to original word if no GB variant exists.
    If multiple GB variants exist, returns the first one.
    """
    # Check if word has GB variants
    gb_variants = dialect_data.get_variant_for_dialect(word, 'GB')
    if gb_variants:
        # Pick first variant
        gb_variant = gb_variants[0]
        # Preserve original casing
        if word and word[0].isupper():
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
        yaml_dir = Path(sys.argv[1])
    else:
        # Default path
        yaml_dir = Path(__file__).parent.parent.parent / 'external/english-wordnet/src/yaml'

    if not yaml_dir.exists():
        print(f"ERROR: WordNet YAML directory not found at {yaml_dir}")
        sys.exit(1)

    # Load data
    data = load_wordnet_dialect_data(yaml_dir)

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
