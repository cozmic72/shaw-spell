#!/usr/bin/env python3
"""
Shaw-Spell Dictionary CGI

Thin HTTP frontend. Parses the request, asks the suggestd daemon for the
dictionary entry (and spelling suggestions on miss), and renders the page.
All heavy state — indexes, entry caches, Hunspell dicts — lives in the
daemon; this script loads nothing from disk beyond its own source.
"""

import json
import os
import socket
import sys
from urllib.parse import parse_qs, urlencode
from http import cookies
import html as html_module


# Unix socket served by suggestd. Must match the path in the systemd unit.
DAEMON_SOCKET = os.environ.get('SHAW_SPELL_SUGGEST_SOCKET',
                               '/run/shaw-spell/suggestd.sock')
DAEMON_TIMEOUT_SEC = 2.0


class DaemonError(Exception):
    """Raised when the daemon is unreachable or returns an error. Caller
    surfaces this to the user rather than silently papering over it."""


def daemon_request(request):
    """Send one JSON request to suggestd, return its JSON response.

    Raises DaemonError on any protocol or transport failure. No fallbacks —
    if the daemon is down the page should fail fast and loud.
    """
    payload = (json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8')
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(DAEMON_TIMEOUT_SEC)
        sock.connect(DAEMON_SOCKET)
        sock.sendall(payload)
        # Daemon writes a single line then closes.
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()
    except (OSError, socket.timeout) as exc:
        raise DaemonError(f'cannot reach suggestd: {exc}') from exc

    raw = b''.join(chunks).decode('utf-8').strip()
    if not raw:
        raise DaemonError('empty response from suggestd')
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DaemonError(f'malformed response: {exc}') from exc

    if 'error' in response:
        raise DaemonError(response['error'])
    return response


def contains_shavian(text):
    """True if text contains any Shavian character (U+10450–U+1047F)."""
    return any('\U00010450' <= c <= '\U0001047F' for c in text)


def get_settings(query_params, cookie):
    """Merge settings from query params and cookies; params win."""
    settings = {'dialect': 'gb', 'shavianDefs': 'english'}

    if 'dialect' in query_params:
        settings['dialect'] = query_params['dialect'][0]
    elif cookie and 'dialect' in cookie:
        settings['dialect'] = cookie['dialect'].value

    if 'shavianDefs' in query_params:
        settings['shavianDefs'] = query_params['shavianDefs'][0]
    elif cookie and 'shavianDefs' in cookie:
        settings['shavianDefs'] = cookie['shavianDefs'].value

    return settings


def choose_dict_type(word, settings):
    """Pick the dict_type for a lookup given the word's script + settings."""
    is_shavian = contains_shavian(word)
    if is_shavian and settings['shavianDefs'] == 'shavian':
        return f"shavian-shavian-{settings['dialect']}"
    direction = 'shavian-english' if is_shavian else 'english-shavian'
    return f"{direction}-{settings['dialect']}"


def choose_suggest_dict(word, dialect):
    """Pick the Hunspell dict that matches the input word's script."""
    if contains_shavian(word):
        return f'shavian-{dialect}'  # shavian-gb / shavian-us
    return 'en_GB' if dialect == 'gb' else 'en_US'


def render_suggestions(suggestions, settings):
    """Render 'Did you mean …?' links preserving settings."""
    if not suggestions:
        return ''
    links = []
    for s in suggestions:
        qs = urlencode({
            'word': s,
            'dialect': settings['dialect'],
            'shavianDefs': settings['shavianDefs'],
        })
        links.append(
            f'<a class="suggestion" href="index.cgi?{qs}">'
            f'{html_module.escape(s)}</a>'
        )
    return (
        '<div class="suggestions">'
        '<div class="suggestions-label">Did you mean:</div>'
        '<div class="suggestions-list">' + ' '.join(links) + '</div>'
        '</div>'
    )


def generate_page(word=None, entry_html=None, error=None, settings=None,
                  suggestions=None):
    """Assemble the full HTML page."""
    settings = settings or {'dialect': 'gb', 'shavianDefs': 'english'}

    immersive = settings['shavianDefs'] == 'shavian'
    welcome_top_template = '{{WELCOME_TOP_SHAVIAN}}' if immersive else '{{WELCOME_TOP}}'
    welcome_bottom_template = '{{WELCOME_BOTTOM_SHAVIAN}}' if immersive else '{{WELCOME_BOTTOM}}'

    welcome_top = f'<div class="welcome-top">{welcome_top_template}</div>' if not word else ''

    if error:
        suggestions_html = render_suggestions(suggestions or [], settings)
        entry_section = (
            f'<div class="entry-container">'
            f'<div class="no-results">{html_module.escape(error)}</div>'
            f'{suggestions_html}'
            f'</div>'
        )
    elif entry_html:
        entry_section = f'<div class="entry-container">{entry_html}</div>'
    elif not word:
        entry_section = f'<div class="entry-container">{welcome_bottom_template}</div>'
    else:
        entry_section = '<div class="entry-container hidden"></div>'

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
    <link rel="stylesheet" href="virtual-keyboard/virtual-keyboard.css">
</head>
<body>
    <div class="container">
        <div class="header-bar">
            <div style="min-width: 40px;"></div>
            <h1>·𐑖𐑷-𐑕𐑐𐑧𐑤</h1>
            <div class="burger-menu">
                <button class="burger-btn" onclick="toggleBurgerMenu()">☰</button>
                <div class="burger-dropdown" id="burgerDropdown">
                    <a href="#" onclick="openAbout(); return false;"><span id="menu-label-about">About&hellip;</span></a>
                    <a href="#" onclick="openSettings(); return false;"><span id="menu-label-settings">Settings&hellip;</span></a>
                    <a href="#" onclick="ShawSpellKeyboard.toggle(); return false;"><span id="menu-label-show-keyboard">Show keyboard</span> (<span id="vk-shortcut">Ctrl+K</span>)</a>
                    <a href="#" onclick="ShawSpellKeyboard.openSettings(); return false;"><span id="menu-label-keyboard-layout">Keyboard layout&hellip;</span></a>
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
        @2025 <a href="https://joro.io">joro.io</a> · Shaw-Spell $VERSION$
    </div>

    <div id="modalOverlay" class="modal-overlay">
        <div class="modal">
            <button class="close-modal" onclick="closeModal()">&times;</button>
            <div id="modalContent"></div>
        </div>
    </div>

    <script>
        window.SETTINGS = {{
            dialect: '{settings['dialect']}',
            shavianDefs: '{settings['shavianDefs']}'
        }};
    </script>
    <script src="js/app.js"></script>
    <script src="virtual-keyboard/virtual-keyboard.js"></script>
    <script src="js/virtual-keyboard-modal.js"></script>
    <script>
        // Per-platform shortcut in the burger item. Fail-soft on the label only:
        // if the keyboard lib is absent, leave the default Ctrl+K text.
        (function () {{
            var el = document.getElementById('vk-shortcut');
            if (el && window.ShawSpellKeyboard && window.ShawSpellKeyboard.shortcutLabel) {{
                el.textContent = window.ShawSpellKeyboard.shortcutLabel;
            }}
        }})();
    </script>
</body>
</html>'''


def main():
    params = parse_qs(os.environ.get('QUERY_STRING', ''))

    cookie = cookies.SimpleCookie()
    if 'HTTP_COOKIE' in os.environ:
        cookie.load(os.environ['HTTP_COOKIE'])

    settings = get_settings(params, cookie)
    word = params.get('word', [''])[0].strip()

    entry_html = None
    error = None
    suggestions = None

    if word:
        response = daemon_request({
            'op': 'lookup',
            'dict_type': choose_dict_type(word, settings),
            'word': word,
            'suggest_dict': choose_suggest_dict(word, settings['dialect']),
        })
        entry_html = response.get('entry_html')
        if not entry_html:
            suggestions = response.get('suggestions') or []
            error = f'No entry found for "{word}"'

    html = generate_page(word, entry_html, error, settings, suggestions)

    print('Content-Type: text/html; charset=utf-8')

    # Persist settings for a year.
    settings_cookie = cookies.SimpleCookie()
    settings_cookie['dialect'] = settings['dialect']
    settings_cookie['dialect']['path'] = '/'
    settings_cookie['dialect']['max-age'] = 31536000
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
