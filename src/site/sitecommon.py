"""Shared between the site's CGIs (index.cgi, card.cgi).

The page and its preview card must agree about which word they are for and
must talk to the daemon the same way, so the transport and the ordering rule
live here rather than in each script.
"""

import json
import socket
import os

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


def searched_first(word, summaries):
    """The daemon's index maps an inflection to its lemma's entry, so a
    searched form that is also a headword in its own right (e.g. 'spelling'
    under 'spell') arrives mixed in with the lemma's. Lead with the searched
    word's own entries so page and card describe what was looked up."""
    shavian_input = contains_shavian(word)
    key = word if shavian_input else word.lower()
    hits, rest = [], []
    for summary in summaries:
        headword = summary['shaw'] if shavian_input else summary['latin'].lower()
        (hits if headword == key else rest).append(summary)
    return hits + rest
