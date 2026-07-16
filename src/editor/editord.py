#!/usr/bin/env python3
"""
editord — backing daemon for the Shaw-Spell editorial editor UI.

The read-write sibling of suggestd. It holds the editorial BASIS (upstream
ReadLex + the wordnet/wiktionary supplements) overlaid with the patch store
(data/patches/patches.jsonl), each basis record annotated with its patch-state,
and serves the editor's filter/step/accept/reject ops. It NEVER touches suggestd
or the read-only production spell-check path.

The basis is large (~189K anchors); it is loaded once at startup, like suggestd
loads its indexes, and filtered in memory per request. A write rebuilds the
annotated view so the next read reflects the new patch-state.

Protocol (line-oriented, UTF-8, one request -> one response, then close):

    Request:   {"op": "entries", "filters": {...}, "offset": 0, "limit": 50}
    Response:  {"total": 1234, "offset": 0, "limit": 50, "records": [...]}

    Request:   {"op": "entry", "anchor": {"word","pos","shaw","var"}}
    Response:  {"records": [...]}   # the record on that natural key

    Request:   {"op": "patch", "anchor": {"word","pos","shaw","var"} | null,
                "record": {...} | null, "author": "…"}
    Response:  {"result": "appended"|"replaced", "id": "p_…",
                "records": [...]}   # the anchor re-annotated after the write

    Errors:    {"error": "<message>"}

An anchor is the reviewed record's IMMUTABLE natural key (word, pos, shaw, var):
it is unchanged when the record is edited, so an entry never moves as a result of
being edited. A `record` is the COMPLETE wanted record; null drops it. anchor null
is authorship.

Usage:
    editord.py --socket /run/shaw-spell/editord.sock

Run under systemd (see shaw-spell-editord.service).
"""

import argparse
import json
import logging
import os
import signal
import socketserver
import sys
import time
from pathlib import Path

# The shared basis/overlay/patch modules live in src/tools and src/editor. Put
# both on the path so `import basis` / `import overlay` resolve regardless of
# the working directory the daemon is launched from.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

from basis import anchor_key                                     # noqa: E402
from overlay import load_view                                    # noqa: E402
from patchstore import make_patch, upsert_patch                  # noqa: E402

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class State:
    """The annotated view plus the lock guarding a rebuild. One instance lives
    for the daemon's lifetime; a write swaps in a freshly built view."""

    def __init__(self, view):
        self.view = view

    def rebuild(self):
        self.view = load_view()


def matches(record, filters):
    """Whether an annotated record passes every supplied filter. Absent filters
    do not constrain; a present filter that the record fails excludes it."""
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if not _field_matches(record, key, value):
            return False
    return True


def _field_matches(record, key, value):
    if key == "word":
        return value.lower() in record["word"].lower()
    if key == "shaw":
        return value in record["shaw"]
    if key in ("source", "status", "pos", "var", "patch_state"):
        return record.get(key) == value
    if key == "reviewed":
        return record["reviewed"] == _as_bool(value)
    if key == "confidence_min":
        conf = record.get("confidence")
        return conf is not None and conf >= value
    if key == "confidence_max":
        conf = record.get("confidence")
        return conf is not None and conf <= value
    raise ValueError(f"unknown filter: {key}")


def _as_bool(value):
    """Coerce a filter value to bool. The UI sends 'reviewed'/'unreviewed' as the
    select value; accept the JSON true/false forms too."""
    if isinstance(value, bool):
        return value
    if value in ("reviewed", "true", "1"):
        return True
    if value in ("unreviewed", "false", "0"):
        return False
    raise ValueError(f"reviewed filter wants reviewed/unreviewed, got {value!r}")


def filter_records(records, filters):
    return [r for r in records if matches(r, filters)]


def serialisable(record):
    """The record without the raw patch object (the UI reads patch_state and,
    when it needs the patch itself, the fields it carries)."""
    result = {k: v for k, v in record.items() if k != "patch"}
    patch = record.get("patch")
    result["patch_id"] = patch["id"] if patch else None
    return result


def handle_entries(state, request):
    filters = request.get("filters") or {}
    offset = int(request.get("offset", 0))
    limit = min(int(request.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)

    matched = filter_records(state.view.records, filters)
    matched.sort(key=lambda r: (r["word"].lower(), r["pos"], r["shaw"], r["var"]))
    page = matched[offset:offset + limit]
    return {
        "total": len(matched),
        "offset": offset,
        "limit": limit,
        "records": [serialisable(r) for r in page],
    }


def handle_entry(state, request):
    anchor = request.get("anchor")
    if not anchor:
        return {"error": "entry requires an anchor"}
    records = state.view.by_anchor(anchor_key(anchor))
    return {"records": [serialisable(r) for r in records]}


ANCHOR_FIELDS = ("word", "pos", "shaw", "var")
RECORD_REQUIRED_FIELDS = ("word", "pos", "shaw", "var")
RECORD_ALLOWED_FIELDS = {"word", "pos", "shaw", "var", "ipa", "freq",
                         "source", "status", "confidence", "note"}


def _validate_patch(anchor, record):
    """The applicator's precondition, enforced at the write so a malformed patch
    is rejected where the actor can fix it — never deferred to a build that
    crashes on an incomplete record. The record is self-contained, so every core
    field must be present. Returns an error string or None."""
    if anchor is not None:
        missing = [f for f in ANCHOR_FIELDS if not anchor.get(f)]
        if missing:
            return f"patch anchor missing {', '.join(missing)}"
    if record is not None:
        unknown = set(record) - RECORD_ALLOWED_FIELDS
        if unknown:
            return f"patch record has unknown keys: {', '.join(sorted(unknown))}"
        missing = [f for f in RECORD_REQUIRED_FIELDS if not record.get(f)]
        if missing:
            return f"patch record missing {', '.join(missing)}"
    return None


def handle_patch(state, request):
    anchor = request.get("anchor")
    record = request.get("record")
    author = request.get("author")
    if not author:
        return {"error": "patch requires an author"}
    if anchor is None and record is None:
        return {"error": "patch must supply anchor (edit/drop) or record (authorship)"}
    error = _validate_patch(anchor, record)
    if error:
        return {"error": error}

    # An edit/drop must anchor to a record that exists in the basis right now.
    # Writing an anchor that resolves to nothing would create an orphan the build
    # later fails on; reject it here where the actor can fix it. (Authorship —
    # anchor null — attests a record no basis holds, so it is exempt.)
    if anchor is not None and not state.view.by_anchor(anchor_key(anchor)):
        return {"error": f"anchor resolves to no basis record: {anchor}"}

    meta = {"author": author, "origin": "editor", "ts": _now_iso()}
    note = request.get("note")
    if note:
        meta["note"] = note

    patch = make_patch(anchor, record, meta)
    result, _previous = upsert_patch(patch)
    state.rebuild()

    key = anchor_key(anchor) if anchor is not None else anchor_key(record)
    return {
        "result": result,
        "id": patch["id"],
        "records": [serialisable(r) for r in state.view.by_anchor(key)],
    }


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


HANDLERS = {
    "entries": handle_entries,
    "entry": handle_entry,
    "patch": handle_patch,
}


def handle_request(state, request):
    """Dispatch one request dict to a response dict."""
    op = request.get("op")
    handler = HANDLERS.get(op)
    if handler is None:
        return {"error": f"unknown op: {op!r}"}
    return handler(state, request)


class RequestHandler(socketserver.StreamRequestHandler):
    """One request, one response, then close."""

    READ_TIMEOUT_SEC = 5.0

    def handle(self):
        start = time.perf_counter()
        self.connection.settimeout(self.READ_TIMEOUT_SEC)

        request = None
        try:
            line = self.rfile.readline()
            if not line:
                logging.warning("empty request from client")
                return
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                response = {"error": f"bad request: {exc}"}
            else:
                response = handle_request(self.server.state, request)
        except Exception as exc:
            logging.exception("handler error")
            response = {"error": str(exc)}

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        op = (request or {}).get("op", "?") if isinstance(request, dict) else "?"
        total = response.get("total")
        logging.info("%s total=%s %.1fms", op, total, elapsed_ms)

        try:
            payload = json.dumps(response, ensure_ascii=False) + "\n"
            self.wfile.write(payload.encode("utf-8"))
        except BrokenPipeError:
            logging.info("client disconnected before response sent")
        except Exception:
            logging.exception("failed to write response")


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Threaded so a slow client can't block others. A patch write rebuilds the
    view under the server's single-writer assumption (this is a single-user
    editor); concurrent writers are a Phase-2 concern, not handled here."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path, state):
        super().__init__(socket_path, RequestHandler)
        self.state = state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="Unix socket path")
    parser.add_argument("--socket-mode", default="0666",
                        help="Octal socket permissions (default 0666)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s editord[%(process)d] %(levelname)s %(message)s",
    )

    logging.info("building annotated view (basis + patches)")
    state = State(load_view())
    logging.info("view ready: %d annotated records", len(state.view.records))

    socket_path = args.socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)

    server = Server(socket_path, state)
    os.chmod(socket_path, int(args.socket_mode, 8))
    logging.info("listening on %s", socket_path)

    def _shutdown(signum, _frame):
        logging.info("signal %d — shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        if os.path.exists(socket_path):
            os.unlink(socket_path)


if __name__ == "__main__":
    sys.exit(main() or 0)
