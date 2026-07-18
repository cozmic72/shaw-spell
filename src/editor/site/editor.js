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
// The daemon query sort is fixed: it decides which records land in the page (the
// highest-confidence candidates, the review targets) and their base order. The
// user reorders the loaded page client-side via the ledger column headers
// (state.columnSort), which never re-pulls.
const QUERY_SORT = "confidence_desc";
const RRP_VAR = "RRP";

const EDITABLE_FIELDS = ["shaw", "var", "ipa", "status"];

// The within-accent vowel mergers a record's spelling reflects (additive, empty
// == canonical). A closed vocabulary mirroring src/tools/dialect_mergers.py; the
// reviewer toggles these on the detail card and they round-trip in the patch.
const MERGERS = [
    ["trap-bath", "TRAP–BATH"],
    ["cot-caught", "COT–CAUGHT"],
];

// The within-accent free-variation marker: an alternate spelling of the same
// accent, not the canonical one (additive boolean, absent == canonical). The
// reviewer toggles it on the detail card and it round-trips in the patch.
const VARIANT_LABEL = "variant";

// Dictionaries to look the word up in while deciding. {word} is URL-encoded so
// phrases and apostrophes ("A for effort", "don't") stay valid.
const REFERENCES = [
    ["Wiktionary", "https://en.wiktionary.org/wiki/{word}"],
    ["Merriam-Webster", "https://www.merriam-webster.com/dictionary/{word}"],
    ["OED", "https://www.oed.com/search/dictionary/?scope=Entries&q={word}"],
];

// CLAWS C5 part-of-speech tags → their plain-English descriptions (the standard
// BNC tagset the ReadLex data carries). Shown as a tooltip wherever a bare tag
// appears, for the reviewer still learning the codes. Portmanteau tags (a
// contraction spanning two words, e.g. "PNP+VHD" for "I've") are not listed
// individually — posTitle composes them from their parts joined with " + ".
const C5_TAGS = {
    AJ0: "adjective (general or positive)",
    AJC: "comparative adjective",
    AJS: "superlative adjective",
    AT0: "article",
    AV0: "adverb (general)",
    AVP: "adverb particle",
    AVQ: "wh-adverb",
    CJC: "coordinating conjunction",
    CJS: "subordinating conjunction",
    CJT: "the conjunction “that”",
    CRD: "cardinal number",
    DPS: "possessive determiner",
    DT0: "general determiner",
    DTQ: "wh-determiner",
    EX0: "existential “there”",
    ITJ: "interjection",
    NN0: "common noun (neutral for number)",
    NN1: "singular common noun",
    NN2: "plural common noun",
    NP0: "proper noun",
    ORD: "ordinal numeral",
    PNI: "indefinite pronoun",
    PNP: "personal pronoun",
    PNQ: "wh-pronoun",
    PNX: "reflexive pronoun",
    POS: "possessive ’s",
    PRF: "the preposition “of”",
    PRP: "preposition",
    PUL: "left bracket punctuation",
    PUN: "general separating punctuation",
    PUQ: "quotation mark",
    PUR: "right bracket punctuation",
    TO0: "infinitive marker “to”",
    UNC: "unclassified",
    VBB: "present-tense “be” (am/are)",
    VBD: "past-tense “be” (was/were)",
    VBG: "“being”",
    VBI: "infinitive “be”",
    VBN: "“been”",
    VBZ: "“is”/“’s”",
    VDB: "base-form “do”",
    VDD: "past-tense “did”",
    VDG: "“doing”",
    VDI: "infinitive “do”",
    VDN: "“done”",
    VDZ: "“does”",
    VHB: "base-form “have”",
    VHD: "past-tense “had”",
    VHG: "“having”",
    VHI: "infinitive “have”",
    VHN: "“had” (past participle)",
    VHZ: "“has”",
    VM0: "modal auxiliary verb",
    VVB: "base form of a lexical verb",
    VVD: "past-tense lexical verb",
    VVG: "-ing form of a lexical verb",
    VVI: "infinitive lexical verb",
    VVN: "past-participle lexical verb",
    VVZ: "-s form of a lexical verb",
    XX0: "the negative “not”/“n’t”",
    ZZ0: "alphabetical symbol",
};

// A tooltip string for a POS tag. A portmanteau tag (a contraction spanning two
// words, joined by "+") composes from its parts; an unknown tag falls back to
// its own code so the tooltip never lies about coverage it does not have.
function posTitle(pos) {
    if (!pos) {
        return "";
    }
    return pos
        .split("+")
        .map((part) => `${part} — ${C5_TAGS[part] ?? part}`)
        .join(" + ");
}

// A POS cell (ledger or detail) carrying its C5 description as a hover tooltip.
function posCell(className, pos) {
    const span = cell(className, pos);
    span.title = posTitle(pos);
    return span;
}

const FILTER_FORM = document.getElementById("filters");
const CHIP_STRIP = document.getElementById("chipStrip");
const ADD_FILTER = document.getElementById("addFilter");
const ADD_FILTER_WRAP = document.getElementById("addFilterWrap");
const FILTER_META = document.getElementById("filterMeta");
const FILTERS_TOGGLE = document.getElementById("filtersToggle");
const REFRESH_RESULTS = document.getElementById("refreshResults");
const TALLY = document.getElementById("tally");
const LEDGER = document.getElementById("ledgerList");
const LEDGER_HEAD = document.getElementById("ledgerHead");
const LEDGER_FOOT = document.getElementById("ledgerFoot");
const SELECT_BAR = document.getElementById("selectBar");
const SELECT_BAR_COUNT = document.getElementById("selectBarCount");
const SELECT_BAR_DONE = document.getElementById("selectBarDone");
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
    // The filters materialised by the last runQuery — the daemon dict. Read by
    // countUnreviewedRemaining and saveSession; written by runQuery from the chips.
    filters: {},
    // The active filter chips, in strip order: an ordered array of entries shaped by
    // their field's kind (see blankEntry). This is the editable model; state.filters
    // is its materialised projection via filtersFromState. An unset entry (empty
    // categorical, blank text, null numeric) contributes nothing to the query.
    activeFilters: [],
    // Client-side ledger ordering, applied to the loaded page after each query and
    // toggled by the column headers. null == daemon order (the QUERY_SORT the page
    // arrived in). {key, dir} where dir is "asc" or "desc".
    columnSort: null,
    selected: -1,
    editing: false,
    // Bulk selection: the anchor keys of the checked rows (an anchor is a stable
    // identity, so a row survives in-place updates and re-renders keyed by it). The
    // single focused row (state.selected) is independent — it stays the review
    // cursor even while a bulk selection is active. 2+ selected == bulk mode.
    multi: new Set(),
    // The last row toggled/clicked by pointer, so a shift-click can range-extend
    // from it — the selection anchor in the file-list sense.
    lastToggledKey: null,
    // Touch multi-select mode (iOS Mail/Photos style): entered by long-press, in
    // which a plain tap toggles rather than reviews. Off = plain tap reviews.
    touchMulti: false,
};

// Long-press threshold to enter touch multi-select, and the movement slop beyond
// which a press is treated as a scroll and cancelled.
const LONG_PRESS_MS = 500;
const LONG_PRESS_SLOP_PX = 10;

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

// ---- filter field registry ----
// The single source of truth for the filter fields: their kind, human label, order,
// and (for categorical) their value vocabulary. The order here drives the +Add menu
// and the chip strip. Populated at boot from the CGI's .filter-meta block (labels +
// closed-vocabulary values) and the daemon facets op (data-derived values). Each
// entry is {field, kind, label, ...}:
//   categorical — kind "categorical", entries [{value,label}], value is a string[]
//   text        — kind "text", value is a scalar string, flags {regex,ci}
//   numeric     — kind "numeric", value is a Number|null
// The registry REPLACES the former CATEGORICAL_FACETS + SUBSTRING_FLAGS sets: every
// downstream reader (filtersFromState, chips, session) consults it by field.
const FIELD_REGISTRY = new Map();

function registerField(spec) {
    FIELD_REGISTRY.set(spec.field, spec);
}

function fieldSpec(field) {
    const spec = FIELD_REGISTRY.get(field);
    if (!spec) {
        throw new Error(`unknown filter field: ${field}`);
    }
    return spec;
}

// The daemon defaults word to case-insensitive, shaw to case-sensitive (Shavian has
// no case). The toggles start UNPRESSED (both flags false) so filtersFromState omits
// them and the daemon applies its own default — matching the former form's unchecked
// checkboxes exactly, which the critical round-trip invariant depends on.
function newTextFlags() {
    return { regex: false, ci: false };
}

// Build one active-filter entry (unset) for a field, its value shaped for its kind.
function blankEntry(field) {
    const spec = fieldSpec(field);
    if (spec.kind === "categorical") {
        return { field, value: [] };
    }
    if (spec.kind === "text") {
        return { field, value: "", flags: newTextFlags() };
    }
    return { field, value: null };
}

// ---- the critical invariant: state.activeFilters → the daemon filters dict ----
// This MUST produce the exact dict the former readFilters() produced for the
// equivalent form state, since the daemon is untouched:
//   categorical → value array, OMITTED when empty
//   text        → trimmed scalar (omitted when empty) + <field>_regex / <field>_ci
//                 booleans, present ONLY when true
//   numeric     → Number, omitted when empty/NaN
// Chip order does not appear in the dict, so reordering never changes the query.
function filtersFromState() {
    const filters = {};
    for (const entry of state.activeFilters) {
        const spec = fieldSpec(entry.field);
        if (spec.kind === "categorical") {
            if (entry.value.length) {
                filters[entry.field] = [...entry.value];
            }
        } else if (spec.kind === "text") {
            const trimmed = entry.value.trim();
            if (!trimmed) {
                continue;
            }
            filters[entry.field] = trimmed;
            if (entry.flags.regex) {
                filters[`${entry.field}_regex`] = true;
            }
            if (entry.flags.ci) {
                filters[`${entry.field}_ci`] = true;
            }
        } else {
            if (entry.value === null || Number.isNaN(entry.value)) {
                continue;
            }
            filters[entry.field] = entry.value;
        }
    }
    return filters;
}

// The inverse map: a saved filters dict → an ordered activeFilters array, so an old
// session (which persisted only `filters`) migrates to chips, and any dict can seed
// the chip strip. Registry order is imposed so chips appear in the canonical order.
// Text flags (<field>_regex / <field>_ci) fold back onto their field's entry; a bare
// flag with no substring value is dropped (it constrained nothing).
function activeFiltersFromDict(filters) {
    const active = [];
    for (const spec of FIELD_REGISTRY.values()) {
        const raw = filters[spec.field];
        if (spec.kind === "categorical") {
            if (Array.isArray(raw) && raw.length) {
                active.push({ field: spec.field, value: [...raw] });
            }
        } else if (spec.kind === "text") {
            if (typeof raw === "string" && raw.trim()) {
                active.push({
                    field: spec.field,
                    value: raw,
                    flags: {
                        regex: Boolean(filters[`${spec.field}_regex`]),
                        ci: Boolean(filters[`${spec.field}_ci`]),
                    },
                });
            }
        } else if (typeof raw === "number" && !Number.isNaN(raw)) {
            active.push({ field: spec.field, value: raw });
        }
    }
    return active;
}

// Flag the text-filter chips whose regex the daemon could not compile (its response
// names them in invalid_regex). The chip's text input gets .invalid — a red border —
// while the query still returns (it simply matched nothing). Chips not named are
// cleared, so fixing the pattern removes the flag on the next live re-query. Only the
// currently-active text chips can be flagged; a removed field has no input to mark.
function markInvalidRegex(invalidFields) {
    const invalid = new Set(invalidFields);
    for (const input of CHIP_STRIP.querySelectorAll(".text-filter")) {
        input.classList.toggle("invalid", invalid.has(input.dataset.field));
    }
}

// Re-run the filter: materialise a fresh working set. This is the ONLY point at
// which the list re-syncs to latest state — membership and order are fixed here
// and stay put until the next re-run. preferredAnchor lands the selection on that
// entry (session restore); if it fell out of the set, on the nearest neighbour.
async function runQuery(offset = 0, preferredAnchor = null) {
    state.filters = filtersFromState();
    state.offset = offset;
    const result = await callDaemon({
        op: "entries",
        filters: state.filters,
        sort: QUERY_SORT,
        offset,
        limit: state.limit,
    });
    // The daemon returns the page in QUERY_SORT order; the active column sort (if
    // any) reorders it for display before the ledger is built, so index-keyed
    // selection and in-place row refresh stay aligned with what is on screen.
    state.records = sortedForDisplay(result.records);
    state.total = result.total;
    markInvalidRegex(result.invalid_regex || []);
    // The selection is over the working set that was on screen; a re-materialise
    // replaces that set, so the old selection no longer refers to these rows. Clear
    // it — select-all means "all currently-loaded rows", scoped to this page.
    state.multi.clear();
    state.lastToggledKey = null;
    state.touchMulti = false;
    materialisedSignature = querySignature(state.filters);
    TALLY.textContent = `${result.total.toLocaleString()} matching`;
    renderLedger();
    renderFoot();
    select(landingIndex(preferredAnchor));
    syncSelectBar();
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

// A stable string identity for an anchor, so the bulk selection can be a Set the
// row's checkbox and its in-place refresh both key off. Mirrors sameAnchor's
// fields; the NUL separator can't occur in a value (a word may contain spaces, so a
// space would not be collision-proof), so distinct anchors never collide.
function anchorKey(anchor) {
    return [anchor.word, anchor.pos, anchor.shaw, anchor.var].join("\0");
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

// Client-side ledger ordering. Each sortable column extracts a comparable key from
// a record; strings compare case-insensitively by locale, numbers numerically.
// Missing numeric values (a record with no freq/confidence) sort last in both
// directions, matching the daemon's "not a review target" convention.
const SORT_KEYS = {
    state: (record) => ({ text: record.patch_state }),
    word: (record) => ({ text: record.word.toLowerCase() }),
    shaw: (record) => ({ text: record.shaw }),
    var: (record) => ({ text: record.var }),
    pos: (record) => ({ text: record.pos }),
    confidence: (record) => ({ number: record.confidence }),
    freq: (record) => ({ number: record.freq }),
};

// Order a page for display under the active column sort. Returns a new array so the
// daemon's page is not mutated; a null columnSort leaves the daemon order intact.
// Array.sort is stable (ES2019+), and the comparator returns 0 for equal keys, so
// records with the same key keep their incoming (daemon) order.
function sortedForDisplay(records) {
    if (!state.columnSort) {
        return records;
    }
    const extract = SORT_KEYS[state.columnSort.key];
    if (!extract) {
        throw new Error(`unknown column sort: ${state.columnSort.key}`);
    }
    const direction = state.columnSort.dir === "desc" ? -1 : 1;
    return [...records].sort((left, right) => compareKeys(extract(left), extract(right), direction));
}

// Compare two extracted keys under `direction` (1 asc, -1 desc). The missing-value
// partition is direction-INDEPENDENT — an absent numeric value (null/undefined)
// always sorts last, in both asc and desc — so `direction` is applied only to the
// both-present (and text) comparison, never to the missing-vs-present verdict. Text
// keys compare by locale case-insensitively (numeric collation).
function compareKeys(left, right, direction) {
    if ("number" in left) {
        const a = left.number;
        const b = right.number;
        const aMissing = a === null || a === undefined;
        const bMissing = b === null || b === undefined;
        if (aMissing || bMissing) {
            return aMissing === bMissing ? 0 : (aMissing ? 1 : -1);
        }
        return direction * (a - b);
    }
    return direction * left.text.localeCompare(right.text, undefined, { numeric: true });
}

// A column header was clicked: sort ascending, or flip to descending if that column
// is already the ascending sort. Re-orders the loaded page in place (preserving the
// focused row by anchor) without re-pulling from the daemon.
function onSortHeaderClick(key) {
    if (state.columnSort && state.columnSort.key === key && state.columnSort.dir === "asc") {
        state.columnSort = { key, dir: "desc" };
    } else {
        state.columnSort = { key, dir: "asc" };
    }
    reorderLedger();
}

// Re-apply the active column sort to the loaded records, keeping the focused entry
// selected by anchor (its index moves under the new order) and the ledger and
// select-bar in sync. Absent-value tie handling matches sortedForDisplay.
function reorderLedger() {
    const focusedAnchor = state.records[state.selected]
        ? state.records[state.selected].anchor
        : null;
    state.records = sortedForDisplay(state.records);
    syncSortIndicators();
    renderLedger();
    select(landingIndex(focusedAnchor));
    // syncSelectionUI re-applies the .picked highlight from state.multi to the
    // freshly re-rendered rows (and calls syncSelectBar internally), so a bulk
    // selection survives a column re-sort visually, not just in state.
    syncSelectionUI();
    saveSession();
}

// Reflect the active column sort on the header row: the sorted column carries the
// direction class (styled to show ▲/▼ via CSS) and aria-sort; the rest are cleared.
function syncSortIndicators() {
    for (const header of LEDGER_HEAD.querySelectorAll(".sort-head")) {
        const active = state.columnSort && state.columnSort.key === header.dataset.sortKey;
        header.classList.toggle("sort-asc", active && state.columnSort.dir === "asc");
        header.classList.toggle("sort-desc", active && state.columnSort.dir === "desc");
        header.setAttribute(
            "aria-sort",
            active ? (state.columnSort.dir === "asc" ? "ascending" : "descending") : "none",
        );
    }
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
        freqCell(record.freq),
        posCell("col-pos", record.pos),
    );
    bindLongPress(row, record);
    row.addEventListener("click", (event) => onRowClick(record, index, event));
    return row;
}

// The native list-selection gesture on a row. Plain click reviews the one row (and
// collapses any multi-selection to it); ⌘/Ctrl-click toggles the row without
// disturbing the rest; shift-click extends a contiguous range from the anchor. In
// touch multi-select mode a plain tap toggles instead of reviewing.
function onRowClick(record, index, event) {
    // A long-press already toggled this row; the synthesised click that follows the
    // finger lift must not toggle it straight back.
    if (suppressNextClick) {
        suppressNextClick = false;
        return;
    }
    setDrawer(false);
    if (state.touchMulti) {
        toggleSelection(record.anchor);
        return;
    }
    if (event.shiftKey && state.lastToggledKey !== null) {
        extendSelection(index);
        return;
    }
    if (event.metaKey || event.ctrlKey) {
        toggleSelection(record.anchor);
        return;
    }
    reviewOnly(index);
}

// A plain click is single-select: any group selection collapses to this one row,
// which becomes both the review focus and the new range anchor.
function reviewOnly(index) {
    state.multi.clear();
    state.lastToggledKey = anchorKey(state.records[index].anchor);
    select(index);
    syncSelectionUI();
}

// Set when a long-press fires, to swallow the click the browser synthesises when
// the finger lifts (which would otherwise re-toggle the just-toggled row).
let suppressNextClick = false;

// Long-press to enter touch multi-select (iOS Mail/Photos). A touch that moves past
// the slop, or lifts before the threshold, is a scroll or tap and cancels the timer.
function bindLongPress(row, record) {
    let timer = null;
    let startX = 0;
    let startY = 0;
    const cancel = () => {
        if (timer !== null) {
            clearTimeout(timer);
            timer = null;
        }
    };
    row.addEventListener("pointerdown", (event) => {
        // A fresh press: any suppression left dangling by a long-press whose click
        // never arrived must not swallow this gesture's click.
        suppressNextClick = false;
        if (event.pointerType !== "touch") {
            return;
        }
        startX = event.clientX;
        startY = event.clientY;
        timer = setTimeout(() => {
            timer = null;
            suppressNextClick = true;
            enterTouchMulti();
            toggleSelection(record.anchor);
        }, LONG_PRESS_MS);
    });
    row.addEventListener("pointermove", (event) => {
        if (Math.abs(event.clientX - startX) > LONG_PRESS_SLOP_PX
            || Math.abs(event.clientY - startY) > LONG_PRESS_SLOP_PX) {
            cancel();
        }
    });
    row.addEventListener("pointerup", cancel);
    row.addEventListener("pointercancel", cancel);
    row.addEventListener("pointerleave", cancel);
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

// Corpus frequency as a plain integer; a record without a freq shows nothing (an
// em dash would read as data). Right-aligned via the col-freq class so the numbers
// line up for scanning.
function freqCell(freq) {
    const span = cell("col-freq", freq === null || freq === undefined ? "" : String(freq));
    if (freq !== null && freq !== undefined) {
        span.title = `frequency ${freq}`;
    }
    return span;
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
    // In bulk mode the card shows the group summary, not a record; moving the review
    // cursor still scrolls the row into view but leaves the summary in place.
    if (inBulkMode()) {
        scrollRowIntoView(index);
    } else if (index < 0) {
        renderEmptyDetail();
    } else {
        scrollRowIntoView(index);
        renderDetail(state.records[index]);
    }
    saveSession();
}

function scrollRowIntoView(index) {
    const active = LEDGER.children[index];
    if (active) {
        active.scrollIntoView({ block: "nearest" });
    }
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

// ---- bulk selection ----
// A set of anchor keys over the current working set. 2+ selected is BULK MODE:
// the verdict actions and their keyboard shortcuts operate on the whole group,
// and the detail card shows a summary instead of the single-record editor. 0–1
// selected leaves the single-record review flow exactly as it was.

function inBulkMode() {
    return state.multi.size >= 2;
}

function toggleSelection(anchor) {
    const key = anchorKey(anchor);
    if (state.multi.has(key)) {
        state.multi.delete(key);
    } else {
        state.multi.add(key);
    }
    state.lastToggledKey = key;
    onSelectionChanged();
}

// Shift-click range: add every row between the last toggled row and this one
// (inclusive) to the selection — the familiar file-list convention. Range always
// selects (never deselects), which is the triage move: pick a contiguous class in
// one gesture. If the anchor row has since gone (a re-run replaced the set), fall
// back to toggling just the clicked row.
function extendSelection(toIndex) {
    const fromIndex = state.records.findIndex(
        (record) => anchorKey(record.anchor) === state.lastToggledKey,
    );
    if (fromIndex < 0) {
        toggleSelection(state.records[toIndex].anchor);
        return;
    }
    const [low, high] = fromIndex <= toIndex
        ? [fromIndex, toIndex]
        : [toIndex, fromIndex];
    for (let i = low; i <= high; i += 1) {
        state.multi.add(anchorKey(state.records[i].anchor));
    }
    state.lastToggledKey = anchorKey(state.records[toIndex].anchor);
    onSelectionChanged();
}

// Toggle the focused row into/out of the selection (the V key) — the keyboard route
// into a group, for the reviewer who never leaves the home row.
function toggleFocusedSelection() {
    const focused = state.records[state.selected];
    if (!focused) {
        return;
    }
    toggleSelection(focused.anchor);
}

function selectAll() {
    for (const record of state.records) {
        state.multi.add(anchorKey(record.anchor));
    }
    onSelectionChanged();
}

function clearSelection() {
    state.multi.clear();
    state.lastToggledKey = null;
    state.touchMulti = false;
    onSelectionChanged();
}

// Touch multi-select mode: a plain tap toggles instead of reviewing. Entered by a
// long-press, left via the Done affordance (which also clears the selection).
function enterTouchMulti() {
    state.touchMulti = true;
}

// Re-sync everything the selection drives: the row highlights, the touch-mode
// select bar, and the detail card (which flips to the bulk summary at 2+, back to
// the focused record below that).
function onSelectionChanged() {
    syncSelectionUI();
    if (inBulkMode()) {
        renderBulkDetail();
    } else if (state.selected >= 0) {
        renderDetail(state.records[state.selected]);
    } else {
        renderEmptyDetail();
    }
}

function syncSelectionUI() {
    for (const row of LEDGER.children) {
        const record = state.records[Number(row.dataset.index)];
        if (record) {
            row.classList.toggle("picked", state.multi.has(anchorKey(record.anchor)));
        }
    }
    syncSelectBar();
}

// The touch select bar only shows in touch multi-select mode, giving the count and
// the Done button that exits the mode.
function syncSelectBar() {
    SELECT_BAR.hidden = !state.touchMulti;
    const count = state.multi.size;
    SELECT_BAR_COUNT.textContent = count === 1 ? "1 selected" : `${count} selected`;
}

function renderDetail(record) {
    const heading = document.createElement("div");
    heading.className = "detail-word";
    heading.append(
        stateBadge(record.patch_state),
        cell("latin", record.word),
        posCell("pos", record.pos),
        mergerBadges(record.mergers),
        variantBadge(record.variant),
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

// ---- bulk detail ----
// When 2+ rows are selected the card drops the single-record editor (you can't
// type one Shavian for forty rows) and shows what the group IS — a count and a
// compact per-field readout — above the group verdict bar. Field editing is
// simply absent here, so only flag/drop/clear/accept are offered.

// The traits summarised, in the order they help a triage decision: the dialect
// and POS the class shares, its origin, and its current review state.
const BULK_TRAITS = [
    ["var", "Dialect"],
    ["pos", "POS"],
    ["source", "Source"],
    ["patch_state", "State"],
];

function renderBulkDetail() {
    const selected = selectedRecords();

    const heading = document.createElement("div");
    heading.className = "bulk-word";
    heading.append(
        cell("bulk-count", String(selected.length)),
        cell("bulk-count-label", "records selected"),
    );

    DETAIL.replaceChildren(
        heading,
        bulkTraits(selected),
        bulkActionBar(),
    );
    setDetailMode();
}

// The records currently in the bulk selection, in working-set order (a selected
// anchor that fell out of the set on a re-run is simply skipped).
function selectedRecords() {
    return state.records.filter(
        (record) => state.multi.has(anchorKey(record.anchor)),
    );
}

// A per-field readout: for each trait, "all X" when the group is homogeneous, or
// a breakdown "X ·12, Y ·3" (commonest first) when it is mixed — so the user sees
// exactly what they are about to act on.
function bulkTraits(records) {
    const grid = document.createElement("dl");
    grid.className = "bulk-traits";
    for (const [field, label] of BULK_TRAITS) {
        const counts = tallyField(records, field);
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = summariseCounts(counts);
        grid.append(dt, dd);
    }
    return grid;
}

function tallyField(records, field) {
    const counts = new Map();
    for (const record of records) {
        const value = record[field] ?? "—";
        counts.set(value, (counts.get(value) ?? 0) + 1);
    }
    return counts;
}

function summariseCounts(counts) {
    if (counts.size === 1) {
        const [only] = counts.keys();
        return `all ${only}`;
    }
    return [...counts.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([value, count]) => `${value} ·${count}`)
        .join(", ");
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
    for (const record of sortedRelated(records, focusedAnchor)) {
        list.append(relatedRow(record, focusedAnchor));
    }
    section.replaceChildren(relatedHeading(records.length), list);
}

// Order the related rows deterministically so the list is stable across landings
// (the daemon returns them in an unspecified index order). The focused entry ("you
// are here") always leads, anchoring the eye to the card above; the rest sort by a
// total key — word (case-SENSITIVE, so a capitalised homograph like "March" sits
// apart from "march"), then pos, var, shaw. Every field participates, so no two
// distinct records ever tie.
function sortedRelated(records, focusedAnchor) {
    return [...records].sort((left, right) => {
        const leftHere = sameAnchor(left.anchor, focusedAnchor);
        const rightHere = sameAnchor(right.anchor, focusedAnchor);
        if (leftHere !== rightHere) {
            return leftHere ? -1 : 1;
        }
        return compareRelated(left, right);
    });
}

function compareRelated(left, right) {
    const fields = ["word", "pos", "var", "shaw"];
    for (const field of fields) {
        if (left[field] < right[field]) return -1;
        if (left[field] > right[field]) return 1;
    }
    return 0;
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
        posCell("related-pos", record.pos),
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

// A record's within-accent variant marker, as a small badge beside the word.
// Canonical (the flag absent) shows nothing — the absence is the signal.
function variantBadge(variant) {
    const wrap = document.createElement("span");
    wrap.className = "variant-badges";
    if (variant) {
        wrap.append(cell("variant-badge", VARIANT_LABEL));
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

// A row of external dictionary look-ups for the focused word. All the reference
// links across the app share ONE named tab (REFERENCE_TARGET), so looking up a
// new word reuses that tab rather than piling up a fresh one each time. The word
// is URL-encoded so phrases and apostrophes stay valid.
const REFERENCE_TARGET = "shaw-ref";

function referenceLinks(word) {
    const row = document.createElement("nav");
    row.className = "references";
    row.setAttribute("aria-label", "Look up in external dictionaries");
    for (const [label, template] of REFERENCES) {
        const link = document.createElement("a");
        link.className = "reference";
        link.href = template.replace("{word}", encodeURIComponent(word));
        link.target = REFERENCE_TARGET;
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
        variantField(record.variant),
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

// variant is an additive boolean, not a scalar, so it edits as a single toggle
// chip mirroring a merger toggle. The checkbox is class "variant-check";
// editedRecord reads whether it is checked. Toggling enters edit mode.
function variantField(current) {
    const wrap = document.createElement("div");
    wrap.className = "edit-field variant-field";

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = "Variant";

    const toggles = document.createElement("div");
    toggles.className = "variant-toggles";
    toggles.append(variantToggle(VARIANT_LABEL, Boolean(current)));

    wrap.append(caption, toggles);
    return wrap;
}

function variantToggle(label, checked) {
    const chip = document.createElement("label");
    chip.className = "variant-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "variant-check";
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

// The group verdict bar. Same buttons and colours as the single-record bar, but
// every action runs over the whole selection; Save/Edit are absent (editing is
// single-record). "Deselect" drops the whole selection without touching data.
function bulkActionBar() {
    const bar = document.createElement("div");
    bar.className = "actions";
    bar.append(
        actionButton("accept", "Accept all", acceptSelected),
        actionButton("drop", "Drop all", dropSelected),
        actionButton("flag", "Flag all", flagSelected),
        actionButton("clear", "Clear all", clearSelected),
        actionButton("undo", "Deselect", clearSelection),
    );
    return bar;
}

// A patch body built from the record's OWN fields, no edit surface involved — the
// shape a bulk verdict writes (bulk mode renders no editable fields). Single-record
// verdicts overlay the live inputs on top of this (editedRecord).
function recordFields(record) {
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
        result[name] = record[name] ?? "";
    }
    if (record.mergers && record.mergers.length) {
        result.mergers = record.mergers;
    }
    if (record.variant) {
        result.variant = true;
    }
    return result;
}

// The complete record the detail editor currently shows: the record's fields with
// the edit surface overlaid from the inputs. Single-record only — the edit inputs
// exist just for the focused record.
function editedRecord(record) {
    const result = recordFields(record);
    for (const name of EDITABLE_FIELDS) {
        const input = document.getElementById(`field-${name}`);
        result[name] = input.value.trim();
    }
    const mergers = [...DETAIL.querySelectorAll(".merger-check:checked")]
        .map((box) => box.value);
    if (mergers.length) {
        result.mergers = mergers;
    } else {
        delete result.mergers;
    }
    const variantBox = DETAIL.querySelector(".variant-check");
    if (variantBox && variantBox.checked) {
        result.variant = true;
    } else {
        delete result.variant;
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

// Run a single-record verdict, surfacing any failure as an error toast. The bulk
// path handles its own errors (per-record, in runBulk), so this guards only the
// single-record branch.
async function single(action) {
    try {
        await action();
    } catch (error) {
        showToast(error.message, true);
    }
}

// Save is inherently single-record — it writes the edited fields, which only make
// sense for the focused record — so it has no bulk form (the group bar omits it).
async function saveSelected() {
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    const record = editedRecord(selected);
    if (!requireShaw(record)) {
        return;
    }
    await single(() => writePatch(anchorOf(selected), record, "saved", selected));
}

async function acceptSelected() {
    if (inBulkMode()) {
        await runBulk("accept", acceptOne);
        return;
    }
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    await single(() => acceptOne(selected, { step: true, toast: true }));
}

// Accept one record: promote its fields with a sanctioned status. A bulk verdict
// takes the record as it stands (no editable fields are rendered); a single verdict
// overlays the live edit inputs. The `bulk` intent is passed in, never re-read from
// global selection state, so a selection that shrinks mid-run can't flip the path.
// Returns the daemon result; throws so the caller can fail loud.
async function acceptOne(selected, options = {}) {
    const record = options.bulk ? recordFields(selected) : editedRecord(selected);
    record.status = ACCEPTED_STATUS;
    if (!record.shaw) {
        throw new Error(`${selected.word}: Shavian cannot be empty.`);
    }
    return writePatch(anchorOf(selected), record, "accepted", selected, options);
}

async function dropSelected() {
    if (inBulkMode()) {
        await runBulk("dropped", dropOne);
        return;
    }
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    await single(() => dropOne(selected, { step: true, toast: true }));
}

// Drop one record. An authored entry has no basis to revert to, so dropping it IS
// deleting its authorship patch (same as Clear); a basis record gets a drop patch.
async function dropOne(selected, options = {}) {
    if (isAuthored(selected)) {
        if (!selected.patch_id) {
            throw new Error(`${selected.word}: authored entry has no patch id.`);
        }
        return unpatch(null, "dropped", { ...options, patchId: selected.patch_id });
    }
    return writePatch(anchorOf(selected), null, "dropped", selected, options);
}

// A verdict (accept/drop/edit) produces a patch. It records an undo frame (whether
// the anchor already had a patch, so undo restores the right prior state) and
// re-annotates the row in place. `step`/`toast` are on for a single verdict and off
// per record in a bulk run (the run does one summary toast, no stepping). Returns
// the daemon result; throws on failure so the bulk loop can fail loud per record.
async function writePatch(anchor, record, verb, selected, { step = true, toast = true, refocus = true } = {}) {
    const priorReviewed = selected ? selected.reviewed : false;
    const request = isAuthored(selected)
        ? { op: "patch", anchor: null, record, author: AUTHOR, replaces: selected.patch_id }
        : { op: "patch", anchor, record, author: AUTHOR };
    const result = await callDaemon(request);
    pushUndo(anchor, priorReviewed);
    countDecision();
    applyWriteResult(result.records, { step, refocus });
    if (toast) {
        showToast(`${verb} · ${result.result}`);
    }
    return result;
}

// Flag: "looked at, no verdict yet". The daemon writes a flag patch carrying the
// source record unchanged; it counts as reviewed but not decided, and is a no-op
// for production output.
async function flagSelected() {
    if (inBulkMode()) {
        await runBulk("flagged", flagOne);
        return;
    }
    const selected = state.records[state.selected];
    if (!selected) {
        return;
    }
    await single(() => flagOne(selected, { step: true, toast: true }));
}

async function flagOne(selected, { step = true, toast = true, refocus = true } = {}) {
    const priorReviewed = selected.reviewed;
    const request = isAuthored(selected)
        ? { op: "flag", anchor: null, author: AUTHOR, replaces: selected.patch_id }
        : { op: "flag", anchor: anchorOf(selected), author: AUTHOR };
    const result = await callDaemon(request);
    pushUndo(anchorOf(selected), priorReviewed);
    applyWriteResult(result.records, { step, refocus });
    if (toast) {
        showToast(`flagged · ${result.result}`);
    }
    return result;
}

// Unflag: remove the flag patch, reverting to unreviewed. Distinct from undo — an
// explicit "actually, back to the pool" on a flagged row.
async function unflagSelected() {
    const selected = state.records[state.selected];
    if (!selected || selected.patch_state !== "flagged") {
        return;
    }
    await single(() => unpatch(anchorOf(selected), "unflagged", { step: false }));
}

// Clear: the general "reset this entry's state" — delete WHATEVER patch it holds
// (accept/edit/drop/flag/authored, this session or a prior one), reverting a basis
// record to its untouched source, or removing an authored record outright. Shown
// whenever the entry is reviewed. An authored record has no anchor, so it is
// cleared by its patch id; the daemon then returns no record and the row is dropped.
async function clearSelected() {
    if (inBulkMode()) {
        await runBulk("cleared", clearOne);
        return;
    }
    const selected = state.records[state.selected];
    if (!selected || !selected.reviewed) {
        return;
    }
    await single(() => clearOne(selected, { step: false, toast: true }));
}

// A record a bulk verdict passed over without writing (not an error, not a write) —
// e.g. Clear on an unreviewed row, which holds no patch. runBulk tallies these apart
// from the writes so the summary count is honest.
const BULK_SKIPPED = Symbol("bulk-skipped");

// Clear one record. An unreviewed record has no patch to clear — a no-op the bulk
// run counts as skipped, not done. An authored record clears by patch id and its row
// is dropped; a basis record clears by anchor and reverts in place.
async function clearOne(selected, options = {}) {
    if (!selected.reviewed) {
        return BULK_SKIPPED;
    }
    if (selected.patch_state === "authored") {
        if (!selected.patch_id) {
            throw new Error(`${selected.word}: authored entry has no patch id.`);
        }
        return unpatch(null, "cleared", { ...options, patchId: selected.patch_id });
    }
    return unpatch(anchorOf(selected), "cleared", options);
}

// ---- bulk verdicts ----
// Run a verdict over every selected record. Each record goes through the SAME
// single-write path (writePatch/unpatch → the daemon's validated write), with
// stepping, per-record toasts, and per-record re-render OFF (refocus:false); the
// loop does one summary toast and one ledger refresh at the end. A large group asks
// for confirmation first. A record that fails is collected and reported, never
// silently skipped — the run continues so one bad row doesn't strand the rest. The
// review cursor is preserved across the run, and the selection is cleared afterwards
// (the class has been triaged).

const BULK_CONFIRM_THRESHOLD = 10;

async function runBulk(verb, applyOne) {
    const targets = selectedRecords();
    if (!targets.length) {
        return;
    }
    if (targets.length >= BULK_CONFIRM_THRESHOLD
        && !window.confirm(`${capitalise(verb)} ${targets.length} records?`)) {
        return;
    }
    const focusedAnchor = state.records[state.selected]?.anchor ?? null;
    let done = 0;
    let skipped = 0;
    const failures = [];
    for (const record of targets) {
        try {
            const outcome = await applyOne(record, { bulk: true, step: false, toast: false, refocus: false });
            if (outcome === BULK_SKIPPED) {
                skipped += 1;
            } else {
                done += 1;
            }
        } catch (error) {
            failures.push(error.message);
        }
    }
    // Clear the set silently — the DOM may be out of step with state.records mid-run
    // (deferred re-render), so the one authoritative rebuild is refreshAfterBulk.
    state.multi.clear();
    state.lastToggledKey = null;
    state.touchMulti = false;
    refreshAfterBulk(focusedAnchor);
    reportBulk(verb, done, skipped, failures);
}

// Rebuild the ledger once after a bulk run (rows may have been re-annotated or
// removed) and restore the review cursor to the entry it was on — or its nearest
// surviving neighbour if that entry was itself dropped. With the selection cleared,
// select() renders the single-record card, back in the ordinary review flow.
function refreshAfterBulk(focusedAnchor) {
    renderLedger();
    let index = focusedAnchor
        ? state.records.findIndex((r) => sameAnchor(r.anchor, focusedAnchor))
        : state.selected;
    if (index < 0) {
        index = Math.min(state.selected, state.records.length - 1);
    }
    select(index);
    syncSelectBar();
}

function reportBulk(verb, done, skipped, failures) {
    const skip = skipped ? `, ${skipped} skipped` : "";
    if (failures.length) {
        showToast(`${verb} ${done}${skip}, ${failures.length} failed: ${failures[0]}`, true);
    } else {
        showToast(`${verb} ${done}${skip}`);
    }
}

function capitalise(word) {
    return word.charAt(0).toUpperCase() + word.slice(1);
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
    await single(() => unpatch(frame.anchor, "undone", { step: false, uncount: true }));
}

// Delete an entry's patch. Returns the daemon result and throws on failure, so a
// bulk loop can fail loud per record. `toast` is off inside a bulk run; the removed
// anchor (an authored entry the daemon returns nothing for) is dropped by anchor,
// not by state.selected, so it works whether or not it is the focused row.
async function unpatch(anchor, verb, { step = true, uncount = false, patchId = null, toast = true, refocus = true } = {}) {
    const request = patchId ? { op: "unpatch", patch_id: patchId } : { op: "unpatch", anchor };
    const result = await callDaemon(request);
    if (uncount) {
        session.decisions = Math.max(0, session.decisions - 1);
    }
    if (!result.records.length) {
        removeRow(anchor ?? findAnchorByPatchId(patchId), { refocus });
    } else {
        applyWriteResult(result.records, { step, refocus });
    }
    if (toast) {
        showToast(`${verb} · ${result.result}`);
    }
    return result;
}

// The anchor of the row holding this patch id (an authored entry — anchor null in
// the store, but its live row carries the resolved word/pos/shaw/var). Used to
// drop the row after the daemon clears it and returns nothing.
function findAnchorByPatchId(patchId) {
    const record = state.records.find((r) => r.patch_id === patchId);
    return record ? record.anchor : null;
}

// Clearing an authored entry leaves no record — the daemon returns an empty set.
// Drop that row (matched by anchor) from the working set, then, if it was the
// focused row, land on its neighbour so the selection stays in view. `refocus:false`
// (a bulk run) mutates the set but defers the ledger re-render to the loop's end.
function removeRow(anchor, { refocus = true } = {}) {
    const removed = anchor
        ? state.records.findIndex((r) => sameAnchor(r.anchor, anchor))
        : state.selected;
    if (removed < 0) {
        return;
    }
    state.multi.delete(anchorKey(state.records[removed].anchor));
    state.records.splice(removed, 1);
    // A removal before the cursor shifts it down by one; keep the same entry
    // focused (or its neighbour if the focused row was itself removed).
    if (removed < state.selected) {
        state.selected -= 1;
    }
    refreshPacing();
    if (refocus) {
        renderLedger();
        select(Math.min(state.selected, state.records.length - 1));
        syncSelectionUI();
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
// place (unflag/undo) stays put. `refocus:false` (a bulk run) updates the row but
// leaves the review cursor where it was — the loop restores focus once at the end.
function applyWriteResult(records, { step: doStep = true, refocus = true } = {}) {
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
    if (!refocus) {
        return;
    }
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
    v: toggleFocusedSelection,
    j: () => step(1),
    k: () => step(-1),
    arrowdown: () => step(1),
    arrowup: () => step(-1),
    "?": () => toggleCheatsheet(),
};

// Keys that mutate must not double-fire on auto-repeat when a key is held.
const NON_REPEAT_KEYS = new Set(["a", "x", "s", "f", "c", "u", "v"]);

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
    // ⌘/Ctrl-A picks the whole working set — the native select-all, replacing the
    // former header checkbox.
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "a") {
        event.preventDefault();
        selectAll();
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
        heading: "Bulk selection",
        rows: [
            { keys: ["V"], state: null, action: "Add / remove the focused row from the selection" },
            { keys: ["⌘", "A"], state: null, action: "Select every row in the working set" },
            { keys: ["⇧", "click"], state: null, action: "Extend a range from the last-clicked row" },
            { keys: ["⌘", "click"], state: null, action: "Add / remove one row (Ctrl-click on Windows)" },
            { keys: ["A", "X", "F", "C"], state: null, action: "With 2+ selected, act on the whole group" },
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

// Session continuity: the active filter, the ledger column sort, plus the ANCHOR
// of the focused entry — not a row index, which is meaningless once the list
// re-materialises. On load the filter + column sort are restored, the list pulled,
// then the anchor re-selected (or its nearest neighbour). Persisted on every query
// and selection.
function saveSession() {
    const selected = state.records[state.selected];
    const stored = {
        activeFilters: state.activeFilters,
        columnSort: state.columnSort,
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

// Adopt a saved session's active filters as the chip strip, dropping any entry whose
// field the registry no longer knows (a field renamed or retired). Entries keep their
// stored order; the strip is rebuilt from them. Called on load before the first query.
function restoreActiveFilters(activeFilters) {
    state.activeFilters = activeFilters.filter((entry) => FIELD_REGISTRY.has(entry.field));
    renderChipStrip();
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

// The filter bar collapses to a chevron on narrow screens so results dominate; on
// wide screens it is always shown and the chevron is hidden by CSS. Collapsed state
// lives as a body class so the CSS can hide #filters; the toggle's aria-expanded
// mirrors it for assistive tech.
function setFiltersOpen(open) {
    document.body.classList.toggle("filters-collapsed", !open);
    FILTERS_TOGGLE.setAttribute("aria-expanded", String(open));
}

function toggleFilters() {
    setFiltersOpen(document.body.classList.contains("filters-collapsed"));
}

// The mobile breakpoint the CSS uses for the collapsed layout. Kept in step with
// the @media (max-width: 860px) rule so the boot-time default collapse matches
// where the chevron actually appears.
const NARROW_BREAKPOINT_PX = 860;

// Start collapsed on a narrow viewport so the results, not the filters, own the
// first screen; stay expanded on desktop.
function collapseFiltersOnNarrow() {
    setFiltersOpen(window.innerWidth > NARROW_BREAKPOINT_PX);
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
// change, so there is no separate "apply" step. A checkbox (a facet chip) commits
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
// ordered list). Scalars serialise as-is. Column sort is display-only (never
// re-pulls), so it is not part of the signature.
function querySignature(filters) {
    const canonical = {};
    for (const key of Object.keys(filters).sort()) {
        const value = filters[key];
        canonical[key] = Array.isArray(value) ? [...value].sort() : value;
    }
    return JSON.stringify(canonical);
}

// Re-run the filter only if the form's current criteria differ from what is
// already on screen — the live change/input path, which must not re-fire on a
// no-op event. Always resets to the first page: a criteria change invalidates
// the old offset.
function requestFilterQuery() {
    if (querySignature(filtersFromState()) === materialisedSignature) {
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

// Enter in a filter field would submit the form (and reload the page in a CGI
// context); there is no Filter button any more, so swallow the submit — each chip's
// own listeners keep the query current.
FILTER_FORM.addEventListener("submit", (event) => event.preventDefault());

// The refresh affordance re-pulls the working set under the CURRENT criteria,
// UNCONDITIONALLY — it bypasses requestFilterQuery's signature guard by calling
// runFilterQuery directly, so an unchanged filter still re-materialises. That is the
// deliberate "drop the rows I have reviewed and refill from the pool" gesture the
// live no-op path cannot express. Cancel a pending debounce so the two do not race.
REFRESH_RESULTS.addEventListener("click", () => {
    clearTimeout(filterDebounceTimer);
    runFilterQuery();
});

DRAWER_TOGGLE.addEventListener("click", toggleDrawer);
DRAWER_BACKDROP.addEventListener("click", () => setDrawer(false));
FILTERS_TOGGLE.addEventListener("click", toggleFilters);
HELP_TOGGLE.addEventListener("click", () => toggleCheatsheet(true));
ADD_FILTER.addEventListener("click", () => toggleAddMenu());

// Column-header sort: one delegated listener over the head row, so a header added
// in the markup needs only its data-sort-key to become sortable.
LEDGER_HEAD.addEventListener("click", (event) => {
    const header = event.target.closest(".sort-head");
    if (header) {
        onSortHeaderClick(header.dataset.sortKey);
    }
});

// Done leaves touch multi-select and drops the selection with it.
SELECT_BAR_DONE.addEventListener("click", clearSelection);

document.addEventListener("keydown", onGlobalKey);

// ---- field registry harvest ----
// Populate FIELD_REGISTRY from the page's .filter-meta block (one div per field,
// carrying its kind and human label, plus closed-vocabulary value→label pairs) and
// the daemon facets op (data-derived vocabularies for pos/var/status/source). Runs
// once at boot; the registry order follows the meta block's document order.
async function buildFieldRegistry() {
    const derived = await callDaemon({ op: "facets" });
    for (const meta of FILTER_META.querySelectorAll("[data-field]")) {
        registerField(fieldSpecFromMeta(meta, derived));
    }
}

// One registry spec from a .filter-meta div. A categorical field takes its values
// from the daemon (data-derived facets) when present, else from its own .chip rows
// (closed vocabulary); text carries its placeholder + Shavian flag; numeric is bare.
function fieldSpecFromMeta(meta, derived) {
    const { field, kind, label } = meta.dataset;
    if (kind === "categorical") {
        const entries = field in derived
            ? derived[field].map((value) => ({ value, label: value }))
            : harvestVocab(meta);
        return { field, kind, label, entries };
    }
    if (kind === "text") {
        return {
            field, kind, label,
            placeholder: meta.dataset.placeholder || "",
            shavian: meta.dataset.shavian === "true",
        };
    }
    return { field, kind, label };
}

// The value→label pairs a closed-vocabulary categorical field ships in its meta div,
// so those labels stay authored in one place (the CGI) rather than duplicated in JS.
function harvestVocab(meta) {
    return [...meta.querySelectorAll(".chip")].map((row) => ({
        value: row.querySelector("input").value,
        label: row.querySelector("span").textContent,
    }));
}

// ---- chip strip ----
// The strip shows one chip per active filter, in state.activeFilters order. Rebuilt
// wholesale on any structural change (add/remove/restore); a value edit updates its
// own chip label in place without a rebuild.
function renderChipStrip() {
    CHIP_STRIP.replaceChildren(...state.activeFilters.map(filterChip));
    syncAddFilterEnabled();
}

// Disable +Add when every registry field is already active — there is nothing left
// to add.
function syncAddFilterEnabled() {
    ADD_FILTER.disabled = state.activeFilters.length >= FIELD_REGISTRY.size;
}

// A chip for one active filter: a labelled trigger that opens the field's value
// picker, and an × to remove the filter. The chip wraps its picker popover so the
// popover overlays anchored to the chip (position:absolute inside position:relative).
function filterChip(entry) {
    const spec = fieldSpec(entry.field);
    const wrap = document.createElement("div");
    wrap.className = "filter-chip";
    wrap.dataset.field = entry.field;

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "chip-label";
    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    trigger.textContent = renderChipLabel(entry);

    const panel = buildPicker(spec, entry);
    trigger.addEventListener("click", () => togglePicker(panel, trigger));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-remove";
    remove.setAttribute("aria-label", `Remove ${spec.label} filter`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeFilter(entry));

    wrap.append(trigger, panel, remove);
    return wrap;
}

// The chip's one-line summary: "POS: NN1, AJ0" for a set categorical, "POS: any" when
// none picked; "Word: cat" for text, "Word: …" when blank; "Conf ≥ 60" for a set
// numeric, "Conf ≥ any" when blank. The label prefix is the field's human name.
function renderChipLabel(entry) {
    const spec = fieldSpec(entry.field);
    if (spec.kind === "categorical") {
        const labels = entry.value.map((value) => vocabLabel(spec, value));
        return `${spec.label}: ${labels.length ? labels.join(", ") : "any"}`;
    }
    if (spec.kind === "text") {
        return `${spec.label}: ${entry.value.trim() || "…"}`;
    }
    return `${spec.label} ${entry.value === null ? "any" : entry.value}`;
}

// The human label for a categorical value (its vocab label; falls back to the raw
// value for a data-derived value that is its own label).
function vocabLabel(spec, value) {
    const match = spec.entries.find((option) => option.value === value);
    return match ? match.label : value;
}

// Refresh one chip's label after its value changed, without rebuilding the strip.
function refreshChipLabel(entry) {
    const wrap = CHIP_STRIP.querySelector(`.filter-chip[data-field="${entry.field}"]`);
    if (wrap) {
        wrap.querySelector(".chip-label").textContent = renderChipLabel(entry);
    }
}

// Remove a filter: drop its entry, rebuild the strip (re-enabling its field in the
// +Add menu), and re-query. Removal is the only way a chip leaves the strip — an
// emptied categorical chip stays (its × is the explicit exit).
function removeFilter(entry) {
    state.activeFilters = state.activeFilters.filter((other) => other !== entry);
    renderChipStrip();
    requestFilterQuery();
}

// ---- value pickers ----
// Each chip's picker is a .facet-panel popover (reused from the former facet
// dropdowns) whose contents depend on the field kind. Categorical is the searchable
// checklist; text is an input plus regex/CI toggles; numeric is a number input. Only
// one picker (or the +Add menu) is open at a time — closePopovers closes them all.
function buildPicker(spec, entry) {
    const panel = document.createElement("div");
    panel.className = "facet-panel";
    panel.hidden = true;
    if (spec.kind === "categorical") {
        panel.append(categoricalPicker(spec, entry));
    } else if (spec.kind === "text") {
        panel.append(textPicker(spec, entry));
    } else {
        panel.append(numericPicker(spec, entry));
    }
    return panel;
}

// A categorical picker: the searchable checklist. Each value is a checkbox reflecting
// entry.value; toggling one rewrites entry.value (the ordered set of checked values),
// refreshes the chip label, and re-queries immediately. Searching hides non-matching
// rows without unchecking them.
function categoricalPicker(spec, entry) {
    const fragment = document.createDocumentFragment();

    const search = document.createElement("input");
    search.type = "text";
    search.className = "facet-search";
    search.placeholder = "filter…";
    search.setAttribute("aria-label", `Filter ${spec.label} values`);

    const list = document.createElement("div");
    list.className = "facet-list";
    const picked = new Set(entry.value);
    for (const { value, label } of spec.entries) {
        list.append(valueRow(spec.field, value, label, picked.has(value)));
    }

    list.addEventListener("change", () => {
        entry.value = [...list.querySelectorAll("input:checked")].map((box) => box.value);
        refreshChipLabel(entry);
        requestFilterQuery();
    });
    search.addEventListener("input", () => {
        const needle = search.value.trim().toLowerCase();
        for (const row of list.querySelectorAll(".chip")) {
            row.hidden = !row.textContent.toLowerCase().includes(needle);
        }
    });

    fragment.append(search, list);
    return fragment;
}

function valueRow(field, value, label, checked) {
    const wrap = document.createElement("label");
    wrap.className = "chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = value;
    input.checked = checked;
    const caption = document.createElement("span");
    caption.textContent = label;
    wrap.append(input, caption);
    return wrap;
}

// A text picker: a substring/regex input plus the regex and case-insensitive toggles.
// The input carries data-field so markInvalidRegex can flag THIS chip's box red. Typing
// re-queries debounced; toggling a flag re-queries immediately. The chip label tracks
// the input value live.
function textPicker(spec, entry) {
    const wrap = document.createElement("div");
    wrap.className = "text-picker";

    const box = document.createElement("input");
    box.type = "text";
    box.className = "text-filter";
    box.dataset.field = spec.field;
    box.placeholder = spec.placeholder;
    box.value = entry.value;
    box.spellcheck = false;
    if (spec.shavian) {
        box.classList.add("shavian-input");
    }
    box.addEventListener("input", () => {
        entry.value = box.value;
        refreshChipLabel(entry);
        requestFilterQueryDebounced();
    });

    wrap.append(
        box,
        flagToggle("regex", "Regex (re.search)", ".*", entry),
        flagToggle("ci", "Case-insensitive", "aA", entry),
    );
    return wrap;
}

// One mode toggle for a text picker (regex or case-insensitive): a checkbox reflecting
// entry.flags[flag]. Toggling rewrites the flag and re-queries immediately.
function flagToggle(flag, title, glyph, entry) {
    const label = document.createElement("label");
    label.className = "toggle";
    label.title = title;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = entry.flags[flag];
    input.addEventListener("change", () => {
        entry.flags[flag] = input.checked;
        requestFilterQuery();
    });
    const caption = document.createElement("span");
    caption.textContent = glyph;
    label.append(input, caption);
    return label;
}

// A numeric picker: a single number input. An empty box is null (no constraint);
// otherwise its Number. Editing re-queries debounced and tracks the chip label.
function numericPicker(spec, entry) {
    const wrap = document.createElement("div");
    wrap.className = "numeric-picker";
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "100";
    input.value = entry.value === null ? "" : String(entry.value);
    input.addEventListener("input", () => {
        entry.value = input.value.trim() === "" ? null : Number(input.value);
        refreshChipLabel(entry);
        requestFilterQueryDebounced();
    });
    wrap.append(input);
    return wrap;
}

// ---- +Add menu ----
// A popover listing the registry fields not yet active, in registry order. Picking one
// appends its blank chip and immediately opens that chip's picker. Reuses the
// .facet-panel overlay, anchored to the +Add button's wrapper.
function toggleAddMenu() {
    const existing = ADD_FILTER_WRAP.querySelector(".facet-panel");
    const opening = !existing || existing.hidden;
    closePopovers();
    if (!opening) {
        return;
    }
    const panel = buildAddMenu();
    ADD_FILTER_WRAP.append(panel);
    panel.hidden = false;
    ADD_FILTER.setAttribute("aria-expanded", "true");
}

function buildAddMenu() {
    const panel = document.createElement("div");
    panel.className = "facet-panel add-menu";
    const active = new Set(state.activeFilters.map((entry) => entry.field));
    for (const spec of FIELD_REGISTRY.values()) {
        if (active.has(spec.field)) {
            continue;
        }
        panel.append(addMenuItem(spec));
    }
    return panel;
}

function addMenuItem(spec) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "add-menu-item";
    item.textContent = spec.label;
    item.addEventListener("click", () => addFilter(spec.field));
    return item;
}

// Add a field to the strip: append its blank entry, rebuild the strip, then open the
// new chip's picker so the user picks a value straightaway. No query yet — a blank
// entry constrains nothing, so the signature guard would skip it regardless.
function addFilter(field) {
    const entry = blankEntry(field);
    state.activeFilters.push(entry);
    renderChipStrip();
    closePopovers();
    const wrap = CHIP_STRIP.querySelector(`.filter-chip[data-field="${field}"]`);
    const trigger = wrap.querySelector(".chip-label");
    togglePicker(wrap.querySelector(".facet-panel"), trigger);
}

// ---- popover management ----
// Only one popover (a chip picker or the +Add menu) is open at a time. Opening a chip
// picker focuses its first input so the keyboard user types straight in.
function togglePicker(panel, trigger) {
    const opening = panel.hidden;
    closePopovers();
    if (!opening) {
        return;
    }
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    const focusable = panel.querySelector("input, .facet-search");
    if (focusable) {
        focusable.focus();
    }
}

// Close every open popover: the chip pickers (kept in the DOM) and the +Add menu
// (removed, since it is rebuilt each open to reflect the current inactive set). Their
// triggers' aria-expanded is reset.
function closePopovers() {
    for (const panel of CHIP_STRIP.querySelectorAll(".facet-panel:not([hidden])")) {
        panel.hidden = true;
        panel.previousElementSibling.setAttribute("aria-expanded", "false");
    }
    const addMenu = ADD_FILTER_WRAP.querySelector(".facet-panel");
    if (addMenu) {
        addMenu.remove();
        ADD_FILTER.setAttribute("aria-expanded", "false");
    }
}

// Tap/click outside any open popover closes it (touch-friendly: no hover involved);
// Esc closes it too. A click on a chip trigger or the +Add button toggles via its own
// handler, so those are excluded here.
document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".filter-chip") && !event.target.closest(".add-filter-wrap")) {
        closePopovers();
    }
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closePopovers();
    }
});

// Restore a saved session's active filters, migrating an old session that persisted
// only the daemon `filters` dict (pre-chips) via the inverse map. Returns true if it
// seeded any chips (so boot skips the empty-strip render).
function restoreSession(stored) {
    if (Array.isArray(stored.activeFilters)) {
        restoreActiveFilters(stored.activeFilters);
        return true;
    }
    if (stored.filters) {
        restoreActiveFilters(activeFiltersFromDict(stored.filters));
        return true;
    }
    return false;
}

// Boot: build the field registry (labels + closed vocabularies from the page's
// .filter-meta block, data-derived values from the daemon facets op), then resume the
// saved session (active filters + column sort + anchor) if one exists — migrating an
// old pre-chips session — else start with no chips and a plain first query in the
// review order (highest confidence first).
async function boot() {
    buildCheatsheet();
    collapseFiltersOnNarrow();
    await buildFieldRegistry();
    const stored = loadSession();
    const restored = stored ? restoreSession(stored) : false;
    if (!restored) {
        renderChipStrip();
    }
    if (stored) {
        state.columnSort = stored.columnSort || null;
    }
    syncSortIndicators();
    return runQuery(0, stored ? stored.anchor : null);
}

boot().catch((error) => showToast(error.message, true));
