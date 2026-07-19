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
        <button type="button" class="filters-toggle chevron-toggle" id="filtersToggle"
                aria-controls="filters" aria-expanded="true"
                title="Filters"><span class="chevron" aria-hidden="true"></span>Filters</button>
        <button type="button" class="drawer-toggle chevron-toggle" id="drawerToggle"
                aria-controls="ledger" aria-expanded="false"
                title="Entries"><span class="chevron" aria-hidden="true"></span>Entries</button>
        <button type="button" class="commit-decisions" id="commitDecisions" disabled
                title="Commit the accumulated editorial decisions to git">Commit</button>
        <button type="button" class="new-entry" id="newEntry"
                title="Author a brand-new dictionary entry">+ New entry</button>
        <button type="button" class="help-toggle" id="helpToggle"
                aria-controls="cheatsheet" title="Keyboard shortcuts (?)">? keys</button>
        <div class="tally" id="tally" aria-live="polite"></div>
    </header>

    <!-- The filter bar shows only ACTIVE filters, as composable chips. "+ Add filter"
         opens a menu of the not-yet-active fields; picking one adds its chip and opens
         its value picker. The registry (editor.js FIELD_REGISTRY) is the single source
         of truth for the fields, their kinds and order; it harvests its metadata from
         the hidden .filter-meta block below at boot. -->
    <form class="filters" id="filters" autocomplete="off">
        <div class="chip-strip" id="chipStrip"></div>
        <div class="add-filter-wrap" id="addFilterWrap">
            <button type="button" class="add-filter" id="addFilter"
                    aria-haspopup="true" aria-expanded="false">+ Add filter</button>
        </div>
        <button type="button" class="refresh-results" id="refreshResults"
                title="Refresh results — re-run the current filter and drop reviewed rows"
                aria-label="Refresh results">⟳</button>
    </form>

    <!-- Filter metadata: one <div data-field> per registry field, carrying its human
         label (data-label) and its kind (data-kind). A closed-vocabulary categorical
         field also lists its value→label pairs as .chip templates, so those labels stay
         authored here rather than duplicated in JS; a data-derived categorical field
         (pos/var/status/source) omits them and takes its values from the daemon facets
         op. The block is never rendered — editor.js harvests it into the registry. -->
    <div class="filter-meta" id="filterMeta" hidden>
        <div data-field="word" data-kind="text" data-label="Word"
             data-placeholder="latin substring"></div>
        <div data-field="shaw" data-kind="text" data-label="Shaw"
             data-placeholder="𐑖𐑷 substring" data-shavian="true"></div>
        <div data-field="source" data-kind="categorical" data-label="Source"></div>
        <div data-field="status" data-kind="categorical" data-label="Status"></div>
        <div data-field="pos" data-kind="categorical" data-label="POS"></div>
        <div data-field="var" data-kind="categorical" data-label="Var"></div>
        <div data-field="word_kind" data-kind="categorical" data-label="Words">
            <label class="chip"><input value="multi"><span>multi-word</span></label>
            <label class="chip"><input value="single"><span>single-word</span></label>
        </div>
        <div data-field="novelty" data-kind="categorical" data-label="Novelty">
            <label class="chip"><input value="new-word"><span>new word</span></label>
            <label class="chip"><input value="new-spelling"><span>new spelling</span></label>
            <label class="chip"><input value="new-pos"><span>new POS</span></label>
        </div>
        <div data-field="reviewed" data-kind="categorical" data-label="Reviewed">
            <label class="chip"><input value="unreviewed"><span>unreviewed</span></label>
            <label class="chip"><input value="flagged"><span>flagged</span></label>
            <label class="chip"><input value="decided"><span>decided</span></label>
        </div>
        <div data-field="patch_state" data-kind="categorical" data-label="State">
            <label class="chip"><input value="unreviewed"><span>unreviewed</span></label>
            <label class="chip"><input value="edited"><span>edited</span></label>
            <label class="chip"><input value="dropped"><span>dropped</span></label>
            <label class="chip"><input value="flagged"><span>flagged</span></label>
            <label class="chip"><input value="authored"><span>authored</span></label>
            <label class="chip"><input value="orphaned"><span>orphaned</span></label>
        </div>
        <div data-field="mergers" data-kind="categorical" data-label="Mergers">
            <label class="chip"><input value="trap-bath"><span>TRAP–BATH</span></label>
            <label class="chip"><input value="cot-caught"><span>COT–CAUGHT</span></label>
            <label class="chip"><input value="(none)"><span>(none / canonical)</span></label>
        </div>
        <div data-field="variant" data-kind="categorical" data-label="Variant">
            <label class="chip"><input value="variant"><span>variant</span></label>
            <label class="chip"><input value="canonical"><span>canonical</span></label>
        </div>
        <div data-field="has_definition" data-kind="categorical" data-label="Definition">
            <label class="chip"><input value="has-definition"><span>has definition</span></label>
            <label class="chip"><input value="no-definition"><span>no definition</span></label>
        </div>
        <div data-field="orphaned" data-kind="categorical" data-label="Orphaned">
            <label class="chip"><input value="orphaned"><span>orphaned</span></label>
            <label class="chip"><input value="not-orphaned"><span>not orphaned</span></label>
        </div>
        <div data-field="confidence_min" data-kind="numeric" data-label="Conf ≥"></div>
        <div data-field="confidence_max" data-kind="numeric" data-label="Conf ≤"></div>
    </div>

    <main class="workbench" id="workbench">
        <div class="drawer-backdrop" id="drawerBackdrop"></div>
        <section class="ledger" id="ledger" aria-label="Matching entries">
            <div class="select-bar" id="selectBar" hidden>
                <span class="select-bar-count" id="selectBarCount"></span>
                <button type="button" class="select-bar-done" id="selectBarDone">Done</button>
            </div>
            <div class="ledger-head" id="ledgerHead">
                <button type="button" class="col-state sort-head" data-sort-key="state">state</button>
                <button type="button" class="col-word sort-head" data-sort-key="word">word</button>
                <button type="button" class="col-shaw sort-head" data-sort-key="shaw">shaw</button>
                <button type="button" class="col-var sort-head" data-sort-key="var">var</button>
                <button type="button" class="col-conf sort-head" data-sort-key="confidence">conf</button>
                <button type="button" class="col-freq sort-head" data-sort-key="freq">freq</button>
                <button type="button" class="col-pos sort-head" data-sort-key="pos">pos</button>
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

    <!-- The shared create-entry modal (New Entry blank, or Clone-as-dialect
         prepopulated). Empty in markup — editor.js builds the form on open. -->
    <div class="create-modal" id="createModal" role="dialog" aria-modal="true"
         aria-label="Create entry" aria-hidden="true"></div>

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
