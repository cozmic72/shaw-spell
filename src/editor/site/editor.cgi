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
import time

# Find authstore whether it sits BESIDE this cgi (deploy: everything editor-web
# in one dir) or one level up (dev tree: src/editor/site/editor.cgi + src/editor/
# authstore.py). Deploy keeps authstore inside the editor docroot, not in the
# shared site root.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_here))
sys.path.insert(0, _here)
import authstore  # noqa: E402 — path set above

DAEMON_SOCKET = os.environ.get("SHAW_SPELL_EDITOR_SOCKET",
                               "/run/shaw-spell/editord.sock")
DAEMON_TIMEOUT_SEC = 10.0
# A commit publishes readlex.json and runs git commit+push — legitimately longer
# than any read op. The 10s cutoff mid-commit made the browser toast a false
# "cannot reach editord" while the commit went on to land, so the commit op alone
# holds the socket until the daemon's real answer (with a generous ceiling so a
# wedged daemon still fails loud eventually).
COMMIT_TIMEOUT_SEC = 600.0

SESSION_COOKIE = "shaw-spell-session"
MAX_AUTH_BODY_BYTES = 4096


class DaemonError(Exception):
    """The daemon is unreachable or errored. Surfaced to the client, not hidden
    behind a fallback — if editord is down the editor should fail loud."""


def daemon_request(request, timeout=DAEMON_TIMEOUT_SEC):
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
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


def read_post_body(limit=None):
    length = int(os.environ.get("CONTENT_LENGTH") or 0)
    if length <= 0:
        raise DaemonError("empty request body")
    if limit is not None and length > limit:
        raise DaemonError("request body too large")
    return sys.stdin.buffer.read(length).decode("utf-8")


# ---- auth (the security boundary) ----

def parse_cookies(header):
    cookies = {}
    for pair in (header or "").split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def session_token():
    return parse_cookies(os.environ.get("HTTP_COOKIE", "")).get(SESSION_COOKIE)


def resolve_user():
    """The verified (user_id, handle) for the request's session cookie, or None.
    Fails CLOSED: any error resolving the session denies (returns None), never
    default-allows."""
    try:
        return authstore.user_for_session(session_token())
    except Exception:  # noqa: BLE001 — deny on any auth-store failure
        return None


def request_is_https():
    """True behind TLS. Secure cookies are dropped by the browser over plain
    HTTP, so we only set Secure when the connection actually is HTTPS — on
    directly (HTTPS=on) or via a TLS-terminating proxy (X-Forwarded-Proto)."""
    if os.environ.get("HTTPS", "").lower() in ("on", "1", "true"):
        return True
    return os.environ.get("HTTP_X_FORWARDED_PROTO", "").lower() == "https"


def set_cookie_header(value, expires_epoch):
    fmt = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(expires_epoch))
    secure = " Secure;" if request_is_https() else ""
    return (f"Set-Cookie: {SESSION_COOKIE}={value}; Path=/; HttpOnly;{secure} "
            f"SameSite=Lax; Expires={fmt}\r\n")


def write_json(status, body, extra_headers=""):
    sys.stdout.write(f"Status: {status}\r\n")
    sys.stdout.write(extra_headers)
    sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n\r\n")
    sys.stdout.write(json.dumps(body, ensure_ascii=False))


def read_auth_body():
    body = read_post_body(limit=MAX_AUTH_BODY_BYTES)
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def handle_login():
    body = read_auth_body()
    handle = body.get("handle")
    password = body.get("password")
    if not isinstance(handle, str) or not isinstance(password, str):
        write_json("401 Unauthorized", {"error": "invalid credentials"})
        return
    user_id = None
    try:
        user_id = authstore.authenticate(handle, password)
    except Exception:  # noqa: BLE001 — fail closed on store error
        user_id = None
    if user_id is None:
        write_json("401 Unauthorized", {"error": "invalid credentials"})
        return
    token = authstore.create_session(user_id)
    verified = authstore.handle_for_user(user_id)
    write_json("200 OK", {"handle": verified},
               set_cookie_header(token, time.time() + authstore.SESSION_TTL_SECONDS))


def handle_logout():
    authstore.delete_session(session_token())
    write_json("200 OK", {"ok": True}, set_cookie_header("", 0))


def handle_me():
    user = resolve_user()
    if user is None:
        write_json("401 Unauthorized", {"error": "not signed in"})
        return
    write_json("200 OK", {"handle": user[1]})


def serve_api():
    """Proxy a daemon op — GATED. A logged-out caller is refused (401); a
    logged-in caller's asserted author is OVERWRITTEN with the verified handle
    before the request reaches editord (the unforgeable-author boundary)."""
    user = resolve_user()
    if user is None:
        write_json("401 Unauthorized", {"error": "not signed in"})
        return
    handle = user[1]
    body = read_post_body()
    try:
        request = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DaemonError(f"bad request json: {exc}") from exc
    # The trust boundary: the verified handle REPLACES any client-asserted
    # author, unconditionally. meta.author becomes unforgeable.
    if isinstance(request, dict):
        request["author"] = handle
    timeout = (COMMIT_TIMEOUT_SEC
               if isinstance(request, dict) and request.get("op") == "commit"
               else DAEMON_TIMEOUT_SEC)
    raw_response = daemon_request(request, timeout)
    sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n\r\n")
    sys.stdout.write(raw_response)


def asset_version(name):
    """A cache-busting stamp for a sibling static asset: its mtime. The editor
    serves editor.css/editor.js by plain filename, so browsers cache them hard
    and an edit only shows after a manual hard-reload. Stamping the href with the
    file's mtime makes every edit a fresh URL — no stale CSS/JS. Fails soft to
    a constant if the file is missing (the browser just caches; no crash).
    The stamps only work because the PAGE embedding them is no-store (see
    serve_page): a cached document would keep referencing old stamped URLs."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


def serve_page():
    """GATED. Logged-out callers get the standalone login page (the editor
    HTML/JS is NOT shipped to them — front gate); logged-in callers get the
    editor. Both documents are no-store: the page is regenerated per request
    (login-state gate + fresh asset stamps), so a cached copy is always wrong —
    stale stamped URLs, or the login page shown to a logged-in user. The
    stamped ASSETS stay cacheable; that is the point of the stamps."""
    sys.stdout.write("Cache-Control: no-store\r\n")
    if resolve_user() is None:
        sys.stdout.write("Content-Type: text/html; charset=utf-8\r\n\r\n")
        sys.stdout.write(LOGIN_PAGE)
        return
    sys.stdout.write("Content-Type: text/html; charset=utf-8\r\n\r\n")
    page = PAGE.replace("{css_v}", asset_version("editor.css")) \
               .replace("{js_v}", asset_version("editor.js"))
    sys.stdout.write(page)


LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shaw-Spell — Sign in</title>
    <style>
        body { font-family: system-ui, sans-serif; background: #14171c; color: #e8eaed;
               display: flex; min-height: 100vh; margin: 0; align-items: center;
               justify-content: center; }
        .card { background: #1e232b; padding: 2rem 2.25rem; border-radius: 10px;
                width: min(22rem, 90vw); box-shadow: 0 8px 30px rgba(0,0,0,.4); }
        h1 { font-size: 1.15rem; margin: 0 0 1.25rem; }
        label { display: block; font-size: .8rem; margin: .75rem 0 .25rem; opacity: .8; }
        input { width: 100%; box-sizing: border-box; padding: .55rem .65rem;
                border: 1px solid #3a4150; border-radius: 6px; background: #12151a;
                color: #e8eaed; font-size: 1rem; }
        button { margin-top: 1.25rem; width: 100%; padding: .6rem; border: 0;
                 border-radius: 6px; background: #4f7cff; color: #fff; font-size: 1rem;
                 cursor: pointer; }
        button:disabled { opacity: .6; cursor: default; }
        .err { color: #ff8080; font-size: .85rem; margin-top: .9rem; min-height: 1.1em; }
    </style>
</head>
<body>
    <form class="card" id="loginForm" autocomplete="on">
        <h1>Editorial Workbench — sign in</h1>
        <label for="handle">Username</label>
        <input id="handle" name="handle" autocomplete="username"
               autocapitalize="off" spellcheck="false" required>
        <label for="password">Password</label>
        <input id="password" name="password" type="password"
               autocomplete="current-password" required>
        <button type="submit" id="submit">Sign in</button>
        <div class="err" id="err" role="alert"></div>
    </form>
    <script>
    (function () {
        var form = document.getElementById("loginForm");
        var btn = document.getElementById("submit");
        var err = document.getElementById("err");
        form.addEventListener("submit", async function (e) {
            e.preventDefault();
            err.textContent = "";
            btn.disabled = true;
            try {
                var resp = await fetch(location.pathname + "?api=login", {
                    method: "POST",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        handle: document.getElementById("handle").value,
                        password: document.getElementById("password").value,
                    }),
                });
                if (resp.ok) { location.reload(); return; }
                err.textContent = "Invalid credentials.";
            } catch (ex) {
                err.textContent = "Sign-in failed. Try again.";
            } finally {
                btn.disabled = false;
            }
        });
    })();
    </script>
</body>
</html>"""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shaw-Spell — Editorial Workbench</title>
    <link rel="stylesheet" href="editor.css?v={css_v}">
    <link rel="stylesheet" href="virtual-keyboard/virtual-keyboard.css">
</head>
<body>
    <header class="masthead">
        <div class="mark">·𐑖𐑷-𐑕𐑐𐑧𐑤</div>
        <div class="masthead-text">
            <h1>Editorial Workbench</h1>
            <p class="strap">The dictionary as an editable overlay — accept, edit, drop, author.</p>
            <!-- Scoped to the CURRENT FILTER (not the whole corpus) plus the one
                 count that changes as the owner works: patches banked but not yet
                 committed. Filled by paintMastheadStats — the matched-count half
                 from runQuery, the uncommitted half from refreshCommitStatus. -->
            <div class="masthead-stats" id="mastheadStats" aria-live="polite"></div>
        </div>
        <button type="button" class="new-entry" id="newEntry" aria-label="New entry"
                title="Author a brand-new dictionary entry">+</button>
        <!-- Overflow menu: the occasional controls behind one ⋯ trigger, in the
             .facet-panel popover idiom the filter pickers use. paintCommitButton
             stamps `uncommitted` on the trigger so uncommitted work stays visible
             while Commit sits in here. -->
        <div class="masthead-menu-wrap">
            <button type="button" class="masthead-btn" id="mastheadMenu"
                    aria-haspopup="true" aria-expanded="false"
                    aria-label="More" title="More">⋯</button>
            <div class="facet-panel masthead-menu" id="mastheadMenuPanel" hidden>
                <span class="whoami" id="whoami" title="Signed in as"></span>
                <button type="button" class="menu-item commit-decisions" id="commitDecisions"
                        disabled hidden
                        title="Commit the accumulated editorial decisions to git">Commit</button>
                <button type="button" class="menu-item" id="viewModeToggle"
                        aria-pressed="false"
                        title="Toggle between the grouped and flat record view">Flat view</button>
                <button type="button" class="menu-item danger" id="revertUncommitted"
                        title="Discard every uncommitted editorial decision since the last commit">Revert uncommitted changes</button>
                <button type="button" class="menu-item" id="helpToggle"
                        aria-controls="cheatsheet"
                        title="Keyboard shortcuts (?)">Keyboard shortcuts</button>
                <button type="button" class="menu-item" id="kbToggle"
                        onclick="ShawSpellKeyboard.openSettings()"
                        title="Keyboard layout & settings (Cmd/Ctrl+K toggles)">Shavian keyboard</button>
                <button type="button" class="menu-item" id="logout"
                        title="Sign out">Sign out</button>
            </div>
        </div>
    </header>

    <!-- Twin disclosure rails (collapsed layout only): the filter panel's and the
         ledger drawer's toggles side by side, one control idiom, one chevron
         convention (▸ closed, ▾ open). -->
    <div class="panel-rails">
        <button type="button" class="rail-toggle chevron-toggle" id="filtersToggle"
                aria-controls="filters" aria-expanded="true"
                title="Filters"><span class="chevron" aria-hidden="true"></span>Filters</button>
        <button type="button" class="rail-toggle chevron-toggle" id="drawerToggle"
                aria-controls="ledger" aria-expanded="false"
                title="Entries"><span class="chevron" aria-hidden="true"></span>Entries</button>
    </div>

    <!-- The filter bar shows only ACTIVE filters, as composable chips. "+ Add filter"
         opens a menu of the not-yet-active fields; picking one adds its chip and opens
         its value picker. The registry (editor.js FIELD_REGISTRY) is the single source
         of truth for the fields, their kinds and order; it harvests its metadata from
         the hidden .filter-meta block below at boot. -->
    <form class="filters" id="filters" autocomplete="off">
        <!-- The inline combined free-text search (Latin OR Shaw, always regex +
             case-insensitive). A bare toolbar box, populated by editor.js from the
             data-inline search field — not a removable chip. -->
        <div class="search-inline" id="searchInline"></div>
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
         defined here rather than duplicated in JS; a field whose vocabulary can
         drift (pos/var/source = observed data; attributes = MERGER_ENABLED) omits
         them and takes its values from the daemon facets op instead.
         `data-pinned="true"` marks the always-shown fields (the combined Search
         box, Review, Data, Novelty) — permanent, seeding the strip and not removable;
         the rest are added on demand from the +Add filter menu. `data-inline="true"`
         marks a field rendered as a bare toolbar control (the Search box), not a chip
         with a popover. `data-multi="true"` marks a MULTI-VALUED categorical facet
         (source, attributes) whose picker offers the any/all mode toggle; scalar
         facets omit it and show no toggle. The block is never rendered — editor.js
         harvests it into the registry.

         The three pinned categoricals are ORTHOGONAL AXES: Review = process status
         (the review lifecycle), Data = data predicates (origin/nature of the record),
         Novelty = word-newness. OR within an axis, AND across axes — 'generated AND
         unreviewed' is Data:generated + Review:unreviewed. -->
    <div class="filter-meta" id="filterMeta" hidden>
        <!-- ONE combined free-text box (Latin OR Shaw). Always regex, always
             case-insensitive — the daemon's `search` filter (SEARCH_FIELD). No
             per-box toggles; it replaces the former separate word + shaw fields.
             Inlined into the toolbar (data-inline), not a chip picker. -->
        <div data-field="search" data-kind="text" data-label="Search" data-pinned="true"
             data-inline="true" data-placeholder="latin or 𐑖𐑷 (regex)"></div>
        <!-- AXIS 1 — Review: the review-lifecycle verdicts (mutually exclusive; a
             record is in exactly one). manual/orphaned are origins, not verdicts —
             they live in Data (see editord _matches_review); a manual record carries
             a real verdict here like any other row. edited/dirty are DECORATIONS,
             not verdicts: accepted covers edited and unreviewed covers dirty (the
             client fans each verdict out to its raw patch_states on the wire —
             editor.js reviewStatesForVerdict). "mixed" is the one GROUP-level value:
             it selects groups whose members do NOT all share one verdict (the
             daemon's REVIEW_MIXED leg), OR-ed with the record verdicts. -->
        <div data-field="review" data-kind="categorical" data-label="Review" data-pinned="true">
            <label class="chip"><input value="unreviewed"><span>unreviewed</span></label>
            <label class="chip"><input value="accepted"><span>accepted</span></label>
            <label class="chip"><input value="dropped"><span>dropped</span></label>
            <label class="chip"><input value="flagged"><span>flagged</span></label>
            <label class="chip"><input value="mixed"><span>mixed</span></label>
        </div>
        <!-- AXIS 2 — Data: origin/nature predicates, NON-mutually-exclusive (a record
             can be manual AND have a definition). Absorbs the former Status and
             Definition facets and the origin values once in Review (see editord
             _matches_data). generated + supplement are DROPPED here — redundant now
             the Source facet is atomic (Source:generated, or Source-ALL wordnet+
             wiktionary for supplement-agreement). promoted = the reclassifier
             relabelled its var (orig_var present). -->
        <div data-field="data" data-kind="categorical" data-label="Data" data-pinned="true">
            <label class="chip"><input value="manual"><span>manual</span></label>
            <label class="chip"><input value="orphaned"><span>orphaned</span></label>
            <label class="chip"><input value="promoted"><span>promoted</span></label>
            <label class="chip"><input value="has-definition"><span>has definition</span></label>
            <label class="chip"><input value="no-definition"><span>no definition</span></label>
        </div>
        <!-- AXIS 3 — Novelty: word-newness against upstream ReadLex; upstream = a
             ReadLex-core row (the not-new baseline the new-* values are measured
             against). Pinned. -->
        <div data-field="novelty" data-kind="categorical" data-label="Novelty" data-pinned="true">
            <label class="chip"><input value="new-word"><span>new word</span></label>
            <label class="chip"><input value="new-spelling"><span>new spelling</span></label>
            <label class="chip"><input value="new-pos"><span>new POS</span></label>
            <label class="chip"><input value="upstream"><span>upstream</span></label>
        </div>
        <!-- Source: ATOMIC origins (readlex/wordnet/wiktionary/names/generated),
             data-derived from the daemon facets op. Multi-valued (a record can be
             attested by several), so its picker offers the any/all mode toggle:
             ALL = multi-source agreement (the record's source-set ⊇ the selected). -->
        <div data-field="source" data-kind="categorical" data-label="Source" data-multi="true"></div>
        <div data-field="pos" data-kind="categorical" data-label="POS"></div>
        <div data-field="var" data-kind="categorical" data-label="Var"></div>
        <div data-field="word_kind" data-kind="categorical" data-label="Words">
            <label class="chip"><input value="multi"><span>multi-word</span></label>
            <label class="chip"><input value="single"><span>single-word</span></label>
        </div>
        <!-- Variations: the has-many union of the (flattened, on-disk) mergers list
             + variant boolean — the same tag-set the detail editor edits as toggle
             buttons. Merges the former Mergers + Variant facets. Multi-valued, so its
             picker offers any/all: ALL = the record carries EVERY selected variation.
             Its chips are CODE-DEFINED (like pos/var/source) rather than listed
             here: the merger vocabulary is env-gated (MERGER_ENABLED) so it can
             drift without a code edit, and a hardcoded list here is exactly the
             staleness bug this replaced — see editord.handle_facets. The "other"
             chip's VALUE stays "variant" (the daemon facet + saved sessions key
             off it); only its label reads "other". -->
        <div data-field="attributes" data-kind="categorical" data-label="Variations" data-multi="true"></div>
        <div data-field="confidence_min" data-kind="numeric" data-label="Conf ≥"
             data-min="0" data-max="100"></div>
        <div data-field="confidence_max" data-kind="numeric" data-label="Conf ≤"
             data-min="0" data-max="100"></div>
        <!-- Author: the patch's meta.author. Data-derived (the distinct authors the
             daemon facets op returns). A record with no patch carries no author and
             matches nothing. -->
        <div data-field="patch_author" data-kind="categorical" data-label="Author"></div>
        <!-- Edited within: a relative "days back" scalar. A record matches when its
             patch was made no more than N days ago (patch_days). data-min/max bound
             the number input (1..365, unlike the 0..100 confidence range). -->
        <div data-field="patch_days" data-kind="numeric" data-label="Edited ≤ days back"
             data-min="1" data-max="365"></div>
    </div>

    <main class="workbench" id="workbench">
        <div class="drawer-backdrop" id="drawerBackdrop"></div>
        <!-- Collapsed-ledger rail (wide screens only): a thin strip standing in for
             the hidden list, its chevron pointing into the page to pull it back.
             Sits BEFORE the ledger so the splitter's siblings stay ledger/detail. -->
        <button type="button" class="ledger-rail" id="ledgerRail"
                aria-controls="ledger" aria-label="Show the entry list"
                title="Show the entry list"><span class="chevron" aria-hidden="true"></span></button>
        <section class="ledger" id="ledger" aria-label="Matching entries">
            <div class="select-bar" id="selectBar" hidden>
                <span class="select-bar-count" id="selectBarCount"></span>
                <button type="button" class="select-bar-done" id="selectBarDone">Done</button>
            </div>
            <div class="ledger-head" id="ledgerHead">
                <span class="col-chevron" aria-hidden="true"></span>
                <span class="col-count" title="group members">#</span>
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

        <!-- Ledger / detail divider (wide screens only): drag the handle to resize
             the split, double-click to collapse the list to the rail above. -->
        <div class="splitter" id="workbenchSplitter">
            <div class="splitter-handle"
                 title="Drag to resize; double-click to hide the entry list"></div>
        </div>

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

    <script src="editor.js?v={js_v}"></script>
    <script src="virtual-keyboard/virtual-keyboard.js"></script>
    <script src="virtual-keyboard/custom-layouts.js"></script>
    <script src="virtual-keyboard-modal.js"></script>
</body>
</html>"""


def parse_query(query):
    params = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key] = value
        elif pair:
            params[pair] = ""
    return params


def main():
    query = os.environ.get("QUERY_STRING", "")
    method = os.environ.get("REQUEST_METHOD", "GET")
    api = parse_query(query).get("api")

    if api == "login":
        handle_login()
    elif api == "logout":
        handle_logout()
    elif api == "me":
        handle_me()
    elif method == "POST" or "api" in query:
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
