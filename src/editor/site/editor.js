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
// Capped at the daemon's MAX_LIMIT (500).
const PAGE_LIMIT = 500;
const ACCEPTED_STATUS = "sanctioned";

// The daemon's patch_state vocabulary. Single source of truth: src/editor/
// overlay.py (PATCH_STATE_*) — a rename there MUST be mirrored here. Manual-ness
// is NOT a state: a manual record carries `manual: true` plus a real verdict.
const PATCH_STATE = {
    UNREVIEWED: "unreviewed",
    ACCEPTED: "accepted",
    EDITED: "edited",
    DIRTY: "dirty",
    DROPPED: "dropped",
    FLAGGED: "flagged",
    ORPHANED: "orphaned",
};

// A statement about a GROUP, never a record's patch_state (the daemon's REVIEW_MIXED).
const GROUP_MIXED = "mixed";

// Mirrors src/editor/overlay.py (ORPHAN_LOST_ACCEPT / ORPHAN_RESURFACED_DROP); keep in sync.
const ORPHAN_KIND = {
    LOST_ACCEPT: "lost-accept",
    RESURFACED_DROP: "resurfaced-drop",
};

const SESSION_KEY = "shaw-spell.editor.session";
// The splitter position is a 0..1 fraction of the workbench width, so the split
// scales with the window.
const SPLIT_FRACTION_KEY = "shaw-spell.editor.splitter.ledger";
const LEDGER_COLLAPSED_KEY = "shaw-spell.editor.ledger.collapsed";
// Persisted apart from SESSION_KEY so section prefs stick across record
// selections AND page reloads.
const SECTION_PREFS_KEY = "shaw-spell.editor.sections";
// Definitions default closed: open, they push related below the fold.
const SECTION_DEFAULTS = { definitions: false, related: true };
// In-memory shadow so the prefs survive when browser storage is unavailable —
// the ONLY graceful fallback here; everything else fails loud.
let sectionPrefsCache = null;

function loadSectionPrefs() {
    if (sectionPrefsCache) {
        return sectionPrefsCache;
    }
    sectionPrefsCache = { ...SECTION_DEFAULTS };
    try {
        const raw = localStorage.getItem(SECTION_PREFS_KEY);
        if (raw) {
            Object.assign(sectionPrefsCache, JSON.parse(raw));
        }
    } catch (error) {
        // Storage unreadable (disabled/quota): fall back to in-memory defaults.
    }
    return sectionPrefsCache;
}

function sectionExpanded(id) {
    const prefs = loadSectionPrefs();
    return id in prefs ? prefs[id] : Boolean(SECTION_DEFAULTS[id]);
}

function setSectionExpanded(id, open) {
    const prefs = loadSectionPrefs();
    prefs[id] = open;
    try {
        localStorage.setItem(SECTION_PREFS_KEY, JSON.stringify(prefs));
    } catch (error) {
        // Storage unwritable: the in-memory cache still carries the preference for
        // this page life, so record-switches within the session honour it.
    }
}
const DEFAULT_QUERY_SORT = "confidence_desc";
const RRP_VAR = "RRP";

// The edit surface. status is NOT here — read-only, set only by the verdict actions.
const EDITABLE_FIELDS = ["word", "shaw", "var", "ipa", "freq"];

// A closed vocabulary mirroring src/tools/dialect_mergers.py; additive, empty == canonical.
const MERGERS = [
    ["trap-bath", "TRAP–BATH"],
    ["cot-caught", "COT–CAUGHT"],
    ["lot-palm", "LOT–PALM"],
];

// The within-accent free-variation marker (additive boolean, absent == canonical).
const VARIANT_LABEL = "variant";

// Display label only — the on-disk field name (`variant`) and the daemon facet
// value key stay unchanged.
const VARIATION_OTHER_LABEL = "other";

const DEFINITION_LABEL = "def";

// Prefix for the basis.orig_var provenance pill ("was GenAm") — the var a
// pipeline transform changed this record's var FROM.
const ORIG_VAR_PREFIX = "was ";

const INFO_FIELD = "info";

const NOVELTY_LABELS = new Map([
    ["new-word", "new word"],
    ["new-spelling", "new spelling"],
    ["new-pos", "new POS"],
]);

const ORPHAN_KIND_TAGS = new Map([
    [ORPHAN_KIND.LOST_ACCEPT, {
        label: "accept-orphan",
        title: "a sanction whose record vanished upstream — re-anchor or clear it",
        reason: "A sanction whose record vanished upstream.",
        action: "Re-anchor it to the current record, or clear the patch.",
    }],
    [ORPHAN_KIND.RESURFACED_DROP, {
        label: "drop — resurfaced",
        title: "a drop the basis evaded: the same word+pos+shaw is back under a different var, so the suppressed record returned — re-suppress it",
        reason: "A drop the basis evaded: the same word + pos + shaw returned under a different var, so the suppressed record is back.",
        action: "Re-suppress it.",
    }],
]);

const REFERENCES = [
    ["Wiktionary", "https://en.wiktionary.org/wiki/{word}"],
    ["Cambridge", "https://dictionary.cambridge.org/dictionary/english/{word}"],
    ["Merriam-Webster", "https://www.merriam-webster.com/dictionary/{word}"],
    ["OED", "https://www.oed.com/search/dictionary/?scope=Entries&q={word}"],
];

// CLAWS C5 part-of-speech tags → plain-English tooltips (the BNC tagset the
// ReadLex data carries).
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

// A portmanteau tag ("PNP+VHD") composes from its parts; an unknown tag falls
// back to its own code so the tooltip never lies about coverage it lacks.
function posTitle(pos) {
    if (!pos) {
        return "";
    }
    return pos
        .split("+")
        .map((part) => `${part} — ${C5_TAGS[part] ?? part}`)
        .join(" + ");
}

function posCell(className, pos) {
    const span = cell(className, pos);
    span.title = posTitle(pos);
    return span;
}

const FILTER_FORM = document.getElementById("filters");
const CHIP_STRIP = document.getElementById("chipStrip");
const SEARCH_INLINE = document.getElementById("searchInline");
const ADD_FILTER = document.getElementById("addFilter");
const ADD_FILTER_WRAP = document.getElementById("addFilterWrap");
const FILTER_META = document.getElementById("filterMeta");
const FILTERS_TOGGLE = document.getElementById("filtersToggle");
const REFRESH_RESULTS = document.getElementById("refreshResults");
const PATCH_COUNTS = document.getElementById("patchCounts");
const LEDGER = document.getElementById("ledgerList");
const LEDGER_HEAD = document.getElementById("ledgerHead");
const LEDGER_FOOT = document.getElementById("ledgerFoot");
const SELECT_BAR = document.getElementById("selectBar");
const SELECT_BAR_COUNT = document.getElementById("selectBarCount");
const SELECT_BAR_DONE = document.getElementById("selectBarDone");
const DETAIL = document.getElementById("detail");
const TOAST = document.getElementById("toast");
const WORKBENCH = document.getElementById("workbench");
const LEDGER_PANE = document.getElementById("ledger");
const SPLITTER = document.getElementById("workbenchSplitter");
const LEDGER_RAIL = document.getElementById("ledgerRail");
const DRAWER_TOGGLE = document.getElementById("drawerToggle");
const HELP_TOGGLE = document.getElementById("helpToggle");
const MASTHEAD_MENU = document.getElementById("mastheadMenu");
const MASTHEAD_MENU_PANEL = document.getElementById("mastheadMenuPanel");
const NEW_ENTRY = document.getElementById("newEntry");
const COMMIT_DECISIONS = document.getElementById("commitDecisions");
const DRAWER_BACKDROP = document.getElementById("drawerBackdrop");
const CHEATSHEET = document.getElementById("cheatsheet");
const CREATE_MODAL = document.getElementById("createModal");
const PACING = document.getElementById("pacing");

const state = {
    records: [],
    total: 0,
    offset: 0,
    limit: PAGE_LIMIT,
    filters: {},
    // The editable chip model; state.filters is its materialised projection
    // (filtersFromState). Entries are shaped by their field's kind (see blankEntry).
    activeFilters: [],
    // {key, dir} or null (= DEFAULT_QUERY_SORT); sent to the daemon, which orders
    // the whole filtered corpus.
    columnSort: null,
    // The related table's client-side sort, {key, dir} or null (default chain).
    // The focused row stays pinned to the top regardless.
    relatedSort: null,
    selected: -1,
    mainContext: null,
    // The open create/clone modal's editor context, or null. Its presence is the
    // modal-open flag: while set the modal owns the keyboard and review verdicts
    // are suppressed.
    modalEditor: null,
    // Group selection: anchor keys of the picked rows. The focused row
    // (state.selected) is independent — it stays the review cursor.
    multi: new Set(),
    // The last row toggled by pointer, so shift-click can range-extend from it.
    lastToggledKey: null,
    // The group whose HEADER the review cursor sits on, or null when it is on a
    // record row. Carries the cursor's position AND the provenance of the
    // group-as-unit selection: stepping off the header dissolves the selection the
    // landing created, but any hand mutation of the pick forfeits the claim, so
    // stepping never dissolves an owner-made selection.
    cursorGroupKey: null,
    // Touch multi-select mode (long-press to enter): a plain tap toggles rather
    // than reviews.
    touchMulti: false,
    // The DAEMON owns grouping and pagination: entries serves whole groups, never
    // split across pages; `groups` mirrors that partition over state.records as
    // {key, size} runs (the key is the daemon's, opaque here). groupsExpanded is
    // transient view state, cleared with the working set.
    groups: [],
    groupsExpanded: new Set(),
    // Monotonic token for the related-entries fetch: only the LATEST request may
    // render, so a slow stale response never paints over the current record.
    relatedGeneration: 0,

    // Monotonic token for the definitions fetch, mirroring relatedGeneration.
    definitionsGeneration: 0,

    // The open definition-correction modal's context, or null. A SEPARATE modal
    // from the record editor: it must NOT set modalEditor (which would route
    // record-editor verdict keys). While set it owns the keyboard and suppresses
    // workbench verdicts.
    definitionModal: null,
};

const LONG_PRESS_MS = 500;
const LONG_PRESS_SLOP_PX = 10;

const session = {
    startedAt: Date.now(),
    decisions: 0,
    undoStack: [],
};

async function callDaemon(request) {
    const response = await fetch(location.pathname, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
    });
    if (response.status === 401) {
        // Session lost mid-session: fail loud and send the user back to the front gate.
        location.reload();
        throw new Error("session expired — signing in again");
    }
    const payload = await response.json();
    if (payload.error) {
        throw new Error(payload.error);
    }
    return payload;
}

// AUTHOR (the client-side const) is advisory — the CGI overrides meta.author with
// the session handle server-side; this only feeds the masthead display.
async function initAuth() {
    const whoami = document.getElementById("whoami");
    const logout = document.getElementById("logout");
    try {
        const resp = await fetch(location.pathname + "?api=me", {
            credentials: "include",
        });
        if (resp.ok) {
            const data = await resp.json();
            if (whoami && data.handle) {
                whoami.textContent = data.handle;
            }
        }
    } catch (error) {
        // The front gate already guarantees a session for this page; a failed
        // me() only costs the handle label, so don't block boot on it.
    }
    if (logout) {
        logout.addEventListener("click", async () => {
            try {
                await fetch(location.pathname + "?api=logout", {
                    method: "POST",
                    credentials: "include",
                });
            } finally {
                location.reload();
            }
        });
    }
}

// ---- filter field registry ----
// Single source of truth for the filter fields, populated at boot from the CGI's
// .filter-meta block (labels + closed vocabularies) and the daemon facets op.
// Each entry is {field, kind, label, ...}:
//   categorical — entries [{value,label}], value is a string[]
//   text        — value is a scalar string, flags {regex,ci}
//   numeric     — value is a Number|null
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

// Both flags start false so filtersFromState omits them and the daemon applies its
// own defaults (word case-insensitive, shaw case-sensitive) — matching the former
// form's unchecked checkboxes, which the round-trip invariant depends on.
function newTextFlags() {
    return { regex: false, ci: false };
}

function blankEntry(field) {
    const spec = fieldSpec(field);
    if (spec.kind === "categorical") {
        return { field, value: [], mode: "any" };
    }
    if (spec.kind === "text") {
        return { field, value: "", flags: newTextFlags() };
    }
    return { field, value: null };
}

// The always-shown fields, marked data-pinned in the CGI's filter-meta: seeded at
// boot, never offered by +Add, not removable.
function pinnedFields() {
    return [...FIELD_REGISTRY.values()]
        .filter((spec) => spec.pinned)
        .map((spec) => spec.field);
}

function isPinned(field) {
    return fieldSpec(field).pinned;
}

function withPinnedFilters(activeFilters) {
    const byField = new Map(activeFilters.map((entry) => [entry.field, entry]));
    const pinned = pinnedFields().map(
        (field) => byField.get(field) || blankEntry(field));
    const pinnedSet = new Set(pinnedFields());
    const rest = activeFilters.filter((entry) => !pinnedSet.has(entry.field));
    return [...pinned, ...rest];
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
                // ANY stays a bare list (back-compat); ALL sends the explicit
                // {values, mode} object the daemon reads as a superset test.
                filters[entry.field] = entry.mode === "all"
                    ? { values: [...entry.value], mode: "all" }
                    : [...entry.value];
            }
        } else if (spec.field === "search") {
            // The combined Search box is ALWAYS regex + case-insensitive (the
            // daemon's `search` filter); no companion flags, no toggles.
            const trimmed = entry.value.trim();
            if (trimmed) {
                filters.search = trimmed;
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

// The Review facet speaks VERDICTS but the daemon's _matches_review compares raw
// patch_state: each selected verdict fans out to every patch_state whose verdict it
// is, derived from verdictState so the two can never disagree.
function reviewStatesForVerdict(verdict) {
    const states = Object.values(PATCH_STATE).filter(
        (patchState) => verdictState({ patch_state: patchState }) === verdict);
    if (!states.length) {
        throw new Error(`not a review verdict: ${verdict}`);
    }
    return states;
}

// The daemon-facing filters dict: Review verdicts expanded to raw patch_states.
// The group-level "mixed" value is no verdict; it passes through for the daemon's
// per-group leg (REVIEW_MIXED).
function daemonFilters(filters) {
    if (!filters.review) {
        return filters;
    }
    if (!Array.isArray(filters.review)) {
        throw new Error("review filter must be a value list");
    }
    return { ...filters, review: filters.review.flatMap((value) =>
        value === GROUP_MIXED ? [value] : reviewStatesForVerdict(value)) };
}

// The inverse map: a saved filters dict → an ordered activeFilters array, so an old
// session (which persisted only `filters`) migrates to chips.
function activeFiltersFromDict(filters) {
    const active = [];
    for (const spec of FIELD_REGISTRY.values()) {
        const raw = filters[spec.field];
        if (spec.kind === "categorical") {
            if (Array.isArray(raw) && raw.length) {
                active.push({ field: spec.field, value: [...raw], mode: "any" });
            } else if (raw && Array.isArray(raw.values) && raw.values.length) {
                active.push({
                    field: spec.field,
                    value: [...raw.values],
                    mode: raw.mode === "all" ? "all" : "any",
                });
            }
        } else if (spec.field === "search") {
            if (typeof raw === "string" && raw.trim()) {
                active.push({ field: spec.field, value: raw, flags: newTextFlags() });
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

// Review values collapse to their verdict: a session saved when edited/dirty were
// their own Review chips migrates to the verdict chips that now cover them.
function restoredFacetValues(field, values) {
    if (field !== "review") {
        return [...values];
    }
    return [...new Set(values.map((value) => verdictState({ patch_state: value })))];
}

// Flag the text-filter chips whose regex the daemon could not compile (named in
// invalid_regex); the query still returned (it simply matched nothing).
function markInvalidRegex(invalidFields) {
    const invalid = new Set(invalidFields);
    for (const root of [CHIP_STRIP, SEARCH_INLINE]) {
        for (const input of root.querySelectorAll(".text-filter")) {
            input.classList.toggle("invalid", invalid.has(input.dataset.field));
        }
    }
}

// Re-run the filter: materialise a fresh working set. This is the ONLY point at
// which the list re-syncs to latest state. preferredAnchor lands the selection on
// that entry, or its nearest neighbour if it fell out of the set.
async function runQuery(offset = 0, preferredAnchor = null) {
    state.filters = filtersFromState();
    state.offset = offset;
    const result = await callDaemon({
        op: "entries",
        filters: daemonFilters(state.filters),
        sort: daemonSort(),
        offset,
        limit: state.limit,
    });
    state.groups = result.groups.map(
        (group) => ({ key: group.key, size: group.records.length }));
    state.records = result.groups.flatMap((group) => group.records);
    state.total = result.total;
    markInvalidRegex(result.invalid_regex || []);
    // The old selection referred to the replaced working set; select-all is scoped
    // to the loaded page.
    state.multi.clear();
    state.lastToggledKey = null;
    state.touchMulti = false;
    state.groupsExpanded.clear();
    materialisedSignature = querySignature(state.filters);
    renderLedger();
    renderFoot();
    select(landingIndex(preferredAnchor));
    syncSelectBar();
    refreshPacing();
}

// Where to land after a query: the exact anchor, else the first entry sorting at or
// after it in natural order — rather than jumping to the top.
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

// Mirrors the daemon's natural-key tiebreak (word.lower, pos, shaw, var).
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

// The intrinsic fields the owner overrode when they accepted this record — the keys
// of the accept patch's `changes` diff. A field's PRESENCE in changes is the
// override, whatever its value, so an emptied field (e.g. mergers: []) marks.
// Authored rows and drop/flag/unreviewed yield the empty set.
function overriddenFields(record) {
    const patch = record.patch;
    if (!patch || patch.op !== "accept" || !patch.anchor || !patch.changes) {
        return new Set();
    }
    return new Set(Object.keys(patch.changes));
}

// The ledger renders the DAEMON's group partition — the client never computes
// grouping. A group of ONE renders byte-identical to the flat row (the N=1
// invariant); 2+ renders a disclosure header previewing the export-winner.
function renderLedger() {
    LEDGER.replaceChildren();
    for (const group of ledgerGroups()) {
        if (group.members.length === 1) {
            LEDGER.append(ledgerRow(group.members[0].record, group.members[0].index));
            continue;
        }
        LEDGER.append(groupRow(group));
        if (state.groupsExpanded.has(group.key)) {
            const children = groupChildRows(group);
            children[0].classList.add("group-child-first");
            children[children.length - 1].classList.add("group-child-last");
            LEDGER.append(...children);
        }
    }
}

function groupChildRows(group) {
    return group.members.map(({ record, index }) => ledgerRow(record, index, true));
}

// A record's VERDICT — collapses the two DECORATION states onto the verdict they
// decorate: `edited` IS an accept, `dirty` IS unreviewed. Every state-semantic
// reader routes through this; raw patch_state is read only where the decoration
// itself is meant.
function verdictState(record) {
    switch (record.patch_state) {
        case PATCH_STATE.EDITED:
            return PATCH_STATE.ACCEPTED;
        case PATCH_STATE.DIRTY:
            return PATCH_STATE.UNREVIEWED;
        default:
            return record.patch_state;
    }
}

// The export var-hierarchy: RRP > RSSB > GenAm, any other var below all listed.
// Mirrors src/tools/collapse_identical_dialects.py (PRECEDENCE / UNKNOWN_RANK).
const VAR_PRECEDENCE = { RRP: 0, RSSB: 1, GenAm: 2 };
const VAR_UNKNOWN_RANK = Object.keys(VAR_PRECEDENCE).length;
function varRank(value) {
    const rank = VAR_PRECEDENCE[value];
    return rank === undefined ? VAR_UNKNOWN_RANK : rank;
}

// The daemon's partition (state.groups) hydrated with member records and their
// working-set indices. Fails loud if partition and working set have drifted apart.
function ledgerGroups() {
    const groups = [];
    let index = 0;
    for (const { key, size } of state.groups) {
        const members = [];
        for (let member = 0; member < size; member += 1, index += 1) {
            members.push({ record: state.records[index], index });
        }
        groups.push({ key, members });
    }
    if (index !== state.records.length) {
        throw new Error("group partition out of step with the working set.");
    }
    return groups;
}

function groupOfIndex(index) {
    if (index < 0) {
        return null;
    }
    return ledgerGroups().find(
        (group) => group.members.some((member) => member.index === index)) || null;
}

// Shrink the owning {key, size} run so the partition stays aligned with
// state.records — call BEFORE splicing the record out.
function shrinkGroupAt(index) {
    let end = 0;
    for (let at = 0; at < state.groups.length; at += 1) {
        end += state.groups[at].size;
        if (index < end) {
            state.groups[at].size -= 1;
            if (state.groups[at].size === 0) {
                state.groupsExpanded.delete(state.groups[at].key);
                state.groups.splice(at, 1);
            }
            return;
        }
    }
    throw new Error("removed record index outside the group partition.");
}

// The export-winner among a group's members: the lowest var rank. The group is
// Latin+Shaw+variation-set uniform by construction, so only var distinguishes; ties
// keep the first (best-under-active-sort) member.
function exportWinner(members) {
    return members.reduce((best, entry) =>
        varRank(entry.record.var) < varRank(best.record.var) ? entry : best);
}

// Guards session restore against a retired column key.
const SORTABLE_COLUMNS = new Set(["state", "word", "shaw", "var", "confidence", "freq", "pos"]);

function daemonSort() {
    return state.columnSort
        ? `${state.columnSort.key}_${state.columnSort.dir}`
        : DEFAULT_QUERY_SORT;
}

function onSortHeaderClick(key) {
    if (state.columnSort && state.columnSort.key === key && state.columnSort.dir === "asc") {
        state.columnSort = { key, dir: "desc" };
    } else {
        state.columnSort = { key, dir: "asc" };
    }
    syncSortIndicators();
    const focusedAnchor = state.records[state.selected]
        ? state.records[state.selected].anchor
        : null;
    // Direct runQuery, not requestFilterQuery: the sort is not in the query signature,
    // so the signature guard would wrongly skip a sort-only re-pull.
    runQuery(0, focusedAnchor).catch((error) => showToast(error.message, true));
}

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

// The seven data cells, shared by flat/child rows and the group header (which
// shows the export-winner's cells). Every row prepends the two gutter tracks
// (chevron, count) itself: a header fills them, flat and child rows leave them
// blank, so all rows share one template.
function ledgerCells(record, verdict = verdictState(record)) {
    return [
        stampCell(record, verdict),
        cell("col-word", record.word),
        cell("col-shaw", record.shaw),
        varCell(record.var),
        confidenceCell(record.confidence),
        freqCell(record.freq),
        posCell("col-pos", record.pos),
    ];
}

// Monochrome text glyphs ONLY, inheriting currentColor — colour is the verdict's
// own channel, so no emoji.
const STAMP_GLYPHS = new Map([
    [PATCH_STATE.UNREVIEWED, "?"],
    [PATCH_STATE.ACCEPTED, "✓"],
    [PATCH_STATE.DROPPED, "✕"],
    [PATCH_STATE.FLAGGED, "⚑"],
    [GROUP_MIXED, "…"],
]);

// An orphaned patch keeps its op's glyph; the orphaned YELLOW alone says "this no
// longer resolves" — shape = what was decided, colour = whether it still holds.
// (Flags never orphan — see overlay._orphan_kind.)
const ORPHAN_GLYPHS = new Map([
    [ORPHAN_KIND.LOST_ACCEPT, STAMP_GLYPHS.get(PATCH_STATE.ACCEPTED)],
    [ORPHAN_KIND.RESURFACED_DROP, STAMP_GLYPHS.get(PATCH_STATE.DROPPED)],
]);

function stampCell(record, verdict) {
    const orphaned = verdict === PATCH_STATE.ORPHANED;
    const glyph = orphaned
        ? ORPHAN_GLYPHS.get(record.orphan_kind)
        : STAMP_GLYPHS.get(verdict);
    if (!glyph) {
        throw new Error(`no stamp glyph for verdict: ${verdict} (orphan_kind: ${record.orphan_kind})`);
    }
    const marked = Boolean(record.manual) && verdict !== GROUP_MIXED;
    const stamp = cell(`stamp col-state ${verdict}`, marked ? `✎ ${glyph}` : glyph);
    const words = orphaned
        ? `orphaned — ${ORPHAN_KIND_TAGS.get(record.orphan_kind).title}`
        : verdict;
    stamp.title = marked ? `manual entry · ${words}` : words;
    return stamp;
}

function ledgerRow(record, index, isChild = false) {
    const row = document.createElement("li");
    row.className = `ledger-row state-${verdictState(record)}`;
    if (isChild) {
        row.classList.add("group-child");
    }
    row.dataset.index = String(index);
    // The anchor key carries NUL separators (not attribute-safe), so it rides on a
    // JS property.
    row._anchorKey = anchorKey(record.anchor);
    row.append(cell("col-chevron", ""), cell("col-count", ""), ...ledgerCells(record));
    bindLongPress(row, record);
    row.addEventListener("click", (event) => onRowClick(record, index, event));
    return row;
}

// A collapsed group HEADER: NOT a state.records row — no data-index, addressed by
// _groupKey — but a selection target: clicking it picks the WHOLE group, while the
// chevron toggles expansion.
function groupRow(group) {
    const winner = exportWinner(group.members).record;
    // The header stamps a shared verdict only when EVERY member shares it — it must
    // never advertise one member's verdict as the group's; disagreement stamps
    // GROUP_MIXED.
    const consensus = verdictConsensus(group.members.map((member) => member.record));
    const verdict = consensus.uniform ? consensus.value : GROUP_MIXED;
    const li = document.createElement("li");
    li.className = `ledger-row ledger-group-header state-${verdict}`;
    // The group key carries NUL separators (not attribute-safe), so it rides on a JS
    // property — read back directly, never queried by selector.
    li._groupKey = group.key;
    const expanded = state.groupsExpanded.has(group.key);
    if (expanded) {
        li.classList.add("expanded");
        bindParentGutter(li);
    }

    li.append(groupDisclosure(group, expanded), groupCountCell(group), ...ledgerCells(winner, verdict));
    li.addEventListener("click", (event) => onGroupHeaderClick(group, event));
    return li;
}

// The indent strip beside an expanded group's children belongs to the HEADER, but
// the children are later SIBLINGS in the flat <li> run — CSS cannot reach them from
// the header's :hover — so the hover walks the child rows and toggles the class the
// strip's wash keys on (.parent-hover; the selected twin is painted by
// paintLedgerSelection).
function bindParentGutter(headerRow) {
    headerRow.addEventListener("mouseenter", () => setParentGutterHover(headerRow, true));
    headerRow.addEventListener("mouseleave", () => setParentGutterHover(headerRow, false));
}

function setParentGutterHover(headerRow, on) {
    for (let row = headerRow.nextElementSibling;
        row && row.classList.contains("group-child");
        row = row.nextElementSibling) {
        row.classList.toggle("parent-hover", on);
    }
}

// The chevron toggles expansion WITHOUT selecting (stopPropagation): the chevron
// drills down, the rest of the header selects/reviews.
function groupDisclosure(group, expanded) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "group-disclosure col-chevron";
    button.setAttribute("aria-expanded", String(expanded));
    button.setAttribute("aria-label", expanded ? "Collapse group" : "Expand group");
    const chevron = document.createElement("span");
    chevron.className = "chevron";
    chevron.setAttribute("aria-hidden", "true");
    button.append(chevron);
    button.addEventListener("click", (event) => {
        event.stopPropagation();
        toggleGroupExpanded(group.key);
    });
    return button;
}

function groupCountCell(group) {
    const total = group.members.length;
    return cell("col-count group-count", total > 99 ? "99+" : String(total));
}

function onGroupHeaderClick(group, event) {
    if (suppressNextClick) {
        suppressNextClick = false;
        return;
    }
    setDrawer(false);
    const toggle = state.touchMulti || event.metaKey || event.ctrlKey;
    selectWholeGroup(group, toggle);
}

// Pure view toggle — the full membership is already on the page, so no fetch; the
// selection keys on anchors and survives the re-render.
function toggleGroupExpanded(key) {
    if (!state.groupsExpanded.delete(key)) {
        state.groupsExpanded.add(key);
    }
    renderLedger();
    paintLedgerSelection();
}

// Select EVERY member's anchor, so a group verdict never silently leaves a sibling
// unreviewed (the export collapses the whole group).
function selectWholeGroup(group, toggle) {
    const anchors = group.members.map((member) => member.record.anchor);
    // A plain header-select lands the cursor ON the header; a toggle is a hand
    // mutation, which forfeits any header claim (see state.cursorGroupKey).
    state.cursorGroupKey = toggle ? null : group.key;
    if (!toggle) {
        state.multi.clear();
    }
    const allSelected = anchors.every((anchor) => state.multi.has(anchorKey(anchor)));
    for (const anchor of anchors) {
        const key = anchorKey(anchor);
        if (toggle && allSelected) {
            state.multi.delete(key);
        } else {
            state.multi.add(key);
        }
    }
    state.lastToggledKey = anchors.length ? anchorKey(anchors[anchors.length - 1]) : null;
    onSelectionChanged();
}

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

function reviewOnly(index) {
    state.multi.clear();
    state.lastToggledKey = anchorKey(state.records[index].anchor);
    select(index);
}

// Set when a long-press fires, to swallow the click the browser synthesises when
// the finger lifts (which would otherwise re-toggle the just-toggled row).
let suppressNextClick = false;

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

function varCell(value) {
    const span = cell("col-var", value);
    if (value === RRP_VAR) {
        span.classList.add("var-default");
    }
    return span;
}

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

// Pagination is GROUP-denominated (the daemon pages by group): the summary and the
// offsets count groups, not records.
function renderFoot() {
    LEDGER_FOOT.replaceChildren();
    const shown = state.groups.length;
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
    button.addEventListener("click", () =>
        runQuery(Math.max(0, targetOffset)).catch((error) => showToast(error.message, true)));
    return button;
}

function select(index) {
    autoSaveMainEdit();
    state.selected = index;
    // A record landing takes the cursor off any group header it sat on.
    state.cursorGroupKey = null;
    // Make the cursor visible: a landing inside a COLLAPSED group expands it so its
    // child row shows. Only when no multi-selection is live — a group selection
    // deliberately keeps the fold as-is.
    if (!state.multi.size) {
        revealSelectedInGroup(index);
    }
    paintLedgerSelection();
    // With a live multi-selection the card shows that GROUP, not the focused record;
    // moving the cursor only scrolls the row into view.
    if (state.multi.size) {
        scrollRowIntoView(index);
    } else if (index < 0) {
        renderEmptyDetail();
    } else {
        scrollRowIntoView(index);
        renderGroupEditor(selectedGroup());
    }
    saveSession();
}

function rowByIndex(index) {
    return index >= 0
        ? LEDGER.querySelector(`.ledger-row[data-index="${index}"]`)
        : null;
}

function scrollRowIntoView(index) {
    const active = rowByIndex(index);
    if (active) {
        active.scrollIntoView({ block: "nearest" });
    }
}

// The header counterpart of rowByIndex. The key carries NUL separators (not
// attribute-safe) and rides on the _groupKey JS property, so it cannot be
// querySelected — scan the rows instead (one page, cheap).
function rowByGroupKey(key) {
    for (const row of LEDGER.querySelectorAll(".ledger-row")) {
        if (row._groupKey === key) {
            return row;
        }
    }
    return null;
}

function revealSelectedInGroup(index) {
    const group = groupOfIndex(index);
    if (!group || group.members.length < 2 || state.groupsExpanded.has(group.key)) {
        return;
    }
    state.groupsExpanded.add(group.key);
    renderLedger();
    // No repaint here: the caller (select) runs paintLedgerSelection right after.
}

function renderEmptyDetail() {
    const message = document.createElement("p");
    message.className = "detail-empty";
    message.textContent = state.total
        ? "Select an entry to review it."
        : "No entries match these filters.";
    DETAIL.replaceChildren(message);
}

// ---- group selection ----
// Selection is a MAIN-context concept — it acts on the workbench. While an edit
// modal owns the screen its verdicts act on the modal record (activeContext()), so
// the workbench selection is dormant: a verdict never fans out to the rows behind
// the backdrop.
function toggleSelection(anchor) {
    const key = anchorKey(anchor);
    if (state.multi.has(key)) {
        state.multi.delete(key);
    } else {
        state.multi.add(key);
    }
    state.lastToggledKey = key;
    // A hand mutation of the pick forfeits any header claim (see state.cursorGroupKey).
    state.cursorGroupKey = null;
    onSelectionChanged();
}

// Shift-click range: always selects (never deselects) — the triage move. If the
// anchor row has since gone (a re-run replaced the set), toggle just the clicked row.
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
    state.cursorGroupKey = null;
    onSelectionChanged();
}

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
    state.cursorGroupKey = null;
    onSelectionChanged();
}

function clearSelection() {
    state.multi.clear();
    state.lastToggledKey = null;
    state.touchMulti = false;
    state.cursorGroupKey = null;
    onSelectionChanged();
}

function enterTouchMulti() {
    state.touchMulti = true;
}

function onSelectionChanged() {
    // A selection change can swap the detail card without routing through select();
    // flush an unsaved edit on the record leaving the card first.
    autoSaveMainEdit();
    paintLedgerSelection();
    const group = selectedGroup();
    if (group.length) {
        renderGroupEditor(group);
    } else {
        renderEmptyDetail();
    }
}

// The SINGLE source of truth for ledger row highlighting. A multi-pick wins over
// the cursor (mirroring selectedGroup()). A group HEADER joins only when its WHOLE
// membership is selected — a partial child-pick leaves the header unlit. The same
// pass carries a selected header's wash onto its children's indent strip
// (.parent-selected): children directly follow their header in the flat run, so the
// sweep just remembers whether the last header lit.
function paintLedgerSelection() {
    const multi = state.multi.size > 0;
    // Hydrate the partition ONCE per paint (this runs per keystroke/step).
    const groupsByKey = new Map(
        ledgerGroups().map((group) => [group.key, group]));
    let headerSelected = false;
    for (const row of LEDGER.querySelectorAll(".ledger-row")) {
        let on;
        if (multi) {
            on = row._groupKey
                ? isGroupFullySelected(groupsByKey.get(row._groupKey))
                : Boolean(row._anchorKey) && state.multi.has(row._anchorKey);
        } else {
            on = rowIsCursor(row, groupsByKey);
        }
        row.classList.toggle("selected", on);
        if (row.classList.contains("group-child")) {
            row.classList.toggle("parent-selected", headerSelected);
        } else {
            headerSelected = Boolean(row._groupKey) && on;
        }
    }
    syncSelectBar();
}

// Whether a row carries the review cursor: a record row by index; a header when the
// cursor sits ON it (cursorGroupKey), or a COLLAPSED header when the cursor's record
// is folded inside. While a header holds the claim its members' rows do NOT light.
function rowIsCursor(row, groupsByKey) {
    if (state.selected < 0) {
        return false;
    }
    if (row._anchorKey) {
        return state.cursorGroupKey === null
            && Number(row.dataset.index) === state.selected;
    }
    if (row._groupKey) {
        if (row._groupKey === state.cursorGroupKey) {
            return true;
        }
        const group = groupsByKey.get(row._groupKey);
        return Boolean(group)
            && group.members.some((member) => member.index === state.selected)
            && !state.groupsExpanded.has(row._groupKey);
    }
    return false;
}

function isGroupFullySelected(group) {
    return Boolean(group) && group.members.every(
        (member) => state.multi.has(anchorKey(member.record.anchor)));
}

function syncSelectBar() {
    SELECT_BAR.hidden = !state.touchMulti;
    const count = state.multi.size;
    SELECT_BAR_COUNT.textContent = count === 1 ? "1 selected" : `${count} selected`;
}

// A record editor's context: the surface a GROUP of records is edited on. Owns its
// harvest `root`, an id `prefix` (detail "field-", modal "modal-" so the two never
// collide), a per-context `editing` flag, and the `group`/`mode` it renders.
// activeContext() routes the review flow to whichever owns the screen.
function makeEditorContext({ scope, root, prefix, group, mode }) {
    return { scope, root, prefix, group, mode };
}

function contextRecord(ctx) {
    return ctx?.group?.[0] ?? null;
}

// The open modal's context when one owns the screen, else the detail context — so a
// stray keypress never harvests or acts on the record behind the backdrop.
function activeContext() {
    return state.modalEditor ?? state.mainContext;
}

// The SINGLE editor renderer for the detail panel and the modal, in both modes.
// Create mode: the verdict IS the authoring action (Accept authors the record, Flag
// authors it flagged). No Drop (authoring only to suppress is marginal) and no
// Clone bar (cloning a not-yet-saved record makes no sense).
const CREATE_MODE = "create";

function recordEditor(group, opts) {
    const record = group[0];
    const container = document.createElement("div");
    container.className = "record-editor";
    const ctx = makeEditorContext({
        scope: opts.scope,
        root: container,
        prefix: opts.scope === "modal" ? MODAL_FIELD_PREFIX : DETAIL_FIELD_PREFIX,
        group,
        mode: opts.mode,
    });
    if (opts.scope === "detail") {
        state.mainContext = ctx;
    } else {
        state.modalEditor = ctx;
    }
    if (opts.mode === CREATE_MODE) {
        container.append(
            createTopMatter(opts.seeded),
            createFieldStack(ctx, record),
            createActionBar(ctx),
        );
        // The distinctness guard runs LIVE as identity fields change; delegated on the
        // container so it covers text inputs (input) and variation toggles (change).
        container.addEventListener("input", () => evaluateDistinctness(ctx));
        container.addEventListener("change", () => evaluateDistinctness(ctx));
        evaluateDistinctness(ctx);
        return container;
    }

    container.append(recordsBar(ctx, group));

    const overridden = group.length === 1 ? overriddenFields(record) : new Set();

    const chrome = document.createElement("div");
    chrome.className = "detail-chrome";

    const glance = glanceColumn(ctx, group, overridden);
    const rail = railColumn(ctx, group, overridden);
    chrome.append(glance, rail);
    container.append(chrome);

    // Single-record affordances — a group has no single word to link out for.
    if (group.length === 1) {
        const orphanNote = orphanReasonNote(record);
        if (orphanNote) {
            container.append(orphanNote);
        }
        container.append(referenceLinks(record.word));
    }
    return container;
}

// The records bar tops every render — single record and group alike — with the
// same geometry, so stepping never reflows the panel. It carries the count, the
// verdict glyph (its border also carries the panel's ONE verdict tint — see
// stampCell/GROUP_MIXED), and (detail scope only — a modal has no list position)
// the step-prev/next buttons.
function recordsBar(ctx, group) {
    const consensus = verdictConsensus(group);
    const verdict = consensus.uniform ? consensus.value : GROUP_MIXED;
    const bar = document.createElement("div");
    bar.className = `records-bar state-${verdict}`;
    const summary = document.createElement("div");
    summary.className = "records-summary";
    summary.append(
        cell("records-count", `${group.length} record${group.length === 1 ? "" : "s"}`),
        stampCell(group[0], verdict),
    );
    if (ctx.scope === "detail") {
        bar.append(stepNavButton(-1), summary, stepNavButton(1));
    } else {
        bar.append(summary);
    }
    return bar;
}

function stepNavButton(delta) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "records-nav";
    button.textContent = delta < 0 ? "‹" : "›";
    const name = delta < 0 ? "Previous record (↑/k)" : "Next record (↓/j)";
    button.setAttribute("aria-label", name);
    button.title = name;
    button.disabled = stepExhausted(delta);
    button.addEventListener("click", () => step(delta));
    return button;
}

// Nothing left to step to: at the edge stop of the working set AND no further
// page to roll into.
function stepExhausted(delta) {
    const stops = cursorStops();
    if (!stops.length) {
        return true;
    }
    const at = currentStopIndex(stops);
    if (at < 0) {
        return false;
    }
    const atEdge = delta < 0 ? at === 0 : at === stops.length - 1;
    return atEdge && !pageAvailable(delta);
}

function glanceColumn(ctx, group, overridden) {
    const column = document.createElement("div");
    column.className = "glance-column";

    const posVar = document.createElement("div");
    posVar.className = "glance-posvar";
    posVar.append(
        posSpelledOut(group, overridden.has("pos")),
        editField(ctx, group, "var", "Dialect (var)", "var-field", overridden.has("var")),
        editField(ctx, group, "freq", "Frequency", "freq-field", overridden.has("freq")),
    );

    const fields = document.createElement("div");
    fields.className = "glance-fields";
    fields.append(
        editField(ctx, group, "word", "Word (latin)", "latin-field", overridden.has("word")),
        editField(ctx, group, "shaw", "Shavian", "shaw-field", overridden.has("shaw")),
        editField(ctx, group, "ipa", "IPA", "ipa-field", overridden.has("ipa")),
    );
    column.append(fields, posVar);
    return column;
}

// The divergent-field display: distinct values, commonest first, on ONE ellipsis-
// truncated line; the FULL list is the title tooltip. No count prefix — a leading
// count would carry the Shavian namer dot (`·`), which reads as linguistic content
// beside Shavian, not a UI count.
function distinctDisplay(consensus) {
    const list = [...consensus.distinct]
        .sort((a, b) => b.count - a.count)
        .map((entry) => entry.key || "—")
        .join(", ");
    return { text: list, title: list };
}

function applyDistinctDisplay(element, consensus) {
    const { text, title } = distinctDisplay(consensus);
    element.textContent = text;
    element.title = title;
    element.classList.add("distinct-values");
}

// POS as a read-only glance field — editable only on create (the patch model would
// carry a `changes.pos` fine; it is just not offered in the edit surface).
function posSpelledOut(group, overridden) {
    const consensus = fieldConsensus(group, "pos");
    const wrap = document.createElement("div");
    wrap.className = "edit-field pos-glance";
    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = "POS";
    const value = document.createElement("span");
    value.className = "pos-glance-value";
    if (consensus.uniform) {
        const pos = consensus.value;
        value.title = posTitle(pos);
        const tag = document.createElement("span");
        tag.className = "pos-glance-tag";
        tag.textContent = pos || "—";
        const expansion = document.createElement("span");
        expansion.className = "pos-glance-name";
        expansion.textContent = posExpansion(pos) || "";
        value.append(tag, expansion);
    } else {
        value.classList.add("pos-glance-multiple");
        const tag = document.createElement("span");
        tag.className = "pos-glance-tag";
        applyDistinctDisplay(tag, consensus);
        value.append(tag);
    }
    wrap.append(caption, value);
    markOverridden(wrap, caption, overridden);
    return wrap;
}

function posExpansion(pos) {
    if (!pos) {
        return "";
    }
    return pos.split("+").map((part) => C5_TAGS[part] ?? part).join(" + ");
}

function railColumn(ctx, group, overridden) {
    const column = document.createElement("div");
    column.className = "rail-column";
    column.append(
        priorityRail(group),
        attributesField(ctx, group, overridden),
        metadataBadges(group[0], overridden),
        actionBar(ctx, group),
    );
    return column;
}

// Two FIXED slots — sources, confidence — each keeping its geometry: an absent
// value's slot goes invisible IN PLACE (.empty) and the other does NOT reflow, so
// the glance loop never re-scans. Freq lives in the glance editField now (it fans
// like any other field). The verdict lives in the records bar above, not here.
function priorityRail(group) {
    const record = group[0];
    const rail = document.createElement("div");
    rail.className = "priority-rail";

    const sources = railSlot("sources");
    const sourceSet = groupSources(group);
    if (sourceSet.length) {
        sources.append(sourcePills(sourceSet));
    } else {
        sources.classList.add("empty");
    }

    const conf = railSlot("confidence");
    const confConsensus = fieldConsensus(group, "confidence");
    if (!confConsensus.uniform) {
        conf.append(cell("rail-value", "mixed"));
    } else if (record.confidence !== null && record.confidence !== undefined) {
        conf.append(confidenceMeter(record.confidence), cell("rail-value", String(record.confidence)));
    } else {
        conf.classList.add("empty");
    }

    rail.append(sources, conf);
    return rail;
}

function groupSources(group) {
    const union = [];
    for (const member of group) {
        for (const source of member.source || []) {
            if (!union.includes(source)) {
                union.push(source);
            }
        }
    }
    return union;
}

const RAIL_SLOT_LABELS = { sources: "sources", confidence: "confidence" };

function railSlot(kind) {
    const slot = document.createElement("div");
    slot.className = `rail-slot rail-${kind}`;
    slot.append(cell("rail-label", RAIL_SLOT_LABELS[kind]));
    const value = document.createElement("div");
    value.className = "rail-slot-value";
    slot.append(value);
    // Children appended by the caller go into the value area.
    slot.append = value.append.bind(value);
    return slot;
}

function sourcePills(sources) {
    const wrap = document.createElement("span");
    wrap.className = "source-pills";
    for (const origin of sources) {
        wrap.append(cell(`source-pill source-${origin}`, origin));
    }
    return wrap;
}

function metadataBadges(record, overridden) {
    const wrap = document.createElement("div");
    wrap.className = "metadata-badges";
    wrap.append(
        noveltyBadge(record.novelty),
        definitionBadge(record.has_definition),
        origVarBadge(record.orig_var, record.var),
        infoBadges(record[INFO_FIELD]),
    );
    return wrap;
}

// The group the detail editor operates on: the picked multi-selection wins over the
// focused row; [] when neither.
function selectedGroup() {
    if (state.multi.size) {
        return selectedRecords();
    }
    const focused = state.records[state.selected];
    return focused ? [focused] : [];
}

// The ONE render path for a single focused record and a multi-selection alike. The
// evidence pair (related + definitions) shows whenever the selection is Latin-
// uniform — every real group shares one Latin word — and keys off that shared word;
// only a hand-picked cross-word selection hides it.
function renderGroupEditor(group) {
    const record = group[0];
    const editor = recordEditor(group, { scope: "detail", mode: "edit" });
    if (!latinUniform(group)) {
        DETAIL.replaceChildren(editor);
        return;
    }
    const definitions = definitionsSection();
    const related = relatedSection();
    const evidence = document.createElement("div");
    evidence.className = "evidence-cols";
    evidence.append(related, definitions);
    DETAIL.replaceChildren(editor, evidence);
    syncEvidenceSections();
    loadDefinitions(record, definitions);
    loadRelated(record, related);
}

// Case-insensitive, mirroring the daemon's natural key (word.lower). N=1 is
// trivially uniform.
function latinUniform(group) {
    const first = group[0].word.toLowerCase();
    return group.every((member) => member.word.toLowerCase() === first);
}

// The consensus of one field across a group: uniform or divergent. Values compare
// by canonical string form (fieldValueKey); the RETURNED `value` for a uniform
// field is the first member's RAW value, so the field renderer sees exactly what a
// single-record render would. N=1 is trivially uniform — what keeps the
// single-record render byte-identical.
function fieldConsensus(group, field) {
    const first = group[0][field];
    const firstKey = fieldValueKey(first);
    const distinct = [];
    let uniform = true;
    for (const member of group) {
        const key = fieldValueKey(member[field]);
        if (key !== firstKey) {
            uniform = false;
        }
        const seen = distinct.find((entry) => entry.key === key);
        if (seen) {
            seen.count += 1;
            seen.members.push(member);
        } else {
            distinct.push({ key, value: member[field], members: [member], count: 1 });
        }
    }
    return { uniform, value: uniform ? first : null, distinct };
}

// A canonical, comparable string: a list-valued field (mergers) sorts-joins so
// order creates no spurious difference; null/undefined/"" collapse to one key.
function fieldValueKey(value) {
    if (Array.isArray(value)) {
        return [...value].sort().join(" ");
    }
    return value == null ? "" : String(value);
}

// fieldConsensus over each member's verdictState, projected onto {verdict} shells
// so the generic keying/count machinery applies unchanged.
function verdictConsensus(group) {
    return fieldConsensus(
        group.map((record) => ({ verdict: verdictState(record) })), "verdict");
}

function cloneButton(record) {
    return actionButton("clone", "Clone", () => openCloneModal(record));
}

const EDITED_TAG_TEXT = "edited";

function markOverridden(wrap, label, overridden) {
    if (!overridden) {
        return wrap;
    }
    wrap.classList.add("overridden");
    label.append(cell("edited-tag", EDITED_TAG_TEXT));
    return wrap;
}

function selectedRecords() {
    return state.records.filter(
        (record) => state.multi.has(anchorKey(record.anchor)),
    );
}

// ---- definitions (read-only inline sense summary) ----
// docs/definitions-editor-design.md §5b, phase P2 — a VIEW, fetched async off the
// definitions op. The US Shavian shows as a second line ONLY where the daemon
// reports divergence (shaw_us present); gloss and POS are shared across dialects.

const DEFINITIONS_TITLE = "Definitions";

// WordNet POS tags → readable labels. `n-1`/`v-2` style tags share the base
// letter's label (the trailing index is an internal sense-split, not a POS).
const DEFINITION_POS_LABELS = new Map([
    ["n", "noun"],
    ["v", "verb"],
    ["a", "adjective"],
    ["s", "adjective"],
    ["r", "adverb"],
]);

function definitionPosLabel(pos) {
    if (!pos) {
        return "";
    }
    return DEFINITION_POS_LABELS.get(pos.split("-")[0]) || pos;
}

function definitionsSection() {
    const section = collapsibleSection("definitions", DEFINITIONS_TITLE);
    section.append(definitionsSummary(null), definitionsLoading());
    return section;
}

function definitionsSummary(count) {
    return collapsibleSummary("definitions-title", DEFINITIONS_TITLE, count);
}

function collapsibleSection(id, label) {
    const section = document.createElement("details");
    section.className = id;
    section.setAttribute("aria-label", label);
    section.open = sectionExpanded(id);
    section.addEventListener("toggle", () => {
        if (evidenceSideBySide(section.parentElement)) {
            section.open = true;
            return;
        }
        setSectionExpanded(id, section.open);
    });
    return section;
}

// Side by side, each section IS its grid column — collapsed it would leave a bare
// title beside a full column — so wide forces both open (and never persists that),
// leaving the stacked open/closed prefs untouched underneath. Wideness is read off
// the container query's own effect, so CSS stays the single owner of the threshold.
function evidenceSideBySide(evidence) {
    return evidence !== null && evidence.classList.contains("evidence-cols")
        && getComputedStyle(evidence).display === "grid";
}

function syncEvidenceSections() {
    const evidence = DETAIL.querySelector(":scope > .evidence-cols");
    if (!evidence) {
        return;
    }
    const wide = evidenceSideBySide(evidence);
    for (const section of evidence.querySelectorAll(":scope > details")) {
        section.open = wide || sectionExpanded(section.className);
    }
}
new ResizeObserver(syncEvidenceSections).observe(DETAIL);

function collapsibleSummary(className, title, count) {
    const summary = document.createElement("summary");
    summary.className = className;
    const chevron = document.createElement("span");
    chevron.className = "chevron";
    chevron.setAttribute("aria-hidden", "true");
    const text = count === null ? title : `${title} · ${count}`;
    summary.append(chevron, document.createTextNode(text));
    return summary;
}

function definitionsLoading() {
    const loading = document.createElement("p");
    loading.className = "definitions-loading";
    loading.textContent = "Loading definitions…";
    return loading;
}

// Mirrors loadRelated's staleness discipline: only the newest fetch for the current
// word may render.
async function loadDefinitions(record, section) {
    const generation = ++state.definitionsGeneration;
    const focused = record.anchor;
    try {
        const result = await callDaemon({ op: "definitions", word: record.word });
        const panel = state.mainContext;
        if (generation !== state.definitionsGeneration
            || !panel.group.some((member) => sameAnchor(member.anchor, focused))
            || !section.isConnected) {
            return;
        }
        renderDefinitions(section, record.word, result.senses);
    } catch (error) {
        if (generation === state.definitionsGeneration && section.isConnected) {
            renderDefinitionsError(section, error.message);
        }
    }
}

function renderDefinitions(section, word, senses) {
    if (!senses.length) {
        section.replaceChildren(definitionsSummary(0), definitionsEmpty());
        return;
    }
    const list = document.createElement("ul");
    list.className = "definitions-list";
    for (const sense of senses) {
        list.append(definitionRow(word, sense, section));
    }
    section.replaceChildren(definitionsSummary(senses.length), list);
}

async function reloadDefinitions(word, section) {
    if (!section || !section.isConnected) {
        return;
    }
    const generation = ++state.definitionsGeneration;
    try {
        const result = await callDaemon({ op: "definitions", word });
        if (generation === state.definitionsGeneration && section.isConnected) {
            renderDefinitions(section, word, result.senses);
        }
    } catch (error) {
        if (generation === state.definitionsGeneration && section.isConnected) {
            renderDefinitionsError(section, error.message);
        }
    }
}

function definitionsEmpty() {
    const note = document.createElement("p");
    note.className = "definitions-empty";
    note.textContent = "No definition on record for this word.";
    return note;
}

function renderDefinitionsError(section, message) {
    const note = document.createElement("p");
    note.className = "definitions-loading";
    note.textContent = `Couldn't load definitions: ${message}`;
    section.replaceChildren(definitionsSummary(null), note);
}

function definitionRow(word, sense, section) {
    const row = document.createElement("li");
    row.className = "definition-row";

    const head = document.createElement("div");
    head.className = "definition-head";
    const pos = definitionPosLabel(sense.pos);
    if (pos) {
        head.append(cell("definition-pos", pos));
    }
    if (sense.source) {
        head.append(definitionSourceTag(sense.source));
    }
    head.append(cell("definition-gloss", sense.gloss || "(no gloss)"));
    head.append(definitionEditButton(word, sense, section));
    row.append(head);

    row.append(definitionShaw(sense));
    return row;
}

function definitionSourceTag(source) {
    const tag = cell("definition-source", source);
    tag.classList.add(`definition-source-${source}`);
    tag.title = source === "wordnet"
        ? "Gloss from WordNet"
        : `Gloss source: ${source}`;
    return tag;
}

function definitionEditButton(word, sense, section) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "definition-edit";
    button.textContent = "✎";
    button.title = "Correct this transliteration";
    button.setAttribute("aria-label", "Correct this transliteration");
    button.addEventListener("click", () => openDefinitionModal(word, sense, section));
    return button;
}

function definitionShaw(sense) {
    const wrap = document.createElement("div");
    wrap.className = "definition-shaw-wrap";
    if (!sense.shaw_gb) {
        wrap.append(cell("definition-no-shaw", "no transliteration yet"));
        return wrap;
    }
    const diverges = Boolean(sense.shaw_us);
    wrap.append(shawLine(sense.shaw_gb, diverges ? "GB" : null));
    if (diverges) {
        wrap.append(shawLine(sense.shaw_us, "US"));
    }
    return wrap;
}

function shawLine(shaw, dialect) {
    const line = document.createElement("div");
    line.className = "definition-shaw shavian";
    if (dialect) {
        line.append(cell("definition-dialect", dialect));
    }
    line.append(cell("definition-shaw-text", shaw));
    return line;
}

// ---- definition correction modal (§5c) ----
// Reuses the modal shell chrome but NOT the record-editor context — it edits a
// dictionary sense, not a basis record, and writes to the definition-patches store.
// gb/us edit behaviour: gb == us → ONE field, saving to BOTH dialects (the owner
// corrected "the transliteration"); gb != us → one field PER dialect, each saving
// its own patch. A sense with no transliteration yet is still correctable — the
// single field starts empty and the save fills the gap for both dialects.

function openDefinitionModal(word, sense, section) {
    const diverges = Boolean(sense.shaw_us);
    const fields = diverges
        ? [{ dialect: "gb", label: "GB", value: sense.shaw_gb || "" },
           { dialect: "us", label: "US", value: sense.shaw_us || "" }]
        : [{ dialect: "both", label: null, value: sense.shaw_gb || "" }];

    state.definitionModal = { word, synset: sense.synset, section };

    const card = document.createElement("div");
    card.className = "create-card definition-modal-card";
    card.setAttribute("role", "document");

    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "create-dismiss";
    dismiss.setAttribute("aria-label", "Cancel");
    dismiss.textContent = "×";
    dismiss.addEventListener("click", closeDefinitionModal);

    card.append(dismiss, definitionModalBody(word, sense, fields));
    CREATE_MODAL.replaceChildren(card);
    CREATE_MODAL.classList.add("open");
    CREATE_MODAL.setAttribute("aria-hidden", "false");

    const first = card.querySelector(".definition-shaw-input");
    if (first) {
        first.focus();
    }
}

function definitionModalBody(word, sense, fields) {
    const body = document.createElement("div");
    body.className = "definition-modal-body";

    const title = document.createElement("div");
    title.className = "detail-create-title";
    title.textContent = `Correct transliteration · ${word}`;
    body.append(title);

    const meta = document.createElement("div");
    meta.className = "definition-modal-meta";
    const pos = definitionPosLabel(sense.pos);
    if (pos) {
        meta.append(cell("definition-pos", pos));
    }
    if (sense.source) {
        meta.append(definitionSourceTag(sense.source));
    }
    body.append(meta);

    const gloss = document.createElement("p");
    gloss.className = "definition-modal-gloss";
    gloss.textContent = sense.gloss || "(no gloss)";
    body.append(gloss);

    const inputs = [];
    for (const field of fields) {
        body.append(definitionModalField(field, inputs));
    }

    const actions = document.createElement("div");
    actions.className = "definition-modal-actions";
    const save = document.createElement("button");
    save.type = "button";
    save.className = "definition-save";
    save.textContent = "Save";
    save.addEventListener("click", () => saveDefinitionPatch(inputs));
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "definition-cancel";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", closeDefinitionModal);
    actions.append(save, cancel);
    body.append(actions);

    return body;
}

// `inputs` collects {dialect, input} so the shared Save reads every field. Enter
// saves; Escape dismisses (its own listener, so the field-focused global guard
// leaves it).
function definitionModalField(field, inputs) {
    const wrap = document.createElement("label");
    wrap.className = "definition-modal-field";
    if (field.label) {
        wrap.append(cell("definition-dialect", field.label));
    }
    const input = document.createElement("input");
    input.type = "text";
    input.className = "text-filter shavian-input definition-shaw-input";
    input.value = field.value;
    input.spellcheck = false;
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            saveDefinitionPatch(inputs);
        } else if (event.key === "Escape") {
            event.preventDefault();
            closeDefinitionModal();
        }
    });
    wrap.append(input);
    inputs.push({ dialect: field.dialect, input });
    return wrap;
}

async function saveDefinitionPatch(inputs) {
    const modal = state.definitionModal;
    if (!modal) {
        return;
    }
    const jobs = [];
    for (const { dialect, input } of inputs) {
        const shaw = input.value.trim();
        if (!shaw) {
            showToast("Shavian cannot be empty.", true);
            return;
        }
        const dialects = dialect === "both" ? ["gb", "us"] : [dialect];
        for (const d of dialects) {
            jobs.push({ dialect: d, shaw });
        }
    }
    try {
        for (const job of jobs) {
            await callDaemon({
                op: "definition_patch",
                anchor: { word: modal.word, synset: modal.synset, dialect: job.dialect },
                changes: { shaw: job.shaw },
                author: AUTHOR,
            });
        }
        showToast(`transliteration · saved (${jobs.length})`);
        const { word, section } = modal;
        closeDefinitionModal();
        reloadDefinitions(word, section);
    } catch (error) {
        showToast(error.message, true);
    }
}

function isDefinitionModalOpen() {
    return state.definitionModal !== null;
}

function closeDefinitionModal() {
    if (!isDefinitionModalOpen()) {
        return;
    }
    state.definitionModal = null;
    CREATE_MODAL.classList.remove("open");
    CREATE_MODAL.setAttribute("aria-hidden", "true");
    CREATE_MODAL.replaceChildren();
}

// ---- related-entries context ----
// Every record sharing the focused entry's Latin word, case-insensitively — so
// capitalisation dupes and proper-noun/common-word homographs surface together.

const RELATED_TITLE = "Related entries";

function relatedSection() {
    const section = collapsibleSection("related", RELATED_TITLE);
    section.append(relatedHeading(null), relatedLoading());
    return section;
}

function relatedHeading(count) {
    return collapsibleSummary("related-title", RELATED_TITLE, count);
}

// Superseded in-flight fetches (a step-on, or a write-triggered reload) are dropped
// via the generation token, backstopped by the panel-membership/connected checks.
// The membership check asks the DETAIL PANEL (state.mainContext), not the review
// cursor: a group header-select gathers evidence off the panel's group[0], which
// need not be the record state.selected points at.
async function loadRelated(record, section) {
    const generation = ++state.relatedGeneration;
    const focused = record.anchor;
    try {
        const result = await callDaemon({ op: "related", word: record.word, shaw: record.shaw });
        const panel = state.mainContext;
        if (generation !== state.relatedGeneration
            || !panel.group.some((member) => sameAnchor(member.anchor, focused))
            || !section.isConnected) {
            return;
        }
        renderRelated(section, result.records, focused);
    } catch (error) {
        if (generation === state.relatedGeneration && section.isConnected) {
            renderRelatedError(section, error.message);
        }
    }
}

// In-place reload after a write re-decided a sibling WITHOUT re-rendering the
// detail (a modal edit); stepping/re-selecting already reloads via renderGroupEditor.
function reloadRelatedForDetail() {
    const record = state.records[state.selected];
    if (!record) {
        return;
    }
    const section = DETAIL.querySelector(".related");
    if (!section) {
        return;
    }
    section.replaceChildren(relatedHeading(null), relatedLoading());
    loadRelated(record, section);
}

function relatedLoading() {
    const loading = document.createElement("p");
    loading.className = "related-loading";
    loading.textContent = "Finding related entries…";
    return loading;
}

// The records + focused anchor are stashed on the section node so a header
// sort-click can re-order in place without a re-fetch.
function renderRelated(section, records, focusedAnchor) {
    section.dataset.hasList = "true";
    section._relatedRecords = records;
    section._focusedAnchor = focusedAnchor;
    section.replaceChildren(
        relatedHeading(records.length),
        relatedTableHead(),
        relatedListEl(records, focusedAnchor),
    );
    syncRelatedSortIndicators(section);
}

// Split out so a header sort click can rebuild just the list from the records
// stashed on the section. The tree's nodes ARE the daemon's ledger groups; the
// node holding the focused entry auto-expands with its leaf highlighted.
function relatedListEl(records, focusedAnchor) {
    const list = document.createElement("ul");
    list.className = "related-list";
    const sorted = sortedRelated(records, focusedAnchor);
    for (const shawGroup of groupRelated(sorted, focusedAnchor)) {
        list.append(shawNode(shawGroup, focusedAnchor));
    }
    return list;
}

// Fold the leaves into the daemon's ledger groups: the node key IS the served
// group_key, so a related node always matches the group the main ledger edits as a
// unit — the client never computes grouping. Node order follows the incoming leaf
// order, so sorting the leaves sorts the nodes. A record without its group token is
// a daemon contract violation — fold nothing rather than fold wrongly.
function groupRelated(sortedRecords, focusedAnchor) {
    const nodes = [];
    const index = new Map();
    for (const record of sortedRecords) {
        const key = record.group_key;
        if (!key) {
            throw new Error("related record carries no group key.");
        }
        let node = index.get(key);
        if (!node) {
            node = {
                key, word: record.word, shaw: record.shaw,
                leaves: [], poses: [], vars: [], here: false,
            };
            index.set(key, node);
            nodes.push(node);
        }
        node.leaves.push(record);
        if (record.pos && !node.poses.includes(record.pos)) {
            node.poses.push(record.pos);
        }
        if (record.var && !node.vars.includes(record.var)) {
            node.vars.push(record.var);
        }
        if (sameAnchor(record.anchor, focusedAnchor)) {
            node.here = true;
        }
    }
    return nodes;
}

function shawNode(node, focusedAnchor) {
    const li = document.createElement("li");
    li.className = "related-group related-shaw-group";
    const details = groupDetails(node.here);
    details.append(shawSummary(node), shawLeaves(node, focusedAnchor));
    li.append(details);
    return li;
}

function shawSummary(node) {
    const summary = document.createElement("summary");
    summary.className = "related-node-summary";
    if (node.here) {
        summary.classList.add("on-path");
    }
    const chevron = document.createElement("span");
    chevron.className = "related-chevron chevron";
    chevron.setAttribute("aria-hidden", "true");

    const label = document.createElement("span");
    label.className = "related-node-label";
    label.append(cell("related-group-word", node.word));
    const shaw = cell("related-group-shaw", node.shaw);
    label.append(shaw);
    const poses = document.createElement("span");
    poses.className = "related-group-pos";
    for (const tag of node.poses) {
        poses.append(posCell("related-group-pos-tag", tag));
    }
    label.append(poses);
    const vars = document.createElement("span");
    vars.className = "related-group-vars";
    for (const value of node.vars) {
        vars.append(cell("related-group-var-tag", value));
    }
    label.append(vars);
    // The variation set is part of the group key, so it is node-uniform and the
    // first leaf speaks for all.
    label.append(...variationMarkers(node.leaves[0]));

    const count = cell("related-node-count", `${node.leaves.length}`);
    summary.append(chevron, label, count);
    // A node that is the focused record ALONE is fully the detail card above — its
    // summary keeps the plain disclosure toggle, mirroring the focused leaf's inert
    // rule. Every other node opens the group editor.
    if (!(node.here && node.leaves.length === 1)) {
        summary.addEventListener("click", (event) => {
            if (event.target.closest(".related-chevron")) {
                return;
            }
            event.preventDefault();
            openRelatedModal(node.leaves);
        });
    }
    return summary;
}

function shawLeaves(node, focusedAnchor) {
    const body = document.createElement("ul");
    body.className = "related-subtree related-leaves";
    for (const record of node.leaves) {
        body.append(relatedRow(record, focusedAnchor));
    }
    return body;
}

function groupDetails(open) {
    const details = document.createElement("details");
    details.className = "related-node";
    details.open = open;
    return details;
}

// The state header (last) spans the badge + label tracks (one logical column), so
// the six headers line up over the row cells they name.
const RELATED_COLUMNS = [
    ["word", "word", "related-word"],
    ["pos", "pos", "related-pos"],
    ["var", "var", "related-dialect"],
    ["shaw", "shaw", "related-shaw"],
    ["source", "source", "related-source"],
    ["state", "state", "related-head-state"],
];

function relatedTableHead() {
    const head = document.createElement("div");
    head.className = "related-head";
    for (const [key, label, colClass] of RELATED_COLUMNS) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `${colClass} sort-head related-sort`;
        button.dataset.sortKey = key;
        button.textContent = label;
        button.addEventListener("click", () => onRelatedSortClick(key));
        head.append(button);
    }
    return head;
}

function onRelatedSortClick(key) {
    if (state.relatedSort && state.relatedSort.key === key && state.relatedSort.dir === "asc") {
        state.relatedSort = { key, dir: "desc" };
    } else {
        state.relatedSort = { key, dir: "asc" };
    }
    const section = DETAIL.querySelector(".related");
    if (!section || !section.dataset.hasList) {
        return;
    }
    const list = section.querySelector(".related-list");
    if (list) {
        list.replaceWith(relatedListEl(section._relatedRecords, section._focusedAnchor));
    }
    syncRelatedSortIndicators(section);
}

function syncRelatedSortIndicators(section) {
    const head = section.querySelector(".related-head");
    if (!head) {
        return;
    }
    for (const header of head.querySelectorAll(".sort-head")) {
        const active = state.relatedSort && state.relatedSort.key === header.dataset.sortKey;
        header.classList.toggle("sort-asc", active && state.relatedSort.dir === "asc");
        header.classList.toggle("sort-desc", active && state.relatedSort.dir === "desc");
        header.setAttribute(
            "aria-sort",
            active ? (state.relatedSort.dir === "asc" ? "ascending" : "descending") : "none",
        );
    }
}

// Deterministic order (the daemon returns unspecified index order). The focused
// entry ALWAYS leads regardless of the active sort; siblings follow the header sort
// when set, else the default chain.
function sortedRelated(records, focusedAnchor) {
    return [...records].sort((left, right) => {
        const leftHere = sameAnchor(left.anchor, focusedAnchor);
        const rightHere = sameAnchor(right.anchor, focusedAnchor);
        if (leftHere !== rightHere) {
            return leftHere ? -1 : 1;
        }
        if (state.relatedSort) {
            const primary = compareRelatedByKey(left, right, state.relatedSort.key);
            if (primary !== 0) {
                return state.relatedSort.dir === "desc" ? -primary : primary;
            }
            // Fall through to the default chain as a stable tiebreak within equal keys.
        }
        return compareRelated(left, right);
    });
}

// Rank states so a "state" sort puts the rows still needing a decision first.
const RELATED_STATE_ORDER = new Map([
    ["unreviewed", 0],
    ["orphaned", 1],
    ["flagged", 2],
    ["dropped", 3],
    ["accepted", 4],
]);

function compareRelatedByKey(left, right, key) {
    if (key === "state") {
        const l = RELATED_STATE_ORDER.get(relatedProvenance(left).state) ?? 99;
        const r = RELATED_STATE_ORDER.get(relatedProvenance(right).state) ?? 99;
        return l - r;
    }
    if (key === "word") {
        return cmpStr((left.word || "").toLowerCase(), (right.word || "").toLowerCase());
    }
    if (key === "source") {
        return cmpStr(sourceKey(left), sourceKey(right));
    }
    return cmpStr(left[key] || "", right[key] || "");
}

function cmpStr(a, b) {
    if (a < b) return -1;
    if (a > b) return 1;
    return 0;
}

function isCanonical(record) {
    return (!record.mergers || record.mergers.length === 0) && !record.variant;
}

function sourceKey(record) {
    return Array.isArray(record.source) ? [...record.source].sort().join("+") : "";
}

function compareRelated(left, right) {
    const leftWord = (left.word || "").toLowerCase();
    const rightWord = (right.word || "").toLowerCase();
    if (leftWord < rightWord) return -1;
    if (leftWord > rightWord) return 1;
    if (left.pos < right.pos) return -1;
    if (left.pos > right.pos) return 1;
    if (left.var < right.var) return -1;
    if (left.var > right.var) return 1;
    const leftSource = sourceKey(left);
    const rightSource = sourceKey(right);
    if (leftSource < rightSource) return -1;
    if (leftSource > rightSource) return 1;
    const canonicalGap = (isCanonical(left) ? 0 : 1) - (isCanonical(right) ? 0 : 1);
    if (canonicalGap !== 0) return canonicalGap;
    if (left.shaw < right.shaw) return -1;
    if (left.shaw > right.shaw) return 1;
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
        row.classList.add("selected");
    }

    const badge = cell(`related-badge ${provenance.state}`, provenance.glyph);
    badge.title = provenance.label;
    row.append(
        cell("related-word", record.word),
        posCell("related-pos", record.pos),
        relatedDialect(record),
        cell("related-shaw", record.shaw),
        relatedSource(record),
        badge,
        cell("related-label", provenance.label),
    );
    // The focused row is already the detail card above, so it is inert.
    if (!here) {
        row.classList.add("clickable");
        row.addEventListener("click", () => openRelatedModal([record]));
    }
    return row;
}

// Open related records in an edit-mode modal: the FULL editor over the workbench.
// The related op already returned full serialisable records — no extra fetch. A
// verdict is the modal's ONE action: it writes, re-annotates the affected main rows
// by anchor (the main cursor never moves), and dismisses.
function openRelatedModal(records) {
    openModal(recordEditor(records, { scope: "modal", mode: "edit" }));
}

function relatedDialect(record) {
    const wrap = document.createElement("span");
    wrap.className = "related-dialect";
    wrap.append(varCell(record.var), ...variationMarkers(record));
    return wrap;
}

function variationMarkers(record) {
    const markers = [];
    if (record.variant) {
        markers.push(cell("related-variant", VARIATION_OTHER_LABEL));
    }
    for (const value of record.mergers || []) {
        markers.push(cell("related-merger", MERGER_LABELS.get(value) ?? value));
    }
    return markers;
}

// Formatted like the source facet (sorted, "+"-joined). Upstream (readlex) rows
// carry no tag — the badge already says "upstream".
function relatedSource(record) {
    const key = sourceKey(record);
    if (!key || key === "readlex") {
        return cell("related-source", "");
    }
    return cell("related-source", key);
}

// Provenance + review state of a related record: the verdict decides first (a
// patch's verdict overrides origin); an untouched row falls back to its origin.
function relatedProvenance(record) {
    switch (verdictState(record)) {
        case PATCH_STATE.DROPPED:
            return { state: "dropped", glyph: STAMP_GLYPHS.get(PATCH_STATE.DROPPED), label: "dropped" };
        case PATCH_STATE.FLAGGED:
            return { state: "flagged", glyph: STAMP_GLYPHS.get(PATCH_STATE.FLAGGED), label: "flagged" };
        case PATCH_STATE.ORPHANED: {
            const kind = record.orphan_kind === ORPHAN_KIND.RESURFACED_DROP
                ? ORPHAN_KIND.RESURFACED_DROP
                : ORPHAN_KIND.LOST_ACCEPT;
            return { state: "orphaned", glyph: ORPHAN_GLYPHS.get(kind),
                     label: ORPHAN_KIND_TAGS.get(kind).label };
        }
        case PATCH_STATE.ACCEPTED:
            return { state: "accepted", glyph: STAMP_GLYPHS.get(PATCH_STATE.ACCEPTED), label: "sanctioned" };
        default:
            if (record.manual) {
                return { state: "unreviewed", glyph: "✎", label: "manual" };
            }
            return record.source.includes("readlex")
                ? { state: "unreviewed", glyph: "✓", label: "upstream" }
                : { state: "unreviewed", glyph: "○", label: "candidate" };
    }
}

function orphanReasonNote(record) {
    if (record.patch_state !== PATCH_STATE.ORPHANED) {
        return null;
    }
    const tag = ORPHAN_KIND_TAGS.get(record.orphan_kind);
    if (!tag) {
        return null;
    }
    const note = document.createElement("div");
    note.className = "orphan-note";
    const head = cell("orphan-note-kind", tag.label);
    const reason = cell("orphan-note-reason", tag.reason);
    const action = document.createElement("div");
    action.className = "orphan-note-action";
    action.append(cell("orphan-note-action-label", "Action"), cell("orphan-note-action-text", tag.action));
    note.append(head, reason, action);
    return note;
}

const MERGER_LABELS = new Map(MERGERS);

function definitionBadge(hasDefinition) {
    const wrap = document.createElement("span");
    wrap.className = "def-badges";
    if (hasDefinition) {
        wrap.append(cell("def-badge", DEFINITION_LABEL));
    }
    return wrap;
}

function origVarBadge(origVar, currentVar) {
    const wrap = document.createElement("span");
    wrap.className = "orig-var-badges";
    if (origVar && origVar !== currentVar) {
        const badge = cell("orig-var-badge", ORIG_VAR_PREFIX + origVar);
        badge.title = `relabelled ${origVar} → ${currentVar} by the pipeline`;
        wrap.append(badge);
    }
    return wrap;
}

function noveltyBadge(novelty) {
    const wrap = document.createElement("span");
    wrap.className = "novelty-badges";
    const label = NOVELTY_LABELS.get(novelty);
    if (label) {
        wrap.append(cell(`novelty-badge ${novelty}`, label));
    }
    return wrap;
}

function infoBadges(info) {
    const wrap = document.createElement("span");
    wrap.className = "info-badges";
    if (Array.isArray(info)) {
        for (const tag of info) {
            wrap.append(cell("info-badge", tag));
        }
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

// All the reference links share ONE named tab, so looking up a new word reuses it
// rather than piling up a fresh tab each time.
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

// The VARIATIONS control: the mergers + the free-variation ("other") marker as one
// toggle group. INTERNAL representation stays FLATTENED: each toggle owns a
// `.merger-check` checkbox or the lone `.variant-check`, so the existing harvest
// (applyAdditiveFields) and dirty-check (mainEditIsDirty) read exactly the DOM they
// always did — the on-disk shape and patch round-trip are byte-identical. A
// display/label skin only; nothing on disk is renamed.
const ATTRIBUTE_VARIANT = VARIANT_LABEL; // on-disk "variant"; displayed "other"

function attributesField(ctx, group, overridden) {
    const wrap = document.createElement("div");
    wrap.className = "edit-field variations-field";

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = "Variations";

    const toggles = document.createElement("div");
    toggles.className = "variation-toggles";
    let anyMixed = false;
    for (const [value, label] of MERGERS) {
        const tally = mergerTally(group, value);
        anyMixed = anyMixed || tally === TRISTATE_MIXED;
        toggles.append(variationToggle(ctx, "merger-check", value, label, tally));
    }
    const variant = variantTally(group);
    anyMixed = anyMixed || variant === TRISTATE_MIXED;
    toggles.append(variationToggle(ctx, "variant-check", "", VARIATION_OTHER_LABEL, variant));

    // A mixed group's harvest must NOT fan the checkbox state out unless the owner
    // actually moved a toggle — else an untouched group edit would silently rewrite
    // each member's flags. markVariationsTouched clears the untouched status.
    if (anyMixed) {
        wrap.dataset.mixed = "true";
    }
    wrap.append(caption, toggles);
    markOverridden(wrap, caption, overridden.has("mergers") || overridden.has("variant"));
    return wrap;
}

function mergerTally(group, value) {
    return tristate(group, (member) => (member.mergers || []).includes(value));
}

function variantTally(group) {
    return tristate(group, (member) => Boolean(member.variant));
}

const TRISTATE_ON = "on";
const TRISTATE_OFF = "off";
const TRISTATE_MIXED = "mixed";

function tristate(group, holds) {
    let any = false;
    let all = true;
    for (const member of group) {
        if (holds(member)) {
            any = true;
        } else {
            all = false;
        }
    }
    if (all) {
        return TRISTATE_ON;
    }
    return any ? TRISTATE_MIXED : TRISTATE_OFF;
}

// One VARIATIONS toggle: the pill IS the affordance; the hidden checkbox is the
// state applyAdditiveFields / mainEditIsDirty read. The first click off "mixed" is
// a uniform decision — the browser clears indeterminate on click — and marks the
// whole control touched so the group harvest fans it out.
function variationToggle(ctx, className, value, label, tally) {
    const chip = document.createElement("label");
    chip.className = "variation-toggle";
    if (className === "variant-check") {
        chip.classList.add("variation-other");
    }
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = className;
    if (className === "merger-check") {
        input.value = value;
    }
    input.checked = tally === TRISTATE_ON;
    input.indeterminate = tally === TRISTATE_MIXED;
    chip.classList.toggle("on", tally === TRISTATE_ON);
    chip.classList.toggle("mixed", tally === TRISTATE_MIXED);
    input.addEventListener("change", () => {
        input.indeterminate = false;
        chip.classList.remove("mixed");
        chip.classList.toggle("on", input.checked);
        markVariationsTouched(ctx);
        enterEdit(ctx);
        // Release the checkbox so the single-key verdicts fire again — a focused form
        // control makes onGlobalKey treat A/X/F as typing and swallow them.
        input.blur();
    });
    const text = document.createElement("span");
    text.textContent = label;
    chip.append(input, text);
    return chip;
}

function markVariationsTouched(ctx) {
    const field = ctx.root.querySelector(".variations-field");
    if (field) {
        field.dataset.touched = "true";
    }
}

const DETAIL_FIELD_PREFIX = "field-";

// The bare labelled text input both the review editor and the modal build on. It
// carries NO review-flow listeners — those belong to the surface that owns it, so
// the modal can bind its own submit/dismiss keys.
function fieldInput(name, label, value, extraClass, idPrefix) {
    const wrap = document.createElement("label");
    wrap.className = "edit-field";
    wrap.setAttribute("for", `${idPrefix}${name}`);

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = label;

    const input = document.createElement("input");
    input.type = "text";
    input.id = `${idPrefix}${name}`;
    input.className = `edit-input ${extraClass}`.trim();
    input.dataset.field = name;
    // The initial value as a STRING: freq arrives as a number, and the dirty
    // toggle below compares against input.value, which is always a string.
    const initial = String(value ?? "");
    input.value = initial;
    input.spellcheck = false;
    input.autocomplete = "off";
    input.addEventListener("input", () => {
        input.classList.toggle("dirty", input.value !== initial);
    });

    wrap.append(caption, input);
    return { wrap, caption, input };
}

// The review-editor field, group-native. Divergent members render the "multiple"
// state: empty box, greyed placeholder, the distinct-values line, and a
// `data-consensus="multiple"` marker the harvest reads. Typing OVERWRITES the field
// for every member; the first keystroke marks it touched (data-touched) so the
// harvest fans the value out — an untouched "multiple" box leaves each member's
// value alone.
function editField(ctx, group, name, label, extraClass, overridden) {
    const consensus = fieldConsensus(group, name);
    const divergent = !consensus.uniform;
    const { wrap, caption, input } = fieldInput(
        name, label, divergent ? "" : consensus.value, extraClass, ctx.prefix,
    );
    input.addEventListener("focus", () => enterEdit(ctx));
    input.addEventListener("keydown", onFieldKey);
    if (divergent) {
        input.placeholder = "multiple";
        input.dataset.consensus = "multiple";
        wrap.classList.add("field-multiple");
        input.addEventListener("input", () => {
            const touched = input.value !== "";
            input.dataset.touched = touched ? "true" : "";
            input.classList.toggle("pending-overwrite", touched);
        });
        const values = document.createElement("span");
        values.className = "field-multiple-values";
        applyDistinctDisplay(values, consensus);
        wrap.append(values);
    }
    markOverridden(wrap, caption, overridden);
    return wrap;
}

// The verdict controls, group-native: every verdict fans out to one patch per
// member. A multi-member group swaps Clone → Deselect (Clone is a single-record
// move) and drops Unflag/Undo, which act on one focused row's patch, not a fan-out.
function actionBar(ctx, group) {
    const record = group[0];
    const many = group.length > 1;
    const bar = document.createElement("div");
    bar.className = "actions";

    // Clear is a PERMANENT slot (the owner wants it always present); clearSelected()
    // itself no-ops on an unreviewed row.
    bar.append(
        actionButton("accept", many ? "Accept all" : "Accept", acceptSelected),
        actionButton("drop", many ? "Drop all" : "Drop", dropSelected),
        actionButton("flag", many ? "Flag all" : "Flag", flagSelected),
        actionButton("clear", many ? "Clear all" : "Clear", clearSelected),
    );
    if (many) {
        bar.append(actionButton("undo", "Deselect", clearSelection));
        return bar;
    }
    bar.append(cloneButton(record));
    if (record.patch_state === PATCH_STATE.FLAGGED) {
        bar.append(actionButton("unflag", "Unflag", unflagSelected));
    }
    if (ctx.scope !== "modal" && session.undoStack.length) {
        bar.append(actionButton("undo", "Undo", undoLast));
    }

    return bar;
}

// Inline SVG icon paths (CSP forbids external assets): 24×24 viewBox, currentColor.
const ACTION_ICONS = {
    accept: '<path d="M5 13l4 4L19 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    drop: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V7M10 11v6M14 11v6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    clear: '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
    flag: '<path d="M6 21V4m0 0h11l-2 4 2 4H6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    unflag: '<path d="M6 21V4m0 0h11l-2 4 2 4H6M3 3l18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    clone: '<path d="M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    undo: '<path d="M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
};

function actionButton(kind, label, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `act ${kind}`;
    button.addEventListener("click", handler);
    const icon = ACTION_ICONS[kind];
    if (icon) {
        button.classList.add("act-icon");
        button.title = label;
        button.setAttribute("aria-label", label);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("class", "act-glyph");
        svg.setAttribute("aria-hidden", "true");
        svg.innerHTML = icon;
        button.append(svg);
    } else {
        button.textContent = label;
    }
    return button;
}

// A patch body built from the record's OWN fields, no edit surface involved — the
// base a group verdict overlays its harvested edits onto.
function recordFields(record) {
    const result = {
        pos: record.pos,
        status: record.status,
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

function harvestRecord(ctx) {
    return ctx.mode === CREATE_MODE
        ? authoredRecord(ctx)
        : editedRecord(ctx);
}

// A self-contained authored record from the modal's inputs alone. No base record is
// carried (an authored row has no basis), so no status/source/freq leaks in.
function authoredRecord(ctx) {
    const record = {};
    for (const name of ["word", "shaw", "pos", "var", "ipa"]) {
        const value = ctx.root.querySelector(`[data-field="${name}"]`).value.trim();
        if (value) {
            record[name] = value;
        }
    }
    applyAdditiveFields(ctx, record);
    return record;
}

// Only run on a single-record context (save/auto-save guard on N=1), so every
// EDITABLE_FIELDS input — including word — is present.
function editedRecord(ctx) {
    const result = recordFields(contextRecord(ctx));
    for (const name of EDITABLE_FIELDS) {
        const input = ctx.root.querySelector(`[data-field="${name}"]`);
        result[name] = name === "freq" ? parsedFreq(input.value) : input.value.trim();
    }
    applyAdditiveFields(ctx, result);
    return result;
}

function applyAdditiveFields(ctx, record) {
    const mergers = [...ctx.root.querySelectorAll(".merger-check:checked")]
        .map((box) => box.value);
    if (mergers.length) {
        record.mergers = mergers;
    } else {
        delete record.mergers;
    }
    const variantBox = ctx.root.querySelector(".variant-check");
    if (variantBox && variantBox.checked) {
        record.variant = true;
    } else {
        delete record.variant;
    }
}

// The group's touched edits: ONLY the fields the owner actually changed, overlaid
// per member so untouched fields keep each member's own value. A COMMON text field
// always contributes its input value (at N=1 every field is common, reproducing
// editedRecord exactly); a "multiple" field only if typed into (data-touched). A
// UNIFORM variations control always contributes; a MIXED one only once touched.
function harvestGroupOverlay(ctx) {
    const overlay = {};
    for (const name of EDITABLE_FIELDS) {
        const input = ctx.root.querySelector(`[data-field="${name}"]`);
        if (input.dataset.consensus === "multiple" && input.dataset.touched !== "true") {
            continue;
        }
        overlay[name] = name === "freq" ? parsedFreq(input.value) : input.value.trim();
    }
    const variations = ctx.root.querySelector(".variations-field");
    if (variations && (variations.dataset.mixed !== "true" || variations.dataset.touched === "true")) {
        overlay.variations = true;
    }
    return overlay;
}

function applyGroupOverlay(record, overlay, ctx) {
    for (const name of EDITABLE_FIELDS) {
        if (name in overlay) {
            record[name] = overlay[name];
        }
    }
    if (overlay.variations) {
        applyAdditiveFields(ctx, record);
    }
    return record;
}

function groupMemberRecord(member, overlay, ctx) {
    return applyGroupOverlay(recordFields(member), overlay, ctx);
}

function requireShaw(record) {
    if (!record.shaw) {
        showToast("Shavian cannot be empty.", true);
        return false;
    }
    return true;
}

// A whole non-negative number, or null (including an emptied box — the input is
// prefilled, so blank is not a value). null is rejected loudly by requireFreq / the
// daemon validator; nothing is silently coerced.
function parsedFreq(text) {
    const trimmed = text.trim();
    return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
}

function requireFreq(record) {
    if (record.freq === null) {
        showToast("Frequency must be a whole number.", true);
        return false;
    }
    return true;
}

// A manual entry (anchor null in the store, `manual: true` on the row) exists
// ONLY via its authorship patch — no basis record backs it. Re-deciding it must
// edit THAT patch in place (anchor stays null), not write an anchored patch that
// would resolve to nothing and orphan the decision (failing the build).
function isManual(record) {
    return Boolean(record.manual);
}

// ---- create/clone modal (authorship from scratch or seeded from a record) ----
// The daemon's authorship path is a patch with anchor null and a self-contained
// record (editord.py handle_patch) — the ONLY flow that mints such a record. A new
// manual record is created DIRTY (verdict UNREVIEWED, shipping nothing) and passes
// through review like any other row: nothing auto-accepts. ONE dialog serves both
// entry points — New Entry opens it blank, Clone opens it seeded from a source
// record; its content is a create-mode recordEditor, so create and edit never
// diverge.

// The identity fields a new record must carry — mirrors the daemon's
// RECORD_REQUIRED_FIELDS.
const NEW_ENTRY_REQUIRED = [
    ["word", "Word"],
    ["shaw", "Shavian"],
    ["pos", "POS"],
    ["var", "Dialect (var)"],
];

// Distinct from DETAIL_FIELD_PREFIX so the modal's fields never collide with the
// detail record's in the DOM behind the backdrop.
const MODAL_FIELD_PREFIX = "modal-";

function blankSeed() {
    return { word: "", pos: "", var: "", ipa: "", shaw: "", mergers: [], variant: false };
}

function openCreateForm() {
    openCreateModal(blankSeed(), false);
}

function openCloneModal(sourceRecord) {
    openCreateModal({
        word: sourceRecord.word ?? "",
        pos: sourceRecord.pos ?? "",
        var: sourceRecord.var ?? "",
        ipa: sourceRecord.ipa ?? "",
        shaw: sourceRecord.shaw ?? "",
        mergers: sourceRecord.mergers ?? [],
        variant: Boolean(sourceRecord.variant),
    }, true);
}

function openCreateModal(seed, seeded) {
    // Fresh guard cache per dialog session, so a sibling authored or re-decided
    // since the last open is reflected.
    relatedGuardCache.clear();
    openModal(recordEditor([seed], { scope: "modal", mode: CREATE_MODE, seeded }));
    const first = document.getElementById(`${MODAL_FIELD_PREFIX}word`);
    if (first) {
        first.focus();
    }
}

// The generic modal shell around a pre-built recordEditor. recordEditor has already
// stored the context as state.modalEditor, so activeContext() routes to it.
function openModal(editor) {
    setDrawer(false);
    const card = document.createElement("div");
    card.className = "create-card";
    card.setAttribute("role", "document");

    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "create-dismiss";
    dismiss.setAttribute("aria-label", "Cancel");
    dismiss.textContent = "×";
    dismiss.addEventListener("click", closeModal);

    card.append(dismiss, editor);
    CREATE_MODAL.setAttribute("aria-labelledby", "create-title");
    CREATE_MODAL.replaceChildren(card);
    CREATE_MODAL.classList.add("open");
    CREATE_MODAL.setAttribute("aria-hidden", "false");
}

function isModalEditorOpen() {
    return state.modalEditor !== null;
}

function isCreateMode(ctx = activeContext()) {
    return Boolean(ctx) && ctx.mode === CREATE_MODE;
}

function closeModal() {
    if (!isModalEditorOpen()) {
        return;
    }
    state.modalEditor = null;
    CREATE_MODAL.classList.remove("open");
    CREATE_MODAL.setAttribute("aria-hidden", "true");
    CREATE_MODAL.replaceChildren();
}

function createTopMatter(seeded) {
    const wrap = document.createElement("div");

    const title = document.createElement("div");
    title.className = "detail-create-title";
    title.id = "create-title";
    title.textContent = seeded ? "Clone entry" : "New entry";

    const hint = document.createElement("p");
    hint.className = "detail-create-hint";
    hint.textContent = seeded
        ? "An exact copy of the source. Edit whatever makes it a distinct sibling."
        : "Author a brand-new record. Word, Shavian, POS and Dialect are required.";

    wrap.append(title, hint);
    return wrap;
}

function createFieldStack(ctx, record) {
    const stack = document.createElement("div");
    stack.className = "field-stack";
    stack.append(
        createField(ctx, "word", "Word (latin)", record.word),
        createField(ctx, "shaw", "Shavian", record.shaw, "shaw-field"),
        createField(ctx, "ipa", "IPA", record.ipa, "ipa-field"),
        createVariantRow(ctx, record),
    );
    return stack;
}

function createField(ctx, name, label, value, extraClass = "") {
    return fieldInput(name, label, value, extraClass, ctx.prefix).wrap;
}

function createVariantRow(ctx, record) {
    const row = document.createElement("div");
    row.className = "field-row";
    row.append(
        createField(ctx, "var", "Dialect (var)", record.var),
        createField(ctx, "pos", "POS", record.pos),
        attributesField(ctx, [record], new Set()),
    );
    return row;
}

function createActionBar(ctx) {
    const bar = document.createElement("div");
    bar.className = "actions create-actions";

    const accept = actionButton("accept", "Create", () => authorEntry(ctx, { flag: false }));
    const flag = actionButton("flag", "Flag", () => authorEntry(ctx, { flag: true }));
    accept.classList.add("create-verdict");
    flag.classList.add("create-verdict");
    bar.append(accept, flag, actionButton("undo", "Cancel", closeModal));

    const guard = document.createElement("p");
    guard.className = "create-guard";
    guard.dataset.state = "ok";
    bar.append(guard);
    return bar;
}

function missingRequiredFields(record) {
    return NEW_ENTRY_REQUIRED
        .filter(([field]) => !record[field])
        .map(([, label]) => label);
}

// The distinctness guard's identity: (word, pos, shaw, var), word CASE-SENSITIVE —
// "I" and "i" are distinct records, so a case-changed clone is legitimate. The daemon's
// anchor_key lowercases the word, so case-variants share an anchor key there; that is a
// read-side grouping (by_anchor holds a list; a manual record is keyed by its patch
// id), not a uniqueness constraint the guard must mirror. The one daemon uniqueness
// gate — one CANONICAL entry per (word_lower, pos, var) — is case-folded and still
// applies; canonicalRival mirrors it below.
function distinctnessKey(record) {
    return [
        record.word || "",
        record.pos || "",
        record.shaw || "",
        record.var || "",
    ].join("\0");
}

// Guard-sibling cache by lowercased word, so typing does not re-query per
// keystroke. `null` means the fetch is IN FLIGHT — treated as "checking", never as
// "distinct", so a duplicate is never waved through in the fetch window.
const relatedGuardCache = new Map();

function guardSiblings(word) {
    const key = (word || "").toLowerCase();
    if (!key) {
        return { pending: false, siblings: [] };
    }
    if (relatedGuardCache.has(key)) {
        const cached = relatedGuardCache.get(key);
        return cached === null
            ? { pending: true, siblings: [] }
            : { pending: false, siblings: cached.filter(isLiveSibling) };
    }
    relatedGuardCache.set(key, null);
    callDaemon({ op: "related", word })
        .then((result) => {
            relatedGuardCache.set(key, result.records);
            if (isCreateMode()) {
                evaluateDistinctness(state.modalEditor);
            }
        })
        .catch(() => relatedGuardCache.delete(key));
    return { pending: true, siblings: [] };
}

// A sibling occupies its anchor only while it is a LIVE record — a dropped or
// resurfaced-drop row has vacated it, so authoring the same anchor is legitimate.
function isLiveSibling(record) {
    return record.patch_state !== PATCH_STATE.DROPPED
        && !(record.patch_state === PATCH_STATE.ORPHANED
             && record.orphan_kind === ORPHAN_KIND.RESURFACED_DROP);
}

// Evaluate the distinctness guard LIVE. An EXACT live duplicate (word case-
// sensitive) HARD-BLOCKS the verdicts, as does a pending sibling fetch. A CANONICAL
// conflict (different-shaw accepted canonical on the same word/pos/var) only WARNS
// — authoring a competing candidate is legitimate. An incomplete anchor stays
// quiet (submit surfaces the precise message).
const BLOCKING_GUARD_STATES = new Set(["collision", "pending"]);

function evaluateDistinctness(ctx) {
    if (!ctx || ctx.mode !== CREATE_MODE) {
        return;
    }
    const record = harvestRecord(ctx);
    const guard = ctx.root.querySelector(".create-guard");
    const verdicts = ctx.root.querySelectorAll(".create-verdict");
    const status = distinctnessStatus(record);
    guard.dataset.state = status.state;
    guard.textContent = status.message;
    const blocked = BLOCKING_GUARD_STATES.has(status.state);
    for (const button of verdicts) {
        button.disabled = blocked;
    }
}

// Read off the guard element evaluateDistinctness already painted (the SOLE
// painter), so the keyboard Accept and the buttons share one source of truth.
function createVerdictBlocked(ctx) {
    const guard = ctx?.root?.querySelector(".create-guard");
    return Boolean(guard) && BLOCKING_GUARD_STATES.has(guard.dataset.state);
}

function distinctnessStatus(record) {
    if (missingRequiredFields(record).length) {
        return { state: "ok", message: "" };
    }
    const { pending, siblings } = guardSiblings(record.word);
    if (pending) {
        return { state: "pending", message: "Checking for an existing entry…" };
    }
    const key = distinctnessKey(record);
    if (siblings.some((sibling) => distinctnessKey(sibling) === key)) {
        return {
            state: "collision",
            message: `This entry already exists (${record.word} · ${record.pos} · ${record.var}). `
                + "Edit the Shavian, POS, dialect or letter case to make it distinct.",
        };
    }
    const rival = canonicalRival(record, siblings);
    if (rival) {
        return {
            state: "warn",
            message: `A canonical ${record.var} entry already exists for ${record.word}/${record.pos} `
                + `(${rival.shaw}). Flag one as a variant/merger, or author a competing candidate.`,
        };
    }
    return { state: "ok", message: "" };
}

// Mirrors editord ACCEPTED_STATES, for the canonical-conflict check.
const ACCEPTED_STATES = new Set([PATCH_STATE.ACCEPTED, PATCH_STATE.EDITED]);

// The daemon's one-canonical-per-(word,pos,var) rival (editord _canonical_conflict),
// mirrored client-side to WARN before the write.
function canonicalRival(record, siblings) {
    if (!isCanonicalRecord(record)) {
        return null;
    }
    return siblings.find((sibling) =>
        sibling.pos === record.pos
        && (sibling.var || "") === (record.var || "")
        && sibling.shaw !== record.shaw
        && isCanonicalRecord(sibling)
        && ACCEPTED_STATES.has(sibling.patch_state)) ?? null;
}

// No additive flag (empty mergers, not variant) — the daemon's _is_canonical.
function isCanonicalRecord(record) {
    return !(record.mergers && record.mergers.length) && !record.variant;
}

// Author a new entry (Create or Flag): {op:"patch", anchor:null, record, author,
// dirty:true} — dirty, so it lands UNREVIEWED, never born accepted. Flag re-authors
// the fresh record with op flag via `replaces` (create-then-flag). The distinctness
// guard already disabled the buttons on a collision; this validation is the
// belt-and-braces backstop.
async function authorEntry(ctx, { flag }) {
    const record = harvestRecord(ctx);
    const missing = missingRequiredFields(record);
    if (missing.length) {
        showToast(`Required: ${missing.join(", ")}.`, true);
        return;
    }
    let authored;
    try {
        authored = await callDaemon(
            { op: "patch", anchor: null, record, author: AUTHOR });
    } catch (error) {
        showToast(error.message, true);
        return;
    }
    // Surface the row NOW — even if the follow-up flag fails — so a written entry is
    // never stranded invisibly. The response carries EVERY record on the daemon's
    // case-folded anchor key (a case-variant sibling may ride along), so the new
    // entry is picked by its own patch id.
    closeModal();
    const created = authored.records.find((r) => r.patch_id === authored.id);
    insertAuthoredRecord(created);
    if (!flag) {
        showToast(`created · ${authored.result}`);
        return;
    }
    try {
        const flagged = await callDaemon(
            { op: "flag", anchor: null, author: AUTHOR, replaces: authored.id });
        applyWriteResult(flagged.records, created.anchor, { refocus: false });
        await refreshCommitStatus();
        await refreshPatchCounts();
        showToast(`flagged · ${flagged.result}`);
    } catch (error) {
        // The entry was created but not flagged — a loud, recoverable state: the row is
        // already on the workbench (unreviewed), so the owner can flag it from there.
        showToast(`created, but flag failed: ${error.message}`, true);
    }
}

// Place a freshly-authored record into the working set and land on it: it JOINS its
// group's run when that group is on the page (a group verdict must fan out to it),
// else it opens a fresh singleton group at the top. The daemon always returns the
// annotated record — an empty response, or one without its group token, is a
// contract violation and fails loud.
function insertAuthoredRecord(record) {
    if (!record) {
        throw new Error("daemon returned no record for the new entry.");
    }
    if (!record.group_key) {
        throw new Error("daemon returned no group key for the new entry.");
    }
    let at = 0;
    let run = null;
    for (const group of state.groups) {
        if (group.key === record.group_key) {
            run = group;
            break;
        }
        at += group.size;
    }
    if (run) {
        state.records.splice(at, 0, record);
        run.size += 1;
    } else {
        at = 0;
        state.records.unshift(record);
        state.groups.unshift({ key: record.group_key, size: 1 });
    }
    countDecision();
    renderLedger();
    select(at);
    saveSession();
    refreshCommitStatus();
    refreshPatchCounts();
}

async function single(action) {
    verdictInFlight = true;
    try {
        await action();
    } catch (error) {
        showToast(error.message, true);
    } finally {
        verdictInFlight = false;
    }
    await refreshCommitStatus();
    await refreshPatchCounts();
}

// Saving is IMPLICIT (auto-save on leave); this remains the explicit "save now,
// don't step" path (⌘Enter in a field) and the shared writePatch("saved") core the
// auto-save reuses. Inherently single-record — the group bar omits it.
async function saveSelected() {
    const ctx = activeContext();
    const selected = contextRecord(ctx);
    if (!selected) {
        return;
    }
    // A group's edits are committed only through an explicit verdict, never a save —
    // so ⌘Enter in a group panel does nothing.
    if (ctx.group.length > 1) {
        return;
    }
    const record = harvestRecord(ctx);
    if (!requireShaw(record) || !requireFreq(record)) {
        return;
    }
    // Saving persists the edit but does NOT accept it — a save is DIRTY, exactly
    // like auto-save on leave. Only the explicit Accept verdict reviews/ships.
    await single(() => writePatch(anchorOf(selected), record, "saved", selected, { dirty: true }));
}

// Set while a single-record verdict runs (see single()); auto-save skips while it is
// set, so a verdict's own step/select leave is never double-written.
let verdictInFlight = false;

// Auto-save the main detail edit when focus is about to leave it. Fires ONLY when a
// field genuinely changed; the write targets the leaving record's OWN anchor, so it
// is independent of wherever the cursor lands next.
function autoSaveMainEdit() {
    if (verdictInFlight || isModalEditorOpen()) {
        return;
    }
    const ctx = state.mainContext;
    if (!ctx || ctx.mode === CREATE_MODE || !contextRecord(ctx)) {
        return;
    }
    // A group edit has no single record to auto-save (its "multiple" boxes read
    // empty and would spuriously fail requireShaw); group edits commit only through
    // an explicit verdict.
    if (ctx.group.length > 1) {
        return;
    }
    // Only trust a harvest while the context's inputs still describe its record;
    // the post-write lag path runs under verdictInFlight, excluded above.
    if (!mainEditIsDirty(ctx)) {
        return;
    }
    const selected = contextRecord(ctx);
    const record = harvestRecord(ctx);
    if (!requireShaw(record) || !requireFreq(record)) {
        // Invalid Shavian/frequency: leave the edit unsaved (the toast says why);
        // navigation still proceeds.
        return;
    }
    // Fire-and-forget: navigation is synchronous and must not block on the daemon. The
    // write hits the leaving record's anchor, so it can't race the record we land on.
    (async () => {
        try {
            await writePatch(anchorOf(selected), record, "saved", selected, {
                step: false,
                refocus: false,
                dirty: true,
            });
        } catch (error) {
            showToast(error.message, true);
        }
        await refreshCommitStatus();
        await refreshPatchCounts();
    })();
}

function mainEditIsDirty(ctx) {
    const record = contextRecord(ctx);
    const harvested = harvestRecord(ctx);
    for (const name of EDITABLE_FIELDS) {
        if (String(harvested[name] ?? "") !== String(record[name] ?? "").trim()) {
            return true;
        }
    }
    const wasMergers = record.mergers ? [...record.mergers].sort() : [];
    const nowMergers = harvested.mergers ? [...harvested.mergers].sort() : [];
    if (wasMergers.join(" ") !== nowMergers.join(" ")) {
        return true;
    }
    if (Boolean(record.variant) !== Boolean(harvested.variant)) {
        return true;
    }
    return false;
}

function verdictGroup(ctx) {
    if (!ctx || !ctx.group) {
        return [];
    }
    // A modal edit acts on its own group, which need not sit in state.records —
    // trust it directly. The main context's group narrows to what is still live.
    if (ctx === state.modalEditor) {
        return ctx.group;
    }
    const live = new Set(state.records.map((record) => anchorKey(record.anchor)));
    return ctx.group.filter((member) => live.has(anchorKey(member.anchor)));
}

// Run a verdict over the active context's group. The overlay — the fields the owner
// actually touched — is harvested ONCE and applied per member, so untouched fields
// keep each member's own value.
async function groupVerdict(verb, applyOne, { step = true } = {}) {
    const ctx = activeContext();
    const group = verdictGroup(ctx);
    if (!group.length) {
        return;
    }
    const overlay = harvestGroupOverlay(ctx);
    if (group.length === 1) {
        await single(() => applyOne(group[0], { step, toast: true, overlay, ctx }));
        return;
    }
    await runGroup(verb, applyOne, group, overlay, ctx);
}

async function acceptSelected() {
    await groupVerdict("accept", acceptOne);
}

async function acceptOne(selected, options = {}) {
    const record = groupMemberRecord(selected, options.overlay, options.ctx);
    record.status = ACCEPTED_STATUS;
    if (!record.shaw) {
        throw new Error(`${selected.word}: Shavian cannot be empty.`);
    }
    if (record.freq === null) {
        throw new Error(`${selected.word}: frequency must be a whole number.`);
    }
    return writePatch(anchorOf(selected), record, "accepted", selected, options);
}

async function dropSelected() {
    await groupVerdict("dropped", dropOne);
}

// Drop one record. A manual entry has no basis to revert to, so dropping it IS
// deleting its authorship patch (same as Clear); a basis record gets a drop patch.
async function dropOne(selected, options = {}) {
    if (isManual(selected)) {
        if (!selected.patch_id) {
            throw new Error(`${selected.word}: manual entry has no patch id.`);
        }
        return unpatch(null, "dropped", { ...options, patchId: selected.patch_id });
    }
    return writePatch(anchorOf(selected), null, "dropped", selected, options);
}

// A verdict produces a patch: records an undo frame and re-annotates the row in
// place. `step`/`toast` are off per record in a group run. Throws on failure so the
// group loop can fail loud per record.
async function writePatch(anchor, record, verb, selected, { step = true, toast = true, refocus = true, dirty = false, deferRender = false } = {}) {
    const priorReviewed = selected ? selected.reviewed : false;
    // A bare edit persisted on navigate is DIRTY (op="edit" server-side) — recorded
    // but not reviewed or shipped; only an explicit Accept writes op="accept". A
    // manual edit stays authorship (re-authored in place, anchor null), never
    // auto-accepted by leaving the row.
    const request = isManual(selected)
        ? { op: "patch", anchor: null, record, author: AUTHOR, replaces: selected.patch_id, dirty }
        : { op: "patch", anchor, record, author: AUTHOR, dirty };
    const result = await callDaemon(request);
    pushUndo(anchor, priorReviewed);
    countDecision();
    applyWriteResult(result.records, anchor, { step, refocus, deferRender });
    if (toast) {
        showToast(`${verb} · ${result.result}`);
    }
    return result;
}

// Flag: "looked at, no verdict yet" — counts as reviewed but not decided; a no-op
// for production output.
async function flagSelected() {
    await groupVerdict("flagged", flagOne);
}

async function flagOne(selected, { step = true, toast = true, refocus = true, deferRender = false } = {}) {
    const priorReviewed = selected.reviewed;
    const request = isManual(selected)
        ? { op: "flag", anchor: null, author: AUTHOR, replaces: selected.patch_id }
        : { op: "flag", anchor: anchorOf(selected), author: AUTHOR };
    const result = await callDaemon(request);
    pushUndo(anchorOf(selected), priorReviewed);
    applyWriteResult(result.records, anchorOf(selected), { step, refocus, deferRender });
    if (toast) {
        showToast(`flagged · ${result.result}`);
    }
    return result;
}

// Unflag: revert to unreviewed — an explicit "actually, back to the pool".
async function unflagSelected() {
    const selected = contextRecord(activeContext());
    if (!selected || selected.patch_state !== PATCH_STATE.FLAGGED) {
        return;
    }
    // A manual entry has no basis row to revert to (deleting its flag patch would
    // delete the record): re-author it DIRTY instead — back to the unreviewed
    // verdict, record kept, awaiting review like any other row.
    if (isManual(selected)) {
        await single(() => writePatch(anchorOf(selected), recordFields(selected),
            "unflagged", selected, { step: false, dirty: true }));
        return;
    }
    await single(() => unpatch(anchorOf(selected), "unflagged", { step: false }));
}

// Clear: delete WHATEVER patch the entry holds (any op, any session), reverting a
// basis record to its untouched source or removing a manual record outright (by
// patch id — a manual record has no anchor).
async function clearSelected() {
    // Clear reverts in place (it does not advance the review cursor to a next record).
    await groupVerdict("cleared", clearOne, { step: false });
}

// A record a group verdict passed over without writing (e.g. Clear on an unreviewed
// row) — tallied apart from the writes so the summary count is honest.
const GROUP_SKIPPED = Symbol("bulk-skipped");

// Only a truly unreviewed record holds no patch to clear. A dirty record is
// unreviewed BY VERDICT but carries an unshipped edit patch, which Clear deletes
// like any other (the reviewed bit would wrongly skip it).
async function clearOne(selected, options = {}) {
    if (selected.patch_state === PATCH_STATE.UNREVIEWED) {
        return GROUP_SKIPPED;
    }
    if (isManual(selected)) {
        if (!selected.patch_id) {
            throw new Error(`${selected.word}: manual entry has no patch id.`);
        }
        return unpatch(null, "cleared", { ...options, patchId: selected.patch_id });
    }
    return unpatch(anchorOf(selected), "cleared", options);
}

// ---- group verdicts (N>=2) ----
// Each member goes through the SAME single-write path as a single verdict, with
// stepping/toasts/re-render off; one summary toast and one ledger refresh at the
// end. A member that fails is collected and reported, never silently skipped — the
// run continues so one bad row doesn't strand the rest.

const GROUP_CONFIRM_THRESHOLD = 10;

async function runGroup(verb, applyOne, group, overlay, ctx) {
    if (group.length >= GROUP_CONFIRM_THRESHOLD
        && !window.confirm(`${capitalise(verb)} ${group.length} records?`)) {
        return;
    }
    const focusedAnchor = state.records[state.selected]?.anchor ?? null;
    let done = 0;
    let skipped = 0;
    const failures = [];
    for (const member of group) {
        try {
            const outcome = await applyOne(member, {
                overlay, ctx, step: false, toast: false, refocus: false, deferRender: true,
            });
            if (outcome === GROUP_SKIPPED) {
                skipped += 1;
            } else {
                done += 1;
            }
        } catch (error) {
            failures.push(error.message);
        }
    }
    // Clear the set silently — the DOM may be out of step mid-run (deferred
    // re-render); the one authoritative rebuild is refreshAfterBulk. A modal-scope
    // run triaged the MODAL's group, so the workbench pick stays.
    if (ctx.scope !== "modal") {
        state.multi.clear();
        state.lastToggledKey = null;
        state.touchMulti = false;
    }
    refreshAfterBulk(focusedAnchor);
    reportBulk(verb, done, skipped, failures);
    await refreshCommitStatus();
    await refreshPatchCounts();
}

// Rebuild the ledger once after a group run and restore the cursor — or its nearest
// surviving neighbour. A cursor whose record re-folds into a COLLAPSED group is
// restored as that group's HEADER stop (select() would auto-expand the fold).
function refreshAfterBulk(focusedAnchor) {
    // The partition is fixed at materialise time, so a group run only re-annotated
    // members in place; expansion state stays valid.
    renderLedger();
    let index = focusedAnchor
        ? state.records.findIndex((r) => sameAnchor(r.anchor, focusedAnchor))
        : state.selected;
    if (index < 0) {
        index = Math.min(state.selected, state.records.length - 1);
    }
    // A verdict never re-keys a group, so a whole-group verdict on a collapsed group
    // lands back on its header, fold untouched.
    const fold = groupOfIndex(index);
    if (fold && fold.members.length >= 2 && !state.groupsExpanded.has(fold.key)) {
        selectStop({ group: fold });
    } else {
        select(index);
    }
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

// Undo: if the last decision created a patch, delete it to restore the untouched
// source. If the anchor already had a patch before, we cannot faithfully restore it
// from the client — surface that and leave the current patch (the honest behaviour).
async function undoLast() {
    const frame = session.undoStack.pop();
    if (!frame) {
        showToast("Nothing to undo.", true);
        return;
    }
    if (frame.priorReviewed) {
        showToast("Can't undo: the entry already had a decision before this one.", true);
        renderGroupEditor(selectedGroup());
        return;
    }
    const index = state.records.findIndex((r) => sameAnchor(r.anchor, frame.anchor));
    if (index >= 0) {
        state.selected = index;
    }
    await single(() => unpatch(frame.anchor, "undone", { step: false, uncount: true }));
}

// Delete an entry's patch. The removed anchor (an authored entry the daemon returns
// nothing for) is dropped by anchor, not by state.selected, so it works whether or
// not it is the focused row.
async function unpatch(anchor, verb, { step = true, uncount = false, patchId = null, toast = true, refocus = true, deferRender = false } = {}) {
    const request = patchId ? { op: "unpatch", patch_id: patchId } : { op: "unpatch", anchor };
    const result = await callDaemon(request);
    if (uncount) {
        session.decisions = Math.max(0, session.decisions - 1);
    }
    if (!result.records.length) {
        removeRow(anchor ?? findAnchorByPatchId(patchId), { refocus, deferRender });
    } else {
        applyWriteResult(result.records, anchor, { step, refocus, deferRender });
    }
    if (toast) {
        showToast(`${verb} · ${result.result}`);
    }
    return result;
}

function findAnchorByPatchId(patchId) {
    const record = state.records.find((r) => r.patch_id === patchId);
    return record ? record.anchor : null;
}

// Clearing an authored entry leaves no record — drop that row from the working set.
// A removal from an edit-modal targets the modal record's anchor — NEVER
// state.selected — and closes the modal. `deferRender` is accepted for call-site
// symmetry with the write path but a removal already defers its render via
// refocus:false.
function removeRow(anchor, { refocus = true, deferRender = false } = {}) {
    if (isModalEditorOpen()) {
        removeModalRow(contextRecord(state.modalEditor).anchor);
        return;
    }
    const removed = anchor
        ? state.records.findIndex((r) => sameAnchor(r.anchor, anchor))
        : state.selected;
    if (removed < 0) {
        return;
    }
    state.multi.delete(anchorKey(state.records[removed].anchor));
    shrinkGroupAt(removed);
    state.records.splice(removed, 1);
    if (removed < state.selected) {
        state.selected -= 1;
    }
    refreshPacing();
    if (refocus) {
        renderLedger();
        select(Math.min(state.selected, state.records.length - 1));
    }
}

function removeModalRow(anchor) {
    const removed = state.records.findIndex((r) => sameAnchor(r.anchor, anchor));
    if (removed >= 0) {
        state.multi.delete(anchorKey(anchor));
        shrinkGroupAt(removed);
        state.records.splice(removed, 1);
        if (removed <= state.selected) {
            state.selected = Math.max(0, state.selected - 1);
        }
        refreshPacing();
        renderLedger();
        paintLedgerSelection();
    }
    closeModal();
    reloadRelatedForDetail();
}

function pushUndo(anchor, priorReviewed) {
    session.undoStack.push({ anchor, priorReviewed });
}

function countDecision() {
    session.decisions += 1;
    refreshPacing();
}

// The write response returns EVERY record on the daemon's case-folded anchor key (a
// case-variant sibling may ride along), so the written row is picked by `anchor`.
// The row updates IN PLACE — it keeps its index even if it no longer matches the
// filter. A write from an edit-modal never steps or re-selects: the main row
// refreshes by anchor, the main cursor/scroll never moves.
function applyWriteResult(records, anchor, { step: doStep = true, refocus = true, deferRender = false } = {}) {
    const replacement = records.find((r) => sameAnchor(r.anchor, anchor));
    // Place the re-annotated record on its OWN row (by anchor), not blindly on
    // state.selected — the affected row may not be the selected one.
    const index = replacement
        ? state.records.findIndex((r) => sameAnchor(r.anchor, replacement.anchor))
        : state.selected;
    if (replacement && index >= 0) {
        state.records[index] = replacement;
        // The partition is the daemon's, fixed at materialise time: even an edit that
        // moves a grouping axis re-groups only on the next re-query. A group run
        // (deferRender) defers its one rebuild to refreshAfterBulk.
        if (!deferRender) {
            renderLedger();
            paintLedgerSelection();
        }
    }
    refreshPacing();
    if (isModalEditorOpen()) {
        // In the edit modal the verdict IS the dismiss — no separate save-then-close.
        closeModal();
        reloadRelatedForDetail();
        return;
    }
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

// The keyboard cursor's stops, in RENDER order, derived from the SAME partition
// renderLedger paints — stepping can never disagree with the screen. A collapsed
// group is ONE stop; an expanded group is its header stop then each child.
function cursorStops() {
    const stops = [];
    for (const group of ledgerGroups()) {
        if (group.members.length === 1) {
            stops.push({ index: group.members[0].index });
            continue;
        }
        stops.push({ group });
        if (state.groupsExpanded.has(group.key)) {
            for (const member of group.members) {
                stops.push({ index: member.index });
            }
        }
    }
    return stops;
}

// The stop the cursor sits on, or -1. A claimed header (cursorGroupKey) wins — it
// distinguishes "on the header" from "on the first child" of an EXPANDED group,
// where both stops exist for one working-set index.
function currentStopIndex(stops) {
    if (state.cursorGroupKey !== null) {
        const at = stops.findIndex(
            (stop) => stop.group && stop.group.key === state.cursorGroupKey);
        if (at >= 0) {
            return at;
        }
        // The claimed group is gone (re-queried away, or emptied by a removal)
        // — fall through to the record search.
    }
    if (state.selected < 0) {
        return -1;
    }
    const recordAt = stops.findIndex(
        (stop) => !stop.group && stop.index === state.selected);
    if (recordAt >= 0) {
        return recordAt;
    }
    return stops.findIndex((stop) => stop.group
        && stop.group.members.some((entry) => entry.index === state.selected));
}

// Land the cursor on a stop through the path the equivalent mouse gesture uses.
// A group stop with no pick live mirrors a plain header click (selectWholeGroup);
// with a live pick it is a pure cursor move, claiming nothing, so stepping never
// clobbers a hand-made selection. state.selected anchors on the group's first
// member so index-keyed flows stay valid.
function selectStop(stop) {
    if (!stop.group) {
        select(stop.index);
        return;
    }
    state.selected = stop.group.members[0].index;
    if (state.multi.size) {
        autoSaveMainEdit();
        paintLedgerSelection();
    } else {
        state.cursorGroupKey = stop.group.key;
        paintLedgerSelection();
        selectWholeGroup(stop.group, false);
    }
    const header = rowByGroupKey(stop.group.key);
    if (header) {
        header.scrollIntoView({ block: "nearest" });
    }
    saveSession();
}

function step(delta) {
    const stops = cursorStops();
    if (!stops.length) {
        return;
    }
    const at = currentStopIndex(stops);
    const target = at < 0
        ? stops[0]
        : stops[Math.min(stops.length - 1, Math.max(0, at + delta))];
    const departed = at >= 0 ? stops[at] : null;
    if (target === departed) {
        rollPage(delta);
        return;
    }
    // Stepping OFF a header the cursor claimed dissolves the group-as-unit selection
    // that landing created — it was the cursor's own, not an owner pick (a hand-made
    // pick clears the claim at mutation time, so it rides through untouched).
    if (departed && departed.group && state.cursorGroupKey === departed.group.key) {
        state.multi.clear();
        state.lastToggledKey = null;
        state.cursorGroupKey = null;
    }
    selectStop(target);
}

function pageAvailable(delta) {
    return delta < 0 ? state.offset > 0 : state.offset + state.limit < state.total;
}

// Stepping past either end of the page rolls into the neighbouring one. Keys and
// nav buttons share step(), so BOTH roll. A roll re-runs the working query — a
// fresh working set, so the multi-selection, group expansions and any rows the
// current filter no longer matches reset, exactly as the footer page buttons do.
let pageRollInFlight = false;
function rollPage(delta) {
    if (pageRollInFlight || !pageAvailable(delta)) {
        return;
    }
    pageRollInFlight = true;
    const targetOffset = delta < 0
        ? Math.max(0, state.offset - state.limit)
        : state.offset + state.limit;
    runQuery(targetOffset)
        .then(() => {
            // runQuery lands on the page's first record; rolling BACKWARD must
            // land on its LAST stop instead, through the same path a step uses.
            const stops = cursorStops();
            if (delta < 0 && stops.length) {
                selectStop(stops[stops.length - 1]);
            }
        })
        .catch((error) => showToast(error.message, true))
        .finally(() => { pageRollInFlight = false; });
}

function setCursorGroupExpanded(expand) {
    const group = groupOfIndex(state.selected);
    if (!group || state.groupsExpanded.has(group.key) === expand) {
        return;
    }
    if (expand && group.members.length < 2) {
        return;
    }
    toggleGroupExpanded(group.key);
}

// Enter edit mode on the context that owns the screen. `focusShaw` is wanted ONLY
// from the "E" shortcut: a field's own focus listener and a variation toggle must
// NOT yank the caret into shaw (which would swallow the next review key).
function enterEdit(ctx, { focusShaw = false } = {}) {
    if (isCreateMode(ctx) || (ctx === state.mainContext && state.selected < 0)) {
        return;
    }
    if (!focusShaw) {
        return;
    }
    const shaw = ctx.root.querySelector('[data-field="shaw"]');
    if (shaw && document.activeElement !== shaw
        && !ctx.root.contains(document.activeElement)) {
        shaw.focus();
        shaw.setSelectionRange(shaw.value.length, shaw.value.length);
    }
}

function exitEdit(ctx) {
    if (ctx.root.contains(document.activeElement)) {
        document.activeElement.blur();
    }
}

function onFieldKey(event) {
    if (event.key === "Escape") {
        event.preventDefault();
        exitEdit(activeContext());
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

const REVIEW_KEYS = {
    a: acceptSelected,
    x: dropSelected,
    e: () => enterEdit(activeContext(), { focusShaw: true }),
    f: flagSelected,
    c: clearSelected,
    u: undoLast,
    v: toggleFocusedSelection,
    j: () => step(1),
    k: () => step(-1),
    arrowdown: () => step(1),
    arrowup: () => step(-1),
    arrowright: () => setCursorGroupExpanded(true),
    arrowleft: () => setCursorGroupExpanded(false),
    "+": () => setCursorGroupExpanded(true),
    "=": () => setCursorGroupExpanded(true),
    "-": () => setCursorGroupExpanded(false),
    _: () => setCursorGroupExpanded(false),
    "?": () => toggleCheatsheet(),
};

// Keys that mutate must not double-fire on auto-repeat when a key is held.
const NON_REPEAT_KEYS = new Set(["a", "x", "f", "c", "u", "v"]);

// The review keys an edit-mode modal honours. Navigation (j/k/arrows) and bulk
// selection (v) are omitted — a modal reviews its own records, not the main cursor
// or selection. Undo (u) walks the global undo stack and moves the main cursor, so
// it belongs to the main flow only; Clear (c) is the modal's in-place reset.
const MODAL_REVIEW_KEYS = new Set(["a", "x", "e", "f", "c"]);

// A create modal takes only Escape (Cancel) and Enter (author — honouring the
// distinctness guard, exactly as the disabled button does). An edit modal mirrors
// the main review flow scoped to the modal record: field-focused keys stay the
// field's own (onFieldKey); otherwise verdict keys act via activeContext().
function handleModalKey(event) {
    if (isCreateMode()) {
        if (event.key === "Escape") {
            event.preventDefault();
            closeModal();
        } else if (event.key === "Enter") {
            event.preventDefault();
            if (!createVerdictBlocked(state.modalEditor)) {
                authorEntry(state.modalEditor, { flag: false });
            }
        }
        return;
    }
    if (event.target instanceof Element && event.target.matches("input, select, textarea")) {
        return;
    }
    if (event.key === "Escape") {
        event.preventDefault();
        closeModal();
        return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
    }
    const key = event.key.toLowerCase();
    if (!MODAL_REVIEW_KEYS.has(key)) {
        return;
    }
    if (event.repeat && NON_REPEAT_KEYS.has(key)) {
        return;
    }
    event.preventDefault();
    REVIEW_KEYS[key]();
}

function onGlobalKey(event) {
    if (isCheatsheetOpen()) {
        if (event.key === "Escape" || event.key === "?") {
            event.preventDefault();
            toggleCheatsheet(false);
        }
        return;
    }
    if (isDefinitionModalOpen()) {
        if (event.key === "Escape"
            && !(event.target instanceof Element
                 && event.target.matches("input, select, textarea"))) {
            event.preventDefault();
            closeDefinitionModal();
        }
        return;
    }
    if (isModalEditorOpen()) {
        handleModalKey(event);
        return;
    }
    if (event.target instanceof Element && event.target.matches("input, select, textarea")) {
        return;
    }
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
const SHORTCUT_GROUPS = [
    {
        heading: "Review actions",
        rows: [
            { keys: ["A"], state: "accepted", action: "Accept — promote & step on" },
            { keys: ["X"], state: "dropped", action: "Drop — reject & step on" },
            { keys: ["F"], state: "flagged", action: "Flag — looked at, no verdict yet" },
            { keys: ["E"], state: null, action: "Edit — focus the Shavian field (auto-saves on leave)" },
            { keys: ["C"], state: "unreviewed", action: "Clear — delete the patch, back to unreviewed" },
        ],
    },
    {
        heading: "Navigation",
        rows: [
            { keys: ["J", "K"], state: null, action: "Step next / previous" },
            { keys: ["↑", "↓"], state: null, action: "Step next / previous" },
            { keys: ["→", "+"], state: null, action: "Expand the focused group" },
            { keys: ["←", "-"], state: null, action: "Collapse the focused group" },
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
            { keys: ["⌘", "Enter"], state: null, action: "Save now, stay on this entry (in a field)" },
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

// Meaningful only while the active Review filter is exactly "unreviewed".
// GROUP-denominated, like the total it nets against: a group is decided once every
// member is.
function countUnreviewedRemaining() {
    const review = state.filters.review;
    if (!Array.isArray(review) || review.length !== 1 || review[0] !== PATCH_STATE.UNREVIEWED) {
        return null;
    }
    const decidedInSet = ledgerGroups().filter((group) =>
        group.members.every(({ record }) =>
            record.reviewed && record.patch_state !== PATCH_STATE.FLAGGED),
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

// Session continuity keys on the focused entry's ANCHOR — not a row index, which is
// meaningless once the list re-materialises.
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

// Adopt a saved session's chips, dropping entries whose field the registry no
// longer knows and values outside the field's current vocabulary — a retired value
// would otherwise wedge the session: the daemon rejects it loudly and its checkbox
// no longer exists to unpick. Pinned fields are folded back in.
function restoreActiveFilters(activeFilters) {
    const known = activeFilters
        .filter((entry) => FIELD_REGISTRY.has(entry.field))
        .map((entry) => sanitizeRestoredEntry(entry));
    state.activeFilters = withPinnedFilters(known);
    renderChipStrip();
}

function sanitizeRestoredEntry(entry) {
    const spec = fieldSpec(entry.field);
    if (spec.kind !== "categorical") {
        return entry;
    }
    // Review values MIGRATE before the vocabulary filter: a session saved when
    // edited/dirty were their own chips collapses onto the verdict chips that now
    // cover them, instead of being dropped as retired vocabulary.
    const vocabulary = new Set(spec.entries.map((option) => option.value));
    return {
        ...entry,
        value: restoredFacetValues(entry.field, entry.value)
            .filter((value) => vocabulary.has(value)),
        mode: entry.mode === "all" ? "all" : "any",
    };
}

function setDrawer(open) {
    WORKBENCH.classList.toggle("drawer-open", open);
    DRAWER_TOGGLE.setAttribute("aria-expanded", String(open));
}

function toggleDrawer() {
    setDrawer(!WORKBENCH.classList.contains("drawer-open"));
}

// ---- ledger/detail splitter ----
// Ported from the shave GUI's splitter idiom: a pointer-captured drag persisting as
// a FRACTION of the container width. Wide screens only — the mobile drawer layout
// hides the splitter and replaces the grid template in CSS.

// In-memory shadow of SPLIT_FRACTION_KEY so resize re-apply never re-parses storage.
let splitFraction = null;

function workbenchPx(property) {
    return parseFloat(getComputedStyle(WORKBENCH).getPropertyValue(property)) || 0;
}

// Clamped so neither pane dips below its floor (--ledger-min / --detail-min).
// Returns the fraction actually applied, so callers persist what was applied rather
// than reading the layout back.
function applyLedgerWidth(width) {
    const total = WORKBENCH.getBoundingClientRect().width;
    // Not laid out yet (0-width container) → no meaningful fraction to compute or
    // persist; bail rather than divide by zero into a NaN/Infinity width.
    if (total <= 0) {
        return null;
    }
    const splitterWidth = SPLITTER.getBoundingClientRect().width;
    const widest = total - splitterWidth - workbenchPx("--detail-min");
    const clamped = Math.max(workbenchPx("--ledger-min"), Math.min(width, widest));
    WORKBENCH.style.setProperty("--ledger-w", clamped + "px");
    return clamped / total;
}

// Re-applied on every window resize. Skipped on narrow viewports — the drawer
// layout ignores --ledger-w, so applying would only thrash layout.
function applySavedSplit() {
    if (splitFraction === null || window.innerWidth <= NARROW_BREAKPOINT_PX) {
        return;
    }
    applyLedgerWidth(splitFraction * WORKBENCH.getBoundingClientRect().width);
}

// Apply and persist are separate so the boot-time restore doesn't write the stored
// value straight back.
function applyLedgerCollapsed(collapsed) {
    WORKBENCH.classList.toggle("ledger-collapsed", collapsed);
}

function setLedgerCollapsed(collapsed) {
    applyLedgerCollapsed(collapsed);
    localStorage.setItem(LEDGER_COLLAPSED_KEY, collapsed ? "1" : "0");
}

function initWorkbenchSplitter() {
    const handle = SPLITTER.querySelector(".splitter-handle");
    let dragPointer = null;
    let dragStartX = 0;
    let dragStartWidth = 0;
    // The last fraction this drag applied; null until the pointer moves, so a
    // press-and-release without movement never overwrites the stored split.
    let dragFraction = null;

    handle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) {
            return;
        }
        dragPointer = event.pointerId;
        dragStartX = event.clientX;
        dragStartWidth = LEDGER_PANE.getBoundingClientRect().width;
        dragFraction = null;
        SPLITTER.classList.add("dragging");
        handle.setPointerCapture(event.pointerId);
        event.preventDefault();
    });
    handle.addEventListener("pointermove", (event) => {
        if (dragPointer !== event.pointerId) {
            return;
        }
        dragFraction = applyLedgerWidth(dragStartWidth + event.clientX - dragStartX);
    });
    const endDrag = (event) => {
        if (dragPointer !== event.pointerId) {
            return;
        }
        dragPointer = null;
        SPLITTER.classList.remove("dragging");
        if (dragFraction !== null) {
            splitFraction = dragFraction;
            localStorage.setItem(SPLIT_FRACTION_KEY, dragFraction.toFixed(4));
        }
    };
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);

    SPLITTER.addEventListener("dblclick", () => setLedgerCollapsed(true));
    LEDGER_RAIL.addEventListener("click", () => setLedgerCollapsed(false));
    window.addEventListener("resize", applySavedSplit);

    const stored = parseFloat(localStorage.getItem(SPLIT_FRACTION_KEY));
    splitFraction = Number.isFinite(stored) && stored > 0 && stored < 1 ? stored : null;
    applySavedSplit();
    applyLedgerCollapsed(localStorage.getItem(LEDGER_COLLAPSED_KEY) === "1");
}

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

function collapseFiltersOnNarrow() {
    setFiltersOpen(window.innerWidth > NARROW_BREAKPOINT_PX);
}

let toastTimer = null;
function showToast(message, isError = false) {
    TOAST.textContent = message;
    TOAST.classList.toggle("error", isError);
    TOAST.classList.add("show");
    clearTimeout(toastTimer);
    if (isError) return; // errors stay up (readable, copyable) until tapped away
    toastTimer = setTimeout(() => TOAST.classList.remove("show"), 2400);
}

TOAST.addEventListener("click", () => {
    // A click that ends a text selection is a copy, not a dismissal.
    if (window.getSelection().toString()) return;
    TOAST.classList.remove("show");
});

// ---- commit ----
// The daemon is the single source of truth for the uncommitted count
// (patches.jsonl lines not yet in HEAD), refreshed on boot and after every write.

// Commit lives in the ⋯ menu; the dot on its trigger is the always-visible
// prompt that uncommitted work exists.
function paintCommitButton(uncommitted) {
    const count = Number.isFinite(uncommitted) ? uncommitted : 0;
    COMMIT_DECISIONS.textContent = count > 0
        ? `Commit ${count.toLocaleString()} decision${count === 1 ? "" : "s"}`
        : "Commit";
    COMMIT_DECISIONS.disabled = count === 0;
    COMMIT_DECISIONS.hidden = false;
    MASTHEAD_MENU.classList.toggle("uncommitted", count > 0);
}

// Committing is unavailable on a tarball deploy (no repo) — commit_available:false
// HIDES the button silently (a state, not an error). A genuine status failure is
// advisory, so it hides the button quietly rather than toasting on every write.
async function refreshCommitStatus() {
    try {
        const status = await callDaemon({ op: "commit_status" });
        if (status.commit_available === false) {
            hideCommitButton();
            return;
        }
        paintCommitButton(status.uncommitted);
    } catch (_error) {
        hideCommitButton();
    }
}

function hideCommitButton() {
    COMMIT_DECISIONS.hidden = true;
    MASTHEAD_MENU.classList.remove("uncommitted");
}

// ---- patch counts ----
// Lives independently of the Commit button so it survives a repo-less tarball
// deploy, where Commit is hidden. Counted from patches.jsonl, never git.

function paintPatchCounts(counts) {
    if (!counts || !Number.isFinite(counts.total)) {
        PATCH_COUNTS.textContent = "";
        return;
    }
    const total = counts.total.toLocaleString();
    const today = Number.isFinite(counts.today) ? counts.today : 0;
    const totalLine = document.createElement("span");
    totalLine.textContent = `${total} patch${counts.total === 1 ? "" : "es"}`;
    const todayLine = document.createElement("span");
    todayLine.className = "today-count";
    todayLine.textContent = `${today.toLocaleString()} today`;
    PATCH_COUNTS.replaceChildren(totalLine, todayLine);
}

// Advisory: a failure clears the element quietly rather than toasting.
async function refreshPatchCounts() {
    try {
        paintPatchCounts(await callDaemon({ op: "patch_counts" }));
    } catch (_error) {
        PATCH_COUNTS.textContent = "";
    }
}

async function commitDecisions() {
    // The fetch has NO client-side timeout: it holds until the daemon's real
    // answer (the CGI gives the commit op a matching long socket timeout), then
    // renders success/failure from the actual result — never a guessed toast.
    COMMIT_DECISIONS.disabled = true;
    COMMIT_DECISIONS.textContent = "Committing…";
    try {
        const result = await callDaemon({ op: "commit" });
        if (result.result === "nothing-to-commit") {
            showToast("Nothing to commit.");
            paintCommitButton(0);
            return;
        }
        // The commit is durable locally even when the off-host push fails, so a
        // push failure is a warning (committed, but not synced), not an error.
        if (result.pushed === false) {
            showToast(`Committed ${result.sha}, but push failed: ${result.push_error}`, true);
        } else {
            showToast(`Committed & pushed ${result.message} · ${result.sha}`);
        }
    } catch (error) {
        showToast(error.message, true);
    }
    await refreshCommitStatus();
}

// Live filtering: checkboxes commit on `change`; free-text/numeric inputs debounce.
// Re-running the filter IS the pull-and-refresh re-sync point.
const FILTER_DEBOUNCE_MS = 250;

// The signature of the query currently materialised, so a no-op event (focus churn,
// a no-op keystroke) does not re-fire it. runQuery() stamps it.
let materialisedSignature = null;

// A canonical string for a query: facet keys and each facet's array are sorted, so
// [a,b] and [b,a] compare equal. Column sort is deliberately NOT in the signature —
// a sort-only change re-pulls directly, bypassing the guard (see onSortHeaderClick).
function querySignature(filters) {
    const canonical = {};
    for (const key of Object.keys(filters).sort()) {
        const value = filters[key];
        canonical[key] = Array.isArray(value) ? [...value].sort() : value;
    }
    return JSON.stringify(canonical);
}

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
// context); swallow the submit.
FILTER_FORM.addEventListener("submit", (event) => event.preventDefault());

// The refresh affordance re-pulls UNCONDITIONALLY — bypassing the signature guard —
// the deliberate "drop the rows I have reviewed and refill from the pool" gesture.
// Cancel a pending debounce so the two do not race.
REFRESH_RESULTS.addEventListener("click", () => {
    clearTimeout(filterDebounceTimer);
    runFilterQuery();
});

DRAWER_TOGGLE.addEventListener("click", toggleDrawer);
DRAWER_BACKDROP.addEventListener("click", () => setDrawer(false));
initWorkbenchSplitter();
FILTERS_TOGGLE.addEventListener("click", toggleFilters);
HELP_TOGGLE.addEventListener("click", () => toggleCheatsheet(true));
NEW_ENTRY.addEventListener("click", openCreateForm);
COMMIT_DECISIONS.addEventListener("click", () => commitDecisions());
CREATE_MODAL.addEventListener("click", (event) => {
    if (event.target === CREATE_MODAL) {
        if (isDefinitionModalOpen()) {
            closeDefinitionModal();
        } else {
            closeModal();
        }
    }
});
ADD_FILTER.addEventListener("click", () => toggleAddMenu());
// A click on any masthead-menu item closes the menu after the item's own handler
// has run (bubbling order).
MASTHEAD_MENU.addEventListener("click", () => togglePicker(MASTHEAD_MENU_PANEL, MASTHEAD_MENU));
MASTHEAD_MENU_PANEL.addEventListener("click", (event) => {
    if (event.target.closest("button")) {
        closePopovers();
    }
});

LEDGER_HEAD.addEventListener("click", (event) => {
    const header = event.target.closest(".sort-head");
    if (header) {
        onSortHeaderClick(header.dataset.sortKey);
    }
});

SELECT_BAR_DONE.addEventListener("click", clearSelection);

document.addEventListener("keydown", onGlobalKey);

// ---- field registry harvest ----
// FIELD_REGISTRY is populated once at boot from the page's .filter-meta block plus
// the daemon facets op; registry order follows the meta block's document order.
async function buildFieldRegistry() {
    const derived = await callDaemon({ op: "facets" });
    for (const meta of FILTER_META.querySelectorAll("[data-field]")) {
        registerField(fieldSpecFromMeta(meta, derived));
    }
}

function fieldSpecFromMeta(meta, derived) {
    const { field, kind, label } = meta.dataset;
    const pinned = meta.dataset.pinned === "true";
    if (kind === "categorical") {
        const entries = field in derived
            ? derived[field].map((value) => ({ value, label: value }))
            : harvestVocab(meta);
        // Only multi-valued facets (source, attributes) offer the any/all mode
        // toggle — ALL on a scalar facet matches nothing.
        const multi = meta.dataset.multi === "true";
        return { field, kind, label, pinned, entries, multi };
    }
    if (kind === "text") {
        return {
            field, kind, label, pinned,
            placeholder: meta.dataset.placeholder || "",
            shavian: meta.dataset.shavian === "true",
            // An inline text field (Search) renders as a bare toolbar box, not a chip.
            inline: meta.dataset.inline === "true",
        };
    }
    return {
        field, kind, label, pinned,
        min: meta.dataset.min ?? null,
        max: meta.dataset.max ?? null,
    };
}

// The value→label pairs ship in the meta div so labels stay authored in one place
// (the CGI) rather than duplicated in JS.
function harvestVocab(meta) {
    return [...meta.querySelectorAll(".chip")].map((row) => ({
        value: row.querySelector("input").value,
        label: row.querySelector("span").textContent,
    }));
}

// ---- chip strip ----
// Rebuilt wholesale on any structural change; a value edit updates its own chip
// label in place without a rebuild.
function renderChipStrip() {
    const inline = state.activeFilters.filter((entry) => fieldSpec(entry.field).inline);
    const chips = state.activeFilters.filter((entry) => !fieldSpec(entry.field).inline);
    SEARCH_INLINE.replaceChildren(...inline.map(inlineSearchBox));
    CHIP_STRIP.replaceChildren(...chips.map(filterChip));
    syncAddFilterEnabled();
}

function inlineSearchBox(entry) {
    const spec = fieldSpec(entry.field);
    const wrap = document.createElement("div");
    wrap.className = "search-box";
    const box = document.createElement("input");
    box.type = "search";
    box.className = "text-filter search-field";
    box.dataset.field = spec.field;
    box.placeholder = spec.placeholder;
    box.value = entry.value;
    box.spellcheck = false;
    box.autocomplete = "off";
    box.setAttribute("aria-label", "Search Latin or Shavian (regex, case-insensitive)");
    box.addEventListener("input", () => {
        entry.value = box.value;
        requestFilterQueryDebounced();
    });
    wrap.append(box);
    return wrap;
}

function syncAddFilterEnabled() {
    ADD_FILTER.disabled = state.activeFilters.length >= FIELD_REGISTRY.size;
}

// The chip wraps its picker popover so the popover anchors to it
// (position:absolute inside position:relative).
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

    wrap.append(trigger, panel);
    if (!spec.pinned) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "chip-remove";
        remove.setAttribute("aria-label", `Remove ${spec.label} filter`);
        remove.textContent = "×";
        remove.addEventListener("click", () => removeFilter(entry));
        wrap.append(remove);
    } else {
        wrap.classList.add("pinned");
    }
    return wrap;
}

function renderChipLabel(entry) {
    const spec = fieldSpec(entry.field);
    if (spec.kind === "categorical") {
        const labels = entry.value.map((value) => vocabLabel(spec, value));
        if (!labels.length) {
            return `${spec.label}: any`;
        }
        const prefix = spec.multi && entry.mode === "all"
            ? `${spec.label} all`
            : spec.label;
        return `${prefix}: ${labels.join(", ")}`;
    }
    if (spec.kind === "text") {
        return `${spec.label}: ${entry.value.trim() || "…"}`;
    }
    return `${spec.label} ${entry.value === null ? "any" : entry.value}`;
}

function vocabLabel(spec, value) {
    const match = spec.entries.find((option) => option.value === value);
    return match ? match.label : value;
}

function refreshChipLabel(entry) {
    const wrap = CHIP_STRIP.querySelector(`.filter-chip[data-field="${entry.field}"]`);
    if (wrap) {
        wrap.querySelector(".chip-label").textContent = renderChipLabel(entry);
    }
}

// Removal is the only way a chip leaves the strip — an emptied categorical chip
// stays (its × is the explicit exit).
function removeFilter(entry) {
    if (isPinned(entry.field)) {
        throw new Error(`pinned filter ${entry.field} cannot be removed`);
    }
    state.activeFilters = state.activeFilters.filter((other) => other !== entry);
    renderChipStrip();
    requestFilterQuery();
}

// ---- value pickers ----
// Only one picker (or the +Add menu) is open at a time — closePopovers closes all.
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

function categoricalPicker(spec, entry) {
    const fragment = document.createDocumentFragment();

    const list = document.createElement("div");
    list.className = "facet-list";
    const picked = new Set(entry.value);
    for (const { value, label } of spec.entries) {
        list.append(valueRow(spec.field, value, label, picked.has(value)));
    }

    const commit = () => {
        entry.value = [...list.querySelectorAll("input:checked")].map((box) => box.value);
        refreshChipLabel(entry);
        requestFilterQuery();
    };
    list.addEventListener("change", commit);

    const bulk = document.createElement("div");
    bulk.className = "facet-bulk";
    const setAll = (checked) => {
        for (const row of list.querySelectorAll(".chip")) {
            row.querySelector("input").checked = checked;
        }
        commit();
    };
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "facet-bulk-btn";
    allBtn.textContent = "All";
    allBtn.addEventListener("click", () => setAll(true));
    const noneBtn = document.createElement("button");
    noneBtn.type = "button";
    noneBtn.className = "facet-bulk-btn";
    noneBtn.textContent = "None";
    noneBtn.addEventListener("click", () => setAll(false));
    bulk.append(allBtn, noneBtn);

    fragment.append(bulk);
    if (spec.multi) {
        fragment.append(modeToggle(spec, entry));
    }
    fragment.append(list);
    return fragment;
}

// ANY = a record matches one checked value (the default OR); ALL = it carries EVERY
// checked value (set superset).
function modeToggle(spec, entry) {
    const wrap = document.createElement("div");
    wrap.className = "facet-mode";
    const caption = document.createElement("span");
    caption.className = "facet-mode-label";
    caption.textContent = "Match";
    wrap.append(caption);
    const name = `mode-${spec.field}`;
    for (const [mode, label] of [["any", "any"], ["all", "all"]]) {
        const option = document.createElement("label");
        option.className = "facet-mode-opt";
        const input = document.createElement("input");
        input.type = "radio";
        input.name = name;
        input.value = mode;
        input.checked = entry.mode === mode;
        input.addEventListener("change", () => {
            if (input.checked) {
                entry.mode = mode;
                refreshChipLabel(entry);
                requestFilterQuery();
            }
        });
        const text = document.createElement("span");
        text.textContent = label;
        option.append(input, text);
        wrap.append(option);
    }
    return wrap;
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

function numericPicker(spec, entry) {
    const wrap = document.createElement("div");
    wrap.className = "numeric-picker";
    const input = document.createElement("input");
    input.type = "number";
    input.min = spec.min ?? "0";
    if (spec.max !== null && spec.max !== undefined) {
        input.max = spec.max;
    }
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
    item.className = "menu-item";
    item.textContent = spec.label;
    item.addEventListener("click", () => addFilter(spec.field));
    return item;
}

// Append the field's blank chip and open its picker straightaway. No query yet — a
// blank entry constrains nothing.
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
function togglePicker(panel, trigger) {
    const opening = panel.hidden;
    closePopovers();
    if (!opening) {
        return;
    }
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    // Focus a text/number input if the picker has one; categorical pickers have
    // none, so nothing is focused and the single-key verdicts stay armed.
    const focusable = panel.querySelector('input[type="text"], input[type="number"]');
    if (focusable) {
        focusable.focus();
    }
}

// Static panels (chip pickers, the masthead menu) are hidden in place; the +Add
// menu is removed — it is rebuilt each open to reflect the current inactive set.
function closePopovers() {
    for (const panel of document.querySelectorAll(".facet-panel:not([hidden])")) {
        panel.hidden = true;
        panel.previousElementSibling.setAttribute("aria-expanded", "false");
    }
    const addMenu = ADD_FILTER_WRAP.querySelector(".facet-panel");
    if (addMenu) {
        addMenu.remove();
        ADD_FILTER.setAttribute("aria-expanded", "false");
    }
}

document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".filter-chip")
        && !event.target.closest(".add-filter-wrap")
        && !event.target.closest(".masthead-menu-wrap")) {
        closePopovers();
    }
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closePopovers();
    }
});

// Migrates an old session that persisted only the daemon `filters` dict (pre-chips).
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

async function boot() {
    await initAuth();
    buildCheatsheet();
    collapseFiltersOnNarrow();
    await buildFieldRegistry();
    const stored = loadSession();
    const restored = stored ? restoreSession(stored) : false;
    if (!restored) {
        state.activeFilters = withPinnedFilters([]);
        renderChipStrip();
    }
    if (stored) {
        // Drop a restored sort whose column is no longer sortable, else daemonSort
        // would compose an enum the daemon rejects on the first (boot) query.
        state.columnSort = stored.columnSort && SORTABLE_COLUMNS.has(stored.columnSort.key)
            ? stored.columnSort
            : null;
    }
    syncSortIndicators();
    refreshCommitStatus();
    refreshPatchCounts();
    return runQuery(0, stored ? stored.anchor : null);
}

boot().catch((error) => showToast(error.message, true));
