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

// The within-accent vowel mergers a record's spelling reflects (additive, empty
// == canonical). A closed vocabulary mirroring src/tools/dialect_mergers.py; the
// reviewer toggles these on the detail card and they round-trip in the patch.
const MERGERS = [
    ["trap-bath", "TRAP–BATH"],
    ["cot-caught", "COT–CAUGHT"],
];

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
const HELP_TOGGLE = document.getElementById("helpToggle");
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

// The categorical facets are multi-select: each checked chip contributes its
// value to that facet's array (OR within the facet; the daemon ANDs across
// facets). word/shaw stay substring scalars, confidence_* numeric scalars. An
// empty array is omitted, so an untouched facet does not constrain.
const CATEGORICAL_FACETS = new Set([
    "source", "status", "pos", "var", "patch_state",
    "reviewed", "word_kind", "novelty", "mergers",
]);

function readFilters() {
    const filters = {};
    for (const [name, rawValue] of new FormData(FILTER_FORM).entries()) {
        if (CATEGORICAL_FACETS.has(name)) {
            (filters[name] ??= []).push(rawValue);
            continue;
        }
        const trimmed = rawValue.trim();
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
    materialisedSignature = querySignature(state.filters, state.sort);
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
        mergerBadges(record.mergers),
        confidenceBadge(record.confidence),
    );

    const related = relatedSection();
    DETAIL.replaceChildren(
        heading,
        referenceLinks(record.word),
        fieldGrid(record),
        provenanceGrid(record),
        actionBar(record),
        related,
    );
    setDetailMode();
    loadRelated(record, related);
}

// ---- related-entries context ----
// Every record sharing the focused entry's Latin word (case-insensitive), so
// capitalisation dupes and proper-noun/common-word homographs surface together.
// Fetched async so a landing never blocks the review loop; a stale response for a
// previously-focused word is dropped (guarded by the focused anchor).

const RELATED_TITLE = "Related entries";

function relatedSection() {
    const section = document.createElement("section");
    section.className = "related";
    section.setAttribute("aria-label", RELATED_TITLE);
    const loading = document.createElement("p");
    loading.className = "related-loading";
    loading.textContent = "Finding related entries…";
    section.append(relatedHeading(null), loading);
    return section;
}

function relatedHeading(count) {
    const heading = document.createElement("h2");
    heading.className = "related-title";
    heading.textContent = count === null
        ? RELATED_TITLE
        : `${RELATED_TITLE} · ${count}`;
    return heading;
}

// Fetch related for the focused record and fill `section` when it returns. The
// selection may have moved on by then (fast stepping); render only if the record
// still occupies the focused slot, matched by anchor — a stale response for a
// prior word must never overwrite the current card.
async function loadRelated(record, section) {
    const focused = record.anchor;
    try {
        const result = await callDaemon({ op: "related", word: record.word });
        const current = state.records[state.selected];
        if (!current || !sameAnchor(current.anchor, focused) || !section.isConnected) {
            return;
        }
        renderRelated(section, result.records, focused);
    } catch (error) {
        if (section.isConnected) {
            renderRelatedError(section, error.message);
        }
    }
}

function renderRelated(section, records, focusedAnchor) {
    const list = document.createElement("ul");
    list.className = "related-list";
    for (const record of records) {
        list.append(relatedRow(record, focusedAnchor));
    }
    section.replaceChildren(relatedHeading(records.length), list);
}

function renderRelatedError(section, message) {
    const note = document.createElement("p");
    note.className = "related-loading";
    note.textContent = `Couldn't load related entries: ${message}`;
    section.replaceChildren(relatedHeading(null), note);
}

function relatedRow(record, focusedAnchor) {
    const provenance = relatedProvenance(record);
    const row = document.createElement("li");
    row.className = `related-row state-${provenance.state}`;
    const here = sameAnchor(record.anchor, focusedAnchor);
    if (here) {
        row.classList.add("here");
    }

    const badge = cell(`related-badge ${provenance.state}`, provenance.glyph);
    badge.title = provenance.label;
    row.append(
        badge,
        cell("related-label", here ? "you are here" : provenance.label),
        cell("related-word", record.word),
        cell("related-pos", record.pos),
        varCell(record.var),
        cell("related-shaw", record.shaw),
    );
    return row;
}

// Provenance + review state of a related record, from the fields the view already
// carries. patch_state decides first (a patch's verdict overrides origin); an
// untouched row falls back to its origin. `state` is a --state-* class so the
// badge reuses the ledger palette; `glyph` is the non-colour channel.
function relatedProvenance(record) {
    switch (record.patch_state) {
        case "authored":
            return { state: "authored", glyph: "✎", label: "authored" };
        case "dropped":
            return { state: "dropped", glyph: "✕", label: "dropped" };
        case "flagged":
            return { state: "flagged", glyph: "⚑", label: "flagged" };
        case "edited":
            return {
                state: "edited",
                glyph: "✓",
                label: record.status === ACCEPTED_STATUS ? "sanctioned" : "edited",
            };
        default:
            return record.source === "readlex"
                ? { state: "unreviewed", glyph: "✓", label: "upstream" }
                : { state: "unreviewed", glyph: "○", label: `candidate · ${record.source}` };
    }
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

// The record's active vowel mergers, as small badges beside the word. Empty (a
// canonical record) shows nothing — the absence is the signal.
const MERGER_LABELS = new Map(MERGERS);

function mergerBadges(mergers) {
    const wrap = document.createElement("span");
    wrap.className = "merger-badges";
    for (const value of mergers || []) {
        wrap.append(cell(`merger-badge ${value}`, MERGER_LABELS.get(value) ?? value));
    }
    return wrap;
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
        mergersField(record.mergers),
        statusField(record.status),
    );
    return stack;
}

// The mergers are an additive set, not a scalar, so they edit as a row of toggle
// chips rather than a text field. Each chip is a checkbox named "merger" carrying
// its merger value; editedRecord harvests the checked ones. Toggling one enters
// edit mode, like focusing any other field.
function mergersField(current) {
    const active = new Set(current || []);
    const wrap = document.createElement("div");
    wrap.className = "edit-field mergers-field";

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = "Mergers";

    const toggles = document.createElement("div");
    toggles.className = "merger-toggles";
    for (const [value, label] of MERGERS) {
        toggles.append(mergerToggle(value, label, active.has(value)));
    }

    wrap.append(caption, toggles);
    return wrap;
}

function mergerToggle(value, label, checked) {
    const chip = document.createElement("label");
    chip.className = "merger-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "merger-check";
    input.value = value;
    input.checked = checked;
    input.addEventListener("change", () => {
        chip.classList.toggle("on", input.checked);
        enterEdit();
    });
    const caption = document.createElement("span");
    caption.textContent = label;
    chip.classList.toggle("on", checked);
    chip.append(input, caption);
    return chip;
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
    if (record.reviewed) {
        bar.append(actionButton("clear", "Clear", clearSelected));
    }
    if (record.patch_state === "flagged") {
        bar.append(actionButton("unflag", "Unflag", unflagSelected));
    }
    if (session.undoStack.length) {
        bar.append(actionButton("undo", "Undo", undoLast));
    }

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
    const mergers = [...DETAIL.querySelectorAll(".merger-check:checked")]
        .map((box) => box.value);
    if (mergers.length) {
        result.mergers = mergers;
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

// An authored entry (anchor null, patch_state "authored") exists ONLY via its
// authorship patch — no basis record backs it. Re-deciding it must edit THAT
// patch in place (anchor stays null), not write an anchored patch that would
// resolve to nothing and orphan the decision (failing the build).
function isAuthored(record) {
    return record.patch_state === "authored";
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
    await writePatch(anchorOf(selected), record, "saved", selected);
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
    await writePatch(anchorOf(selected), record, "accepted", selected);
}

async function dropSelected() {
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    // Dropping an authored entry means removing the word entirely — it exists only
    // via its patch, so the drop IS deleting that patch (same as Clear).
    if (isAuthored(selected)) {
        if (!selected.patch_id) {
            showToast("Can't drop: authored entry has no patch id.", true);
            return;
        }
        await unpatch(null, "dropped", { step: true, patchId: selected.patch_id });
        return;
    }
    await writePatch(anchorOf(selected), null, "dropped", selected);
}

// A verdict (accept/drop/edit) produces a patch and steps on. It also records an
// undo frame: whether the anchor already had a patch before, so undo restores the
// right prior state. Re-deciding an authored entry edits its authorship patch in
// place (anchor null + replaces), never writing an anchored patch.
async function writePatch(anchor, record, verb, selected) {
    const priorReviewed = selected ? selected.reviewed : false;
    const request = isAuthored(selected)
        ? { op: "patch", anchor: null, record, author: AUTHOR, replaces: selected.patch_id }
        : { op: "patch", anchor, record, author: AUTHOR };
    try {
        const result = await callDaemon(request);
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
    const request = isAuthored(selected)
        ? { op: "flag", anchor: null, author: AUTHOR, replaces: selected.patch_id }
        : { op: "flag", anchor: anchorOf(selected), author: AUTHOR };
    try {
        const result = await callDaemon(request);
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

// Clear: the general "reset this entry's state" — delete WHATEVER patch it holds
// (accept/edit/drop/flag/authored, this session or a prior one), reverting a basis
// record to its untouched source, or removing an authored record outright. Shown
// whenever the entry is reviewed. An authored record has no anchor, so it is
// cleared by its patch id; the daemon then returns no record and the row is dropped.
async function clearSelected() {
    const selected = state.records[state.selected];
    if (!selected || !selected.reviewed) {
        return;
    }
    if (selected.patch_state === "authored") {
        if (!selected.patch_id) {
            showToast("Can't clear: authored entry has no patch id.", true);
            return;
        }
        await unpatch(null, "cleared", { step: false, patchId: selected.patch_id });
    } else {
        await unpatch(anchorOf(selected), "cleared", { step: false });
    }
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

async function unpatch(anchor, verb, { step = true, uncount = false, patchId = null } = {}) {
    const request = patchId ? { op: "unpatch", patch_id: patchId } : { op: "unpatch", anchor };
    try {
        const result = await callDaemon(request);
        if (uncount) {
            session.decisions = Math.max(0, session.decisions - 1);
        }
        if (!result.records.length) {
            removeSelectedRow();
        } else {
            applyWriteResult(result.records, { step });
        }
        showToast(`${verb} · ${result.result}`);
    } catch (error) {
        showToast(error.message, true);
    }
}

// Clearing an authored entry leaves no record — the daemon returns an empty set.
// Drop the row from the working set and DOM, then land on its neighbour so the
// selection stays in view.
function removeSelectedRow() {
    const removed = state.selected;
    if (removed < 0) {
        return;
    }
    state.records.splice(removed, 1);
    renderLedger();
    refreshPacing();
    select(Math.min(removed, state.records.length - 1));
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
    c: clearSelected,
    u: undoLast,
    j: () => step(1),
    k: () => step(-1),
    arrowdown: () => step(1),
    arrowup: () => step(-1),
    "?": () => toggleCheatsheet(),
};

// Keys that mutate must not double-fire on auto-repeat when a key is held.
const NON_REPEAT_KEYS = new Set(["a", "x", "s", "f", "c", "u"]);

function onGlobalKey(event) {
    if (isCheatsheetOpen()) {
        // While the dialog is open only its own keys act — Escape or ? close it;
        // review verdicts must not leak through to the entry behind the backdrop.
        if (event.key === "Escape" || event.key === "?") {
            event.preventDefault();
            toggleCheatsheet(false);
        }
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

// ---- keyboard shortcuts dialog ----
// Grouped so the sheet reads as a map of the workflow, not a flat key dump. Each
// verdict row carries the same state class the ledger stamp uses, so its key chip
// is tinted the colour the editor already associates with that outcome. `state`
// null leaves a row in the neutral utility tone.
const SHORTCUT_GROUPS = [
    {
        heading: "Review actions",
        rows: [
            { keys: ["A"], state: "edited", action: "Accept — promote & step on" },
            { keys: ["X"], state: "dropped", action: "Drop — reject & step on" },
            { keys: ["F"], state: "flagged", action: "Flag — looked at, no verdict yet" },
            { keys: ["E"], state: null, action: "Edit — focus the Shavian field" },
            { keys: ["S"], state: "edited", action: "Save the current edit & step on" },
            { keys: ["C"], state: "unreviewed", action: "Clear — delete the patch, back to unreviewed" },
        ],
    },
    {
        heading: "Navigation",
        rows: [
            { keys: ["J", "K"], state: null, action: "Step next / previous" },
            { keys: ["↑", "↓"], state: null, action: "Step next / previous" },
        ],
    },
    {
        heading: "Editing & session",
        rows: [
            { keys: ["Enter"], state: null, action: "Accept (in a field)" },
            { keys: ["⇧", "Enter"], state: null, action: "Drop (in a field)" },
            { keys: ["⌘", "Enter"], state: null, action: "Save (in a field)" },
            { keys: ["Esc"], state: null, action: "Leave edit mode / close this dialog" },
            { keys: ["U"], state: null, action: "Undo the last decision" },
            { keys: ["?"], state: null, action: "Toggle this dialog" },
        ],
    },
];

let cheatsheetReturnFocus = null;

function buildCheatsheet() {
    const card = document.createElement("div");
    card.className = "cheatsheet-card";
    card.setAttribute("role", "document");

    const title = document.createElement("h2");
    title.id = "cheatsheet-title";
    title.textContent = "Keyboard shortcuts";
    card.append(title);

    for (const group of SHORTCUT_GROUPS) {
        card.append(shortcutGroup(group));
    }

    const close = document.createElement("button");
    close.type = "button";
    close.className = "cheat-close";
    close.textContent = "Close";
    close.addEventListener("click", () => toggleCheatsheet(false));
    card.append(close);

    CHEATSHEET.setAttribute("aria-labelledby", "cheatsheet-title");
    CHEATSHEET.replaceChildren(card);
    CHEATSHEET.addEventListener("click", (event) => {
        if (event.target === CHEATSHEET) {
            toggleCheatsheet(false);
        }
    });
}

function shortcutGroup({ heading, rows }) {
    const section = document.createElement("section");
    section.className = "cheat-group";

    const label = document.createElement("h3");
    label.textContent = heading;
    section.append(label);

    const list = document.createElement("dl");
    list.className = "cheat-list";
    for (const row of rows) {
        const dt = document.createElement("dt");
        if (row.state) {
            dt.className = `state-${row.state}`;
        }
        for (const label of row.keys) {
            dt.append(kbd(label));
        }
        const dd = document.createElement("dd");
        dd.textContent = row.action;
        list.append(dt, dd);
    }
    section.append(list);
    return section;
}

function kbd(label) {
    const element = document.createElement("kbd");
    element.textContent = label;
    return element;
}

function isCheatsheetOpen() {
    return CHEATSHEET.classList.contains("open");
}

// Open/close the modal, moving focus in on open and restoring it on close so the
// dialog is keyboard-navigable and never strands focus behind the backdrop.
function toggleCheatsheet(force) {
    const open = force === undefined ? !isCheatsheetOpen() : force;
    if (open === isCheatsheetOpen()) {
        return;
    }
    CHEATSHEET.classList.toggle("open", open);
    CHEATSHEET.setAttribute("aria-hidden", String(!open));
    if (open) {
        cheatsheetReturnFocus = document.activeElement;
        CHEATSHEET.querySelector(".cheat-close").focus();
    } else if (cheatsheetReturnFocus) {
        cheatsheetReturnFocus.focus();
        cheatsheetReturnFocus = null;
    }
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
    const reviewed = state.filters.reviewed;
    if (!Array.isArray(reviewed) || reviewed.length !== 1 || reviewed[0] !== "unreviewed") {
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
// matches what the user last ran. A categorical facet's persisted array re-checks
// exactly its chips; a scalar sets its input value. Values with no matching chip
// (e.g. a POS chip not yet populated, or a value dropped from the enum) are simply
// left unchecked — the restore reflects only what the form can currently express.
function restoreFilters(filters) {
    for (const [name, value] of Object.entries(filters)) {
        if (CATEGORICAL_FACETS.has(name)) {
            restoreChips(name, value);
        } else {
            const field = FILTER_FORM.elements[name];
            if (field) {
                field.value = value;
            }
        }
    }
}

function restoreChips(facet, values) {
    const wanted = new Set(values);
    for (const box of FILTER_FORM.querySelectorAll(`input[name="${facet}"]`)) {
        box.checked = wanted.has(box.value);
    }
    // Programmatic .checked does not fire `change`, so a dropdown's trigger label
    // (built off the checked count) must be nudged to reflect the restored selection.
    refreshFacetTrigger(facet);
}

// Re-sync a facet dropdown's trigger label to its current checked count, for the
// paths that set .checked directly (session restore) rather than via a user toggle.
function refreshFacetTrigger(facet) {
    const list = FILTER_FORM.querySelector(`.chips[data-facet="${facet}"] .facet-list`);
    list.dispatchEvent(new Event("change"));
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

// Live filtering: the filter form re-runs the query the moment the criteria
// change, so there is no separate "apply" step. A <select> (or the sort) commits
// on `change`; a free-text or numeric input debounces, re-running once the user
// pauses. Re-running the filter IS the pull-and-refresh re-sync point (an
// explicit filter change, so re-syncing membership is the intended behaviour).
const FILTER_DEBOUNCE_MS = 250;

// The signature of the query currently materialised, so an event that leaves the
// criteria unchanged (e.g. focus churn, a no-op keystroke) does not re-fire it.
// runQuery() stamps this after every materialise (live change, paging, or boot).
let materialisedSignature = null;

// A canonical string for a query so a no-op change (chip toggled off then on, a
// re-order, focus churn) does not re-fire. Facet keys are sorted, and each facet's
// array is sorted, so [a,b] and [b,a] compare equal (selection is a set, not an
// ordered list). Scalars serialise as-is.
function querySignature(filters, sort) {
    const canonical = {};
    for (const key of Object.keys(filters).sort()) {
        const value = filters[key];
        canonical[key] = Array.isArray(value) ? [...value].sort() : value;
    }
    return JSON.stringify([canonical, sort]);
}

// Re-run the filter only if the form's current criteria differ from what is
// already on screen — the live change/input path, which must not re-fire on a
// no-op event. Always resets to the first page: a criteria change invalidates
// the old offset.
function requestFilterQuery() {
    const filters = readFilters();
    const sort = SORT_SELECT.value || DEFAULT_SORT;
    if (querySignature(filters, sort) === materialisedSignature) {
        return;
    }
    runFilterQuery();
}

function runFilterQuery() {
    runQuery(0).catch((error) => showToast(error.message, true));
}

let filterDebounceTimer = null;
function requestFilterQueryDebounced() {
    clearTimeout(filterDebounceTimer);
    filterDebounceTimer = setTimeout(requestFilterQuery, FILTER_DEBOUNCE_MS);
}

// Chips and the sort <select> commit immediately on change; free-text and numeric
// inputs debounce. Binding by element/input type keeps the wiring declarative — a
// new filter field needs no change here, only the right control in the CGI form.
// The sort <select> lives inside the filter form, so it is covered by this loop.
function bindLiveFilters() {
    for (const field of FILTER_FORM.elements) {
        if (field.tagName === "SELECT" || field.type === "checkbox") {
            field.addEventListener("change", requestFilterQuery);
        } else if (field.tagName === "INPUT") {
            field.addEventListener("input", requestFilterQueryDebounced);
        }
    }
}

// Submit (the Filter button / Enter in a field) is the explicit manual re-sync:
// it re-pulls unconditionally — even when the criteria are unchanged — so the
// user can deliberately drop just-reviewed rows from the working set. It bypasses
// the debounce and the redundant-query guard.
FILTER_FORM.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(filterDebounceTimer);
    runFilterQuery();
});

DRAWER_TOGGLE.addEventListener("click", toggleDrawer);
DRAWER_BACKDROP.addEventListener("click", () => setDrawer(false));
HELP_TOGGLE.addEventListener("click", () => toggleCheatsheet(true));

document.addEventListener("keydown", onGlobalKey);

// Every categorical facet renders as the same compact dropdown, so the filter bar
// stays one tidy row of triggers no matter a facet's cardinality (POS alone is 113
// genuine CLAWS tags — 53 of them contraction portmanteaux like PNP+VHD — that a chip
// each would explode the bar with). One control for all eight keeps the chrome
// uniform. The data-derived facets (pos/var/status/source) take their values from the
// daemon's distinct-value op; the closed vocabularies (word_kind/novelty/reviewed/
// patch_state) carry their value→label pairs in the page markup as .chip templates,
// harvested here. Either way each value becomes a name=facet/value=value checkbox, so
// readFilters/restoreChips/querySignature/bindLiveFilters treat them identically.
async function buildFacetDropdowns() {
    const derived = await callDaemon({ op: "facets" });
    for (const fieldset of FILTER_FORM.querySelectorAll(".chips[data-facet]")) {
        const facet = fieldset.dataset.facet;
        const entries = facet in derived
            ? derived[facet].map((value) => ({ value, label: value }))
            : harvestChipTemplates(fieldset);
        fieldset.replaceChildren(fieldset.querySelector("legend"), facetDropdown(facet, entries));
    }
}

// A closed-vocabulary facet ships its value→label pairs in an unrendered <template>
// in the page (e.g. value "new-pos" shown as "new POS"); read them off so the human
// labels stay authored in one place rather than duplicated in JS.
function harvestChipTemplates(fieldset) {
    const template = fieldset.querySelector("template");
    return [...template.content.querySelectorAll(".chip")].map((chip) => ({
        value: chip.querySelector("input").value,
        label: chip.querySelector("span").textContent,
    }));
}

function chip(facet, value, label) {
    const wrap = document.createElement("label");
    wrap.className = "chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = facet;
    input.value = value;
    const caption = document.createElement("span");
    caption.textContent = label;
    wrap.append(input, caption);
    return wrap;
}

// A single facet's dropdown: a compact trigger button whose label stays one line
// however many values there are, and a popover holding a search box and a scrollable
// checklist. The checkboxes are the same name=facet/value=value ones the chips use,
// so every downstream reader (readFilters, restoreChips, querySignature, the
// bindLiveFilters change-listener) treats them identically. The popover is
// position:absolute so opening it overlays the layout rather than growing the bar.
function facetDropdown(facet, entries) {
    const wrap = document.createElement("div");
    wrap.className = "facet-select";

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "facet-trigger";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");

    const panel = document.createElement("div");
    panel.className = "facet-panel";
    panel.hidden = true;

    const search = document.createElement("input");
    search.type = "text";
    search.className = "facet-search";
    search.placeholder = "filter…";
    search.setAttribute("aria-label", `Filter ${facet} values`);

    const list = document.createElement("div");
    list.className = "facet-list";
    for (const { value, label } of entries) {
        list.append(chip(facet, value, label));
    }
    panel.append(search, list);
    wrap.append(trigger, panel);

    // The fieldset's legend already names the facet, so the trigger only summarises
    // the selection: "All" when unconstrained, "N selected" when it filters.
    const refreshLabel = () => {
        const count = list.querySelectorAll("input:checked").length;
        trigger.textContent = count ? `${count} selected` : "All";
        trigger.classList.toggle("has-selection", count > 0);
    };
    refreshLabel();

    // The trigger label reflects the checked count; the checkbox change also runs
    // the live query via bindLiveFilters, so the two stay in step with no re-query
    // wiring of our own.
    list.addEventListener("change", refreshLabel);
    // Filter the checklist to matching values — a plain substring match so 113 tags
    // are reachable without scrolling. Hiding a checked box does not uncheck it, so
    // the selection (and thus the query) is unaffected by searching.
    search.addEventListener("input", () => {
        const needle = search.value.trim().toLowerCase();
        for (const label of list.querySelectorAll(".chip")) {
            label.hidden = !label.textContent.toLowerCase().includes(needle);
        }
    });

    trigger.addEventListener("click", () => toggleFacetPanel(panel, trigger, search));
    return wrap;
}

// Only one facet panel is open at a time. Opening focuses the search box so the
// keyboard user can type straight into it; the outside-click / Esc handlers
// (installed once, below) close whatever is open.
function toggleFacetPanel(panel, trigger, search) {
    const opening = panel.hidden;
    closeFacetPanels();
    if (!opening) {
        return;
    }
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    search.focus();
}

function closeFacetPanels() {
    for (const panel of FILTER_FORM.querySelectorAll(".facet-panel:not([hidden])")) {
        panel.hidden = true;
        panel.previousElementSibling.setAttribute("aria-expanded", "false");
    }
}

// Tap/click outside an open panel closes it (touch-friendly: no hover involved);
// Esc closes it too. Scoped to the filter form so a click on a trigger toggles via
// its own handler rather than being pre-closed here.
document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".facet-select")) {
        closeFacetPanels();
    }
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closeFacetPanels();
    }
});

// Boot: build the facet dropdowns (data-derived values from the daemon, closed
// vocabularies from the page markup), then resume the saved session (filter + sort +
// anchor) if one exists, else a plain first query at the review default sort (highest
// confidence first). Filters are bound AFTER the dropdowns exist so every checkbox,
// dynamic ones included, re-runs the query on toggle.
async function boot() {
    buildCheatsheet();
    await buildFacetDropdowns();
    bindLiveFilters();
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
