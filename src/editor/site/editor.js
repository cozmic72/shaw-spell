"use strict";

// The editor speaks editord's protocol directly: the CGI forwards each POSTed
// body to the daemon verbatim and returns its reply. See editord.py for the op
// shapes (entries / entry / patch / flag / unpatch) and overlay.py for
// patch_state semantics.
//
// Pull-and-refresh: runQuery() materialises a working set (state.records). While
// the user works it, membership and order stay STABLE — a just-reviewed row keeps
// its place, updated in-place with its new content and stamp, even if it no longer
// matches the filter. The list only re-syncs (dropping non-matching rows and
// re-sorting) when the user RE-RUNS the filter.
//
// Review mode vs edit mode: on landing the user is in REVIEW MODE — no field is
// focused, and single-key verdicts (A/X/F/E/…) fire immediately. Edit mode is an
// explicit choice (E, or clicking a field); saving or Escape returns to review
// mode. A single-key verdict never fires while a field holds focus.

const AUTHOR = "editor";
const PAGE_LIMIT = 200;
const ACCEPTED_STATUS = "sanctioned";
const SESSION_KEY = "shaw-spell.editor.session";
const DEFAULT_SORT = "confidence_desc";
const RRP_VAR = "RRP";

const EDITABLE_FIELDS = ["shaw", "var", "ipa", "status"];

// Dictionaries to look the word up in while deciding. {word} is URL-encoded so
// phrases and apostrophes ("A for effort", "don't") stay valid.
const REFERENCES = [
    ["Wiktionary", "https://en.wiktionary.org/wiki/{word}"],
    ["Merriam-Webster", "https://www.merriam-webster.com/dictionary/{word}"],
    ["OED", "https://www.oed.com/search/dictionary/?scope=Entries&q={word}"],
];

const FILTER_FORM = document.getElementById("filters");
const SORT_SELECT = document.getElementById("sort");
const TALLY = document.getElementById("tally");
const LEDGER = document.getElementById("ledgerList");
const LEDGER_FOOT = document.getElementById("ledgerFoot");
const DETAIL = document.getElementById("detail");
const TOAST = document.getElementById("toast");
const WORKBENCH = document.getElementById("workbench");
const DRAWER_TOGGLE = document.getElementById("drawerToggle");
const DRAWER_BACKDROP = document.getElementById("drawerBackdrop");
const CHEATSHEET = document.getElementById("cheatsheet");
const PACING = document.getElementById("pacing");

const state = {
    records: [],
    total: 0,
    offset: 0,
    limit: PAGE_LIMIT,
    filters: {},
    sort: DEFAULT_SORT,
    selected: -1,
    editing: false,
};

// Session pacing: decisions this session and when it began, to show rate and
// progress. An "undo" pops the stack and does not inflate the count.
const session = {
    startedAt: Date.now(),
    decisions: 0,
    undoStack: [],
};

async function callDaemon(request) {
    const response = await fetch(location.pathname, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
    });
    const payload = await response.json();
    if (payload.error) {
        throw new Error(payload.error);
    }
    return payload;
}

function readFilters() {
    const filters = {};
    for (const [name, value] of new FormData(FILTER_FORM).entries()) {
        const trimmed = value.trim();
        if (!trimmed) {
            continue;
        }
        filters[name] = name.startsWith("confidence_") ? Number(trimmed) : trimmed;
    }
    return filters;
}

// Re-run the filter: materialise a fresh working set. This is the ONLY point at
// which the list re-syncs to latest state — membership and order are fixed here
// and stay put until the next re-run. preferredAnchor lands the selection on that
// entry (session restore); if it fell out of the set, on the nearest neighbour.
async function runQuery(offset = 0, preferredAnchor = null) {
    state.filters = readFilters();
    state.sort = SORT_SELECT.value || DEFAULT_SORT;
    state.offset = offset;
    const result = await callDaemon({
        op: "entries",
        filters: state.filters,
        sort: state.sort,
        offset,
        limit: state.limit,
    });
    state.records = result.records;
    state.total = result.total;
    TALLY.textContent = `${result.total.toLocaleString()} matching`;
    renderLedger();
    renderFoot();
    select(landingIndex(preferredAnchor));
    refreshPacing();
}

// Where to land the selection after a query. Prefer the exact anchor; if it is no
// longer present (e.g. it was reviewed and the new filter excludes it), the nearest
// neighbour — the first entry that sorts at or after it in the list's own order
// (word, pos, shaw, var) — rather than jumping to the top.
function landingIndex(preferredAnchor) {
    if (!state.records.length) {
        return -1;
    }
    if (!preferredAnchor) {
        return 0;
    }
    const exact = state.records.findIndex(
        (record) => sameAnchor(record.anchor, preferredAnchor),
    );
    if (exact >= 0) {
        return exact;
    }
    const after = state.records.findIndex(
        (record) => compareAnchors(record.anchor, preferredAnchor) >= 0,
    );
    return after >= 0 ? after : state.records.length - 1;
}

// Mirrors the daemon's natural-key tiebreak (word.lower, pos, shaw, var) so a
// dropped-out anchor can be placed among its neighbours. The active sort may order
// the visible list differently, but the anchor's neighbours in natural order are a
// sensible fallback landing.
function compareAnchors(a, b) {
    const fields = [
        [a.word.toLowerCase(), b.word.toLowerCase()],
        [a.pos, b.pos], [a.shaw, b.shaw], [a.var, b.var],
    ];
    for (const [left, right] of fields) {
        if (left < right) return -1;
        if (left > right) return 1;
    }
    return 0;
}

function sameAnchor(a, b) {
    return a && b
        && a.word === b.word && a.pos === b.pos
        && a.shaw === b.shaw && a.var === b.var;
}

// A record's immutable anchor {word, pos, shaw, var} — its identity, unchanged
// by any edit. A patch is always written against the anchor, never the (possibly
// edited) displayed content, so the entry never moves out from under the writer.
function anchorOf(record) {
    return record.anchor;
}

function renderLedger() {
    LEDGER.replaceChildren();
    state.records.forEach((record, index) => {
        LEDGER.append(ledgerRow(record, index));
    });
}

function ledgerRow(record, index) {
    const row = document.createElement("li");
    row.className = `ledger-row state-${record.patch_state}`;
    row.dataset.index = String(index);

    row.append(
        cell("stamp col-state " + record.patch_state, record.patch_state),
        cell("col-word", record.word),
        cell("col-shaw", record.shaw),
        varCell(record.var),
        confidenceCell(record.confidence),
        cell("col-pos", record.pos),
    );
    row.addEventListener("click", () => {
        select(index);
        setDrawer(false);
    });
    return row;
}

function cell(className, value) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = value;
    return span;
}

// The dialect var, de-emphasised when it is the RRP default so the non-default
// dialects (GenAm, TrapBath, RSSB, …) stand out at a glance.
function varCell(value) {
    const span = cell("col-var", value);
    if (value === RRP_VAR) {
        span.classList.add("var-default");
    }
    return span;
}

// Confidence as a compact three-pip meter (non-colour channel: filled vs empty
// pips). Upstream records carry no confidence and show nothing.
function confidenceCell(confidence) {
    const meter = document.createElement("span");
    meter.className = "col-conf";
    if (confidence === null || confidence === undefined) {
        return meter;
    }
    meter.append(confidenceMeter(confidence));
    meter.title = `confidence ${confidence}`;
    return meter;
}

const CONFIDENCE_PIPS = 3;

function confidenceMeter(confidence) {
    const meter = document.createElement("span");
    meter.className = "conf-meter";
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `confidence ${confidence} of 100`);
    const filled = Math.round((confidence / 100) * CONFIDENCE_PIPS);
    for (let i = 0; i < CONFIDENCE_PIPS; i += 1) {
        const pip = document.createElement("span");
        pip.className = i < filled ? "pip on" : "pip";
        meter.append(pip);
    }
    return meter;
}

function renderFoot() {
    LEDGER_FOOT.replaceChildren();
    const shown = state.records.length;
    const from = shown ? state.offset + 1 : 0;
    const summary = document.createElement("span");
    summary.textContent = `${from}–${state.offset + shown} of ${state.total}`;
    LEDGER_FOOT.append(summary);

    const prev = pageButton("‹ prev", state.offset - state.limit);
    prev.disabled = state.offset <= 0;
    const next = pageButton("next ›", state.offset + state.limit);
    next.disabled = state.offset + state.limit >= state.total;
    LEDGER_FOOT.append(prev, next);
}

function pageButton(label, targetOffset) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => runQuery(Math.max(0, targetOffset)));
    return button;
}

// Selecting an entry always lands in REVIEW MODE (no field focused). Edit mode is
// entered explicitly (enterEdit), never as a side effect of stepping.
function select(index) {
    state.selected = index;
    state.editing = false;
    for (const row of LEDGER.children) {
        row.classList.toggle("active", Number(row.dataset.index) === index);
    }
    if (index < 0) {
        renderEmptyDetail();
    } else {
        const active = LEDGER.children[index];
        if (active) {
            active.scrollIntoView({ block: "nearest" });
        }
        renderDetail(state.records[index]);
    }
    saveSession();
}

function renderEmptyDetail() {
    const message = document.createElement("p");
    message.className = "detail-empty";
    message.textContent = state.total
        ? "Select an entry to review it."
        : "No entries match these filters.";
    DETAIL.replaceChildren(message);
    setDetailMode();
}

function renderDetail(record) {
    const heading = document.createElement("div");
    heading.className = "detail-word";
    heading.append(
        stateBadge(record.patch_state),
        cell("latin", record.word),
        cell("pos", record.pos),
        confidenceBadge(record.confidence),
    );

    DETAIL.replaceChildren(
        heading,
        referenceLinks(record.word),
        fieldGrid(record),
        provenanceGrid(record),
        actionBar(record),
    );
    setDetailMode();
}

// The detail card reads its mode off the card element: review mode shows the
// "REVIEW" affordance and keeps every field non-focused; edit mode lifts it.
function setDetailMode() {
    DETAIL.classList.toggle("mode-edit", state.editing);
    DETAIL.classList.toggle("mode-review", !state.editing && state.selected >= 0);
}

function stateBadge(patchState) {
    return cell(`state-badge ${patchState}`, patchState);
}

function confidenceBadge(confidence) {
    const badge = document.createElement("span");
    badge.className = "conf-badge";
    if (confidence === null || confidence === undefined) {
        return badge;
    }
    badge.append(confidenceMeter(confidence), cell("conf-value", String(confidence)));
    return badge;
}

// A row of external dictionary look-ups for the focused word, each opening in a
// new tab. The word is URL-encoded so phrases and apostrophes stay valid.
function referenceLinks(word) {
    const row = document.createElement("nav");
    row.className = "references";
    row.setAttribute("aria-label", "Look up in external dictionaries");
    for (const [label, template] of REFERENCES) {
        const link = document.createElement("a");
        link.className = "reference";
        link.href = template.replace("{word}", encodeURIComponent(word));
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = label;
        row.append(link);
    }
    return row;
}

// The record is self-contained, so every field is editable. shaw/var/ipa/status
// are the edit surface; word/pos are the anchor's Latin identity, shown read-only.
// Every field is a full-width labelled row (label above a large value) — pivoted,
// not a cramped grid — so the payload Shavian and the IPA read comfortably.
function fieldGrid(record) {
    const stack = document.createElement("div");
    stack.className = "field-stack";
    stack.append(
        editField("shaw", "Shavian", record.shaw, "shaw-field"),
        editField("ipa", "IPA", record.ipa, "ipa-field"),
        editField("var", "Dialect (var)", record.var, ""),
        statusField(record.status),
    );
    return stack;
}

function editField(name, label, value, extraClass) {
    const wrap = document.createElement("label");
    wrap.className = "edit-field";
    wrap.setAttribute("for", `field-${name}`);

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = label;

    const input = document.createElement("input");
    input.type = "text";
    input.id = `field-${name}`;
    input.className = `edit-input ${extraClass}`.trim();
    input.dataset.field = name;
    input.value = value ?? "";
    input.spellcheck = false;
    input.autocomplete = "off";
    input.addEventListener("input", () => {
        input.classList.toggle("dirty", input.value !== (value ?? ""));
    });
    input.addEventListener("focus", () => enterEdit());
    input.addEventListener("keydown", onFieldKey);

    wrap.append(caption, input);
    return wrap;
}

const STATUS_OPTIONS = ["supplement", "new", "sanctioned", "manual"];

function statusField(current) {
    const wrap = document.createElement("label");
    wrap.className = "edit-field";
    wrap.setAttribute("for", "field-status");

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = "Status";

    const select = document.createElement("select");
    select.id = "field-status";
    select.className = "edit-input";
    select.dataset.field = "status";
    const options = STATUS_OPTIONS.includes(current)
        ? STATUS_OPTIONS
        : [current, ...STATUS_OPTIONS];
    for (const value of options) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === current;
        select.append(option);
    }
    select.addEventListener("focus", () => enterEdit());

    wrap.append(caption, select);
    return wrap;
}

function provenanceGrid(record) {
    const grid = document.createElement("dl");
    grid.className = "provenance";
    const rows = [
        ["source", record.source],
        ["confidence", record.confidence ?? "—"],
        ["freq", record.freq],
        ["reviewed", record.reviewed ? "yes" : "no"],
        ["patch-state", record.patch_state],
    ];
    for (const [term, value] of rows) {
        const cell = document.createElement("div");
        cell.className = "prov";
        const dt = document.createElement("dt");
        dt.textContent = term;
        const dd = document.createElement("dd");
        dd.textContent = String(value);
        cell.append(dt, dd);
        grid.append(cell);
    }
    return grid;
}

// The verdict controls. Unflag/undo appear only when they apply, so the bar shows
// exactly the moves available on this record. The keyboard is the fast path; the
// buttons mirror it and give mobile real touch targets.
function actionBar(record) {
    const bar = document.createElement("div");
    bar.className = "actions";

    bar.append(
        actionButton("accept", "Accept", acceptSelected),
        actionButton("save", "Save edit", saveSelected),
        actionButton("drop", "Drop", dropSelected),
        actionButton("flag", "Flag", flagSelected),
    );
    if (record.patch_state === "flagged") {
        bar.append(actionButton("unflag", "Unflag", unflagSelected));
    }
    if (session.undoStack.length) {
        bar.append(actionButton("undo", "Undo", undoLast));
    }

    const help = document.createElement("button");
    help.type = "button";
    help.className = "act-help";
    help.textContent = "? keys";
    help.addEventListener("click", () => toggleCheatsheet(true));
    bar.append(help);

    return bar;
}

function actionButton(kind, label, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `act ${kind}`;
    button.textContent = label;
    button.addEventListener("click", handler);
    return button;
}

// The complete record the detail editor currently shows: the selected record's
// fields with the edit surface overlaid from the inputs. word/pos/freq/source/
// confidence come from the record; shaw/var/ipa/status from the fields.
function editedRecord(record) {
    const result = {
        word: record.word,
        pos: record.pos,
        freq: record.freq,
    };
    if (record.source) {
        result.source = record.source;
    }
    if (record.confidence !== null && record.confidence !== undefined) {
        result.confidence = record.confidence;
    }
    for (const name of EDITABLE_FIELDS) {
        const input = document.getElementById(`field-${name}`);
        result[name] = input.value.trim();
    }
    return result;
}

function requireShaw(record) {
    if (!record.shaw) {
        showToast("Shavian cannot be empty.", true);
        return false;
    }
    return true;
}

async function saveSelected() {
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    const record = editedRecord(selected);
    if (!requireShaw(record)) {
        return;
    }
    await writePatch(anchorOf(selected), record, "saved");
}

async function acceptSelected() {
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    const record = editedRecord(selected);
    record.status = ACCEPTED_STATUS;
    if (!requireShaw(record)) {
        return;
    }
    await writePatch(anchorOf(selected), record, "accepted");
}

async function dropSelected() {
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    await writePatch(anchorOf(selected), null, "dropped");
}

// A verdict (accept/drop/edit) produces a patch and steps on. It also records an
// undo frame: whether the anchor already had a patch before, so undo restores the
// right prior state.
async function writePatch(anchor, record, verb) {
    const selected = state.records[state.selected];
    const priorReviewed = selected ? selected.reviewed : false;
    try {
        const result = await callDaemon({
            op: "patch",
            anchor,
            record,
            author: AUTHOR,
        });
        pushUndo(anchor, priorReviewed);
        countDecision();
        applyWriteResult(result.records);
        showToast(`${verb} · ${result.result}`);
    } catch (error) {
        showToast(error.message, true);
    }
}

// Flag: "looked at, no verdict yet". The daemon writes a flag patch carrying the
// source record unchanged; it counts as reviewed but not decided, and is a no-op
// for production output.
async function flagSelected() {
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    const priorReviewed = selected.reviewed;
    try {
        const result = await callDaemon({
            op: "flag",
            anchor: anchorOf(selected),
            author: AUTHOR,
        });
        pushUndo(anchorOf(selected), priorReviewed);
        applyWriteResult(result.records);
        showToast(`flagged · ${result.result}`);
    } catch (error) {
        showToast(error.message, true);
    }
}

// Unflag: remove the flag patch, reverting to unreviewed. Distinct from undo — an
// explicit "actually, back to the pool" on a flagged row.
async function unflagSelected() {
    const selected = state.records[state.selected];
    if (!selected || selected.patch_state !== "flagged") {
        return;
    }
    await unpatch(anchorOf(selected), "unflagged", { step: false });
}

// Undo the last decision: if it created a patch (the anchor was previously
// unreviewed), delete it to restore the untouched source; the row is restored in
// place. If the anchor already had a patch before, we cannot faithfully restore
// that prior patch from the client, so we surface that and leave the current
// patch — the safe, honest behaviour.
async function undoLast() {
    const frame = session.undoStack.pop();
    if (!frame) {
        showToast("Nothing to undo.", true);
        return;
    }
    if (frame.priorReviewed) {
        showToast("Can't undo: the entry already had a decision before this one.", true);
        renderDetail(state.records[state.selected]);
        return;
    }
    const index = state.records.findIndex((r) => sameAnchor(r.anchor, frame.anchor));
    if (index >= 0) {
        state.selected = index;
    }
    await unpatch(frame.anchor, "undone", { step: false, uncount: true });
}

async function unpatch(anchor, verb, { step = true, uncount = false } = {}) {
    try {
        const result = await callDaemon({ op: "unpatch", anchor });
        if (uncount) {
            session.decisions = Math.max(0, session.decisions - 1);
        }
        applyWriteResult(result.records, { step });
        showToast(`${verb} · ${result.result}`);
    } catch (error) {
        showToast(error.message, true);
    }
}

function pushUndo(anchor, priorReviewed) {
    session.undoStack.push({ anchor, priorReviewed });
}

function countDecision() {
    session.decisions += 1;
    refreshPacing();
}

// The write response returns the anchor re-annotated (one record — the anchor is
// a full natural key). Update the row IN PLACE: it keeps its index, so it stays
// put in the working set showing its new content and stamp, even if it no longer
// matches the active filter. By default step to the next entry; a re-render in
// place (unflag/undo) stays put.
function applyWriteResult(records, { step: doStep = true } = {}) {
    const replacement = records[0];
    // Place the re-annotated record on its OWN row (matched by anchor), not
    // blindly on state.selected — the affected row may not be the selected one
    // (e.g. an undo after the filter was re-run moved the selection elsewhere).
    const index = replacement
        ? state.records.findIndex((r) => sameAnchor(r.anchor, replacement.anchor))
        : state.selected;
    if (replacement && index >= 0) {
        state.records[index] = replacement;
        refreshRow(index, replacement);
    }
    refreshPacing();
    if (doStep) {
        step(1);
    } else if (index >= 0) {
        state.selected = index;
        select(index);
    }
}

function refreshRow(index, record) {
    const row = LEDGER.children[index];
    if (!row) {
        return;
    }
    row.className = `ledger-row state-${record.patch_state}`;
    if (Number(row.dataset.index) === state.selected) {
        row.classList.add("active");
    }
    const stamp = row.querySelector(".col-state");
    stamp.className = `stamp col-state ${record.patch_state}`;
    stamp.textContent = record.patch_state;
    row.querySelector(".col-shaw").textContent = record.shaw;
    const varSpan = row.querySelector(".col-var");
    varSpan.textContent = record.var;
    varSpan.classList.toggle("var-default", record.var === RRP_VAR);
}

function step(delta) {
    if (!state.records.length) {
        return;
    }
    const next = Math.min(
        state.records.length - 1,
        Math.max(0, state.selected + delta),
    );
    select(next);
}

// Enter edit mode: focus the Shavian field and mark the card. Saving or Escape
// returns to review mode. Called by E and by focusing any field directly.
function enterEdit() {
    if (state.selected < 0) {
        return;
    }
    state.editing = true;
    setDetailMode();
    const shaw = document.getElementById("field-shaw");
    if (shaw && document.activeElement !== shaw
        && !DETAIL.contains(document.activeElement)) {
        shaw.focus();
        shaw.setSelectionRange(shaw.value.length, shaw.value.length);
    }
}

// Leave edit mode without saving: blur the field and return to review mode, so
// single-key verdicts work again.
function exitEdit() {
    state.editing = false;
    if (DETAIL.contains(document.activeElement)) {
        document.activeElement.blur();
    }
    setDetailMode();
}

function onFieldKey(event) {
    if (event.key === "Escape") {
        event.preventDefault();
        exitEdit();
        return;
    }
    if (event.key !== "Enter") {
        return;
    }
    event.preventDefault();
    if (event.shiftKey) {
        dropSelected();
    } else if (event.metaKey || event.ctrlKey) {
        saveSelected();
    } else {
        acceptSelected();
    }
}

// Review-mode single-key bindings. These fire ONLY when no field holds focus (the
// event target is not an input/select/textarea) — so typing Shavian never
// triggers a verdict. The legacy arrow steppers stay as aliases (J/K mirror them).
const REVIEW_KEYS = {
    a: acceptSelected,
    x: dropSelected,
    e: enterEdit,
    s: saveSelected,
    f: flagSelected,
    u: undoLast,
    j: () => step(1),
    k: () => step(-1),
    arrowdown: () => step(1),
    arrowup: () => step(-1),
    "?": () => toggleCheatsheet(),
};

// Keys that mutate must not double-fire on auto-repeat when a key is held.
const NON_REPEAT_KEYS = new Set(["a", "x", "s", "f", "u"]);

function onGlobalKey(event) {
    if (event.key === "Escape" && isCheatsheetOpen()) {
        toggleCheatsheet(false);
        return;
    }
    if (event.target instanceof Element && event.target.matches("input, select, textarea")) {
        return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
    }
    const key = event.key.toLowerCase();
    const handler = REVIEW_KEYS[key];
    if (!handler) {
        return;
    }
    if (event.repeat && NON_REPEAT_KEYS.has(key)) {
        return;
    }
    event.preventDefault();
    handler();
}

// ---- keyboard cheatsheet overlay ----
const CHEATSHEET_ROWS = [
    ["A", "Accept — promote & step on"],
    ["X", "Drop — reject & step on"],
    ["E", "Edit — focus the Shavian field"],
    ["S", "Save the current edit & step on"],
    ["F", "Flag for later — looked at, no verdict"],
    ["U", "Undo the last decision"],
    ["J / K", "Step next / previous"],
    ["↑ / ↓", "Step next / previous"],
    ["Esc", "Leave edit mode (in a field)"],
    ["?", "Toggle this cheatsheet"],
];

function buildCheatsheet() {
    const card = document.createElement("div");
    card.className = "cheatsheet-card";
    const title = document.createElement("h2");
    title.textContent = "Keyboard";
    card.append(title);

    const list = document.createElement("dl");
    list.className = "cheat-list";
    for (const [keys, description] of CHEATSHEET_ROWS) {
        const dt = document.createElement("dt");
        for (const label of keys.split(" / ")) {
            dt.append(kbd(label));
        }
        const dd = document.createElement("dd");
        dd.textContent = description;
        list.append(dt, dd);
    }
    card.append(list);

    const close = document.createElement("button");
    close.type = "button";
    close.className = "cheat-close";
    close.textContent = "Close";
    close.addEventListener("click", () => toggleCheatsheet(false));
    card.append(close);

    CHEATSHEET.replaceChildren(card);
    CHEATSHEET.addEventListener("click", (event) => {
        if (event.target === CHEATSHEET) {
            toggleCheatsheet(false);
        }
    });
}

function kbd(label) {
    const element = document.createElement("kbd");
    element.textContent = label;
    return element;
}

function isCheatsheetOpen() {
    return CHEATSHEET.classList.contains("open");
}

function toggleCheatsheet(force) {
    const open = force === undefined ? !isCheatsheetOpen() : force;
    CHEATSHEET.classList.toggle("open", open);
    CHEATSHEET.setAttribute("aria-hidden", String(!open));
}

// ---- session pacing strip ----
function refreshPacing() {
    const remaining = countUnreviewedRemaining();
    const elapsedHours = (Date.now() - session.startedAt) / 3_600_000;
    const rate = elapsedHours > 0 ? Math.round(session.decisions / elapsedHours) : 0;
    PACING.replaceChildren(
        pacingStat(String(session.decisions), "decided this session"),
        pacingStat(session.decisions ? `${rate}/h` : "—", "pace"),
        pacingStat(remaining === null ? "—" : remaining.toLocaleString(), "unreviewed left"),
    );
}

// "Unreviewed remaining" is meaningful only while reviewing the unreviewed pool;
// under any other filter the total is not a remaining count, so we show it only
// when the active filter is unreviewed.
function countUnreviewedRemaining() {
    if (state.filters.reviewed !== "unreviewed") {
        return null;
    }
    const decidedInSet = state.records.filter(
        (r) => r.reviewed && r.patch_state !== "flagged",
    ).length;
    return Math.max(0, state.total - decidedInSet);
}

function pacingStat(value, label) {
    const stat = document.createElement("span");
    stat.className = "pace-stat";
    const strong = document.createElement("strong");
    strong.textContent = value;
    const caption = document.createElement("span");
    caption.className = "pace-label";
    caption.textContent = label;
    stat.append(strong, caption);
    return stat;
}

// Session continuity: the active filter, sort, plus the ANCHOR of the focused
// entry — not a row index, which is meaningless once the list re-materialises. On
// load the filter/sort are restored, the list pulled, then the anchor re-selected
// (or its nearest neighbour). Persisted on every query and selection.
function saveSession() {
    const selected = state.records[state.selected];
    const stored = {
        filters: state.filters,
        sort: state.sort,
        anchor: selected ? selected.anchor : null,
    };
    localStorage.setItem(SESSION_KEY, JSON.stringify(stored));
}

function loadSession() {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) {
        return null;
    }
    return JSON.parse(raw);
}

// Populate the filter form + sort from a saved session so the restored query
// matches what the user last ran.
function restoreFilters(filters) {
    for (const [name, value] of Object.entries(filters)) {
        const field = FILTER_FORM.elements[name];
        if (field) {
            field.value = value;
        }
    }
}

// Off-canvas ledger drawer for narrow screens. On wide screens the list is always
// visible and the toggle is hidden by CSS, so this only bites on mobile.
function setDrawer(open) {
    WORKBENCH.classList.toggle("drawer-open", open);
    DRAWER_TOGGLE.setAttribute("aria-expanded", String(open));
}

function toggleDrawer() {
    setDrawer(!WORKBENCH.classList.contains("drawer-open"));
}

let toastTimer = null;
function showToast(message, isError = false) {
    TOAST.textContent = message;
    TOAST.classList.toggle("error", isError);
    TOAST.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => TOAST.classList.remove("show"), 2400);
}

FILTER_FORM.addEventListener("submit", (event) => {
    event.preventDefault();
    runQuery(0).catch((error) => showToast(error.message, true));
});

SORT_SELECT.addEventListener("change", () => {
    runQuery(0).catch((error) => showToast(error.message, true));
});

DRAWER_TOGGLE.addEventListener("click", toggleDrawer);
DRAWER_BACKDROP.addEventListener("click", () => setDrawer(false));

document.addEventListener("keydown", onGlobalKey);

// Boot: resume the saved session (filter + sort + anchor) if one exists, else a
// plain first query at the review default sort (highest confidence first).
function boot() {
    buildCheatsheet();
    const stored = loadSession();
    if (stored && stored.filters) {
        restoreFilters(stored.filters);
        SORT_SELECT.value = stored.sort || DEFAULT_SORT;
        return runQuery(0, stored.anchor);
    }
    SORT_SELECT.value = DEFAULT_SORT;
    return runQuery(0);
}

boot().catch((error) => showToast(error.message, true));
