#!/usr/bin/env python3
"""
suggestd — backing daemon for the Shaw-Spell web UI.

Holds every piece of state the CGI would otherwise load on each request:
  - 4 Hunspell dictionaries (shavian-{gb,us}, en_{GB,US})
  - 6 search indexes (dict_type → {word: [entry_ids]})
  - 6 entry caches   (dict_type → {entry_id: html_fragment})
  - 6 summary caches (dict_type → {entry_id: preview summary})

The CGI connects per request over a Unix socket, asks for a lookup by
(dict_type, word), and gets back JSON containing either the entry HTML or
a list of spelling suggestions. All heavy state is loaded once at startup.

Protocol (line-oriented, UTF-8, one request → one response, then close):

    Request:   {"op": "lookup", "dict_type": "english-shavian-gb",
                "word": "dog", "suggest_dict": "en_GB"}
    Response:  {"entry_html": "<h1>…</h1>…", "summary": [{…}], "suggestions": []}
               # summary: one link-preview summary per matched entry, in
               # entry order (see build_site_index.extract_summary)
               # or on miss:
               {"entry_html": null, "suggestions": ["dog", "dot", "fog"]}

    Request:   {"op": "suggest", "suggest_dict": "en_GB", "word": "definately"}
    Response:  {"suggestions": ["definitely", "definable", …]}

    Errors:    {"error": "<message>"}

Usage:
    suggestd.py --socket /run/shaw-spell/suggestd.sock \
                --hunspell-dir /opt/shaw-spell/hunspell \
                --data-dir /opt/shaw-spell/site-data

Run under systemd (see shaw-spell-suggestd.service).
"""

import argparse
import json
import logging
import os
import signal
import socketserver
import sys
import threading
from pathlib import Path

import hunspell  # pyhunspell — https://pypi.org/project/hunspell/ — exposes HunSpell(dic_path, aff_path)


HUNSPELL_DICTS = ('shavian-gb', 'shavian-us', 'en_GB', 'en_US')
HUNSPELL_PREFIX = 'io.joro.shaw-spell.'

DICT_TYPES = (
    'english-shavian-gb',
    'english-shavian-us',
    'shavian-english-gb',
    'shavian-english-us',
    'shavian-shavian-gb',
    'shavian-shavian-us',
)

MAX_SUGGESTIONS = 8


class State:
    """All loaded state. One instance lives for the daemon's lifetime."""

    def __init__(self, hunspell_dicts, indexes, entries, summaries):
        self.hunspell_dicts = hunspell_dicts  # name → Hunspell
        self.indexes = indexes                 # dict_type → {word: [entry_id]}
        self.entries = entries                 # dict_type → {entry_id: html}
        # dict_type → {entry_id: summary as JSON string} — held serialized
        # because ~340k parsed summary dicts cost ~430 MB of object overhead
        # vs ~165 MB as ASCII-escaped strings (astral Shavian chars would
        # force UCS-4 strings); a lookup parses only its own 1–4 matches.
        self.summaries = summaries


def lookup_entry(state, dict_type, word):
    """Return (concatenated entry HTML, summaries) for a hit, or (None, [])."""
    index = state.indexes.get(dict_type)
    entries = state.entries.get(dict_type)
    if index is None or entries is None:
        return None, []

    entry_ids = index.get(word) or index.get(word.lower())
    if not entry_ids:
        return None, []

    summaries = state.summaries.get(dict_type, {})
    parts = []
    matched_summaries = []
    for entry_id in entry_ids:
        html = entries.get(entry_id)
        if html:
            parts.append(html)
            summary = summaries.get(entry_id)
            if summary:
                matched_summaries.append(json.loads(summary))
            else:
                # The build writes a summary for every entry — a miss here
                # means the site-data files are out of sync with each other.
                logging.warning('no summary for %s/%s', dict_type, entry_id)
    if not parts:
        return None, []
    return '\n'.join(parts), matched_summaries


def spelling_suggestions(state, suggest_dict, word, dict_type_for_filter=None):
    """Return suggestions from Hunspell, optionally filtered to words that
    have real entries in dict_type_for_filter."""
    if not word:
        return []
    checker = state.hunspell_dicts.get(suggest_dict)
    if checker is None:
        return []

    raw = list(checker.suggest(word))[:MAX_SUGGESTIONS * 3]  # over-fetch for filtering

    if dict_type_for_filter:
        index = state.indexes.get(dict_type_for_filter) or {}
        filtered = [s for s in raw if s in index or s.lower() in index]
        return filtered[:MAX_SUGGESTIONS]
    return raw[:MAX_SUGGESTIONS]


def handle_request(state, request):
    """Dispatch one request dict to a response dict. Never raises."""
    op = request.get('op')

    if op == 'lookup':
        dict_type = request.get('dict_type')
        word = request.get('word', '')
        suggest_dict = request.get('suggest_dict')
        if dict_type not in state.indexes:
            return {'error': f'unknown dict_type: {dict_type}'}

        entry_html, summary = lookup_entry(state, dict_type, word)
        if entry_html:
            return {'entry_html': entry_html, 'summary': summary,
                    'suggestions': []}

        # Miss — also look up suggestions (filtered to in-index words).
        suggestions = []
        if suggest_dict and word:
            suggestions = spelling_suggestions(
                state, suggest_dict, word, dict_type_for_filter=dict_type
            )
        return {'entry_html': None, 'suggestions': suggestions}

    if op == 'suggest':
        suggest_dict = request.get('suggest_dict')
        word = request.get('word', '')
        if suggest_dict not in state.hunspell_dicts:
            return {'error': f'unknown suggest_dict: {suggest_dict}'}
        return {'suggestions': spelling_suggestions(state, suggest_dict, word)}

    return {'error': f'unknown op: {op!r}'}


class RequestHandler(socketserver.StreamRequestHandler):
    """One request, one response, then close."""

    # Cap the time spent reading the request line. A misbehaving client that
    # opens a connection but never sends '\n' would otherwise wedge a thread
    # forever on readline().
    READ_TIMEOUT_SEC = 5.0

    def handle(self):
        import time
        start = time.perf_counter()
        self.connection.settimeout(self.READ_TIMEOUT_SEC)

        request = None
        try:
            line = self.rfile.readline()
            if not line:
                logging.warning('empty request from client')
                return
            try:
                request = json.loads(line.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                response = {'error': f'bad request: {exc}'}
            else:
                response = handle_request(self.server.state, request)
        except Exception as exc:
            logging.exception('handler error')
            response = {'error': str(exc)}

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        # Compact single-line summary per request — grep-friendly.
        op = (request or {}).get('op', '?') if isinstance(request, dict) else '?'
        word = (request or {}).get('word', '') if isinstance(request, dict) else ''
        dict_type = (request or {}).get('dict_type', '') if isinstance(request, dict) else ''
        hit = 'error' in response and 'err' or (
            'hit' if response.get('entry_html') else 'miss'
        )
        suggest_count = len(response.get('suggestions', []) or [])
        logging.info(
            '%s %s word=%r dict=%s suggest_n=%d %.1fms',
            op, hit, word, dict_type, suggest_count, elapsed_ms,
        )

        try:
            payload = json.dumps(response, ensure_ascii=False) + '\n'
            self.wfile.write(payload.encode('utf-8'))
        except BrokenPipeError:
            # Client gave up (likely browser navigated away / refreshed)
            # before we finished. Not an error on our side.
            logging.info('client disconnected before response sent')
        except Exception:
            logging.exception('failed to write response')


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded so slow/hung clients can't block others. Hunspell.suggest()
    is thread-safe; dict reads are safe because we never mutate after load."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path, state):
        super().__init__(socket_path, RequestHandler)
        self.state = state


def load_hunspell(hunspell_dir):
    """Load all four Hunspell dicts. Fail fast if any are missing."""
    result = {}
    for name in HUNSPELL_DICTS:
        # NOTE: Path.with_suffix() would misbehave here — the basename
        # contains dots (e.g. 'io.joro.shaw-spell.shavian-gb'), which
        # pathlib reads as having a suffix of '.shavian-gb'. Build the
        # paths by string concatenation instead.
        stem = f'{HUNSPELL_PREFIX}{name}'
        aff = hunspell_dir / f'{stem}.aff'
        dic = hunspell_dir / f'{stem}.dic'
        if not aff.exists() or not dic.exists():
            raise FileNotFoundError(
                f'missing hunspell dict: {hunspell_dir}/{stem}.{{aff,dic}}'
            )
        logging.info('loading hunspell %s', name)
        # pyhunspell's HunSpell takes explicit dic and aff paths.
        result[name] = hunspell.HunSpell(str(dic), str(aff))
    return result


def load_dict_data(data_dir):
    """Load all 6 search indexes, entry caches and summary caches.
    Fail fast on missing files."""
    indexes = {}
    entries = {}
    summaries = {}
    for dict_type in DICT_TYPES:
        index_file = data_dir / f'{dict_type}-index.json'
        entries_file = data_dir / f'{dict_type}-entries.json'
        summaries_file = data_dir / f'{dict_type}-summaries.json'
        for path in (index_file, entries_file, summaries_file):
            if not path.exists():
                raise FileNotFoundError(f'missing site data: {path}')
        logging.info('loading %s', dict_type)
        with open(index_file, 'r', encoding='utf-8') as f:
            indexes[dict_type] = json.load(f)
        with open(entries_file, 'r', encoding='utf-8') as f:
            entries[dict_type] = json.load(f)
        with open(summaries_file, 'r', encoding='utf-8') as f:
            summaries[dict_type] = {
                entry_id: json.dumps(summary)
                for entry_id, summary in json.load(f).items()
            }
        logging.info('  %s: %d index terms, %d entries',
                     dict_type, len(indexes[dict_type]), len(entries[dict_type]))
    return indexes, entries, summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True, help='Unix socket path')
    parser.add_argument('--hunspell-dir', required=True, type=Path,
                        help='Directory with Hunspell .aff/.dic files')
    parser.add_argument('--data-dir', required=True, type=Path,
                        help='Directory with {dict_type}-{index,entries}.json')
    parser.add_argument('--socket-mode', default='0666',
                        help='Octal socket permissions (default 0666)')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s suggestd[%(process)d] %(levelname)s %(message)s',
    )

    state = State(
        hunspell_dicts=load_hunspell(args.hunspell_dir),
        **dict(zip(('indexes', 'entries', 'summaries'),
                   load_dict_data(args.data_dir))),
    )
    logging.info('all state loaded; ready')

    socket_path = args.socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)

    server = Server(socket_path, state)
    os.chmod(socket_path, int(args.socket_mode, 8))
    logging.info('listening on %s', socket_path)

    # server.shutdown() BLOCKS until serve_forever() returns and MUST run on a
    # different thread than the one running serve_forever() (stdlib docs). The
    # signal handler fires on the MAIN thread — the same thread serving — so
    # calling shutdown() inline deadlocks; systemd then SIGKILLs after timeout.
    # Spawn it off-thread; a flag makes a repeat signal a no-op.
    shutting_down = threading.Event()

    def _shutdown(signum, _frame):
        logging.info('signal %d — shutting down', signum)
        if shutting_down.is_set():
            return
        shutting_down.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        if os.path.exists(socket_path):
            os.unlink(socket_path)


if __name__ == '__main__':
    sys.exit(main() or 0)
