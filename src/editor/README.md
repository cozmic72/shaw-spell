# Editorial editor

The read-write editorial tool: an editable view of the dictionary with extra ways
of searching. The dictionary is the **basis** (upstream ReadLex + wordnet/wiktionary
supplements, computed on demand) overlaid with the **patch store**
(`data/patches/patches.jsonl`, the only persisted editorial artifact). Each basis
record is annotated with its patch-state — unreviewed / accepted / edited / dirty /
dropped / flagged / orphaned — and a derived `reviewed` flag (a patch exists).
Manual authorship is an ORIGIN, not a state: an authored row carries `manual: true`
and takes a verdict like any other. See `docs/editorial-overlay-design.md`.

A **persisted** patch is `{anchor, op, changes, meta}` — a minimal diff over the live basis
(see `src/editor/patchstore.py`). `anchor` is the reviewed record's immutable natural key
`{word, pos, shaw, var}` (never changed on edit, so an entry never moves; `anchor: null`
is authorship). `op` is `accept` (sanction the anchored basis record), `edit` (a bare
not-yet-reviewed edit), `drop` (remove it), or `flag` (a production no-op). `changes` are
the intrinsic edits (`word, shaw, pos, ipa, var, mergers, variant, freq`) laid over the
basis record — empty means accept as-is; for authorship it is the whole self-contained
record.

The **socket `patch` op** (below) is client-facing and still sends the COMPLETE wanted
`record`; the daemon diffs its intrinsic fields against the live basis and persists the
minimal-diff patch above.

It is a sibling of the production `suggestd`, never touching it or the read-only
spell-check path.

## Parts

- `editord.py` — the daemon. Loads the annotated view once, serves editor ops over a
  Unix socket, and on each write updates only the affected anchor's annotation in the
  in-memory view (an incremental update, not a full reload).
- `overlay.py`, `patchstore.py` — the annotated view and the patch read/write, both
  built on `src/tools/basis.py` (the same anchor logic the applicator uses).
- `site/editor.cgi` — thin HTTP frontend. Serves the page and proxies each POSTed
  JSON body to the daemon verbatim.
- `site/editor.js`, `site/editor.css` — the browser UI.

## Ops (line-oriented JSON over the socket)

    {"op":"entries","filters":{...},"offset":0,"limit":50}
        -> {"total","offset","limit","groups":[{"key","records":[...]},...]}
        # group-denominated: total/offset/limit count GROUPS (word_lower+shaw+
        # variation-set), a group is never split across pages, groups rank by
        # their best member under the active sort; only the daemon computes
        # grouping — `key` is opaque to the client
    {"op":"entry","anchor":{"word","pos","shaw","var"}}
        -> {"records":[...]}                       # the record on that natural key
    {"op":"patch","anchor":{"word","pos","shaw","var"}|null,"record":{...}|null,
     "author":"…","dirty"?:bool,"replaces"?:"p_…"}
        -> {"result":"appended"|"replaced","id","records":[...]}
    {"op":"flag","anchor":{"word","pos","shaw","var"}|null,"author":"…"}   # production no-op
    {"op":"unpatch","anchor":{...}|"patch_id":"p_…"}                        # undo/clear

`record` is the complete wanted record; `record:null` is a drop; `anchor:null`
(with a record) is authorship. `dirty` marks a bare edit-on-navigate (persisted
`op:edit`, not reviewed/shipped); an explicit Accept (no `dirty`) reviews and ships.
The daemon diffs the record and persists the minimal-diff patch (see above). The write
validates the patch shape and, for an accept/edit/drop, that the anchor resolves to a
basis record. See `editord.py` for the full op set (`related`, `definitions`,
`commit`, …).

Filters: the combined `search` free-text (always-regex, case-insensitive, matched
against word OR shaw OR ipa) plus `word`/`shaw` substring (back-compat); the three
orthogonal facet axes `review` (verdict lifecycle), `data` (origin/nature) and
`novelty` (vs upstream ReadLex), plus `pos`, `var`, `source`, `attributes`,
`word_kind`, `patch_author`; numeric `confidence_min`/`confidence_max` and
`patch_days`. See `editord.py`'s protocol docstring for the full semantics.

## Run locally

One command spawns the daemon and serves `site/` over CGI, bound to `0.0.0.0` so
the editor is reachable from other devices on the LAN:

    ./src/tools/test_editor.py [port]        # default 8010

NOTE: `0.0.0.0` exposes an unauthenticated WRITE endpoint (the patch op mutates the
store) on the LAN — auth is deferred to Phase 2. The daemon itself stays behind a
local Unix socket; only the CGI HTTP front is on the network.

To run the daemon alone (AF_UNIX paths are length-limited, so keep it short):

    python3 src/editor/editord.py --socket /tmp/editord.sock

Then serve `site/` with a CGI-capable web server whose `.cgi` handler runs
`editor.cgi`, with `SHAW_SPELL_EDITOR_SOCKET` pointing at that socket. `editor.cgi`,
`editor.css` and `editor.js` are siblings under one document root.

`editor.css` loads the Shavian webfont from `fonts/BernieSansBetaVF.woff2` relative
to that document root, matching the production site (`src/site/css/style.css`). The
single source of that font is `src/fonts/BernieSansBetaVF.woff2`; make it reachable
at `fonts/` under the editor's document root — the production `deploy_site.py` does
this by copying `src/fonts/*` into `output/fonts/`. Until an editor deploy step
exists, serve it there manually (e.g. symlink `src/fonts` to `fonts` in the doc
root); without it, Shavian falls back to a sans-serif and renders incorrectly.

The default socket is `/run/shaw-spell/editord.sock`; override it with
`SHAW_SPELL_EDITOR_SOCKET`.

## Deploy

`shaw-spell-editord.service` mirrors `shaw-spell-suggestd.service`. Unlike suggestd,
editord writes the patch store, so the unit grants `ReadWritePaths` for
`data/patches` rather than mounting the tree read-only.

## Editing

The detail editor exposes every intrinsic field of the focused record (word, shaw,
pos, ipa, var, mergers/variant chips, freq) because the record is self-contained.
Actions produce a patch on the record's immutable anchor: **Accept** (persisted
`op:accept`, reviewed and shipped), **Drop** (`op:drop`, removes the record),
**Flag** (`op:flag`, looked-at-no-verdict). A bare edit is auto-saved on navigate
as a DIRTY patch (`op:edit` — kept but not reviewed, ships nothing) until an
explicit Accept.

The filtered list is a materialised working set: a just-reviewed row stays in place
showing its new content and stamp (it does not vanish), and the list only re-syncs —
dropping now-non-matching rows and re-sorting — when the filter is re-run.

## Keyboard

Enter accepts the focused entry; Cmd/Ctrl+Enter saves the edit; Shift+Enter drops;
Up/Down step through the filtered list.
