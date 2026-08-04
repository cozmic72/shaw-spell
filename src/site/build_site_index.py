#!/usr/bin/env python3
"""
Build searchable JSON indexes from dictionary XML files for the web frontend.

This script parses the Apple Dictionary XML files and creates:
1. Search indexes mapping query terms to entry IDs
2. Entry content cache for fast lookups
3. Entry summaries (headword forms, POS, definition counts) for social-media
   link previews

Usage:
    python build_site_index.py
"""

import xml.etree.ElementTree as ET
import json
from pathlib import Path
import sys
import html
import re
from copy import deepcopy

NS = {
    'd': 'http://www.apple.com/DTDs/DictionaryService-1.0.rdf',
    'xhtml': 'http://www.w3.org/1999/xhtml'
}

def strip_namespace(elem):
    """Recursively strip namespace from element and all children."""
    tag = elem.tag
    if tag.startswith('{'):
        close_idx = tag.find('}')
        if close_idx != -1:
            elem.tag = tag[close_idx + 1:]

    attribs = elem.attrib
    if attribs:
        # Build a new dict to avoid modifying the dict during iteration.
        new_attribs = {}
        for name, value in attribs.items():
            if name.startswith('{'):
                close_idx = name.find('}')
                if close_idx != -1:
                    new_attribs[name[close_idx + 1:]] = value
                else:
                    new_attribs[name] = value
            else:
                new_attribs[name] = value
        elem.attrib.clear()
        elem.attrib.update(new_attribs)

    for child in elem:
        strip_namespace(child)


_WORD_PATTERN = re.compile(
    r"\b[\w\u0400-\u04FF\u10450-\u1047F][\w\u0400-\u04FF\u10450-\u1047F\-']*\b",
    re.UNICODE
)

_SKIP_CLASSES = frozenset({'ipa'})
_FORCE_WRAP_CLASSES = frozenset({'definition', 'lemma-form', 'derived-form', 'variant'})


def wrap_text_nodes_in_spans(elem, should_wrap=True):
    """Recursively wrap words in text nodes with span elements.

    Modifies the XML tree in-place, wrapping text content in <span class="w">
    elements while preserving the tree structure.

    Args:
        elem: The XML element to process
        should_wrap: Whether words in this element should be wrapped
    """
    elem_class = elem.get('class', '')

    if elem_class in _SKIP_CLASSES:
        current_should_wrap = False
    elif elem_class in _FORCE_WRAP_CLASSES:
        current_should_wrap = True
    else:
        current_should_wrap = should_wrap

    def split_text_into_words(text):
        """Split text into alternating non-words and words."""
        if not text:
            return []

        parts = []
        last_end = 0

        for match in _WORD_PATTERN.finditer(text):
            if match.start() > last_end:
                parts.append(('text', text[last_end:match.start()]))
            parts.append(('word', match.group(0)))
            last_end = match.end()

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

    if current_should_wrap and elem.text:
        parts = split_text_into_words(elem.text)
        if parts:
            first_type, first_content = parts[0]
            if first_type == 'text':
                elem.text = first_content
                parts = parts[1:]
            else:
                elem.text = ''

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

    # Tail texts of existing children. Index map built once to avoid O(n²)
    # list(parent).index(child) calls.
    if current_should_wrap:
        child_to_index = {child: idx for idx, child in enumerate(existing_children)}

        for child in existing_children:
            if child.tail:
                parts = split_text_into_words(child.tail)
                if parts:
                    first_type, first_content = parts[0]
                    if first_type == 'text':
                        child.tail = first_content
                        parts = parts[1:]
                    else:
                        child.tail = ''

                    parent = elem
                    child_index = child_to_index[child]
                    insert_pos = child_index + 1
                    for part_type, content in parts:
                        if part_type == 'word':
                            span = ET.Element('span')
                            span.set('class', 'w')
                            span.text = content
                            parent.insert(insert_pos, span)
                            insert_pos += 1
                        else:
                            if insert_pos > 0:
                                parent[insert_pos - 1].tail = (parent[insert_pos - 1].tail or '') + content


def extract_entry_html(entry_elem):
    """Extract the HTML content of a dictionary entry (everything except the
    entry wrapper)."""
    parts = []

    for child in entry_elem:
        # Skip index elements early (before copying) - they're for searching, not display
        if child.tag == '{http://www.apple.com/DTDs/DictionaryService-1.0.rdf}index':
            continue

        child_copy = deepcopy(child)
        strip_namespace(child_copy)

        wrap_text_nodes_in_spans(child_copy, should_wrap=False)

        # 'html' serialization is faster than 'xml' here.
        content = ET.tostring(child_copy, encoding='unicode', method='html')

        parts.append(content)

    return '\n'.join(parts)


# The dictionary XML carries POS headings and form labels as display text
# (Shavian in the english→shavian direction). Map them back to English for
# preview cards; unmapped values (already-English ones in the shavian→english
# direction) pass through as their own display form. Inverses of the POS and
# GRAMMAR_TERM_SHAVIAN translations in src/dictionaries.
POS_ENGLISH = {
    '𐑯𐑬𐑯': 'noun',
    '𐑝𐑻𐑚': 'verb',
    '𐑨𐑡𐑩𐑒𐑑𐑦𐑝': 'adjective',
    '𐑨𐑡𐑦𐑒𐑑𐑦𐑝': 'adjective',
    '𐑨𐑛𐑝𐑻𐑚': 'adverb',
    '𐑦𐑯𐑑𐑼𐑡𐑧𐑒𐑖𐑩𐑯': 'interjection',
    '𐑐𐑮𐑧𐑐𐑩𐑟𐑦𐑖𐑩𐑯': 'preposition',
    '𐑒𐑩𐑯𐑡𐑳𐑙𐑒𐑖𐑩𐑯': 'conjunction',
}

FORM_LABEL_ENGLISH = {
    '𐑐𐑤𐑫𐑼𐑩𐑤': 'plural',
    '𐑐𐑭𐑕𐑑 𐑑𐑧𐑯𐑕': 'past tense',
    '𐑐𐑮𐑧𐑟𐑩𐑯𐑑 𐑐𐑸𐑑𐑦𐑕𐑦𐑐𐑩𐑤': 'present participle',
    '𐑐𐑭𐑕𐑑 𐑐𐑸𐑑𐑦𐑕𐑦𐑐𐑩𐑤': 'past participle',
    '𐑔𐑻𐑛 𐑐𐑻𐑕𐑩𐑯 𐑕𐑦𐑙𐑜𐑘𐑫𐑤𐑼': 'third person singular',
    '𐑒𐑩𐑥𐑐𐑨𐑮𐑩𐑑𐑦𐑝': 'comparative',
    '𐑕𐑵𐑐𐑻𐑤𐑩𐑑𐑦𐑝': 'superlative',
}

# Matches MAX_SUB_LINES in card.cgi — the card can never show more
# definitions than the build baked into the summary.
MAX_SUMMARY_DEFS = 2


def element_text(elem):
    return ''.join(elem.itertext()).strip()


def extract_form(form_div):
    """One lemma-form/derived-form row → {text, ipa, label, variant}."""
    fields = {'ipa': '', 'label': '', 'variant': ''}
    classes = {'ipa': 'ipa', 'form-label': 'label', 'variant': 'variant'}
    for span in form_div.findall('xhtml:span', NS):
        field = classes.get(span.get('class'))
        if field:
            fields[field] = element_text(span)
    fields['variant'] = fields['variant'].strip('()')
    fields['label'] = FORM_LABEL_ENGLISH.get(fields['label'], fields['label'])
    fields['text'] = (form_div.text or '').strip()
    return fields


def extract_summary(entry, dict_type):
    """Preview summary for one entry: headword in both scripts, IPA,
    derived forms, POS with definition counts, and (for shavian→english,
    where definitions are Latin and preview-safe) the first definitions."""
    title = ''
    h1 = entry.find('xhtml:h1', NS)
    if h1 is not None:
        title = element_text(h1)

    lemma = {'text': '', 'ipa': ''}
    forms = []
    forms_div = entry.find('xhtml:div[@class="forms"]', NS)
    if forms_div is not None:
        for form_div in forms_div.findall('xhtml:div', NS):
            cls = form_div.get('class')
            if cls == 'lemma-form':
                lemma = extract_form(form_div)
            elif cls == 'derived-form':
                forms.append(extract_form(form_div))

    pos = []
    defs = []
    want_defs = dict_type.startswith('shavian-english')
    for group in entry.iterfind(
            'xhtml:div[@class="definitions"]/xhtml:div[@class="pos-group"]', NS):
        heading = group.find('xhtml:h3/xhtml:i', NS)
        definitions = group.findall(
            './/xhtml:li[@class="definition"]', NS)
        name = element_text(heading) if heading is not None else ''
        pos.append({'name': POS_ENGLISH.get(name, name),
                    'ndefs': len(definitions)})
        if want_defs:
            defs.extend(element_text(li) for li in
                        definitions[:MAX_SUMMARY_DEFS - len(defs)])

    if dict_type.startswith('shavian-shavian'):
        # Immersive dicts have no Latin anywhere — the lemma-form is Shavian.
        shaw, latin = title, ''
    elif dict_type.startswith('shavian-english'):
        shaw, latin = title, lemma['text']
    else:
        shaw, latin = lemma['text'], title
    summary = {
        'shaw': shaw,
        'latin': latin,
        'ipa': lemma['ipa'],
        'forms': forms,
        'pos': pos,
    }
    if want_defs:
        summary['defs'] = defs
    return summary


def build_index(xml_path, dict_type):
    """Build search index from an XML dictionary file.

    Args:
        xml_path: Path to the XML file
        dict_type: Type identifier (e.g., 'english-shavian-gb')

    Returns:
        Tuple of (search_index, entry_cache, entry_order, summaries)
        - search_index: dict mapping search terms to list of entry IDs
        - entry_cache: dict mapping entry IDs to HTML content
        - entry_order: dict mapping entry IDs to document order number
        - summaries: dict mapping entry IDs to preview summaries
    """
    print(f"Parsing {xml_path}...")
    tree = ET.parse(xml_path)
    root = tree.getroot()

    search_index = {}
    entry_cache = {}
    entry_order = {}  # Track document order
    summaries = {}
    entry_count = 0

    for entry in root.findall('d:entry', NS):
        entry_id = entry.get('id')

        # Skip front/back matter
        if entry_id == 'front_back_matter':
            continue

        entry_count += 1

        # Track document order
        entry_order[entry_id] = entry_count

        summaries[entry_id] = extract_summary(entry, dict_type)

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
        # Use list to preserve order (we'll sort by document order later)
        for value in index_values:
            # Store both original and lowercase for exact and fuzzy matching
            for key in [value, value.lower()]:
                if key not in search_index:
                    search_index[key] = []
                search_index[key].append(entry_id)

        if entry_count % 10000 == 0:
            print(f"  Processed {entry_count} entries...")

    print(f"  Total: {entry_count} entries, {len(search_index)} index terms")
    return search_index, entry_cache, entry_order, summaries


def main():
    """Build indexes for dictionary types.

    Can build all dictionaries or specific ones based on command-line args.
    Usage: build_site_index.py [dict-type ...]
    Example: build_site_index.py english-shavian-gb shavian-english-us
    """
    project_root = Path(__file__).parent.parent.parent
    build_dir = project_root / 'build'
    xml_dir = build_dir / 'dictionaries' / 'xml'
    output_dir = build_dir / 'site-data'

    output_dir.mkdir(parents=True, exist_ok=True)

    # All available dictionary files
    all_dict_files = [
        ('english-shavian-gb', xml_dir / 'english-shavian-gb.xml'),
        ('english-shavian-us', xml_dir / 'english-shavian-us.xml'),
        ('shavian-english-gb', xml_dir / 'shavian-english-gb.xml'),
        ('shavian-english-us', xml_dir / 'shavian-english-us.xml'),
        ('shavian-shavian-gb', xml_dir / 'shavian-shavian-gb.xml'),
        ('shavian-shavian-us', xml_dir / 'shavian-shavian-us.xml'),
    ]

    # Filter based on command-line arguments
    if len(sys.argv) > 1:
        requested_dicts = set(sys.argv[1:])
        dict_files = [(dt, path) for dt, path in all_dict_files if dt in requested_dicts]
        if not dict_files:
            print(f"Error: No valid dictionary types specified")
            print(f"Available types: {', '.join(dt for dt, _ in all_dict_files)}")
            return 1
    else:
        dict_files = all_dict_files

    print("Building dictionary indexes for web frontend...")
    print()

    for dict_type, xml_path in dict_files:
        if not xml_path.exists():
            print(f"Warning: {xml_path} not found, skipping")
            continue

        search_index, entry_cache, entry_order, summaries = build_index(xml_path, dict_type)

        # Deduplicate and sort entry lists by document order
        search_index_serializable = {}
        for key, entry_ids in search_index.items():
            # Remove duplicates while preserving order
            seen = set()
            unique_ids = []
            for eid in entry_ids:
                if eid not in seen:
                    seen.add(eid)
                    unique_ids.append(eid)

            # Sort by document order
            sorted_ids = sorted(unique_ids, key=lambda eid: entry_order.get(eid, 0))
            search_index_serializable[key] = sorted_ids

        # Save search index
        index_file = output_dir / f'{dict_type}-index.json'
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(search_index_serializable, f, ensure_ascii=False)
        print(f"  → {index_file} ({len(search_index)} terms)")

        # Save entry cache
        cache_file = output_dir / f'{dict_type}-entries.json'
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(entry_cache, f, ensure_ascii=False)
        print(f"  → {cache_file} ({len(entry_cache)} entries)")

        # Save preview summaries
        summaries_file = output_dir / f'{dict_type}-summaries.json'
        with open(summaries_file, 'w', encoding='utf-8') as f:
            json.dump(summaries, f, ensure_ascii=False)
        print(f"  → {summaries_file} ({len(summaries)} summaries)")
        print()

    print("✅ Index building complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
