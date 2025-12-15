#!/usr/bin/env python3
"""
Build searchable JSON indexes from dictionary XML files for the web frontend.

This script parses the Apple Dictionary XML files and creates:
1. Search indexes mapping query terms to entry IDs
2. Entry content cache for fast lookups

Usage:
    python build_site_index.py
"""

import xml.etree.ElementTree as ET
import json
from pathlib import Path
import sys
import html
import re

# XML namespaces
NS = {
    'd': 'http://www.apple.com/DTDs/DictionaryService-1.0.rdf',
    'xhtml': 'http://www.w3.org/1999/xhtml'
}

def strip_namespace(elem):
    """Recursively strip namespace from element and all children."""
    # Strip namespace from tag
    if elem.tag.startswith('{'):
        elem.tag = elem.tag.split('}', 1)[1]

    # Strip namespace from attributes
    attribs = elem.attrib
    if attribs:
        for name, value in list(attribs.items()):
            if name.startswith('{'):
                new_name = name.split('}', 1)[1]
                del attribs[name]
                attribs[new_name] = value

    # Recursively process children
    for child in elem:
        strip_namespace(child)


def wrap_text_nodes_in_spans(elem, should_wrap=True):
    """Recursively wrap words in text nodes with span elements.

    Modifies the XML tree in-place, wrapping text content in <span class="w">
    elements while preserving the tree structure.

    Args:
        elem: The XML element to process
        should_wrap: Whether words in this element should be wrapped
    """
    # Determine which elements should have clickable words
    elem_class = elem.get('class', '')

    # Never wrap these
    skip_classes = {'ipa'}

    # Always wrap these (even if parent said no)
    force_wrap_classes = {'definition', 'lemma-form', 'derived-form', 'variant'}

    # Determine if we should wrap words in this element
    if elem_class in skip_classes:
        current_should_wrap = False
    elif elem_class in force_wrap_classes:
        current_should_wrap = True
    else:
        current_should_wrap = should_wrap

    # Word pattern: letters, Shavian chars, hyphens, apostrophes
    word_pattern = re.compile(
        r"\b[\w\u0400-\u04FF\u10450-\u1047F][\w\u0400-\u04FF\u10450-\u1047F\-']*\b",
        re.UNICODE
    )

    def split_text_into_words(text):
        """Split text into alternating non-words and words."""
        if not text:
            return []

        parts = []
        last_end = 0

        for match in word_pattern.finditer(text):
            # Add non-word text before this match
            if match.start() > last_end:
                parts.append(('text', text[last_end:match.start()]))
            # Add the word
            parts.append(('word', match.group(0)))
            last_end = match.end()

        # Add any remaining text
        if last_end < len(text):
            parts.append(('text', text[last_end:]))

        return parts

    # First, recursively process all existing children (before we add spans)
    existing_children = list(elem)
    for child in existing_children:
        # Skip span.w elements we may have already created
        if child.tag == 'span' and child.get('class') == 'w':
            continue
        wrap_text_nodes_in_spans(child, current_should_wrap)

    # Now process this element's text and tail texts (only if we should wrap)
    if current_should_wrap and elem.text:
        parts = split_text_into_words(elem.text)
        if parts:
            # Set first part as element text
            first_type, first_content = parts[0]
            if first_type == 'text':
                elem.text = first_content
                parts = parts[1:]
            else:
                elem.text = ''

            # Insert remaining parts as children at the beginning
            insert_pos = 0
            for part_type, content in parts:
                if part_type == 'word':
                    span = ET.Element('span')
                    span.set('class', 'w')
                    span.text = content
                    elem.insert(insert_pos, span)
                    insert_pos += 1
                else:
                    # Non-word text - attach to previous element's tail
                    if insert_pos > 0:
                        elem[insert_pos - 1].tail = (elem[insert_pos - 1].tail or '') + content

    # Process tail texts of existing children
    if current_should_wrap:
        for child in existing_children:
            if child.tail:
                parts = split_text_into_words(child.tail)
                if parts:
                    # First part becomes the tail
                    first_type, first_content = parts[0]
                    if first_type == 'text':
                        child.tail = first_content
                        parts = parts[1:]
                    else:
                        child.tail = ''

                    # Insert remaining parts after this child
                    parent = elem
                    child_index = list(parent).index(child)
                    insert_pos = child_index + 1
                    for part_type, content in parts:
                        if part_type == 'word':
                            span = ET.Element('span')
                            span.set('class', 'w')
                            span.text = content
                            parent.insert(insert_pos, span)
                            insert_pos += 1
                        else:
                            # Attach to previous element's tail
                            if insert_pos > 0:
                                parent[insert_pos - 1].tail = (parent[insert_pos - 1].tail or '') + content


def extract_entry_html(entry_elem):
    """Extract the HTML content of a dictionary entry (everything except the entry wrapper)."""
    # Convert the entry element to string, excluding the <d:entry> wrapper
    parts = []

    # Process all child elements
    for child in entry_elem:
        if child.tag == '{http://www.apple.com/DTDs/DictionaryService-1.0.rdf}index':
            # Skip index elements (they're for searching, not display)
            continue

        # Make a copy and strip namespaces
        import copy
        child_copy = copy.deepcopy(child)
        strip_namespace(child_copy)

        # Wrap words in clickable spans (process XML tree before serialization)
        wrap_text_nodes_in_spans(child_copy, should_wrap=False)

        # Serialize the element to string
        content = ET.tostring(child_copy, encoding='unicode', method='html')

        parts.append(content)

    return '\n'.join(parts)


def build_index(xml_path, dict_type):
    """Build search index from an XML dictionary file.

    Args:
        xml_path: Path to the XML file
        dict_type: Type identifier (e.g., 'english-shavian-gb')

    Returns:
        Tuple of (search_index, entry_cache)
        - search_index: dict mapping search terms to list of entry IDs
        - entry_cache: dict mapping entry IDs to HTML content
    """
    print(f"Parsing {xml_path}...")
    tree = ET.parse(xml_path)
    root = tree.getroot()

    search_index = {}
    entry_cache = {}
    entry_count = 0

    for entry in root.findall('d:entry', NS):
        entry_id = entry.get('id')

        # Skip front/back matter
        if entry_id == 'front_back_matter':
            continue

        entry_count += 1

        # Extract HTML content
        html_content = extract_entry_html(entry)
        entry_cache[entry_id] = html_content

        # Extract all index values for searching
        index_values = []
        for index_elem in entry.findall('d:index', NS):
            value = index_elem.get('{http://www.apple.com/DTDs/DictionaryService-1.0.rdf}value')
            if value:
                index_values.append(value)

        # Also index the title
        title = entry.get('{http://www.apple.com/DTDs/DictionaryService-1.0.rdf}title')
        if title and title not in index_values:
            index_values.append(title)

        # Add to search index (normalize for case-insensitive search)
        for value in index_values:
            # Store both original and lowercase for exact and fuzzy matching
            for key in [value, value.lower()]:
                if key not in search_index:
                    search_index[key] = []
                if entry_id not in search_index[key]:
                    search_index[key].append(entry_id)

        if entry_count % 10000 == 0:
            print(f"  Processed {entry_count} entries...")

    print(f"  Total: {entry_count} entries, {len(search_index)} index terms")
    return search_index, entry_cache


def main():
    """Build indexes for all dictionary types."""
    project_root = Path(__file__).parent.parent.parent
    build_dir = project_root / 'build'
    output_dir = build_dir / 'site-data'

    output_dir.mkdir(parents=True, exist_ok=True)

    # Dictionary files to index
    dict_files = [
        ('english-shavian-gb', build_dir / 'english-shavian-gb.xml'),
        ('english-shavian-us', build_dir / 'english-shavian-us.xml'),
        ('shavian-english-gb', build_dir / 'shavian-english-gb.xml'),
        ('shavian-english-us', build_dir / 'shavian-english-us.xml'),
        ('shavian-shavian-gb', build_dir / 'shavian-shavian-gb.xml'),
        ('shavian-shavian-us', build_dir / 'shavian-shavian-us.xml'),
    ]

    print("Building dictionary indexes for web frontend...")
    print()

    for dict_type, xml_path in dict_files:
        if not xml_path.exists():
            print(f"Warning: {xml_path} not found, skipping")
            continue

        search_index, entry_cache = build_index(xml_path, dict_type)

        # Save search index
        index_file = output_dir / f'{dict_type}-index.json'
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(search_index, f, ensure_ascii=False)
        print(f"  → {index_file} ({len(search_index)} terms)")

        # Save entry cache
        cache_file = output_dir / f'{dict_type}-entries.json'
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(entry_cache, f, ensure_ascii=False)
        print(f"  → {cache_file} ({len(entry_cache)} entries)")
        print()

    print("✅ Index building complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
