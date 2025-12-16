#!/usr/bin/env python3
"""
Test dictionary generation output for correctness.

Tests:
1. Homographs with different pronunciations are separate entries
2. Spelling variants (color/colour) are merged into one entry
3. Irregular forms are properly indexed to their lemma
"""

import xml.etree.ElementTree as ET
from pathlib import Path
import sys

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
RESET = '\033[0m'
BOLD = '\033[1m'

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def assert_true(self, condition, test_name, message=""):
        if condition:
            self.passed += 1
            print(f"{GREEN}✓{RESET} {test_name}")
        else:
            self.failed += 1
            self.failures.append(f"{test_name}: {message}")
            print(f"{RED}✗{RESET} {test_name}: {message}")

    def assert_equals(self, actual, expected, test_name):
        if actual == expected:
            self.passed += 1
            print(f"{GREEN}✓{RESET} {test_name}")
        else:
            self.failed += 1
            msg = f"Expected {expected}, got {actual}"
            self.failures.append(f"{test_name}: {msg}")
            print(f"{RED}✗{RESET} {test_name}: {msg}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}Test Results: {self.passed}/{total} passed{RESET}")
        if self.failed > 0:
            print(f"{RED}{BOLD}Failed tests:{RESET}")
            for failure in self.failures:
                print(f"  {RED}•{RESET} {failure}")
            return 1
        else:
            print(f"{GREEN}{BOLD}All tests passed!{RESET}")
            return 0


def parse_xml(xml_path):
    """Parse XML dictionary file."""
    tree = ET.parse(xml_path)
    return tree.getroot()


def find_entries_by_index(root, index_value):
    """Find all entries that have a d:index with the given value."""
    # Namespace for Apple Dictionary
    ns = {'d': 'http://www.apple.com/DTDs/DictionaryService-1.0.rdf'}

    entries = []
    for entry in root.findall('.//d:entry', ns):
        indices = entry.findall('d:index', ns)
        for idx in indices:
            if idx.get(f'{{{ns["d"]}}}value') == index_value:
                entries.append(entry)
                break

    return entries


# Namespaces
NS = {
    'd': 'http://www.apple.com/DTDs/DictionaryService-1.0.rdf',
    'xhtml': 'http://www.w3.org/1999/xhtml'
}


def get_entry_h1(entry):
    """Get the h1 text from an entry."""
    h1 = entry.find('.//xhtml:h1', NS)
    return h1.text if h1 is not None else None


def get_entry_definitions(entry):
    """Get all definition text from an entry."""
    definitions = []
    # Find all li elements and filter by class
    for def_elem in entry.findall('.//xhtml:li', NS):
        if def_elem.get('class') == 'definition' and def_elem.text:
            definitions.append(def_elem.text)
    return definitions


def get_lemma_forms(entry):
    """Get all lemma-form divs from an entry."""
    forms = []
    for div in entry.findall('.//xhtml:div', NS):
        if div.get('class') == 'lemma-form':
            # Get text content, stripping tags
            text = ''.join(div.itertext())
            forms.append(text.strip())
    return forms


def test_homographs_read_red(xml_path, results):
    """Test that read and red are separate entries under 𐑮𐑧𐑛."""
    print(f"\n{BOLD}Testing: Homographs (read vs red){RESET}")

    root = parse_xml(xml_path)
    entries = find_entries_by_index(root, '𐑮𐑧𐑛')

    # Should have at least 2 entries
    results.assert_true(
        len(entries) >= 2,
        "𐑮𐑧𐑛 has multiple entries",
        f"Expected at least 2 entries, found {len(entries)}"
    )

    if len(entries) < 2:
        return

    # Check that we have both "read" (verb) and "red" (color)
    h1_texts = [get_entry_h1(e) for e in entries]

    # One should be about reading (verb)
    read_entries = [e for e in entries if any('interpret' in d.lower() or 'written' in d.lower() for d in get_entry_definitions(e))]
    results.assert_true(
        len(read_entries) > 0,
        "Found entry for 'read' (verb)",
        "No entry found with reading-related definitions"
    )

    # One should be about the color red
    red_entries = [e for e in entries if any('spectrum' in d.lower() or 'blood' in d.lower() or 'cherries' in d.lower() for d in get_entry_definitions(e))]
    results.assert_true(
        len(red_entries) > 0,
        "Found entry for 'red' (color)",
        "No entry found with color-related definitions"
    )


def test_homographs_dew_due(xml_path, results):
    """Test that dew and due are separate entries with no duplicates."""
    print(f"\n{BOLD}Testing: Homographs (dew vs due){RESET}")

    root = parse_xml(xml_path)

    # Check 𐑛𐑿 (dew) - should have exactly 1 entry (the noun "dew")
    dew_entries = find_entries_by_index(root, '𐑛𐑿')
    results.assert_equals(
        len(dew_entries),
        1,
        "𐑛𐑿 (dew) has exactly 1 entry (no duplicates)"
    )

    # Verify it's about dew (water droplets)
    if len(dew_entries) == 1:
        defs = get_entry_definitions(dew_entries[0])
        has_dew_def = any('water' in d.lower() or 'condensed' in d.lower() for d in defs)
        results.assert_true(
            has_dew_def,
            "𐑛𐑿 entry is about dew (water)",
            f"Entry doesn't contain dew-related definitions"
        )

    # Check 𐑛𐑵 (due) - should have exactly 3 entries (noun, adj, adverb senses)
    due_entries = find_entries_by_index(root, '𐑛𐑵')
    results.assert_equals(
        len(due_entries),
        3,
        "𐑛𐑵 (due) has exactly 3 entries (no duplicates)"
    )


def get_entry_pos(entry):
    """Get the part of speech from an entry."""
    pos_groups = entry.findall('.//xhtml:div[@class="pos-group"]', NS)
    pos_list = []
    for pg in pos_groups:
        h3 = pg.find('.//xhtml:h3', NS)
        if h3 is not None:
            # Text is inside <i> tag, use itertext()
            text = ''.join(h3.itertext()).strip()
            if text:
                pos_list.append(text)
    return pos_list


def test_spelling_variants_color(xml_path, results):
    """Test that color/colour entries are properly managed."""
    print(f"\n{BOLD}Testing: Spelling variants (color/colour){RESET}")

    root = parse_xml(xml_path)
    entries = find_entries_by_index(root, '𐑒𐑳𐑤𐑼')

    # Should have exactly 2 entries total: 1 noun, 1 verb
    results.assert_equals(
        len(entries),
        2,
        "𐑒𐑳𐑤𐑼 (color/colour) has exactly 2 entries (noun + verb, no duplicates)"
    )

    # Count noun and verb entries
    noun_entries = []
    verb_entries = []
    for entry in entries:
        pos_list = get_entry_pos(entry)
        if any('n' in pos.lower() for pos in pos_list):
            noun_entries.append(entry)
        if any('v' in pos.lower() for pos in pos_list):
            verb_entries.append(entry)

    # Should have exactly 1 noun and 1 verb
    results.assert_equals(
        len(noun_entries),
        1,
        "𐑒𐑳𐑤𐑼 has exactly 1 noun entry"
    )

    results.assert_equals(
        len(verb_entries),
        1,
        "𐑒𐑳𐑤𐑼 has exactly 1 verb entry"
    )

    if len(noun_entries) >= 1:
        entry = noun_entries[0]
        forms = get_lemma_forms(entry)

        # Should show both colour and color
        all_text = ' '.join(forms)
        has_colour = 'colour' in all_text.lower()
        has_color = 'color' in all_text.lower()

        results.assert_true(
            has_colour or has_color,
            "Entry shows color/colour spelling",
            f"Forms: {forms}"
        )

        # For GB dictionary, should show (color, US) or similar variant notation
        # Check if alternate dialect is mentioned
        entry_text = ''.join(entry.itertext())
        has_variant_marker = 'US' in entry_text or 'GB' in entry_text

        results.assert_true(
            has_variant_marker,
            "Entry shows dialect variant (US/GB)",
            "No dialect variant marker found"
        )


def test_irregular_forms_indexing(xml_path, results):
    """Test that irregular past tense 𐑮𐑧𐑛 points to lemma 𐑮𐑰𐑛."""
    print(f"\n{BOLD}Testing: Irregular forms indexing{RESET}")

    root = parse_xml(xml_path)

    # Find entries indexed by 𐑮𐑧𐑛 that are about the verb "read"
    entries = find_entries_by_index(root, '𐑮𐑧𐑛')
    read_verb_entries = [e for e in entries if any('interpret' in d.lower() or 'written' in d.lower() for d in get_entry_definitions(e))]

    results.assert_true(
        len(read_verb_entries) > 0,
        "Found verb 'read' entry indexed by 𐑮𐑧𐑛",
        f"No verb read entries found among {len(entries)} total entries"
    )

    if len(read_verb_entries) > 0:
        entry = read_verb_entries[0]
        h1 = get_entry_h1(entry)

        # The h1 should be 𐑮𐑰𐑛 (the lemma form), not 𐑮𐑧𐑛 (the past tense)
        results.assert_equals(
            h1,
            '𐑮𐑰𐑛',
            "Verb 'read' entry has h1='𐑮𐑰𐑛' (lemma form)"
        )


def test_heteronyms_bow(xml_path, results):
    """Test that bow (tie) and bow (of ship) are separate entries with no duplicates."""
    print(f"\n{BOLD}Testing: Heteronyms (bow - tie vs ship){RESET}")

    root = parse_xml(xml_path)

    # Check 𐑚𐑴 (bow - as in bow tie /boʊ/) - should have exactly 3 entries (noun, verb, and mixed)
    bow_tie_entries = find_entries_by_index(root, '𐑚𐑴')
    results.assert_equals(
        len(bow_tie_entries),
        3,
        "𐑚𐑴 (bow /boʊ/) has exactly 3 entries (no duplicates)"
    )

    # Check 𐑚𐑬 (bow - as in bow of ship /baʊ/) - should have exactly 3 entries
    bow_ship_entries = find_entries_by_index(root, '𐑚𐑬')
    results.assert_equals(
        len(bow_ship_entries),
        3,
        "𐑚𐑬 (bow /baʊ/) has exactly 3 entries (no duplicates)"
    )


def test_inflected_forms_running(xml_path, results):
    """Test that gerunds like 'running' index to their base verb 'run'."""
    print(f"\n{BOLD}Testing: Inflected forms (running → run){RESET}")

    root = parse_xml(xml_path)

    # Find entries indexed by 𐑮𐑳𐑯𐑦𐑙 (running) - should have exactly 2 (verb + noun)
    running_entries = find_entries_by_index(root, '𐑮𐑳𐑯𐑦𐑙')
    results.assert_equals(
        len(running_entries),
        2,
        "𐑮𐑳𐑯𐑦𐑙 (running) has exactly 2 entries (verb + noun, no duplicates)"
    )

    # Find verb entries (not noun "running")
    verb_entries = []
    for entry in running_entries:
        pos_list = get_entry_pos(entry)
        if any('v' in pos.lower() for pos in pos_list):
            verb_entries.append(entry)

    if len(verb_entries) > 0:
        # The h1 should be 𐑮𐑳𐑯 (run), not 𐑮𐑳𐑯𐑦𐑙 (running)
        entry = verb_entries[0]
        h1 = get_entry_h1(entry)
        results.assert_equals(
            h1,
            '𐑮𐑳𐑯',
            "Verb 'running' entry has h1='𐑮𐑳𐑯' (base form 'run')"
        )
    else:
        results.assert_true(
            False,
            "Found verb 'run' entry indexed by 𐑮𐑳𐑯𐑦𐑙",
            f"No verb entries found among {len(running_entries)} total entries"
        )


def main():
    """Run all tests."""
    # Get XML path from command line or use default
    if len(sys.argv) > 1:
        xml_path = Path(sys.argv[1])
    else:
        xml_path = Path(__file__).parent.parent.parent / 'build' / 'shavian-english-gb.xml'

    if not xml_path.exists():
        print(f"{RED}Error: Dictionary XML not found at {xml_path}{RESET}")
        print(f"Please generate dictionaries first or specify path as argument")
        return 1

    print(f"{BOLD}Testing dictionary: {xml_path}{RESET}")

    results = TestResult()

    # Run all tests
    test_homographs_read_red(xml_path, results)
    test_homographs_dew_due(xml_path, results)
    test_spelling_variants_color(xml_path, results)
    test_irregular_forms_indexing(xml_path, results)
    test_heteronyms_bow(xml_path, results)
    test_inflected_forms_running(xml_path, results)

    # Print summary
    return results.summary()


if __name__ == '__main__':
    sys.exit(main())
