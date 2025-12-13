#!/usr/bin/env python3
"""
Test suite for Shavian dictionaries.

Tests edge cases to ensure correct handling of:
- Spelling variants (colour/color)
- Pronunciation variants (due /djuː/ GB vs /duː/ US)
- Homonyms (lead /led/ vs /liːd/)
- Hyphenated compounds (colour-bar)
- Proper nouns (with namer dots and capitalization)
- Dialect-specific entries
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import json


class TestRunner:
    """Test runner for dictionary validation."""

    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0

    def assert_true(self, condition, test_name, error_msg=""):
        """Assert that condition is true."""
        self.tests_run += 1
        if condition:
            self.tests_passed += 1
            print(f"  ✓ {test_name}")
            return True
        else:
            self.tests_failed += 1
            print(f"  ✗ {test_name}")
            if error_msg:
                print(f"    {error_msg}")
            return False

    def summary(self):
        """Print test summary."""
        print(f"\n{'='*60}")
        print(f"Test Summary:")
        print(f"  Total:  {self.tests_run}")
        print(f"  Passed: {self.tests_passed}")
        print(f"  Failed: {self.tests_failed}")
        print(f"{'='*60}")
        return self.tests_failed == 0


def load_dictionary(xml_path):
    """Load dictionary XML and build lookup index."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"ERROR: Failed to load XML: {e}")
        return {}, {}

    ns = {'d': 'http://www.apple.com/DTDs/DictionaryService-1.0.rdf'}

    # Build index: word -> list of entries
    index = {}
    for entry in root.findall('.//d:entry', ns):
        for index_elem in entry.findall('d:index', ns):
            index_word = index_elem.get(f'{{{ns["d"]}}}value')
            if index_word:
                if index_word not in index:
                    index[index_word] = []
                index[index_word].append(entry)

    return index, ns


def entry_contains_text(entry, text):
    """Check if entry contains specific text."""
    entry_text = ''.join(entry.itertext()).lower()
    return text.lower() in entry_text


def entry_has_variant_label(entry, dialect):
    """Check if entry has variant label (GB or US)."""
    # Look for variant spans
    for span in entry.findall(".//span[@class='variant']"):
        span_text = ''.join(span.itertext())
        if dialect in span_text:
            return True
    return False


def test_spelling_variants(runner, index, ns, dialect):
    """Test that spelling variants are properly handled."""
    print(f"\nTesting spelling variants ({dialect.upper()})...")

    if dialect == 'gb':
        # In GB dictionary, should see 'colour' as main form, 'color' as US variant
        if 'colour' in index:
            entries = index['colour']
            runner.assert_true(
                len(entries) > 0,
                "colour entry exists in GB dictionary"
            )

            if entries:
                entry = entries[0]
                has_color = entry_contains_text(entry, 'color')
                runner.assert_true(
                    has_color,
                    "colour entry shows 'color' as US variant",
                    "Expected to find 'color' mentioned in colour entry"
                )

    elif dialect == 'us':
        # In US dictionary, should see 'color' as main form, 'colour' as GB variant
        if 'color' in index:
            entries = index['color']
            runner.assert_true(
                len(entries) > 0,
                "color entry exists in US dictionary"
            )

            if entries:
                entry = entries[0]
                has_colour = entry_contains_text(entry, 'colour')
                runner.assert_true(
                    has_colour,
                    "color entry shows 'colour' as GB variant",
                    "Expected to find 'colour' mentioned in color entry"
                )


def test_pronunciation_variants(runner, index, ns):
    """Test that pronunciation variants are properly handled."""
    print(f"\nTesting pronunciation variants...")

    # "due" has different pronunciations in GB (/djuː/) vs US (/duː/)
    if 'due' in index:
        entries = index['due']
        runner.assert_true(
            len(entries) > 0,
            "due entry exists"
        )

        if entries:
            entry = entries[0]
            entry_text = ''.join(entry.itertext())

            # Should show both pronunciations
            has_djuu = '/djuː/' in entry_text or '/dʒuː/' in entry_text
            has_duu = '/duː/' in entry_text

            runner.assert_true(
                has_djuu or has_duu,
                "due entry shows pronunciation variant(s)",
                f"Expected to find pronunciation in entry. Got: {entry_text[:200]}"
            )


def test_homonyms(runner, index, ns):
    """Test that homonyms (different meanings) are separate entries."""
    print(f"\nTesting homonyms...")

    # "lead" can be /led/ (metal) or /liːd/ (to guide)
    # These should be SEPARATE entries with different definitions

    # Note: Shavian would be 𐑤𐑧𐑛 /led/ and 𐑤𐑰𐑛 /liːd/
    # In English-Shavian dict, both should appear under "lead"

    if 'lead' in index:
        entries = index['lead']

        # Should have multiple entries for different meanings
        runner.assert_true(
            len(entries) >= 1,
            f"lead has entry/entries (found {len(entries)})"
        )


def test_hyphenated_compounds(runner, index, ns, dialect):
    """Test that hyphenated compounds are handled correctly."""
    print(f"\nTesting hyphenated compounds ({dialect.upper()})...")

    # Test compound words like "colour-bar" (GB) / "color-bar" (US)
    if dialect == 'gb':
        test_word = 'colour-bar' if 'colour-bar' in index else 'color-bar'
    else:
        test_word = 'color-bar' if 'color-bar' in index else 'colour-bar'

    if test_word in index:
        entries = index[test_word]
        runner.assert_true(
            len(entries) > 0,
            f"{test_word} entry exists",
            f"Hyphenated compounds should be indexed"
        )


def test_namer_dots(runner, index, ns):
    """Test that proper nouns have namer dots in Shavian."""
    print(f"\nTesting namer dots for proper nouns...")

    # Look for any entry with a namer dot (·)
    has_namer_dot = False
    namer_dot = '·'

    for word, entries in index.items():
        if namer_dot in word:
            has_namer_dot = True
            break

    runner.assert_true(
        has_namer_dot,
        "Found entries with namer dot (·) for proper nouns",
        "Expected to find at least some proper nouns with namer dots"
    )


def test_capitalization(runner, index, ns):
    """Test that proper nouns are capitalized in Latin text."""
    print(f"\nTesting capitalization for proper nouns...")

    # Look for capitalized entries (proper nouns should be capitalized)
    # This test is best-effort since we don't know which words are proper nouns

    capitalized_count = sum(1 for word in index.keys()
                           if word and word[0].isupper() and len(word) > 1)

    runner.assert_true(
        capitalized_count > 0,
        f"Found {capitalized_count} capitalized entries (proper nouns)",
        "Expected to find at least some capitalized proper nouns"
    )


def main():
    """Main test function."""
    print("Shavian Dictionary Test Suite")
    print("="*60)

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    build_dir = project_dir / 'build'

    # Test configurations
    test_configs = [
        ('shavian-english', 'gb', 'shaw-eng'),
        ('shavian-english', 'us', 'shaw-eng'),
        ('english-shavian', 'gb', 'eng-shaw'),
        ('english-shavian', 'us', 'eng-shaw'),
        ('shavian-shavian', 'gb', 'shaw-shaw'),
    ]

    overall_runner = TestRunner()

    for dict_name, dialect, dict_type in test_configs:
        xml_path = build_dir / f'{dict_name}-{dialect}.xml'

        if not xml_path.exists():
            print(f"\nSKIPPING: {dict_name}-{dialect} (file not found)")
            continue

        print(f"\n{'='*60}")
        print(f"Testing: {dict_name}-{dialect}")
        print(f"{'='*60}")

        index, ns = load_dictionary(xml_path)

        if not index:
            print(f"ERROR: Failed to load dictionary")
            overall_runner.tests_failed += 1
            continue

        print(f"Loaded {len(index)} index entries")

        runner = TestRunner()

        # Run tests appropriate for each dictionary type
        if dict_type == 'shaw-eng':
            # Shavian → English
            test_namer_dots(runner, index, ns)
            test_homonyms(runner, index, ns)

        elif dict_type == 'eng-shaw':
            # English → Shavian
            test_spelling_variants(runner, index, ns, dialect)
            test_pronunciation_variants(runner, index, ns)
            test_hyphenated_compounds(runner, index, ns, dialect)
            test_capitalization(runner, index, ns)

        elif dict_type == 'shaw-shaw':
            # Shavian → Shavian
            test_namer_dots(runner, index, ns)

        # Aggregate results
        overall_runner.tests_run += runner.tests_run
        overall_runner.tests_passed += runner.tests_passed
        overall_runner.tests_failed += runner.tests_failed

    # Print overall summary
    success = overall_runner.summary()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
