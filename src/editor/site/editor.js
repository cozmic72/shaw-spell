"use strict";

// The editor speaks editord's protocol directly: the CGI forwards each POSTed
// body to the daemon verbatim and returns its reply. See editord.py for the op
// shapes (entries / entry / patch) and overlay.py for patch_state semantics.
//
// Pull-and-refresh: runQuery() materialises a working set (state.records). While
// the user works it, membership and order stay STABLE — a just-reviewed row keeps
// its place, updated in-place with its new content and stamp, even if it no longer
// matches the filter. The list only re-syncs (dropping non-matching rows and
// re-sorting) when the user RE-RUNS the filter.

const AUTHOR = "editor";
const PAGE_LIMIT = 200;
const ACCEPTED_STATUS = "sanctioned";

const EDITABLE_FIELDS = ["shaw", "var", "ipa", "status"];

const FILTER_FORM = document.getElementById("filters");
const TALLY = document.getElementById("tally");
const LEDGER = document.getElementById("ledgerList");
const LEDGER_FOOT = document.getElementById("ledgerFoot");
const DETAIL = document.getElementById("detail");
const TOAST = document.getElementById("toast");

const state = {
    records: [],
    total: 0,
    offset: 0,
    limit: PAGE_LIMIT,
    filters: {},
    selected: -1,
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
// and stay put until the next re-run.
async function runQuery(offset = 0) {
    state.filters = readFilters();
    state.offset = offset;
    const result = await callDaemon({
        op: "entries",
        filters: state.filters,
        offset,
        limit: state.limit,
    });
    state.records = result.records;
    state.total = result.total;
    TALLY.textContent = `${result.total.toLocaleString()} matching`;
    renderLedger();
    renderFoot();
    select(state.records.length ? 0 : -1);
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
    row.className = "ledger-row";
    row.dataset.index = String(index);

    row.append(
        cell("stamp col-state " + record.patch_state, record.patch_state),
        cell("col-word", record.word),
        cell("col-shaw", record.shaw),
        cell("col-var", record.var),
        cell("col-pos", record.pos),
    );
    row.addEventListener("click", () => select(index));
    return row;
}

function cell(className, value) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = value;
    return span;
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

function select(index, { focusFirst = true } = {}) {
    state.selected = index;
    for (const row of LEDGER.children) {
        row.classList.toggle("active", Number(row.dataset.index) === index);
    }
    if (index < 0) {
        renderEmptyDetail();
        return;
    }
    const active = LEDGER.children[index];
    if (active) {
        active.scrollIntoView({ block: "nearest" });
    }
    renderDetail(state.records[index], focusFirst);
}

function renderEmptyDetail() {
    const message = document.createElement("p");
    message.className = "detail-empty";
    message.textContent = state.total
        ? "Select an entry to edit it."
        : "No entries match these filters.";
    DETAIL.replaceChildren(message);
}

function renderDetail(record, focusFirst) {
    const heading = document.createElement("div");
    heading.className = "detail-word";
    heading.append(cell("latin", record.word), cell("pos", record.pos));

    const fields = fieldGrid(record);

    DETAIL.replaceChildren(heading, fields, provenanceGrid(record), actionBar());

    if (focusFirst) {
        const first = document.getElementById("field-shaw");
        first.focus();
        first.setSelectionRange(first.value.length, first.value.length);
    }
}

// The record is self-contained, so every field is editable. shaw/var/ipa/status
// are the edit surface; word/pos are the anchor's Latin identity, shown read-only.
function fieldGrid(record) {
    const grid = document.createElement("div");
    grid.className = "field-editor";
    grid.append(
        editField("shaw", "Shavian", record.shaw, "shaw-field"),
        editField("var", "Dialect (var)", record.var, ""),
        editField("ipa", "IPA", record.ipa, "ipa-field"),
        statusField(record.status),
    );
    return grid;
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
    input.addEventListener("keydown", onFieldKey);

    wrap.append(caption, input);
    return wrap;
}

const STATUS_OPTIONS = ["supplement", "supplemental", "new", "sanctioned", "manual"];

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

function actionBar() {
    const bar = document.createElement("div");
    bar.className = "actions";

    const accept = actionButton("accept", "Accept", acceptSelected);
    const save = actionButton("save", "Save edit", saveSelected);
    const drop = actionButton("drop", "Drop", dropSelected);

    const hint = document.createElement("span");
    hint.className = "act-hint";
    hint.append(
        kbd("Enter"), text(" accept  "),
        kbd("⌘"), text("+"), kbd("Enter"), text(" save  "),
        kbd("⇧"), text("+"), kbd("Enter"), text(" drop  "),
        kbd("↑"), kbd("↓"), text(" step"),
    );

    bar.append(accept, save, drop, hint);
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

function kbd(label) {
    const element = document.createElement("kbd");
    element.textContent = label;
    return element;
}

function text(value) {
    return document.createTextNode(value);
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

async function writePatch(anchor, record, verb) {
    try {
        const result = await callDaemon({
            op: "patch",
            anchor,
            record,
            author: AUTHOR,
        });
        applyPatchResult(result.records);
        showToast(`${verb} · ${result.result}`);
    } catch (error) {
        showToast(error.message, true);
    }
}

// The patch response returns the anchor re-annotated (one record — the anchor is
// a full natural key). Update the row IN PLACE: it keeps its index, so it stays
// put in the working set showing its new content and stamp, even if it no longer
// matches the active filter. Then step to the next entry.
function applyPatchResult(records) {
    const replacement = records[0];
    if (replacement) {
        state.records[state.selected] = replacement;
        refreshRow(state.selected, replacement);
    }
    step(1);
}

function refreshRow(index, record) {
    const row = LEDGER.children[index];
    if (!row) {
        return;
    }
    const stamp = row.querySelector(".col-state");
    stamp.className = `stamp col-state ${record.patch_state}`;
    stamp.textContent = record.patch_state;
    row.querySelector(".col-shaw").textContent = record.shaw;
    row.querySelector(".col-var").textContent = record.var;
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

function onFieldKey(event) {
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

function onGlobalKey(event) {
    if (event.target.matches("input, select, textarea")) {
        return;
    }
    if (event.key === "ArrowDown") {
        event.preventDefault();
        step(1);
    } else if (event.key === "ArrowUp") {
        event.preventDefault();
        step(-1);
    }
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

document.addEventListener("keydown", onGlobalKey);

runQuery(0).catch((error) => showToast(error.message, true));
