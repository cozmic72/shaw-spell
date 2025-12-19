#!/usr/bin/env python3
"""
Shaw-Spell Dictionary CGI
Main page generator - handles both search form and results display.
"""

import json
import sys
import os
from pathlib import Path
from urllib.parse import parse_qs
from http import cookies
import html as html_module


def load_index(dict_type, data_dir):
    """Load the search index for a dictionary type."""
    index_file = data_dir / f'{dict_type}-index.json'
    if not index_file.exists():
        return None
    with open(index_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_entries(dict_type, data_dir):
    """Load the entry cache for a dictionary type."""
    entries_file = data_dir / f'{dict_type}-entries.json'
    if not entries_file.exists():
        return None
    with open(entries_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def search_word(word, dict_type, data_dir):
    """Search for a word in the specified dictionary."""
    index = load_index(dict_type, data_dir)
    if index is None:
        return None

    # Try exact match first, then case-insensitive
    entry_ids = index.get(word) or index.get(word.lower())
    if not entry_ids:
        return None

    entries = load_entries(dict_type, data_dir)
    if entries is None:
        return None

    # Collect all matching entries (for homographs)
    entry_htmls = []
    for entry_id in entry_ids:
        entry_html = entries.get(entry_id)
        if entry_html:
            entry_htmls.append(entry_html)

    if not entry_htmls:
        return None

    # Concatenate all entries
    return '\n'.join(entry_htmls)


def contains_shavian(text):
    """Check if text contains Shavian characters (U+10450–U+1047F)."""
    return any('\U00010450' <= c <= '\U0001047F' for c in text)


def get_settings(query_params, cookie):
    """Get settings from query params or cookies."""
    settings = {
        'dialect': 'gb',
        'shavianDefs': 'english'
    }

    # Try query params first
    if 'dialect' in query_params:
        settings['dialect'] = query_params['dialect'][0]
    elif cookie and 'dialect' in cookie:
        settings['dialect'] = cookie['dialect'].value

    if 'shavianDefs' in query_params:
        settings['shavianDefs'] = query_params['shavianDefs'][0]
    elif cookie and 'shavianDefs' in cookie:
        settings['shavianDefs'] = cookie['shavianDefs'].value

    return settings


def load_template(name):
    """Load an HTML template snippet."""
    template_path = Path(__file__).parent.parent / 'templates' / f'{name}.html'
    if template_path.exists():
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ''


def generate_page(word=None, entry_html=None, error=None, settings=None):
    """Generate the complete HTML page."""
    settings = settings or {'dialect': 'gb', 'shavianDefs': 'english'}

    # Choose templates based on immersive mode
    immersive = settings['shavianDefs'] == 'shavian'
    welcome_top_template = '{{WELCOME_TOP_SHAVIAN}}' if immersive else '{{WELCOME_TOP}}'
    welcome_bottom_template = '{{WELCOME_BOTTOM_SHAVIAN}}' if immersive else '{{WELCOME_BOTTOM}}'

    # Determine welcome top display
    welcome_top = f'<div class="welcome-top">{welcome_top_template}</div>' if not word else ''

    # Determine entry display
    if error:
        entry_section = f'<div class="entry-container"><div class="no-results">{html_module.escape(error)}</div></div>'
    elif entry_html:
        entry_section = f'<div class="entry-container">{entry_html}</div>'
    elif not word:
        entry_section = f'<div class="entry-container">{welcome_bottom_template}</div>'
    else:
        entry_section = '<div class="entry-container hidden"></div>'

    # Build settings checkboxes
    gb_checked = 'checked' if settings['dialect'] == 'gb' else ''
    us_checked = 'checked' if settings['dialect'] == 'us' else ''
    eng_defs_checked = 'checked' if settings['shavianDefs'] == 'english' else ''
    shaw_defs_checked = 'checked' if settings['shavianDefs'] == 'shavian' else ''

    word_value = html_module.escape(word or '')

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shaw-Spell Dictionary{f' - {word}' if word else ''}</title>
    <meta name="description" content="Online Shavian-English dictionary. Look up words in both Shavian and Latin scripts.">
    <link rel="icon" type="image/png" href="favicon.png">
    <link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon-180x180.png">
    <link rel="apple-touch-icon" sizes="192x192" href="apple-touch-icon-192x192.png">
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <div class="container">
        <div class="header-bar">
            <div style="min-width: 40px;"></div>
            <h1>·𐑖𐑷-𐑕𐑐𐑧𐑤</h1>
            <div class="burger-menu">
                <button class="burger-btn" onclick="toggleBurgerMenu()">☰</button>
                <div class="burger-dropdown" id="burgerDropdown">
                    <a href="#" onclick="openAbout(); return false;">About</a>
                    <a href="#" onclick="openSettings(); return false;">Settings</a>
                </div>
            </div>
        </div>

        {welcome_top}

        <form class="search-form" method="get" action="index.cgi">
            <input type="hidden" name="dialect" value="{settings['dialect']}">
            <input type="hidden" name="shavianDefs" value="{settings['shavianDefs']}">
            <div class="search-input-group">
                <input
                    type="text"
                    name="word"
                    id="searchInput"
                    class="search-input"
                    placeholder="Enter a word..."
                    value=""
                    autocomplete="off"
                    autofocus
                >
                <button type="submit" class="search-btn">Search</button>
            </div>
        </form>

        {entry_section}
    </div>

    <div class="copyright">
        @2025 joro.io · Shaw-Spell $VERSION$
    </div>

    <!-- Modals -->
    <div id="modalOverlay" class="modal-overlay">
        <div class="modal">
            <button class="close-modal" onclick="closeModal()">&times;</button>
            <div id="modalContent"></div>
        </div>
    </div>

    <!-- Settings data for JavaScript -->
    <script>
        window.SETTINGS = {{
            dialect: '{settings['dialect']}',
            shavianDefs: '{settings['shavianDefs']}'
        }};
    </script>
    <script src="js/app.js"></script>
</body>
</html>'''


def main():
    """Main CGI handler."""
    # Parse query string
    query_string = os.environ.get('QUERY_STRING', '')
    params = parse_qs(query_string)

    # Parse cookies
    cookie = cookies.SimpleCookie()
    if 'HTTP_COOKIE' in os.environ:
        cookie.load(os.environ['HTTP_COOKIE'])

    # Get settings
    settings = get_settings(params, cookie)

    # Get search word
    word = params.get('word', [''])[0].strip()

    # Prepare response
    entry_html = None
    error = None

    if word:
        # Detect direction
        is_shavian = contains_shavian(word)
        direction = 'shavian-english' if is_shavian else 'english-shavian'

        # Choose dictionary
        if is_shavian and settings['shavianDefs'] == 'shavian':
            dict_type = f"shavian-shavian-{settings['dialect']}"
        else:
            dict_type = f"{direction}-{settings['dialect']}"

        # Perform search
        data_dir = Path(__file__).parent / 'data'
        entry_html = search_word(word, dict_type, data_dir)

        if not entry_html:
            error = f'No entry found for "{html_module.escape(word)}"'

    # Generate page
    html = generate_page(word, entry_html, error, settings)

    # Output response
    print('Content-Type: text/html; charset=utf-8')

    # Set cookies for settings
    settings_cookie = cookies.SimpleCookie()
    settings_cookie['dialect'] = settings['dialect']
    settings_cookie['dialect']['path'] = '/'
    settings_cookie['dialect']['max-age'] = 31536000  # 1 year
    settings_cookie['shavianDefs'] = settings['shavianDefs']
    settings_cookie['shavianDefs']['path'] = '/'
    settings_cookie['shavianDefs']['max-age'] = 31536000

    print(settings_cookie.output())
    print()
    print(html)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('Content-Type: text/html')
        print()
        print(f'<h1>Error</h1><pre>{html_module.escape(str(e))}</pre>')
        import traceback
        traceback.print_exc()
        sys.exit(1)
