#!/usr/bin/env python3
"""
Shaw-Spell editorial editor — CGI frontend.

Thin HTTP client, mirroring src/site/index.cgi's role: it serves the editor
shell (a single page) and proxies the browser's JSON to the editord daemon over
its Unix socket. All state — the basis, the overlay, the patch store — lives in
the daemon; this script loads nothing from disk beyond its own source.

Two request shapes:
  - GET  (no ?api): serve the editor page.
  - POST (Content-Type application/json): forward the body to editord, return
    its JSON response verbatim. The browser's fetch() speaks the daemon's
    protocol directly through this proxy.
"""

import json
import os
import socket
import sys

DAEMON_SOCKET = os.environ.get("SHAW_SPELL_EDITOR_SOCKET",
                               "/run/shaw-spell/editord.sock")
DAEMON_TIMEOUT_SEC = 10.0


class DaemonError(Exception):
    """The daemon is unreachable or errored. Surfaced to the client, not hidden
    behind a fallback — if editord is down the editor should fail loud."""


def daemon_request(request):
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(DAEMON_TIMEOUT_SEC)
        sock.connect(DAEMON_SOCKET)
        sock.sendall(payload)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()
    except (OSError, socket.timeout) as exc:
        raise DaemonError(f"cannot reach editord: {exc}") from exc

    raw = b"".join(chunks).decode("utf-8").strip()
    if not raw:
        raise DaemonError("empty response from editord")
    return raw


def read_post_body():
    length = int(os.environ.get("CONTENT_LENGTH") or 0)
    if length <= 0:
        raise DaemonError("empty request body")
    return sys.stdin.buffer.read(length).decode("utf-8")


def serve_api():
    body = read_post_body()
    try:
        request = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DaemonError(f"bad request json: {exc}") from exc
    raw_response = daemon_request(request)
    sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n\r\n")
    sys.stdout.write(raw_response)


def serve_page():
    sys.stdout.write("Content-Type: text/html; charset=utf-8\r\n\r\n")
    sys.stdout.write(PAGE)


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shaw-Spell — Editorial Workbench</title>
    <link rel="stylesheet" href="editor.css">
</head>
<body>
    <header class="masthead">
        <div class="mark">·𐑖𐑷-𐑕𐑐𐑧𐑤</div>
        <div class="masthead-text">
            <h1>Editorial Workbench</h1>
            <p class="strap">The dictionary as an editable overlay — accept, edit, drop, author.</p>
        </div>
        <button type="button" class="drawer-toggle" id="drawerToggle"
                aria-controls="ledger" aria-expanded="false">Entries</button>
        <button type="button" class="help-toggle" id="helpToggle"
                aria-controls="cheatsheet" title="Keyboard shortcuts (?)">? keys</button>
        <div class="tally" id="tally" aria-live="polite"></div>
    </header>

    <form class="filters" id="filters" autocomplete="off">
        <label class="field">
            <span>Word</span>
            <input type="text" name="word" placeholder="latin substring">
        </label>
        <label class="field">
            <span>Shaw</span>
            <input type="text" name="shaw" placeholder="𐑖𐑷 substring" class="shavian-input">
        </label>
        <!-- source/status/var/pos chips are populated at boot from the daemon's
             distinct-value facets op, so they track the data rather than drift
             from a hardcoded enum. -->
        <fieldset class="field chips" data-facet="source">
            <legend>Source</legend>
        </fieldset>
        <fieldset class="field chips" data-facet="status">
            <legend>Status</legend>
        </fieldset>
        <fieldset class="field chips" data-facet="word_kind">
            <legend>Words</legend>
            <label class="chip"><input type="checkbox" name="word_kind" value="multi"><span>multi-word</span></label>
            <label class="chip"><input type="checkbox" name="word_kind" value="single"><span>single-word</span></label>
        </fieldset>
        <fieldset class="field chips state-chips" data-facet="novelty">
            <legend>Novelty</legend>
            <label class="chip"><input type="checkbox" name="novelty" value="new-word"><span>new word</span></label>
            <label class="chip"><input type="checkbox" name="novelty" value="new-spelling"><span>new spelling</span></label>
            <label class="chip"><input type="checkbox" name="novelty" value="new-pos"><span>new POS</span></label>
        </fieldset>
        <fieldset class="field chips state-chips" data-facet="reviewed">
            <legend>Reviewed</legend>
            <label class="chip"><input type="checkbox" name="reviewed" value="unreviewed"><span>unreviewed</span></label>
            <label class="chip"><input type="checkbox" name="reviewed" value="flagged"><span>flagged</span></label>
            <label class="chip"><input type="checkbox" name="reviewed" value="decided"><span>decided</span></label>
        </fieldset>
        <fieldset class="field chips state-chips" data-facet="patch_state">
            <legend>State</legend>
            <label class="chip"><input type="checkbox" name="patch_state" value="unreviewed"><span>unreviewed</span></label>
            <label class="chip"><input type="checkbox" name="patch_state" value="edited"><span>edited</span></label>
            <label class="chip"><input type="checkbox" name="patch_state" value="dropped"><span>dropped</span></label>
            <label class="chip"><input type="checkbox" name="patch_state" value="flagged"><span>flagged</span></label>
            <label class="chip"><input type="checkbox" name="patch_state" value="authored"><span>authored</span></label>
        </fieldset>
        <fieldset class="field chips" data-facet="pos">
            <legend>POS</legend>
        </fieldset>
        <fieldset class="field chips" data-facet="var">
            <legend>Var</legend>
        </fieldset>
        <label class="field narrow">
            <span>Conf ≥</span>
            <input type="number" name="confidence_min" min="0" max="100">
        </label>
        <label class="field narrow">
            <span>Conf ≤</span>
            <input type="number" name="confidence_max" min="0" max="100">
        </label>
        <label class="field">
            <span>Sort</span>
            <select id="sort">
                <option value="confidence_desc">confidence ↓</option>
                <option value="confidence_asc">confidence ↑</option>
                <option value="freq_desc">frequency ↓</option>
                <option value="word">word</option>
            </select>
        </label>
        <button type="submit" class="apply">Filter</button>
    </form>

    <main class="workbench" id="workbench">
        <div class="drawer-backdrop" id="drawerBackdrop"></div>
        <section class="ledger" id="ledger" aria-label="Matching entries">
            <div class="ledger-head">
                <span class="col-state">state</span>
                <span class="col-word">word</span>
                <span class="col-shaw">shaw</span>
                <span class="col-var">var</span>
                <span class="col-conf">conf</span>
                <span class="col-pos">pos</span>
            </div>
            <ul class="ledger-list" id="ledgerList" tabindex="0"></ul>
            <div class="ledger-foot" id="ledgerFoot"></div>
        </section>

        <section class="detail mode-review" id="detail" aria-label="Focused entry">
            <p class="detail-empty">Select an entry to review it.</p>
        </section>
    </main>

    <footer class="pacing" id="pacing" aria-label="Session progress"></footer>

    <div class="cheatsheet" id="cheatsheet" role="dialog" aria-modal="true"
         aria-label="Keyboard shortcuts" aria-hidden="true"></div>

    <div class="toast" id="toast" role="status" aria-live="polite"></div>

    <script src="editor.js"></script>
</body>
</html>"""


def main():
    query = os.environ.get("QUERY_STRING", "")
    method = os.environ.get("REQUEST_METHOD", "GET")
    if method == "POST" or "api" in query:
        serve_api()
    else:
        serve_page()


if __name__ == "__main__":
    try:
        main()
    except DaemonError as exc:
        sys.stdout.write("Status: 502 Bad Gateway\r\n")
        sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n\r\n")
        sys.stdout.write(json.dumps({"error": str(exc)}))
    except Exception as exc:  # noqa: BLE001 — CGI last resort, surface loudly
        sys.stdout.write("Status: 500 Internal Server Error\r\n")
        sys.stdout.write("Content-Type: text/plain; charset=utf-8\r\n\r\n")
        sys.stdout.write(f"editor.cgi error: {exc}\n")
        import traceback
        traceback.print_exc(file=sys.stdout)
