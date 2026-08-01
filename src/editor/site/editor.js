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
// The page size, capped at the daemon's MAX_LIMIT (500). A larger page means
// select-all (which is scoped to the loaded page) covers more of a filtered set
// in one go, without a corpus-wide bulk op.
const PAGE_LIMIT = 500;
const ACCEPTED_STATUS = "sanctioned";

// The daemon's patch_state vocabulary — the review-state a record carries, read
// off record.patch_state. The Review facet offers only the VERDICT subset of it
// (edited/dirty collapse onto accepted/unreviewed — see verdictState). A closed set;
// the client compares against it in switches and guards, so it must track the
// daemon's constants exactly. Single source of truth on the Python side:
// src/editor/overlay.py (PATCH_STATE_*). A rename there MUST be mirrored here.
// Manual-ness is NOT a state: a manual record carries `manual: true` plus a real
// verdict like any other row (see isManual).
const PATCH_STATE = {
    UNREVIEWED: "unreviewed",
    ACCEPTED: "accepted",
    EDITED: "edited",
    DIRTY: "dirty",
    DROPPED: "dropped",
    FLAGGED: "flagged",
    ORPHANED: "orphaned",
};

// The mixed-verdicts marker — "the members do NOT all share one verdict". A
// statement about a GROUP, never a record's patch_state: the group header stamps
// it (pale blue, deliberately outside the four verdict colours), and the Review
// facet offers it as its one group-level value (the daemon's REVIEW_MIXED).
const GROUP_MIXED = "mixed";

// The daemon's orphan_kind vocabulary — WHY an orphaned patch stranded, read off
// record.orphan_kind. Single source of truth on the Python side:
// src/editor/overlay.py (ORPHAN_LOST_ACCEPT / ORPHAN_RESURFACED_DROP). Keep in sync.
const ORPHAN_KIND = {
    LOST_ACCEPT: "lost-accept",
    RESURFACED_DROP: "resurfaced-drop",
};

const SESSION_KEY = "shaw-spell.editor.session";
// Ledger/detail split, kept apart from SESSION_KEY like the section prefs: the
// splitter's position is the ledger's share of the workbench width (a 0..1
// fraction, so the split scales with the window), saved on drag end; the
// collapsed flag remembers the list tucked away behind its rail.
const SPLIT_FRACTION_KEY = "shaw-spell.editor.splitter.ledger";
const LEDGER_COLLAPSED_KEY = "shaw-spell.editor.ledger.collapsed";
// Detail-panel sub-section expansion prefs. Persisted apart from SESSION_KEY (which
// carries query/selection state) so the owner's "keep related at a glance" choice
// sticks per section across record selections AND page reloads. Keyed by a stable
// section id; the value is the remembered open/closed boolean.
const SECTION_PREFS_KEY = "shaw-spell.editor.sections";
// Default expansion when nothing is persisted: related opens (owner reads it at a
// glance), definitions stay collapsed (they push related below the fold otherwise).
const SECTION_DEFAULTS = { definitions: false, related: true };
// In-memory shadow so the prefs survive record-switch re-renders even when browser
// storage is unavailable (private mode / storage disabled). Seeded from storage on
// first read; the ONLY graceful fallback here — everything else fails loud.
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
// The default query sort — today's landing order, the highest-confidence review
// candidates first. A column header click sets state.columnSort, which daemonSort()
// composes into a `${column}_${dir}` sort the daemon applies to the whole filtered
// corpus; paging then walks that order. With no column sort active this default holds.
const DEFAULT_QUERY_SORT = "confidence_desc";
const RRP_VAR = "RRP";

// The edit surface: the fields the reviewer types or toggles. status is NOT here —
// it is read-only (shown in the top matter) and set only by the verdict actions
// (accept/drop/flag), never typed. recordFields carries the record's own status
// forward so a plain Save preserves it. word and freq are SINGLE-RECORD-ONLY: a
// patch is written against the stored anchor, so editing the Latin never
// re-anchors, but a group renders no word or freq input and its overlay skips
// them (fanning ONE word across N members is never right, and freq is
// POS-specific — a group's members differ exactly by POS — see glanceColumn /
// harvestGroupOverlay). freq is an INTEGER: harvest parses it (parsedFreq) and
// an invalid value is rejected loudly, never silently coerced.
const EDITABLE_FIELDS = ["word", "shaw", "var", "ipa", "freq"];

// The within-accent vowel mergers a record's spelling reflects (additive, empty
// == canonical). A closed vocabulary mirroring src/tools/dialect_mergers.py; the
// reviewer toggles these on the detail card and they round-trip in the patch.
const MERGERS = [
    ["trap-bath", "TRAP–BATH"],
    ["cot-caught", "COT–CAUGHT"],
    ["lot-palm", "LOT–PALM"],
];

// The within-accent free-variation marker: an alternate spelling of the same
// accent, not the canonical one (additive boolean, absent == canonical). The
// reviewer toggles it on the detail card and it round-trips in the patch.
const VARIANT_LABEL = "variant";

// The DISPLAY label for the free-variation member (the one backed by the `variant`
// boolean). Shown in the Variations toggle group and the related-row marker as
// "other"; the on-disk field name (`variant`) and the daemon facet value key stay
// unchanged — this is a label change only.
const VARIATION_OTHER_LABEL = "other";

// The upstream-definition provenance marker: the source(s) that produced this
// candidate carry a definition for it (read-only; a provenance fact, not editable).
// Shown as a quiet "def" pill beside the word; absent == no upstream definition.
const DEFINITION_LABEL = "def";

// The relabel-provenance marker: the dialect var a pipeline transform CHANGED this
// record's var FROM (basis.orig_var — e.g. the identical-dialect collapse relabels a
// lower-precedence dialect onto the winning var). Read-only (derived provenance, not
// editable); shown as a quiet "was GenAm" pill so the transformation is visible at a
// glance. Absent when no transform moved the var — the absence is the signal.
const ORIG_VAR_PREFIX = "was ";

// The general-purpose informational field (basis.INFO_FIELD): a catch-all list of
// non-essential metadata strings (e.g. Wiktionary quality tags obsolete/dialectal/
// dated). Read-only — derived provenance, not editable; shown as quiet pills beside
// the word, one per tag. Absent/empty renders nothing — the absence is the signal,
// mirroring the def/orig-var provenance badges.
const INFO_FIELD = "info";

// The novelty marker: is this word/spelling/pos new to the dictionary, measured
// against upstream ReadLex (read-only; a triage fact the daemon computes, not
// editable). Shown as a quiet pill beside the word for the new-* buckets — the
// signal that matters; `known` (all present upstream) shows nothing, mirroring the
// absence-is-the-signal convention of the other badges.
const NOVELTY_LABELS = new Map([
    ["new-word", "new word"],
    ["new-spelling", "new spelling"],
    ["new-pos", "new POS"],
]);

// An orphaned row's op + sub-kind (overlay.orphan_kind), so the owner can triage the
// two apart: a lost-accept is a stranded sanction (re-anchor or clear), a
// resurfaced-drop is URGENT — a suppression the basis EVADED, the junk returned under
// a relabelled var. `label` names it, `title` explains it; the class hangs off the
// kind for the palette (resurfaced-drop reads as a warning). Shown only on `orphaned`
// rows, beside the state badge.
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
const STEP_PREV = document.getElementById("stepPrev");
const STEP_NEXT = document.getElementById("stepNext");
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
    // The filters materialised by the last runQuery — the daemon dict. Read by
    // countUnreviewedRemaining and saveSession; written by runQuery from the chips.
    filters: {},
    // The active filter chips, in strip order: an ordered array of entries shaped by
    // their field's kind (see blankEntry). This is the editable model; state.filters
    // is its materialised projection via filtersFromState. An unset entry (empty
    // categorical, blank text, null numeric) contributes nothing to the query.
    activeFilters: [],
    // The active column-header sort, sent to the daemon so it orders the whole
    // filtered corpus (not just the loaded page). null == DEFAULT_QUERY_SORT.
    // {key, dir} where key is a sortable column and dir is "asc" or "desc".
    columnSort: null,
    // The related-entries list's client-side sort, set by clicking the related
    // table's own header. null == the default order (compareRelated's chain).
    // {key, dir} where key is a related column (state/word/pos/var/shaw/source)
    // and dir is "asc"/"desc". The focused ("you are here") row is pinned to the
    // top regardless — this only orders the siblings beneath it.
    relatedSort: null,
    selected: -1,
    // The detail panel's record editor context (see makeEditorContext), created on
    // first render and reused. Carries the edit flag and the harvest root, so the
    // review flow scopes to it rather than reaching through globals.
    mainContext: null,
    // The open create/clone modal's record editor context (create mode, scope "modal"),
    // or null when the modal is closed. Its presence is the modal-open flag: while set,
    // the modal owns the keyboard (Escape dismisses, Enter submits) and review verdicts
    // are suppressed — the workbench sits inert behind the backdrop. Both New Entry
    // (blank seed) and Clone (prepopulated seed) host a create-mode recordEditor here.
    modalEditor: null,
    // Group selection: the anchor keys of the picked rows (an anchor is a stable
    // identity, so a row survives in-place updates and re-renders keyed by it). The
    // single focused row (state.selected) is independent — it stays the review
    // cursor. A non-empty selection is the group the panel edits and verdicts fan out
    // over; 1 member is the degenerate single record, 2+ the multi-selection.
    multi: new Set(),
    // The last row toggled/clicked by pointer, so a shift-click can range-extend
    // from it — the selection anchor in the file-list sense.
    lastToggledKey: null,
    // The group whose HEADER the review cursor sits on (a header stop: a keyboard step
    // onto it, or a plain header click), or null when the cursor is on a record row.
    // It carries both the cursor's POSITION (currentStopIndex resolves it before the
    // record search; rowIsCursor lights the header) and the PROVENANCE of the
    // group-as-unit selection (stepping off the header dissolves the selection the
    // landing created). Any hand mutation of the pick — toggle, range, select-all,
    // clear — forfeits the claim, so stepping never dissolves an owner-made selection;
    // any record landing (select()) takes the cursor off the header.
    cursorGroupKey: null,
    // Touch multi-select mode (iOS Mail/Photos style): entered by long-press, in
    // which a plain tap toggles rather than reviews. Off = plain tap reviews.
    touchMulti: false,
    // Record-list grouping. The DAEMON owns grouping and pagination: the entries
    // op serves whole (word_lower, shaw, variation-set) groups — never split
    // across pages, every member on the page — and `groups` mirrors that partition
    // over state.records as {key, size} runs (the key is the daemon's, opaque
    // here). A multi-member group renders as a disclosure. `groupsExpanded` holds
    // the keys of the groups the owner has opened (transient view state — a
    // re-query replaces the partition, so it is cleared with the working set).
    groups: [],
    groupsExpanded: new Set(),
    // Monotonic token for the related-entries fetch. Each loadRelated bumps it and
    // captures the new value; only the LATEST request may render its result. A fetch
    // issued for an earlier landing (or an earlier state of the same record — a
    // reload after a write) is superseded and drops its result, so a slow in-flight
    // response can never paint stale rows over the current, freshest one.
    relatedGeneration: 0,

    // Monotonic token for the definitions fetch, mirroring relatedGeneration: each
    // loadDefinitions bumps it, and only the LATEST fetch may render — a slow
    // response for a previously-focused word is dropped rather than painted over
    // the current word's senses.
    definitionsGeneration: 0,

    // The open definition-correction modal's context (the sense being corrected +
    // the DOM node whose senses re-render after a write), or null when closed. This
    // is a SEPARATE modal from the record editor (state.modalEditor): it edits a
    // dictionary sense's Shavian transliteration, not a basis record, so it must
    // NOT set modalEditor (which would route record-editor verdict keys). While set,
    // it owns the keyboard (Escape dismisses) and suppresses workbench verdicts.
    definitionModal: null,
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
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
    });
    if (response.status === 401) {
        // Session lost mid-session — the server refused the op. Fail loud and
        // send the user back to the front gate.
        location.reload();
        throw new Error("session expired — signing in again");
    }
    const payload = await response.json();
    if (payload.error) {
        throw new Error(payload.error);
    }
    return payload;
}

// The verified handle, resolved from ?api=me at boot. AUTHOR (the client-side
// const) is advisory only — the CGI overrides meta.author with the session
// handle server-side — but the display uses this so the masthead shows who is
// signed in.
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
// A categorical entry carries a `mode` ("any"|"all") — how its checked values
// combine — defaulting to "any" (the back-compatible OR).
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

// The always-shown fields (word + shaw search, Review, Novelty), marked
// data-pinned in the CGI's filter-meta. They are permanent chips: seeded into the
// strip at boot in registry order, never offered by +Add (already active), and not
// removable (no ×). Every other field is added on demand.
function pinnedFields() {
    return [...FIELD_REGISTRY.values()]
        .filter((spec) => spec.pinned)
        .map((spec) => spec.field);
}

function isPinned(field) {
    return fieldSpec(field).pinned;
}

// Merge the pinned fields into an activeFilters list, preserving any values the
// list already carries for them (a restored session's word search survives) and
// dropping duplicates. Pinned entries lead, in registry order, so the always-shown
// chips keep a stable position; the rest follow in their existing order.
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

// The Review facet speaks VERDICTS (edited/dirty are decorations, not lifecycle
// states), but the daemon's _matches_review compares raw patch_state exactly. At the
// query boundary each selected verdict fans out to every patch_state whose verdict
// it is — accepted ⊇ edited, unreviewed ⊇ dirty, the rest map to themselves —
// derived from verdictState so the two can never disagree.
function reviewStatesForVerdict(verdict) {
    const states = Object.values(PATCH_STATE).filter(
        (patchState) => verdictState({ patch_state: patchState }) === verdict);
    if (!states.length) {
        throw new Error(`not a review verdict: ${verdict}`);
    }
    return states;
}

// The daemon-facing filters dict: the Review verdicts expanded to their raw
// patch_states. Only the wire dict differs — state.filters (the query signature,
// the session, pacing) stays in the verdict vocabulary. The group-level "mixed"
// value is no verdict (it fans out to no patch_state); it passes through as-is
// for the daemon's per-group leg (REVIEW_MIXED).
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
// session (which persisted only `filters`) migrates to chips, and any dict can seed
// the chip strip. Registry order is imposed so chips appear in the canonical order.
// Text flags (<field>_regex / <field>_ci) fold back onto their field's entry; a bare
// flag with no substring value is dropped (it constrained nothing).
function activeFiltersFromDict(filters) {
    const active = [];
    for (const spec of FIELD_REGISTRY.values()) {
        const raw = filters[spec.field];
        if (spec.kind === "categorical") {
            // Accept both the bare list (ANY) and the {values, mode} object (ALL).
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

// A restored categorical value list, for sanitizeRestoredEntry (every session
// restore path funnels through it). Review values collapse to their verdict
// (verdictState applied value-wise): a session saved when edited/dirty were their
// own Review chips migrates to the verdict chips that now cover them.
function restoredFacetValues(field, values) {
    if (field !== "review") {
        return [...values];
    }
    return [...new Set(values.map((value) => verdictState({ patch_state: value })))];
}

// Flag the text-filter chips whose regex the daemon could not compile (its response
// names them in invalid_regex). The chip's text input gets .invalid — a red border —
// while the query still returns (it simply matched nothing). Chips not named are
// cleared, so fixing the pattern removes the flag on the next live re-query. Only the
// currently-active text chips can be flagged; a removed field has no input to mark.
function markInvalidRegex(invalidFields) {
    const invalid = new Set(invalidFields);
    for (const root of [CHIP_STRIP, SEARCH_INLINE]) {
        for (const input of root.querySelectorAll(".text-filter")) {
            input.classList.toggle("invalid", invalid.has(input.dataset.field));
        }
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
        filters: daemonFilters(state.filters),
        sort: daemonSort(),
        offset,
        limit: state.limit,
    });
    // The daemon owns grouping AND order: it sorts the whole filtered corpus (per
    // daemonSort), partitions it into groups ranked by their best-sorted member,
    // and pages by GROUP — so this page carries whole groups, already in order.
    // state.records stays the flat member run (index-keyed selection and in-place
    // row refresh untouched); state.groups is the partition over it.
    state.groups = result.groups.map(
        (group) => ({ key: group.key, size: group.records.length }));
    state.records = result.groups.flatMap((group) => group.records);
    state.total = result.total;
    markInvalidRegex(result.invalid_regex || []);
    // The selection is over the working set that was on screen; a re-materialise
    // replaces that set, so the old selection no longer refers to these rows. Clear
    // it — select-all means "all currently-loaded rows", scoped to this page.
    state.multi.clear();
    state.lastToggledKey = null;
    state.touchMulti = false;
    // The expansion state is over the partition that was on screen; a re-materialise
    // replaces that partition, so clear it — fresh groups land closed.
    state.groupsExpanded.clear();
    materialisedSignature = querySignature(state.filters);
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

// The intrinsic fields the owner overrode when they accepted this record — the
// keys of the accept patch's minimal `changes` diff (any of word/shaw/pos/ipa/
// var/mergers/variant). Only an accept against a real basis has a diff to mark:
// an accept carries op "accept" and a non-null anchor. Authored rows (anchor
// null) ARE their content with no basis to diff, and drop/flag/unreviewed have
// no accept changes — all yield the empty set. A field's PRESENCE in changes is
// the override, whatever its value, so an emptied field (e.g. mergers: []) marks.
function overriddenFields(record) {
    const patch = record.patch;
    if (!patch || patch.op !== "accept" || !patch.anchor || !patch.changes) {
        return new Set();
    }
    return new Set(Object.keys(patch.changes));
}

// The ledger renders the DAEMON's group partition (§3, D5–D7) — the client never
// computes grouping. A group of ONE renders as a plain ledger row — byte-identical
// to the flat row, empty gutter cells (the N=1 invariant). A group of 2+ renders a
// disclosure HEADER (previewing the export-winner) that expands to its member
// rows. `state.records` stays the flat, daemon-ordered working set, so paging,
// in-place refresh, and anchor-keyed selection are untouched.
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
            // The children form an inset bordered block hanging under their header:
            // the first child opens it (top border + top corners), the last closes it
            // (bottom border + bottom corners).
            children[0].classList.add("group-child-first");
            children[children.length - 1].classList.add("group-child-last");
            LEDGER.append(...children);
        }
    }
}

// The child rows of an expanded group (§3.3): every member, in served order. The
// daemon pages whole groups, so the full membership is on the page — each child a
// bright, index-addressable working-set row.
function groupChildRows(group) {
    return group.members.map(({ record, index }) => ledgerRow(record, index, true));
}

// A record's VERDICT — the single source of truth collapsing the two DECORATION
// states onto the verdict they decorate: `edited` IS an accept (one carrying field
// edits), `dirty` IS unreviewed (an unshipped persisted edit, reviewed=False). The
// remaining states are their own verdict. Every state-semantic reader — the row
// hue/class, the stamp and state pills, the Review filter — routes
// through this; raw patch_state is read only where the edit decoration itself is
// meant (overridden-field tags) or the daemon's raw vocabulary is mirrored.
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

// The export var-hierarchy (§5a): the same precedence the export collapse applies —
// RRP > RSSB > GenAm, and any other var ranks below all listed ones. Mirrors
// src/tools/collapse_identical_dialects.py (PRECEDENCE / UNKNOWN_RANK): lower rank
// wins. This is the authority for WHICH member a collapsed group header displays (the
// export-winner it will ship, §3.6).
const VAR_PRECEDENCE = { RRP: 0, RSSB: 1, GenAm: 2 };
const VAR_UNKNOWN_RANK = Object.keys(VAR_PRECEDENCE).length;
function varRank(value) {
    const rank = VAR_PRECEDENCE[value];
    return rank === undefined ? VAR_UNKNOWN_RANK : rank;
}

// The grouped view of the working set (§3.1, §3.5): the daemon's partition
// (state.groups — contiguous {key, size} runs over state.records) hydrated with
// member records and their working-set indices. The daemon already ranked each
// group at its BEST member under the active sort (§3.5) and ordered members
// within it; the client only re-reads that partition — it NEVER computes
// grouping, so it cannot drift from the daemon's group_key. The group's DISPLAY
// member is the export-winner (the var-hierarchy winner, §3.6), which may differ
// from the first (best-under-sort) member. Fails loud if the partition and the
// working set have drifted apart (a bookkeeping bug, not a state to render).
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

// The group holding the record at a working-set index, or null when the index is
// unset/out of range — the lookup every cursor/fold flow uses instead of ever
// recomputing a group key from the record.
function groupOfIndex(index) {
    if (index < 0) {
        return null;
    }
    return ledgerGroups().find(
        (group) => group.members.some((member) => member.index === index)) || null;
}

// A record removed from the working set leaves its group too: shrink the owning
// {key, size} run so the partition stays aligned with state.records (call BEFORE
// splicing the record out). A group emptied of its last member is dropped, along
// with any expansion state it held. An index outside the partition is a caller bug.
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

// The export-winner among a group's members (§3.6, D5): the highest-in-hierarchy var
// (the member the export will ship for this group). The group is Latin+Shaw+
// variation-set uniform by construction, so only var distinguishes members for the
// display — pick the lowest var rank; ties (same var, differing pos/source) keep the
// first, i.e. the best-under-active-sort member. Operates on {record, index} entries.
function exportWinner(members) {
    return members.reduce((best, entry) =>
        varRank(entry.record.var) < varRank(best.record.var) ? entry : best);
}

// The columns the daemon can sort on; the header's data-sort-key is one of these,
// and daemonSort composes it with a direction into the daemon's `${column}_${dir}`
// sort enum. Guards session restore against a retired column key.
const SORTABLE_COLUMNS = new Set(["state", "word", "shaw", "var", "confidence", "freq", "pos"]);

// The sort string to send with a query: the active column sort composed as the
// daemon's `${column}_${dir}` enum, or the default landing order when none is set.
function daemonSort() {
    return state.columnSort
        ? `${state.columnSort.key}_${state.columnSort.dir}`
        : DEFAULT_QUERY_SORT;
}

// A column header was clicked: sort ascending, or flip to descending if that column
// is already the ascending sort. Re-pulls the WHOLE filtered corpus in the new order
// (daemon-side) reset to page 0, keeping the cursor on the focused record by anchor.
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

// The seven data cells for a record (state stamp, word, shaw, var, confidence,
// freq, pos), in column order. Shared by the flat/child row and the collapsed group
// header (which shows the export-winner's cells), so a header scans as one ledger row.
// `verdict` defaults to the record's own; a group header passes the group's shared
// verdict — or GROUP_MIXED when members disagree.
// Every row prepends the two narrow gutter tracks (chevron, count) itself: a header
// fills them, flat and child rows leave them blank — children share the top-level
// template, aligned full-width under their header.
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

// The STATE stamp: the verdict WORD in the verdict's colour — colour is ONLY ever
// one of the four acceptance states (or the group-level mixed blue). A manual
// record keeps its verdict colour; its manual-ness rides the label TEXT as a ✎
// mark (colour and word are orthogonal). GROUP_MIXED is a group statement, so the
// mark is dropped there — expand for each member's own stamp.
function stampCell(record, verdict) {
    const marked = Boolean(record.manual) && verdict !== GROUP_MIXED;
    const stamp = cell(`stamp col-state ${verdict}`, marked ? `✎ ${verdict}` : verdict);
    if (marked) {
        stamp.title = "manual entry";
    }
    return stamp;
}

// A record-bearing ledger row: a flat singleton group, or (`isChild`) a child of
// an expanded group. Every row is a working-set row — the daemon serves whole
// groups per page, so a child is always index-addressable.
function ledgerRow(record, index, isChild = false) {
    const row = document.createElement("li");
    row.className = `ledger-row state-${verdictState(record)}`;
    // An orphaned row's edge-bar + stamp are coloured by WHICH orphan reason it is
    // (patch_state is just "orphaned" for both), so the two triage apart at a glance
    // in the list. The wide DROP·RESURFACED / ACCEPT·ORPHAN badge is NOT crammed into
    // the narrow state column any more (it overflowed onto the word); it lives in the
    // detail panel, where there is room. Here the hue alone carries the distinction.
    if (record.patch_state === PATCH_STATE.ORPHANED && record.orphan_kind) {
        row.classList.add(`orphan-${record.orphan_kind}`);
    }
    if (isChild) {
        row.classList.add("group-child");
    }
    row.dataset.index = String(index);
    // Every record-bearing row carries its anchor key so the selection wash can be
    // painted by anchor. The key carries NUL separators (not attribute-safe), so it
    // rides on a JS property.
    row._anchorKey = anchorKey(record.anchor);
    row.append(cell("col-chevron", ""), cell("col-count", ""), ...ledgerCells(record));
    bindLongPress(row, record);
    row.addEventListener("click", (event) => onRowClick(record, index, event));
    return row;
}

// A collapsed group HEADER (§3.6, D5): a tightened ledger row previewing the
// export-winner (the var-hierarchy winner the export will ship), fronted by a
// disclosure chevron and a member-count gutter cell. It is NOT a state.records
// row — it carries no data-index (so index-keyed refresh skips it; the selection
// painter addresses it by _groupKey, lighting a COLLAPSED header when the cursor's
// record is folded inside) — but it IS a selection target: clicking its select region
// picks the WHOLE group (§3.2), while the chevron toggles expansion. Expanding
// appends every member row below (§3.3).
function groupRow(group) {
    const winner = exportWinner(group.members).record;
    // The header stamps a shared verdict (state class + STATE-track stamp) only when
    // EVERY member shares it — a group verdict is unconditional, so a header must
    // never advertise one member's verdict as the group's. Disagreeing members stamp
    // GROUP_MIXED instead (pale blue — a statement about the group, not a verdict),
    // the owner's handle for sweeping part-reviewed groups (the Review mixed filter).
    const consensus = verdictConsensus(group.members.map((member) => member.record));
    const verdict = consensus.uniform ? consensus.value : GROUP_MIXED;
    const li = document.createElement("li");
    li.className = `ledger-row ledger-group-header state-${verdict}`;
    if (winner.patch_state === PATCH_STATE.ORPHANED && winner.orphan_kind) {
        li.classList.add(`orphan-${winner.orphan_kind}`);
    }
    // The group key carries NUL separators (anchor-safe, not attribute-safe), so it
    // rides on a JS property rather than a data-* attribute — it is read back directly,
    // never queried by selector.
    li._groupKey = group.key;
    const expanded = state.groupsExpanded.has(group.key);
    // The expanded header is the TOP of the group unit — the CSS frame state rides
    // on this row-level class (aria-expanded on the disclosure button carries the
    // accessibility semantics only).
    if (expanded) {
        li.classList.add("expanded");
        bindParentGutter(li);
    }

    // Gutter tracks: the disclosure chevron, then the member count. The data cells
    // preview the export-winner; the STATE track stamps the group's shared verdict,
    // "mixed" when members disagree — expand for each member's own stamp.
    li.append(groupDisclosure(group, expanded), groupCountCell(group), ...ledgerCells(winner, verdict));
    li.addEventListener("click", (event) => onGroupHeaderClick(group, event));
    return li;
}

// The indent strip left of an expanded group's child block belongs to the HEADER
// (one continuous shape: hovering the header washes it AND the strip beside its
// children). The children are later SIBLINGS in the flat <li> run — CSS cannot reach
// "the children up to the next header" from the header's :hover — so the header's
// hover walks its child rows and toggles the class the strip's wash keys on
// (.parent-hover; the selected twin is painted by paintLedgerSelection).
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

// The header's disclosure chevron, filling the chevron gutter track. Its click
// toggles the group's expansion WITHOUT selecting the group (stopPropagation), so the
// chevron drills down and the rest of the header row selects/reviews.
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

// The header's member-count gutter cell (§3.6): the group's full membership — the
// daemon serves whole groups. Capped at two digits ("99+") to keep the track narrow.
function groupCountCell(group) {
    const total = group.members.length;
    return cell("col-count group-count", total > 99 ? "99+" : String(total));
}

// A group header was clicked (outside its disclosure triangle): the group is a
// selection target acting on the WHOLE group (§3.2, D7). A plain click reviews the
// group (selects every member, showing the group-native panel); ⌘/Ctrl or
// touch-multi toggles the group into the selection.
function onGroupHeaderClick(group, event) {
    if (suppressNextClick) {
        suppressNextClick = false;
        return;
    }
    setDrawer(false);
    const toggle = state.touchMulti || event.metaKey || event.ctrlKey;
    selectWholeGroup(group, toggle);
}

// Toggle a group's expansion and re-render so its member rows appear/vanish in
// place. The full membership is already on the page (the daemon serves whole
// groups), so this is a pure view toggle — no fetch. The selection is preserved
// (it keys on anchors, which survive the re-render).
function toggleGroupExpanded(key) {
    if (!state.groupsExpanded.delete(key)) {
        state.groupsExpanded.add(key);
    }
    renderLedger();
    paintLedgerSelection();
}

// Select the WHOLE group (§3.2, D7): add EVERY member's anchor to the selection, so
// a group verdict never silently leaves a sibling unreviewed (the export collapses
// the whole group — and the daemon serves it whole, so every member is on the
// page). A plain click reviews the group (replaces the selection); a toggle gesture
// flips the group's members in/out.
function selectWholeGroup(group, toggle) {
    const anchors = group.members.map((member) => member.record.anchor);
    // A plain header-select lands the cursor ON the header (the group-as-unit stop),
    // for keyboard and mouse alike; a toggle is a hand mutation of the pick, which
    // forfeits any header claim (see state.cursorGroupKey).
    state.cursorGroupKey = toggle ? null : group.key;
    if (!toggle) {
        state.multi.clear();
    }
    // On a toggle, if the whole group is already selected, deselect it; else select it
    // — the group behaves as one selection unit under ⌘-click.
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

// Selecting an entry always lands in REVIEW MODE (no field focused). Edit mode is
// entered explicitly (enterEdit), never as a side effect of stepping.
function select(index) {
    // Leaving the currently-shown record: flush any genuine unsaved edit first, before
    // state.selected and the main context switch to the new record.
    autoSaveMainEdit();
    state.selected = index;
    // A record landing takes the cursor off any group header it sat on.
    state.cursorGroupKey = null;
    if (state.mainContext) {
        state.mainContext.editing = false;
    }
    // The review cursor must be visible: if it lands on a record inside a COLLAPSED
    // multi-member group, expand that group so its child row shows (keyboard stepping
    // into a group, or a landing on a grouped record, otherwise leaves no visible
    // cursor). Only when no multi-selection is live — a group selection deliberately
    // keeps the fold as-is.
    if (!state.multi.size) {
        revealSelectedInGroup(index);
    }
    paintLedgerSelection();
    // When a multi-selection is live the card shows that GROUP, not the focused record;
    // moving the review cursor still scrolls the row into view but leaves the group
    // panel in place. Otherwise the focused record (or the empty state) renders through
    // the same group-native path.
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

// The record-bearing rows (flat singletons + expanded group children) carry a
// data-index keyed to state.records; group headers do not. This helper addresses a row
// by its working-set index across the now-grouped DOM, so the index-keyed flows
// (scroll, in-place refresh) stay index-driven without knowing the fold.
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

// A group HEADER row addressed by its group key — the header counterpart of
// rowByIndex. The key carries NUL separators (not attribute-safe), so it rides on the
// row's _groupKey JS property and cannot be querySelected; scan the rows instead (the
// ledger is one page, so this is cheap).
function rowByGroupKey(key) {
    for (const row of LEDGER.querySelectorAll(".ledger-row")) {
        if (row._groupKey === key) {
            return row;
        }
    }
    return null;
}

// Expand the collapsed group holding the record at `index` so the review cursor is
// visible. A no-op when the record is a singleton or already-expanded group.
// Re-renders the ledger in place.
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
    setDetailMode();
}

// ---- group selection ----
// A set of anchor keys over the current working set. A non-empty selection is the
// GROUP the detail panel edits and every verdict fans out over — one member is the
// degenerate single record, 2+ members the multi-selection. An empty selection leaves
// the focused single record in the panel.
//
// Selection is a MAIN-context concept — it acts on the workbench. While an edit modal
// owns the screen its verdicts act on the single modal record (via activeContext()), so
// the workbench selection is dormant: a verdict never fans out to the rows behind the
// backdrop.
function toggleSelection(anchor) {
    const key = anchorKey(anchor);
    if (state.multi.has(key)) {
        state.multi.delete(key);
    } else {
        state.multi.add(key);
    }
    state.lastToggledKey = key;
    // A hand mutation of the pick: the selection is the owner's now, so stepping off
    // a header must no longer dissolve it (see state.cursorGroupKey).
    state.cursorGroupKey = null;
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
    state.cursorGroupKey = null;
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

// Touch multi-select mode: a plain tap toggles instead of reviewing. Entered by a
// long-press, left via the Done affordance (which also clears the selection).
function enterTouchMulti() {
    state.touchMulti = true;
}

// Re-sync everything the selection drives: the row highlights, the touch-mode
// select bar, and the detail card. The card renders whatever selectedGroup() yields —
// the multi-selection when the owner has picked rows, the focused singleton otherwise,
// the empty state when neither — through the ONE group-native path.
function onSelectionChanged() {
    // A selection change can swap the detail card (single → group, or to a different
    // focused record) without routing through select(); flush an unsaved edit on the
    // record leaving the card first.
    autoSaveMainEdit();
    paintLedgerSelection();
    const group = selectedGroup();
    if (group.length) {
        renderGroupEditor(group);
    } else {
        renderEmptyDetail();
    }
}

// The SINGLE source of truth for ledger row highlighting. Given the current
// (state.selected, state.multi), set .selected on exactly the rows that belong to the
// active selection and clear it on every other row — headers included, so no row can
// retain a stale highlight across a selection change. A multi-pick wins over the
// cursor (mirroring selectedGroup()); with no pick, the cursor row (or the collapsed
// header hiding it) is the selection. Record rows join by their own anchor; a group
// HEADER joins when its WHOLE membership is selected — the group is a selection unit
// (§3.2); a partial child-pick (the split case, §3.4) leaves the header unlit while
// its picked children light individually. The same pass carries a selected header's
// wash onto its children's parent-owned indent strip (.parent-selected): children
// directly follow their header in the flat run, so the sweep just remembers whether
// the last header lit — the split case leaves the strip dark by construction.
function paintLedgerSelection() {
    const multi = state.multi.size > 0;
    // Hydrate the partition ONCE per paint (this runs per keystroke/step), keyed
    // for the header lookups below.
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

// Whether a row carries the review cursor: a record row by its working-set index, a
// group HEADER when the cursor sits ON it (state.cursorGroupKey — a header stop
// landing, before its whole-group selection resolves and the multi wash takes over),
// or a COLLAPSED header when the cursor's record is folded inside it (a non-stepping
// landing — refocus, undo — that reveals no row). While a header holds the claim its
// members' record rows do NOT light by index — the header IS the cursor.
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

// True when every member of a group is in the selection — the condition for washing
// its header picked. The daemon serves whole groups, so the page IS the full
// membership.
function isGroupFullySelected(group) {
    return Boolean(group) && group.members.every(
        (member) => state.multi.has(anchorKey(member.record.anchor)));
}

// The touch select bar only shows in touch multi-select mode, giving the count and
// the Done button that exits the mode.
function syncSelectBar() {
    SELECT_BAR.hidden = !state.touchMulti;
    const count = state.multi.size;
    SELECT_BAR_COUNT.textContent = count === 1 ? "1 selected" : `${count} selected`;
}

// A record editor's context: the surface a GROUP of one-or-more records is being
// edited on. It owns its harvest `root` (the container the field inputs live under,
// queried scoped by data-field), an id `prefix` for those inputs (the detail keeps
// "field-", the modal uses "modal-" so the two never collide), a per-context `editing`
// flag, and the `group` and `mode` it renders. The `group` is always an array; today
// every editor is single-record, so the group is the singleton `[record]` (N=1 is the
// degenerate case). The detail panel holds one context (state.mainContext, mode
// "edit"); the open modal holds another (state.modalEditor) — create mode for a New
// Entry/Clone, edit mode for a related entry opened for in-place review.
// activeContext() routes the review flow to whichever owns the screen.
function makeEditorContext({ scope, root, prefix, group, mode }) {
    return { scope, root, prefix, editing: false, group, mode };
}

// The single record a context describes when its group is a singleton — the N=1
// accessor every current consumer reads through. Null-safe to mirror the optional
// `activeContext()?.record` reads it replaces (an absent context, or a context with no
// group member, yields null).
function contextRecord(ctx) {
    return ctx?.group?.[0] ?? null;
}

// The context whose edit inputs the verdict/harvest flow acts on: the open modal's
// context when a modal owns the screen, otherwise the detail context. Returning the
// modal context while it is open keeps a stray keypress from harvesting or acting on
// the record behind the backdrop — in create mode only Enter/Escape act, so no verdict
// ever reaches it; in edit mode (a related entry opened for review) the verdicts DO
// act, but on the modal record, never the detail behind.
function activeContext() {
    return state.modalEditor ?? state.mainContext;
}

// Build the reusable record editor for `group` — the SINGLE editor renderer for the
// detail panel and the modal, in both modes. `group` is the array of records the
// context edits; today it is always a singleton, and the chrome renders that one member.
// Returns a `.record-editor` container that owns the field inputs (the context's harvest
// root), context-scoped so its ids and harvest never collide with another instance's.
// The related section is never part of it (renderGroupEditor appends that separately). Scope
// "detail" stores the context as state.mainContext; scope "modal" stores it as
// state.modalEditor. It never shows the related section.
//
// Edit mode renders the review top matter (badges/facts/overridden marks), the field
// editors (word editable on a single record, pos read-only), the verdict bar and the
// clone bar — the same
// whether it hosts the detail panel or a modal opened on a related entry. Create mode
// renders a minimal title + hint, EDITABLE word/pos (the author types the anchor), the
// same field editors, and an [Accept, Flag, Cancel] verdict bar: the verdict IS the
// authoring action (Accept authors the record; Flag authors it flagged; Cancel
// dismisses). No Drop (authoring only to suppress is marginal) and no Clone bar (cloning
// a not-yet-saved record makes no sense).
const CREATE_MODE = "create";

function recordEditor(group, opts) {
    // The context carries the whole group; the chrome renders it group-native — every
    // field that is common across the group edits exactly as a single record's, every
    // field that differs renders the "multiple"/tri-state form. N=1 is the degenerate
    // case in which every field is trivially common, so its render is byte-identical to
    // the single-record card.
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
        // The distinctness guard runs LIVE: an edit to any identity field (word / shaw /
        // pos / var / mergers / variant) re-evaluates whether the authored anchor already
        // exists, so the verdict buttons enable/disable as the owner types. Delegated on
        // the container so it covers the text inputs (input) and the variation toggles
        // (change) alike.
        container.addEventListener("input", () => evaluateDistinctness(ctx));
        container.addEventListener("change", () => evaluateDistinctness(ctx));
        evaluateDistinctness(ctx);
        return container;
    }

    // A multi-member group leads with a banner naming the count — the single unambiguous
    // signal that a verdict or edit fans out to N records, not one.
    if (group.length > 1) {
        container.append(groupHeader(group));
    }

    // For a group the "overridden" provenance marks are a single-record concept (which
    // fields the owner changed on THIS record's accept); they only apply at N=1.
    const overridden = group.length === 1 ? overriddenFields(record) : new Set();

    // Full-width chrome: the FIVE glance-fields compact in the left column (the
    // Latin/Shavian/IPA text stack with POS + var beside it), and on the right the
    // priority rail (state / sources / freq / confidence, fixed slots), the
    // attributes chips, demoted metadata, and the action buttons (the owner uses
    // keyboard shortcuts on desktop, so the buttons ride the rail).
    const chrome = document.createElement("div");
    chrome.className = "detail-chrome";

    const glance = glanceColumn(ctx, group, overridden);
    const rail = railColumn(ctx, group, overridden);
    chrome.append(glance, rail);
    container.append(chrome);

    // The orphan note, reference links and word-identity chrome below are single-record
    // affordances — a group has no single word to link out for. Render them at N=1 only.
    if (group.length === 1) {
        const orphanNote = orphanReasonNote(record);
        if (orphanNote) {
            container.append(orphanNote);
        }
        container.append(referenceLinks(record.word));
    }
    return container;
}

// The group banner: a one-line header naming how many records the panel edits, so a
// verdict's or edit's fan-out to N records is never a surprise. Absent at N=1 (a single
// record needs no banner — the N=1 invariant).
function groupHeader(group) {
    const header = document.createElement("div");
    header.className = "group-edit-header";
    header.append(
        cell("group-edit-title", "Group edit"),
        cell("group-edit-count", `${group.length} records`),
    );
    return header;
}

// The LEFT column of the chrome: two compact sub-columns side by side. The TEXT
// STACK (Latin word, Shavian, IPA — stacked close) on the left; the categorical
// POS (code prominent) + var column beside it, using the horizontal room. No state
// badge on the word: it moved to the rail to keep the left edge clean. On a narrow
// screen the POS + var column wraps below the stack (glance-column is flex-wrap).
function glanceColumn(ctx, group, overridden) {
    const record = group[0];
    const column = document.createElement("div");
    column.className = "glance-column";

    // The word: EDITABLE for a single record — a patch is written against the stored
    // anchor, so a word edit is an ordinary `changes.word`, never a re-anchor. A GROUP
    // renders it read-only (common → the single big word; divergent, a cross-group
    // hand-pick → the distinct words rolled up): a group edit fans ONE value across N
    // members, which is never right for the word (see harvestGroupOverlay).
    let word;
    if (group.length === 1) {
        word = editField(ctx, group, "word", "Word (latin)", "latin-field",
            overridden.has("word"));
    } else {
        const wordConsensus = fieldConsensus(group, "word");
        word = cell("latin", record.word);
        if (!wordConsensus.uniform) {
            word.classList.add("latin-multiple");
            applyDistinctDisplay(word, wordConsensus);
        }
    }
    // The word wears its verdict as a colour-coded box (state hue border) instead of
    // a separate STATE pill — so state is glanceable right on the word. The state name
    // is on title/aria-label since the pill text is gone. A group with a mixed state
    // carries no single hue, so its box is neutral.
    const stateConsensus = verdictConsensus(group);
    const wordGroup = document.createElement("div");
    wordGroup.className = stateConsensus.uniform
        ? `glance-word state-box ${stateConsensus.value}`
        : "glance-word state-box state-multiple";
    if (stateConsensus.uniform) {
        wordGroup.title = `state: ${stateConsensus.value}`;
        wordGroup.setAttribute("aria-label",
            `${record.word} — state: ${stateConsensus.value}`);
    } else {
        wordGroup.title = "state: mixed";
    }
    wordGroup.append(word, editedSummary(overridden));

    const posVar = document.createElement("div");
    posVar.className = "glance-posvar";
    posVar.append(
        posSpelledOut(group, overridden.has("pos")),
        editField(ctx, group, "var", "Dialect (var)", "var-field", overridden.has("var")),
    );
    // freq: EDITABLE for a single record (an override of the corpus-derived value —
    // the derivation runs before the patch overlay, so a patched freq is the last
    // word). A GROUP renders no freq input: freq is POS-specific and a group's
    // members differ exactly by POS, so fanning ONE freq across N members is wrong;
    // the priority rail already shows the group's min–max spread.
    if (group.length === 1) {
        posVar.append(editField(ctx, group, "freq", "Frequency", "freq-field",
            overridden.has("freq")));
    }

    // Two side-by-side sub-columns: the text stack (word / Shavian / IPA, kept close
    // together) and the small categorical fields (POS + var) beside it — horizontal
    // space instead of a scroll. On a too-narrow screen posvar wraps below the stack.
    const fields = document.createElement("div");
    fields.className = "glance-fields";
    fields.append(
        wordGroup,
        editField(ctx, group, "shaw", "Shavian", "shaw-field", overridden.has("shaw")),
        editField(ctx, group, "ipa", "IPA", "ipa-field", overridden.has("ipa")),
    );
    column.append(fields, posVar);
    return column;
}

// The uniform divergent-field display: the distinct values (commonest first) on ONE
// line as a plain comma-separated list. CSS truncates the line with an ellipsis, so an
// unbounded selection can never wall the panel; the FULL list is the element's `title=`
// tooltip, reachable on hover. No count prefix — the list already shows the values and
// the tooltip the rest; a leading count would carry the Shavian namer dot (`·`), which
// reads as linguistic content beside Shavian, not a UI count.
// Applied to every divergent slot — the read-only anchor rollups (word/pos) and the
// editable "multiple" fields (var/shaw/ipa) — so they all read the same way.
function distinctDisplay(consensus) {
    const list = [...consensus.distinct]
        .sort((a, b) => b.count - a.count)
        .map((entry) => entry.key || "—")
        .join(", ");
    return { text: list, title: list };
}

// Set the truncated one-line divergent display on an element and its full-list tooltip.
function applyDistinctDisplay(element, consensus) {
    const { text, title } = distinctDisplay(consensus);
    element.textContent = text;
    element.title = title;
    element.classList.add("distinct-values");
}

// POS as a read-only glance field (editable only on create — the patch model would
// carry a `changes.pos` fine, it is just not offered in the edit surface). Common
// across the group → the CLAWS CODE (e.g. NN1) big, the spelled-out English beneath it,
// the full expansion as the hover title (byte-identical to the single-record render).
// Divergent (a group spanning several POS) → a compact "NN1 ·2, NN2 ·1" rollup so the
// owner sees the span.
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

// The CLAWS-tag human description(s), joined for a compound tag; the bare tag when
// it has no known expansion.
function posExpansion(pos) {
    if (!pos) {
        return "";
    }
    return pos.split("+").map((part) => C5_TAGS[part] ?? part).join(" + ");
}

// The RIGHT column of the chrome: the priority rail (fixed-slot state/sources/freq/
// confidence), the attributes chips, the demoted metadata badges, and the action
// buttons.
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

// The priority rail: four FIXED slots — state, sources, freq, confidence — each
// keeping its geometry so the glance loop never re-scans. An absent value's slot
// goes invisible IN PLACE (visibility:hidden via .empty), and the others do NOT
// reflow to fill it. Sources render as one atomic pill per attesting origin.
//
// Read-only context. Where the group shares a value the slot renders it exactly as a
// single record's; where it differs the slot rolls up (state/source as "·N" tallies,
// freq as a min–max range, confidence as "mixed") so the owner sees the spread without
// the rail pretending the group is uniform.
function priorityRail(group) {
    const record = group[0];
    const rail = document.createElement("div");
    rail.className = "priority-rail";

    // The word-box carries state by COLOUR; this rail slot restates the exact verdict
    // WORD as a small, unobtrusive pill (so accepted/dropped/flagged read apart —
    // colour alone can't). An orphaned record also gets its sub-tag (op + why). A
    // group of mixed verdicts tallies each verdict instead.
    const state = railSlot("state");
    const stateConsensus = verdictConsensus(group);
    if (stateConsensus.uniform) {
        // A manual record's origin rides the pill TEXT beside its verdict — the
        // colour stays the verdict's (colour and word are orthogonal).
        const stateName = group.every((member) => member.manual)
            ? `${stateConsensus.value} · manual`
            : stateConsensus.value;
        state.append(cell(`state-pill ${stateConsensus.value}`, stateName));
        const orphanKind = orphanKindBadge(record);
        if (orphanKind.childElementCount) {
            state.append(orphanKind);
        }
    } else {
        for (const entry of stateConsensus.distinct) {
            state.append(cell(`state-pill ${entry.value}`,
                `${entry.value} ·${entry.count}`));
        }
    }

    const sources = railSlot("sources");
    const sourceSet = groupSources(group);
    if (sourceSet.length) {
        sources.append(sourcePills(sourceSet));
    } else {
        sources.classList.add("empty");
    }

    const freq = railSlot("freq");
    freqSlotContent(group, freq);

    const conf = railSlot("confidence");
    const confConsensus = fieldConsensus(group, "confidence");
    if (!confConsensus.uniform) {
        conf.append(cell("rail-value", "mixed"));
    } else if (record.confidence !== null && record.confidence !== undefined) {
        conf.append(confidenceMeter(record.confidence), cell("rail-value", String(record.confidence)));
    } else {
        conf.classList.add("empty");
    }

    rail.append(state, sources, freq, conf);
    return rail;
}

// The union of every source attesting any member of the group, first-seen order — so
// the sources slot shows every origin behind the selection, not just the first
// member's. A single record's own source list is returned unchanged at N=1.
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

// Fill the freq slot: the single value when the group shares one, a "min–max" range
// when the members' frequencies span a spread, or empty when no member carries one.
function freqSlotContent(group, slot) {
    const freqs = group
        .map((member) => member.freq)
        .filter((freq) => freq !== null && freq !== undefined);
    if (!freqs.length) {
        slot.classList.add("empty");
        return;
    }
    const min = Math.min(...freqs);
    const max = Math.max(...freqs);
    slot.append(cell("rail-value", min === max ? String(min) : `${min}–${max}`));
}

// One labelled rail slot: a small uppercase caption over its value area. The label
// stays even when the value is absent (the slot is hidden as a whole via .empty),
// so the layout keeps its shape.
const RAIL_SLOT_LABELS = { state: "state", sources: "sources", freq: "freq", confidence: "confidence" };

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

// Atomic source pills — one per attesting origin (wordnet, wiktionary, …). Two
// pills side by side ARE the agreement signal, matching the atomic Source facet.
function sourcePills(sources) {
    const wrap = document.createElement("span");
    wrap.className = "source-pills";
    for (const origin of sources) {
        wrap.append(cell(`source-pill source-${origin}`, origin));
    }
    return wrap;
}

// The demoted (tier-3) metadata badges: novelty, was-GenAm, definition, info tags —
// the lower-priority provenance the priority rail does not carry. Each keeps
// "absence is the signal": an absent badge renders nothing.
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

// The group the detail editor operates on: the multi-selection when the owner has
// picked one-or-more rows (⌘-click / V / range), otherwise the focused singleton.
// N=1 is the degenerate case that renders identically to a single-record card. The
// picked selection wins over the focused row when both exist (the panel edits what is
// selected). Returns [] when nothing is picked and nothing is focused.
function selectedGroup() {
    if (state.multi.size) {
        return selectedRecords();
    }
    const focused = state.records[state.selected];
    return focused ? [focused] : [];
}

// Render the detail panel for a group of N>=1 records — the ONE path both a single
// focused record and a multi-selection route through. N=1 renders exactly today's
// single-record card (chrome + the related/definitions evidence for that record); N>=2
// renders the group-native chrome (common fields editable, divergent fields in the
// "multiple"/tri-state form). The evidence pair (related + definitions) shows whenever
// the selection is Latin-uniform — every real group shares one Latin word, so the
// evidence is unambiguous and keys off that shared word, exactly as at N=1. Only a
// hand-picked cross-word selection (mixed Latin words) hides it. The verdict bar fans
// out to one patch per member (§1.3).
function renderGroupEditor(group) {
    const record = group[0];
    // A fresh context starts in review mode; but a re-render of the SAME focused record
    // (an undo, a selection re-sync) must not silently drop an active edit — carry the
    // flag over, exactly as the flag survived a render not preceded by select(). Only
    // meaningful for N=1 (a group edit has no single "the record" to compare against).
    const wasEditing = Boolean(
        group.length === 1
        && state.mainContext && contextRecord(state.mainContext) === record
        && state.mainContext.editing,
    );
    const editor = recordEditor(group, { scope: "detail", mode: "edit" });
    state.mainContext.editing = wasEditing;
    // Evidence keys off the Latin word: a Latin-uniform group (every real group, and
    // trivially N=1) shares one word, so the related tree + definitions are unambiguous
    // and gather off the shared word. A cross-word hand-pick has no single word to
    // gather for, so it renders chrome alone.
    if (!latinUniform(group)) {
        DETAIL.replaceChildren(editor);
        setDetailMode();
        return;
    }
    const definitions = definitionsSection();
    const related = relatedSection();
    // Full-width editor chrome on top; the evidence pair (related + definitions)
    // BELOW it, side by side — related WIDER (the scan-to-decide table, all rows
    // visible), definitions beside it. The CSS .evidence-cols grid gives related
    // the larger track and collapses to one column on narrow screens (source order
    // related, then definitions).
    const evidence = document.createElement("div");
    evidence.className = "evidence-cols";
    evidence.append(related, definitions);
    DETAIL.replaceChildren(editor, evidence);
    setDetailMode();
    loadDefinitions(record, definitions);
    loadRelated(record, related);
}

// True when every member of the selection shares the same Latin word — the condition
// under which the word-keyed evidence (related + definitions) is unambiguous. Words are
// compared case-insensitively, mirroring the daemon's natural key (word.lower, per
// compareAnchors). N=1 is trivially uniform.
function latinUniform(group) {
    const first = group[0].word.toLowerCase();
    return group.every((member) => member.word.toLowerCase() === first);
}

// The consensus of one field across a group: uniform (every member holds the same
// value) or divergent ("multiple"). For a uniform field the shared value is returned
// so the editor renders it exactly; for a divergent field the distinct values are
// listed (with each member's identity) so the "·N values" reveal can name them. N=1 is
// trivially uniform, which is what keeps the single-record render byte-identical.
//
// Values are compared by their canonical string form (`fieldValueKey`) so list-valued
// mergers and null/empty compare correctly; the RETURNED `value` for a uniform field is
// the first member's raw value (not the key), so the field renderer sees exactly what a
// single-record render would.
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

// A canonical, comparable string for a field value, so two members "hold the same
// value" iff their keys match. A list-valued field (mergers) collapses to a
// sorted-joined key so order does not create a spurious difference; null/undefined/""
// all collapse to the empty key so an absent field reads as one value, not several.
function fieldValueKey(value) {
    if (Array.isArray(value)) {
        return [...value].sort().join(" ");
    }
    return value == null ? "" : String(value);
}

// The verdict consensus across a (possibly hand-picked, cross-group) selection:
// fieldConsensus over each member's verdictState rather than a stored field. Members
// are projected onto {verdict} shells so the generic keying/count machinery applies
// unchanged; callers read uniform/value/distinct only.
function verdictConsensus(group) {
    return fieldConsensus(
        group.map((record) => ({ verdict: verdictState(record) })), "verdict");
}

// The Clone action: open the shared create modal PREPOPULATED with an exact copy of
// this record, for the owner to adapt into a sibling — a dialect variant (change var),
// a spelling variant (change shaw), a re-tag (change pos), whatever. It is a general
// clone, so it takes no target: the owner edits the copy themselves before saving.
function cloneButton(record) {
    return actionButton("clone", "Clone", () => openCloneModal(record));
}

// The provenance mark for a field the owner overrode on accept: an `overridden`
// class hook on the field wrap and an "edited" tag pinned to its label. A field
// NOT overridden (the live basis value flowing through) is left untouched.
// Read-only — it never changes the field's value or edit behaviour. `wrap` and
// `label` are the same element for the inline word/pos cells.
const EDITED_TAG_TEXT = "edited";

function markOverridden(wrap, label, overridden) {
    if (!overridden) {
        return wrap;
    }
    wrap.classList.add("overridden");
    label.append(cell("edited-tag", EDITED_TAG_TEXT));
    return wrap;
}

// A one-line "edited: shaw, mergers" recap beside the state badge, naming every
// overridden field at a glance. Absent (renders nothing) when nothing was
// overridden — an accept-as-is or an unreviewed row stays quiet.
function editedSummary(overridden) {
    const wrap = document.createElement("span");
    wrap.className = "edited-summary";
    if (overridden.size) {
        wrap.append(
            cell("edited-summary-label", EDITED_TAG_TEXT),
            cell("edited-summary-fields", [...overridden].join(", ")),
        );
    }
    return wrap;
}

// The records currently in the group selection, in working-set order (a selected
// anchor that fell out of the set on a re-run is simply skipped). The working set
// is the whole selection corpus: the daemon serves whole groups per page, so a
// header-selected sibling is always on the page.
function selectedRecords() {
    return state.records.filter(
        (record) => state.multi.has(anchorKey(record.anchor)),
    );
}

// ---- definitions (read-only inline sense summary) ----
// A collapsed, READ-ONLY summary of the focused word's definitions (dictionary
// senses): each sense's English gloss, its Shavian transliteration, and its POS —
// docs/definitions-editor-design.md §5b, phase P2. It is purely a VIEW: no edit or
// flag affordances (those are a later phase). Fetched async off the definitions op
// so a landing never blocks the review loop; a stale response for a previously-
// focused word is dropped (guarded by the definitions generation token).
//
// gb/us: one row per sense with the GB Shavian; the US Shavian is shown as a second
// line ONLY where the daemon reports it diverges (shaw_us present) — "one view, both
// shown only on divergence". The English gloss and POS are shared across dialects.

const DEFINITIONS_TITLE = "Definitions";

// The WordNet POS tags the corpus carries, expanded to a readable label for the
// sense summary. `n-1`/`v-2` style disambiguated tags share the base letter's label
// (the trailing index is an internal sense-split, not a different part of speech).
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

// The section starts collapsed under a summary/disclosure (<details>), so the sense
// list never crowds the word panel until the owner opens it — the design's "collapsed
// summary". The header carries the sense count once loaded.
function definitionsSection() {
    const section = collapsibleSection("definitions", DEFINITIONS_TITLE);
    section.append(definitionsSummary(null), definitionsLoading());
    return section;
}

function definitionsSummary(count) {
    return collapsibleSummary("definitions-title", DEFINITIONS_TITLE, count);
}

// A detail-panel sub-section (definitions, related) as a native <details> whose
// open state is seeded from the owner's persisted per-section preference, so it
// re-opens the same way across record-switches and page reloads. Toggling writes
// the new state back. `id` is the stable persistence key; `label` names it for AT.
function collapsibleSection(id, label) {
    const section = document.createElement("details");
    section.className = id;
    section.setAttribute("aria-label", label);
    section.open = sectionExpanded(id);
    section.addEventListener("toggle", () => setSectionExpanded(id, section.open));
    return section;
}

// The <summary> for a collapsible section: a project chevron (matching the filter/
// drawer toggles) plus the title, with an optional " · count" suffix. The chevron's
// rotation is driven by the parent <details>[open] state in CSS.
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

// Fetch the focused word's senses and fill `section` when it returns. Mirrors
// loadRelated's staleness discipline: the generation token plus the panel-membership
// and connected checks ensure only the newest fetch for the current word may render.
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

// `word` is threaded through so each sense's ✎ can build its correction anchor
// (word + synset + dialect). `section` is retained on the list so a write can
// re-render the just-corrected word's senses in place (see saveDefinitionPatch).
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

// Re-fetch and re-render the senses for `word` into `section` after a correction,
// so the inline view reflects the just-saved Shavian without a full landing. Uses
// the definitions generation guard like loadDefinitions so a stale response for a
// word no longer focused is dropped.
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

// The "this word has no definition" state — the coverage gap made visible rather
// than hidden (the design: ~50% of words have none). A plain note, not an error.
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

// One sense: a POS tag, a source-provenance tag, the English gloss, a ✎ edit
// affordance, and the Shavian transliteration beneath. The source tag is the
// discriminator the owner wants — "wordnet" vs a future "generated" gloss — so a
// reviewer judges trust at a glance. The ✎ opens the correction modal for THIS
// sense. A divergent US transliteration (shaw_us) gets its own dialect-tagged line;
// a sense with no transliteration yet renders the explicit "no transliteration yet"
// gap state, so the coverage tail is discoverable.
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

// The source-provenance tag: a quiet pill naming where the gloss came from. WordNet
// is the neutral default; "generated" (a future machine-drafted / function-word
// batch) is highlighted so a low-trust gloss stands out. Read-only — provenance is
// a fact, not editable.
function definitionSourceTag(source) {
    const tag = cell("definition-source", source);
    tag.classList.add(`definition-source-${source}`);
    tag.title = source === "wordnet"
        ? "Gloss from WordNet"
        : `Gloss source: ${source}`;
    return tag;
}

// The ✎ per-sense affordance: opens the correction modal for this sense. It sits in
// the sense head so it is discoverable inline (design §5b) but the actual editing
// happens in the focused modal (§5c).
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

// The Shavian transliteration line(s) of a sense. The GB Shavian is the primary
// line (untagged when it is the only one); a divergent US transliteration is a
// second line tagged "US" (and the primary is then tagged "GB"), so the two
// dialects read as distinct where they genuinely differ. Absent GB Shavian renders
// the "no transliteration yet" gap state.
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
// The focused surface for correcting a sense's SHAVIAN transliteration. The English
// gloss + synset + source are read-only identity; the Shavian is editable. It reuses
// the modal shell chrome (CREATE_MODAL card/backdrop) but NOT the record-editor
// context (state.modalEditor) — it edits a dictionary sense, not a basis record, and
// writes to the SEPARATE definition-patches store via the definition_patch op.
//
// gb/us edit behaviour (design lean (c), simplest correct):
//   - gb == us (the view shows ONE Shavian line): ONE editable field. Save writes a
//     patch to BOTH dialects, keeping the shared transliteration in sync — the owner
//     corrected "the transliteration".
//   - gb != us (the view shows TWO lines): ONE field PER dialect, each saving its own
//     dialect patch, so a correction to GB never disturbs a genuinely-different US.
// A sense with no transliteration yet (shaw_gb absent) is still correctable — the
// single field starts empty and the save fills the coverage gap for both dialects.

function openDefinitionModal(word, sense, section) {
    const diverges = Boolean(sense.shaw_us);
    // The dialects the modal edits: both-in-one when they match (or when neither is
    // set yet), or each independently when they diverge.
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

    // Read-only identity: POS, source provenance, and the English gloss.
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

// One editable Shavian field for a dialect. `inputs` collects {dialect, input} so
// the shared Save reads every field's current value. Enter in the field saves;
// Escape dismisses (its own listener, so the field-focused global guard leaves it).
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

// Save the correction(s): one definition_patch per edited dialect. A "both" field
// fans onto gb AND us (they were in sync); a per-dialect field targets that dialect.
// Empty Shavian is rejected (a correction must be a real transliteration; removing a
// sense is not a UI feature). After the writes, the inline view re-renders the word's
// senses so the correction shows through.
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
// Every record sharing the focused entry's Latin word (case-insensitive), so
// capitalisation dupes and proper-noun/common-word homographs surface together.
// Fetched async so a landing never blocks the review loop; a stale response for a
// previously-focused word is dropped (guarded by the focused anchor).

const RELATED_TITLE = "Related entries";

function relatedSection() {
    const section = collapsibleSection("related", RELATED_TITLE);
    section.append(relatedHeading(null), relatedLoading());
    return section;
}

function relatedHeading(count) {
    return collapsibleSummary("related-title", RELATED_TITLE, count);
}

// Fetch related for the focused record and fill `section` when it returns. Two things
// can supersede an in-flight fetch before it resolves: the selection may have stepped
// on (fast review), or a write may have re-decided a related entry and triggered a
// fresh reload of THIS record's list. Both are caught by the generation token — only
// the latest loadRelated may render — backstopped by the panel-membership/connected
// checks. So the list always reflects the newest daemon state (e.g. the sibling you
// just accepted shows accepted), never a slower earlier response. The membership check
// asks the DETAIL PANEL (state.mainContext), not the review cursor: a group
// header-select gathers evidence off the panel's group[0], which need not be the
// record state.selected points at.
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

// Re-fetch the related list for the record currently in the detail panel, in place —
// after a write that re-decided one of its siblings WITHOUT re-rendering the detail
// (a modal edit of a related entry, whose main card sits untouched behind the modal).
// The stepping/re-selecting flow already reloads via renderGroupEditor, so this is only for
// the in-place case. A no-op when nothing is focused (empty/group detail has no list).
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

// The "Finding related entries…" placeholder, shared by the initial section and an
// in-place reload so the list shows work-in-progress the same way in both.
function relatedLoading() {
    const loading = document.createElement("p");
    loading.className = "related-loading";
    loading.textContent = "Finding related entries…";
    return loading;
}

// The related list retains its records + focused anchor on the section node, so a
// header sort-click can re-order and re-paint the rows in place without a re-fetch.
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

// The tree of related rows in the current sort order. Split out so a header sort
// click can rebuild just the list against the records stashed on the section.
//
// A flat sibling list hides the key fact — that several entries share ONE spelling
// — so it is folded into a TWO-level tree whose nodes ARE the daemon's ledger groups
// (group_key: word + Shavian + variation set — nearly always one node per spelling;
// a spelling splits only where the ledger itself keeps variation-distinct groups
// apart, and the header's variation markers tell those apart). The node HEADER
// summarises what's inside — the distinct POS tags and distinct VAR tags rolled up,
// plus the leaf count — so the shared spelling reads at a glance; clicking it opens
// the group editor over the node's members (the same modal, and the same fan-out, as
// a main-ledger group edit), while its chevron toggles the fold. EXPANDING a node
// reveals the full flat table (every pos × var × source row) for that spelling; there
// is no deeper nesting. The node holding the focused entry is the default selection:
// it auto-expands and its focused leaf wears the selected-row highlight. Sorting
// orders the nodes (by their first leaf) and the leaves within them (see
// sortedRelated); it never flattens.
function relatedListEl(records, focusedAnchor) {
    const list = document.createElement("ul");
    list.className = "related-list";
    const sorted = sortedRelated(records, focusedAnchor);
    for (const shawGroup of groupRelated(sorted, focusedAnchor)) {
        list.append(shawNode(shawGroup, focusedAnchor));
    }
    return list;
}

// Fold the (already sorted) leaf records into the daemon's ledger groups: the node
// key IS the served group_key (word + Shavian + variation set), so a related node
// always matches the group the main ledger edits as a unit — the client never
// computes grouping. Node order follows the incoming leaf order (the active sort): a
// node appears where its first leaf falls, so sorting the leaves sorts the nodes too.
// Each node collects its leaves plus the distinct POS and VAR tags they carry (order
// of first appearance), for the summarised header. A record without its group token
// is a daemon contract violation — fold nothing rather than fold wrongly.
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

// A spelling node: a summarising header (disclosure + word + Shavian glyphs +
// rolled-up POS/VAR tags + leaf count) plus, when expanded, the flat table of every
// leaf for that spelling. Auto-expanded when it holds the focused entry so the owner
// lands on the current record in context; other nodes collapse to one glance line.
function shawNode(node, focusedAnchor) {
    const li = document.createElement("li");
    li.className = "related-group related-shaw-group";
    const details = groupDetails(node.here);
    details.append(shawSummary(node), shawLeaves(node, focusedAnchor));
    li.append(details);
    return li;
}

// The node's summarising header: word, Shavian spelling, the distinct POS tags and
// VAR tags rolled up from its leaves (so a glance shows what the spelling covers),
// the group's variation markers, and the " · N" leaf count. A focused node is tinted
// to tie it to the detail card. Clicking the header (outside the chevron, which keeps
// the native disclosure toggle) opens the group editor over the node's members — the
// ledger group, edited as a unit.
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
    // The variation set is part of the group key, so it is node-uniform and the first
    // leaf speaks for all: its markers distinguish same-spelling sibling nodes the
    // ledger deliberately keeps apart.
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

// The expanded node body: the flat related-row table, scoped to this spelling's
// leaves. Each leaf is clickable → modal (except the focused one, inert above).
function shawLeaves(node, focusedAnchor) {
    const body = document.createElement("ul");
    body.className = "related-subtree related-leaves";
    for (const record of node.leaves) {
        body.append(relatedRow(record, focusedAnchor));
    }
    return body;
}

// A tree node's <details> shell — native disclosure, open per the caller's default.
function groupDetails(open) {
    const details = document.createElement("details");
    details.className = "related-node";
    details.open = open;
    return details;
}

// The related table's sortable header, mirroring the ledger's sort-head row: one
// clickable header per column (word / pos / var / shaw / source / state) whose
// click sets state.relatedSort and re-orders the list client-side. The state
// header (last) spans the badge + label tracks (one logical column), so the six
// headers line up over the row cells they name.
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

// A related header was clicked: sort ascending, or flip to descending if that
// column is already the ascending sort. Re-orders + re-paints the list in place
// (client-side; no re-fetch), keeping the focused row pinned to the top.
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

// Reflect the active related sort on its header: the sorted column carries the
// direction class (▲/▼ via the shared sort-head CSS) and aria-sort; the rest clear.
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

// Order the related rows deterministically so the list is stable across landings
// (the daemon returns them in an unspecified index order). The focused entry ("you
// are here") ALWAYS leads regardless of the active sort, anchoring the eye to the
// card above. Beneath it the siblings sort by the active header sort (state.relatedSort)
// when one is set, else the default chain (word, pos, var, source, canonical, shaw).
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

// A ranking of the related state glyphs so a "state" sort orders by review status
// meaningfully (unreviewed/candidate first — the rows that still need a decision —
// then the settled verdicts) rather than by the raw patch_state string.
const RELATED_STATE_ORDER = new Map([
    ["unreviewed", 0],
    ["orphaned", 1],
    ["flagged", 2],
    ["dropped", 3],
    ["accepted", 4],
]);

// Compare two related records on one header column. Returns <0/0/>0 for the
// ascending order of `key`; sortedRelated negates it for descending. String keys
// compare case-sensitively except word (case-insensitive, matching the row/ledger).
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

// A record with no dialect merger and no variant flag is the canonical spelling;
// its flagged siblings are alternates that sort beneath it within their bunch.
function isCanonical(record) {
    return (!record.mergers || record.mergers.length === 0) && !record.variant;
}

// source is list-valued (the origins that agreed); collapse it to one deterministic
// key so multi-source records group consistently regardless of origin order.
function sourceKey(record) {
    return Array.isArray(record.source) ? [...record.source].sort().join("+") : "";
}

function compareRelated(left, right) {
    // Latin word first (case-insensitive), so a word's entries stay together and
    // shaw-only siblings (estrogen/oestrogen, lat/lotte) don't interleave with them.
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
    // A sibling row opens in a modal for in-place review; the focused row is already
    // the detail card above (it wears the selected-row highlight), so it is inert.
    if (!here) {
        row.classList.add("clickable");
        row.addEventListener("click", () => openRelatedModal([record]));
    }
    return row;
}

// Open related records in an edit-mode modal for in-place review: the FULL editor
// (top matter, fields, verdict/clone bar) hosting the given records — one for a leaf
// row, the whole ledger group for a node header — over the workbench. The related op
// already returned full serialisable records, so no extra fetch is needed. Verdicts
// and edits act on these records (activeContext() = the modal), fanning out per
// member exactly as a main-ledger group edit. A verdict is the modal's ONE action:
// it writes the patch(es), re-annotates the affected main ledger rows by anchor (the
// main cursor never moves), and dismisses back to the exact spot the owner left —
// one action, no separate save-then-close.
function openRelatedModal(records) {
    openModal(recordEditor(records, { scope: "modal", mode: "edit" }));
}

// The dialect column of a related row: the var, plus compact variant/merger
// markers when the record carries them, so a variant or merger alternate is
// distinguishable from a canonical sibling at a glance. Grouped into one grid
// track (the row's column template is fixed) and kept quiet — a canonical row
// shows only its var. Markers mirror the detail badges but sized to the dense
// row (see .related-variant / .related-merger).
function relatedDialect(record) {
    const wrap = document.createElement("span");
    wrap.className = "related-dialect";
    wrap.append(varCell(record.var), ...variationMarkers(record));
    return wrap;
}

// The compact variant/merger marker cells for a record, shared by the dialect column
// and the node header (where the variation set is part of the group identity).
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

// The source column of a related row: the collapsed provenance combo as one tag,
// formatted exactly like the source facet (sorted, "+"-joined — e.g.
// "wordnet+wiktionary"), so a multi-source agreement reads the same here as in the
// filter. Upstream (readlex) rows carry no tag — the badge already says "upstream".
function relatedSource(record) {
    const key = sourceKey(record);
    if (!key || key === "readlex") {
        return cell("related-source", "");
    }
    return cell("related-source", key);
}

// Provenance + review state of a related record, from the fields the view already
// carries. The verdict decides first (a patch's verdict overrides origin; edited
// reads as its accept, dirty as unreviewed); an untouched row falls back to its
// origin. `state` is a --state-* class so the badge reuses the ledger palette;
// `glyph` is the non-colour channel.
function relatedProvenance(record) {
    switch (verdictState(record)) {
        case PATCH_STATE.DROPPED:
            return { state: "dropped", glyph: "✕", label: "dropped" };
        case PATCH_STATE.FLAGGED:
            return { state: "flagged", glyph: "⚑", label: "flagged" };
        case PATCH_STATE.ORPHANED:
            return record.orphan_kind === ORPHAN_KIND.RESURFACED_DROP
                ? { state: "dropped", glyph: "⚠", label: "drop — resurfaced" }
                : { state: "orphaned", glyph: "⚠", label: "accept-orphan" };
        case PATCH_STATE.ACCEPTED:
            return { state: "accepted", glyph: "✓", label: "sanctioned" };
        default:
            // An unreviewed-verdict row: upstream, a manual record awaiting review
            // (the word says manual, the colour stays the verdict grey), or a
            // harvested candidate.
            if (record.manual) {
                return { state: "unreviewed", glyph: "✎", label: "manual" };
            }
            return record.source.includes("readlex")
                ? { state: "unreviewed", glyph: "✓", label: "upstream" }
                : { state: "unreviewed", glyph: "○", label: "candidate" };
    }
}

// The detail card reads its mode off the card element: review mode shows the
// "REVIEW" affordance and keeps every field non-focused; edit mode lifts it.
function setDetailMode() {
    const editing = Boolean(state.mainContext && state.mainContext.editing);
    DETAIL.classList.toggle("mode-edit", editing);
    DETAIL.classList.toggle("mode-review", !editing && state.selected >= 0);
}

// The orphan sub-tag: on an `orphaned` row, a small badge naming the op + why it
// orphaned (accept-orphan vs the URGENT drop-resurfaced), from overlay.orphan_kind.
// Non-orphan rows render nothing. Mirrors the other quiet badges (wrapped span,
// empty when the signal is absent) so it sits naturally beside the state badge.
function orphanKindBadge(record) {
    const wrap = document.createElement("span");
    wrap.className = "orphan-kind-badges";
    if (record.patch_state !== PATCH_STATE.ORPHANED) {
        return wrap;
    }
    const tag = ORPHAN_KIND_TAGS.get(record.orphan_kind);
    if (!tag) {
        return wrap;
    }
    const badge = cell(`orphan-kind-badge ${record.orphan_kind}`, tag.label);
    badge.title = tag.title;
    wrap.append(badge);
    return wrap;
}

// The detail-panel explanation of an orphaned record: the kind, WHY it orphaned, and
// the action the owner should take. The ledger row shows only the coloured "orphaned"
// tag (room is tight there); this note — shown where there is room — spells the reason
// and action out in words rather than hiding them in a tooltip. Non-orphan records, or
// an orphan of an unrecognised kind, render nothing.
function orphanReasonNote(record) {
    if (record.patch_state !== PATCH_STATE.ORPHANED) {
        return null;
    }
    const tag = ORPHAN_KIND_TAGS.get(record.orphan_kind);
    if (!tag) {
        return null;
    }
    const note = document.createElement("div");
    note.className = `orphan-note orphan-${record.orphan_kind}`;
    const head = cell("orphan-note-kind", tag.label);
    const reason = cell("orphan-note-reason", tag.reason);
    const action = document.createElement("div");
    action.className = "orphan-note-action";
    action.append(cell("orphan-note-action-label", "Action"), cell("orphan-note-action-text", tag.action));
    note.append(head, reason, action);
    return note;
}

// The merger label map — the related-row dialect column still renders compact
// merger markers from it (the detail heading's merger badges are gone, replaced by
// the attributes chips control).
const MERGER_LABELS = new Map(MERGERS);

// A record's upstream-definition provenance, as a small "def" badge beside the
// word. Shown only when the source(s) carry a definition; no-definition shows
// nothing — the absence is the signal, mirroring the merger/variant badges.
function definitionBadge(hasDefinition) {
    const wrap = document.createElement("span");
    wrap.className = "def-badges";
    if (hasDefinition) {
        wrap.append(cell("def-badge", DEFINITION_LABEL));
    }
    return wrap;
}

// A record's relabel provenance, as a quiet "was GenAm" pill beside the word: the
// var a pipeline transform changed this record's var away from (basis.orig_var).
// Read-only — derived provenance, an audit/triage signal, never editable. Shown
// only when orig_var is present and genuinely differs from the current var; equal
// or absent shows nothing (the absence is the signal, mirroring the other badges).
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

// A record's novelty against upstream ReadLex, as a quiet pill beside the word: is
// this word/spelling/pos new to the dictionary. Shown only for the new-* buckets —
// the triage signal that matters; `known` (present upstream) renders nothing, the
// absence being the signal, mirroring the def/orig-var provenance badges.
function noveltyBadge(novelty) {
    const wrap = document.createElement("span");
    wrap.className = "novelty-badges";
    const label = NOVELTY_LABELS.get(novelty);
    if (label) {
        wrap.append(cell(`novelty-badge ${novelty}`, label));
    }
    return wrap;
}

// A record's informational metadata (basis.INFO_FIELD), as quiet pills beside the
// word — one per tag (e.g. obsolete/dialectal). Read-only derived provenance, never
// editable. Shown only when the list is non-empty; absent/empty renders nothing,
// the absence being the signal, mirroring the def/orig-var provenance badges.
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

// The VARIATIONS control: a row of always-visible TOGGLE BUTTONS unifying the
// mergers and the free-variation ("other") marker under one labelled group. Each
// button toggles its member on/off (like the pre-redesign merger toggle-row + the
// variant toggle, merged into one "Variations" group). The vocabulary is the
// mergers (MERGERS, keeping their display labels) plus the "other" member (backed
// by the variant boolean, relabelled from "variant").
//
// INTERNAL representation stays FLATTENED: each toggle owns a `.merger-check`
// checkbox (mergers) or the lone `.variant-check` checkbox ("other"), so the
// existing harvest (applyAdditiveFields) and dirty-check (mainEditIsDirty) read
// exactly the same DOM they always did — the on-disk shape (mergers list + variant
// bool) and the patch round-trip are byte-identical when unchanged. The buttons are
// just a display+edit skin over those checkboxes. This is a DISPLAY/LABEL change
// only: nothing on disk is renamed.
const ATTRIBUTE_VARIANT = VARIANT_LABEL; // on-disk "variant"; displayed "other"

function attributesField(ctx, group, overridden) {
    const wrap = document.createElement("div");
    wrap.className = "edit-field variations-field";

    const caption = document.createElement("span");
    caption.className = "edit-label";
    caption.textContent = "Variations";

    const toggles = document.createElement("div");
    toggles.className = "variation-toggles";
    // All the mergers, then the "other" (variant) member — always visible, mirroring
    // the pre-redesign toggle row (which showed every merger + the variant toggle). Each
    // toggle's state comes from the group tally: all members carry it → on, none → off,
    // some → indeterminate ("mixed", D2). Within a single record-list group the variation
    // set is identical by construction, so "mixed" only arises for a cross-group hand-pick.
    let anyMixed = false;
    for (const [value, label] of MERGERS) {
        const tally = mergerTally(group, value);
        anyMixed = anyMixed || tally === TRISTATE_MIXED;
        toggles.append(variationToggle(ctx, "merger-check", value, label, tally));
    }
    const variant = variantTally(group);
    anyMixed = anyMixed || variant === TRISTATE_MIXED;
    toggles.append(variationToggle(ctx, "variant-check", "", VARIATION_OTHER_LABEL, variant));

    // A group whose members disagree on their variation flags starts "mixed": the harvest
    // must NOT fan the checkbox state out unless the owner actually moved a toggle (else an
    // untouched group edit would silently rewrite each member's flags to the union). A
    // uniform control (N=1 always) is never mixed, so its flags always apply — the N=1
    // invariant. `markVariationsTouched` clears the block's untouched status on first move.
    if (anyMixed) {
        wrap.dataset.mixed = "true";
    }
    wrap.append(caption, toggles);
    // An accept that changed either flattened field (mergers or variant) marks the
    // Variations control as edited (a single-record provenance mark; empty for a group).
    markOverridden(wrap, caption, overridden.has("mergers") || overridden.has("variant"));
    return wrap;
}

// The group tally for one merger value: "on" if every member carries it, "off" if none
// does, "mixed" if some do — the tri-state a toggle renders (D2). N=1 is always on/off.
function mergerTally(group, value) {
    return tristate(group, (member) => (member.mergers || []).includes(value));
}

// The group tally for the "other" (variant) flag: on/off/mixed across the members.
function variantTally(group) {
    return tristate(group, (member) => Boolean(member.variant));
}

// Collapse a per-member boolean predicate to a tri-state over the group: "on" when all
// hold, "off" when none holds, "mixed" otherwise. The single primitive both variation
// tallies share.
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

// One VARIATIONS toggle button. It hosts the flattened backing checkbox — a
// `.merger-check` carrying its merger value, or the lone `.variant-check` (no
// value; its presence is the "other"/variant flag) — exactly the inputs
// applyAdditiveFields / mainEditIsDirty read. The pill IS the affordance; the
// checkbox is the hidden state. Toggling enters edit mode on the owning context.
//
// `tally` is the tri-state over the group: "on"/"off" render a plain checked/unchecked
// toggle (N=1 always lands here); "mixed" renders the indeterminate dash. The first
// click off "mixed" is a uniform decision — it sets the checkbox for real (the browser
// clears indeterminate on click) and marks the whole Variations control touched, so the
// group harvest fans the uniform mergers/variant out to every member (an untouched
// control leaves each member's own flags alone — §1.3).
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

// Mark the context's Variations control as touched: once the owner moves any variation
// toggle, the whole mergers+variant block becomes a uniform decision the group harvest
// fans out to every member. Left untouched, each member keeps its own flags.
function markVariationsTouched(ctx) {
    const field = ctx.root.querySelector(".variations-field");
    if (field) {
        field.dataset.touched = "true";
    }
}

// The detail editor's field id prefix (its harvest is scoped by data-field, not id;
// the id just keeps its label/for association stable). A modal editor uses its OWN
// prefix (MODAL_FIELD_PREFIX) so the two never collide in the DOM while a modal sits
// over the detail record.
const DETAIL_FIELD_PREFIX = "field-";

// The bare labelled text input: the shared markup both the review editor and the
// modal create form build on. It carries the field's identity (id + data-field)
// and dirty tracking, but NO review-flow listeners — those belong to the surface
// that owns it, so the modal can bind its own submit/dismiss keys instead.
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

// The review-editor field: the shared input plus the review-flow listeners
// (focus enters edit mode, keys run the in-field verdicts) and the overridden mark.
// Bound to its editor context, so focus enters edit mode on THAT context.
//
// Group-native: the field consults the whole group. When every member shares the value
// the box shows it exactly and editing applies to all (N=1 is the trivial case — this is
// the byte-identical single-record render). When members differ, the box renders the
// "multiple" state (D1): empty, a greyed `multiple` placeholder, a one-line truncated
// `·N a, b, c` list of the distinct values (full list on hover), and a marker
// (`data-consensus="multiple"`) the harvest reads. Typing OVERWRITES the field for every
// member (no unlock); the first keystroke
// flips the box to a pending-overwrite style and marks it touched so the harvest knows
// to fan the value out (an untouched "multiple" box leaves each member's value alone).
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

// The verdict controls, group-native. Every verdict fans out to one patch per member
// (§1.3), so the same four buttons drive a single record and a group alike — only their
// tooltips ("Accept" vs "Accept all") and the trailing affordances differ. The keyboard
// is the fast path; the buttons mirror it and give mobile real touch targets.
//
// N=1 renders exactly today's single-record bar: Accept/Drop/Flag/Clear, then Clone,
// then (conditionally) Unflag and Undo. A multi-member group swaps Clone → Deselect
// (Clone authors a NEW record FROM this one — a single-record move; a group has no one
// record to clone) and drops the single-record Unflag/Undo, which act on one focused
// row's patch, not a fan-out.
function actionBar(ctx, group) {
    const record = group[0];
    const many = group.length > 1;
    const bar = document.createElement("div");
    bar.className = "actions";

    // Clear is a PERMANENT slot in the action row (not gated on record.reviewed):
    // the owner wants it always present. clearSelected() itself no-ops on an
    // unreviewed row (no patch to clear), so an always-visible Clear is safe.
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

// Inline SVG icon paths per action kind (CSP forbids external assets). Drawn in a
// 24×24 viewBox with currentColor so each button's own colour flows through:
//   accept = checkmark · drop = trash · clear = cross/x · flag = flag ·
//   clone = duplicate/clone · undo = undo-arrow · unflag = flag-off.
const ACTION_ICONS = {
    accept: '<path d="M5 13l4 4L19 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    drop: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V7M10 11v6M14 11v6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    clear: '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
    flag: '<path d="M6 21V4m0 0h11l-2 4 2 4H6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    unflag: '<path d="M6 21V4m0 0h11l-2 4 2 4H6M3 3l18 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    clone: '<path d="M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    undo: '<path d="M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
};

// An action button: ICON-ONLY. The inline SVG glyph IS the button — no visible
// text label, so every action fits one compact row on both desktop and mobile. The
// label survives only as the title (hover tooltip) and aria-label (accessible
// name). A kind with no icon (the modal create/cancel) falls back to a text button.
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
// base each member's group verdict overlays its harvested group edits onto. Single-
// record verdicts overlay the live inputs on top of this (editedRecord, via harvestRecord).
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

// The record an editor context currently describes, harvested scoped to the context's
// root (by data-field), so it reads THAT editor's inputs and no other's. The SINGLE
// harvest for both modes: create authors a self-contained record from scratch (no base
// to overlay onto); edit overlays the live edit surface onto the record's own fields.
function harvestRecord(ctx) {
    return ctx.mode === CREATE_MODE
        ? authoredRecord(ctx)
        : editedRecord(ctx);
}

// A create-mode harvest: a self-contained authored record built only from the modal's
// inputs — word/shaw/pos/var/ipa (non-empty) plus the additive mergers/variant. No
// base record is carried (an authored row has no basis), so no status/source/freq
// leaks in; the daemon anchors it on the identity fields alone.
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

// An edit-mode harvest: the record's own fields with the edit surface overlaid from
// the inputs. Only run on a single-record context (save/auto-save guard on N=1), so
// every EDITABLE_FIELDS input — including word — is present; the read-only pos
// carries through from recordFields.
function editedRecord(ctx) {
    const result = recordFields(contextRecord(ctx));
    for (const name of EDITABLE_FIELDS) {
        const input = ctx.root.querySelector(`[data-field="${name}"]`);
        result[name] = name === "freq" ? parsedFreq(input.value) : input.value.trim();
    }
    applyAdditiveFields(ctx, result);
    return result;
}

// Overlay the additive mergers/variant flags from the context's toggles onto a
// harvested record: present only when set, absent (deleted) otherwise — the canonical
// "absence is the signal" convention both harvests share.
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

// The group's touched edits: ONLY the fields the owner actually changed, to overlay onto
// each member so untouched fields keep each member's own value (§1.3). A verdict on a
// group fans this overlay across every member. The rules per field kind:
// - text (shaw/var/ipa, plus word at N=1 only): a COMMON field always contributes its (possibly edited) input
//   value — at N=1 every field is common, so this reproduces editedRecord's overlay
//   exactly (the N=1 invariant). A "multiple" field contributes ONLY if the owner typed
//   into it (data-touched), overwriting all members; left blank it is omitted.
// - variations (mergers/variant): a UNIFORM control (never mixed — always so at N=1)
//   always contributes its checkbox state; a MIXED control contributes only once the
//   owner has moved a toggle (data-touched on the variations field).
function harvestGroupOverlay(ctx) {
    const overlay = {};
    for (const name of EDITABLE_FIELDS) {
        // word and freq are single-record-only: a group renders no input for
        // them (glanceColumn), so skip both — fanning ONE word or ONE
        // POS-specific freq across N members is never right. At N=1 the inputs
        // exist and harvest like any field.
        if ((name === "word" || name === "freq") && ctx.group.length > 1) {
            continue;
        }
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

// Apply the group's harvested overlay to one member's own record body: touched text
// fields overwrite; an untouched text field keeps the member's value (recordFields
// already carried it). When the variations control is included, its checkbox state
// (uniform, or the owner's uniform decision off a mixed state) replaces the member's
// mergers/variant via the shared applyAdditiveFields.
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

// One member's patch body under a group verdict: its OWN fields (recordFields) with the
// group's touched edits overlaid. This is the group-native analogue of editedRecord —
// at N=1 the overlay is the full editable surface, so the two produce the same body.
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

// freq harvested from its input: a whole non-negative number, or null for
// anything else (including an emptied box — the input is prefilled, so blank is
// not a value). null is rejected loudly by requireFreq / the daemon validator;
// nothing is ever silently coerced.
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
// Author a brand-new manual record with no basis behind it. The daemon's authorship
// path is a patch with anchor null and a self-contained record (see editord.py
// handle_patch): {op:"patch", anchor:null, record:{…}, author, dirty:true}. This is
// the ONLY flow that mints such a record; every other write edits or re-decides an
// existing one. A new manual record is created DIRTY — verdict UNREVIEWED, shipping
// nothing — and then passes through review like any other row (accepting it is a
// separate, explicit act on the workbench). No surprises, nothing auto-accepts.
//
// ONE dismissable dialog serves both entry points: New Entry opens it BLANK, and Clone
// opens the SAME dialog SEEDED with an exact copy of a source record — cloning is just
// "open the edit dialog seeded from this record". Its CONTENT is a recordEditor in
// create mode (scope "modal") — the single editor renderer shared with the detail
// panel — so create and edit never diverge. The action bar is [Create, Flag, Cancel]
// (D6 — no Drop, no Clear before creation). Create authors the record unreviewed,
// Flag authors it flagged, Cancel dismisses. The distinctness guard (D3) blocks the
// actions LIVE while the new anchor duplicates an existing live record.
//
// The only difference between New Entry and Clone is the seed and the title/hint wording.

// The identity fields a new record must carry — the natural key the daemon anchors
// it on (RECORD_REQUIRED_FIELDS). ipa/mergers/variant are optional spelling detail.
const NEW_ENTRY_REQUIRED = [
    ["word", "Word"],
    ["shaw", "Shavian"],
    ["pos", "POS"],
    ["var", "Dialect (var)"],
];

// A modal editor's inputs carry their OWN id prefix (distinct from the detail
// editor's "field-"), so the modal's fields never collide with the detail record's
// fields in the DOM behind the backdrop. Both modal modes — create (New Entry/Clone)
// and edit (a related entry opened for review) — share it, since only one modal is
// ever open. Harvest scopes to the context's root by data-field, never by id.
const MODAL_FIELD_PREFIX = "modal-";

// A blank seed for the New Entry route: every create field empty. Gives the create
// field builders a uniform record shape to read, whether seeded (clone) or blank.
function blankSeed() {
    return { word: "", pos: "", var: "", ipa: "", shaw: "", mergers: [], variant: false };
}

// Open the create dialog BLANK — the New Entry route. Bulk selection and the review
// cursor are left as they are: the dialog sits OVER the workbench and dismisses back
// to it untouched.
function openCreateForm() {
    openCreateModal(blankSeed(), false);
}

// Open the create dialog SEEDED with an exact copy of a source record — the Clone
// route. EVERY field is seeded verbatim (word/pos/var/ipa/shaw/mergers/variant); the
// owner edits whatever makes it a distinct sibling before a verdict. An unedited copy
// stays blocked by the distinctness guard (its anchor duplicates the source).
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

// Open the create dialog: host a create-mode recordEditor in the modal shell. Its
// content owns the fields, harvest and verdict bar; the shell supplies the backdrop,
// dismiss × and keyboard guards. `seeded` picks the Clone vs New Entry wording.
function openCreateModal(seed, seeded) {
    // Each dialog session starts with a fresh guard cache, so a sibling authored or
    // re-decided since the last open is reflected (the cache is primed lazily per word
    // as the owner types the identity).
    relatedGuardCache.clear();
    openModal(recordEditor([seed], { scope: "modal", mode: CREATE_MODE, seeded }));
    const first = document.getElementById(`${MODAL_FIELD_PREFIX}word`);
    if (first) {
        first.focus();
    }
}

// The generic modal shell: stand up the card chrome (backdrop, dismiss ×) around a
// pre-built recordEditor and raise the keyboard/selection guards. recordEditor has
// already stored the context as state.modalEditor, so isModalEditorOpen() is true and
// activeContext() routes to it. Both entry points — create (New Entry/Clone) and edit
// (a related entry opened for review) — funnel through here so the shell lifecycle is
// defined once.
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

// Whether the given (or the active) context is a create-mode editor — the New
// Entry/Clone form, which authors from scratch and shows no review affordances. An
// edit-mode modal (a related entry opened for review) is NOT this.
function isCreateMode(ctx = activeContext()) {
    return Boolean(ctx) && ctx.mode === CREATE_MODE;
}

// Dismiss the modal without writing anything, returning to the workbench exactly as
// it was. A create modal never touched the workbench; an edit modal already refreshed
// the affected ledger row by anchor on each write (main cursor/scroll untouched), so
// there is nothing to re-render on dismiss. Every route (Escape / backdrop / X /
// Cancel) lands here.
function closeModal() {
    if (!isModalEditorOpen()) {
        return;
    }
    state.modalEditor = null;
    CREATE_MODAL.classList.remove("open");
    CREATE_MODAL.setAttribute("aria-hidden", "true");
    CREATE_MODAL.replaceChildren();
}

// The create editor's top matter: title + hint (NOT the edit-mode badges/facts —
// a not-yet-created record has no patch state). Clone (seeded) and New Entry differ
// only in wording.
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

// The create editor's field stack: word/shaw/ipa each on their own row, then Dialect
// (var) + POS + mergers + variant grouped on one row. POS is EDITABLE here (the
// author types the anchor), unlike the detail editor where it is read-only; word is
// editable in both.
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

// A create-editor text field: the shared input markup under the context's id prefix,
// with none of the review-flow listeners (the modal owns Enter/Escape itself).
function createField(ctx, name, label, value, extraClass = "") {
    return fieldInput(name, label, value, extraClass, ctx.prefix).wrap;
}

// Dialect (var) + POS + mergers + variant on one row, mirroring the detail editor's
// variantRow. POS lives here (not a read-only glance) because on a new entry the
// author types it.
function createVariantRow(ctx, record) {
    const row = document.createElement("div");
    row.className = "field-row";
    row.append(
        createField(ctx, "var", "Dialect (var)", record.var),
        createField(ctx, "pos", "POS", record.pos),
        // The create form authors ONE record; its variations render as the trivial
        // singleton group (every tally on/off, never mixed) — identical to before.
        attributesField(ctx, [record], new Set()),
    );
    return row;
}

// The create/clone dialog's action bar (D6) — [Create, Flag, Cancel]. Create
// authors the record UNREVIEWED (a new manual record enters the review queue, it
// is never born accepted); Flag authors it flagged; Cancel dismisses. No Drop
// (authoring only to suppress is marginal) and no Clear (meaningless before a
// record exists). Below the buttons sits the distinctness-guard message, hidden
// until the guard has something to say. Create/Flag carry the `create-verdict`
// hook the guard enables/disables live.
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

// The required fields left blank, by human label, for a fail-loud validation toast.
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

// The live siblings of `word` the distinctness guard checks against — every annotated
// record sharing the Latin word case-insensitively (the daemon's `related` read; a
// SUPERSET of what can collide, since the comparison itself is case-sensitive). Cached
// by lowercased word so typing does not re-query per keystroke. A cache
// value of `null` means the fetch is IN FLIGHT (the siblings are not yet known); the
// guard treats that as "checking", never as "distinct", so a duplicate is never waved
// through in the fetch window. The fetch re-evaluates the open dialog once it lands.
const relatedGuardCache = new Map();

// The guard's view of a word's siblings: {pending, siblings}. `pending` true = the
// fetch is outstanding, so the caller must not conclude "distinct". `siblings` is the
// LIVE occupants (a dropped / resurfaced-drop sibling has vacated its anchor and never
// blocks a re-author). An absent word (nothing typed yet) is neither pending nor
// occupied — an empty, resolved set.
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

// Evaluate the distinctness guard (D3) against the dialog's current fields and paint it
// LIVE. EXACT duplication (word, pos, shaw, var already live — word case-sensitive)
// HARD-BLOCKS:
// the verdict buttons disable and the guard names the collision. While the sibling fetch
// is in flight ("pending") the verdicts are ALSO disabled — the guard never waves an
// anchor through before it knows the siblings. A CANONICAL conflict (a different-shaw
// accepted canonical on the same word/pos/var — the daemon's _canonical_conflict) only
// WARNS: authoring a competing candidate is legitimate, so the verdicts stay live. An
// anchor still missing a required field is neither blocked nor warned, and the guard
// stays quiet (submit surfaces the precise "Required: …" message).
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

// Whether the create dialog's verdicts are currently blocked by the distinctness guard
// — read off the guard element the live evaluation already painted (evaluateDistinctness
// is the SOLE painter, running synchronously on every input/change and on open), so the
// keyboard Accept and the buttons share one source of truth. A collision OR a pending
// fetch blocks both.
function createVerdictBlocked(ctx) {
    const guard = ctx?.root?.querySelector(".create-guard");
    return Boolean(guard) && BLOCKING_GUARD_STATES.has(guard.dataset.state);
}

// The guard verdict for a harvested record: {state, message}. "collision" (exact live
// anchor exists) and "pending" (siblings not yet fetched) both block; "warn" (a rival
// canonical exists) allows; "ok" (distinct, or still incomplete) is silent.
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

// The patch states the daemon treats as an accepted (sanctioned/shipped) entry —
// mirrors editord ACCEPTED_STATES, for the canonical-conflict check. (An accepted
// manual record carries "accepted" like any other.)
const ACCEPTED_STATES = new Set([PATCH_STATE.ACCEPTED, PATCH_STATE.EDITED]);

// The daemon's one-canonical-per-(word,pos,var) rival (editord _canonical_conflict),
// mirrored client-side to WARN before the write: only when the authored record is itself
// canonical (no merger, not variant) does a different-shaw live canonical sibling on the
// same (word,pos,var) count. Returns that sibling, or null.
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

// A record is CANONICAL when it carries no additive flag (empty mergers, not variant) —
// the daemon's _is_canonical. Only canonical accepts contend for the one-per-key slot.
function isCanonicalRecord(record) {
    return !(record.mergers && record.mergers.length) && !record.variant;
}

// Author a new entry from the create dialog (Create or Flag). Validates the identity
// fields client-side (the daemon validates too, but this gives a precise, immediate
// message), then sends the authorship patch: {op:"patch", anchor:null, record,
// author, dirty:true} — dirty, so the new manual record lands UNREVIEWED and goes
// through review like any other row (never born accepted). Flag additionally
// re-authors the fresh record with op flag (the daemon flags a manual entry via
// `replaces`, so a flagged authorship is create-then-flag). On success the modal
// closes and the owner lands on the new row; a daemon rejection on the authorship
// write surfaces as a toast with the dialog left open. The distinctness guard has
// already disabled the buttons on an exact-anchor collision, so this is the
// belt-and-braces backstop, not the primary block.
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
            { op: "patch", anchor: null, record, author: AUTHOR, dirty: true });
    } catch (error) {
        showToast(error.message, true);
        return;
    }
    // The record is now live. Surface its row NOW — even if the follow-up flag fails —
    // so a written entry is never stranded invisibly in the store. The dialog closes
    // regardless: the row is on the workbench and re-decidable from there. The response
    // carries EVERY record on the daemon's (case-folded) anchor key — a case-variant
    // sibling may ride along — so the new entry is picked by its own patch id.
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

// Place a freshly-authored record into the working set and land on it. Unlike a
// verdict (which re-annotates an existing row in place), a new record has no row
// yet. The daemon stamps every served record with its group_key, so the new record
// JOINS its group's run when that group is already on the page (a group verdict
// must fan out to it — every member on the page, §3.2/D7), else it opens a fresh
// singleton group at the top so the owner sees it at once. The daemon always
// returns the annotated record for an authorship write, so an empty response — or
// one without its group token — is a contract violation and fails loud.
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

// Run a single-record verdict, surfacing any failure as an error toast. The group
// path handles its own errors (per-record, in runGroup), so this guards only the
// single-record branch.
async function single(action) {
    // A single-record verdict may step/select to the next record as part of its own
    // flow (accept → step → select). That leave has already been persisted by the
    // verdict, so the auto-save-on-leave must NOT fire again for it — the flag
    // suppresses auto-save for the duration of any verdict.
    verdictInFlight = true;
    try {
        await action();
    } catch (error) {
        showToast(error.message, true);
    } finally {
        verdictInFlight = false;
    }
    // Every single-record action here mutates the patch store, so the uncommitted
    // count may have changed — keep the Commit button and the masthead counts honest.
    await refreshCommitStatus();
    await refreshPatchCounts();
}

// Save is inherently single-record — it writes the edited fields, which only make
// sense for the focused record — so it has no bulk form (the group bar omits it).
// No longer bound to a button: saving is now IMPLICIT (auto-save on leave, see
// autoSaveMainEdit). Kept as the explicit "save now, don't step" path (⌘Enter in a
// field) and as the shared writePatch("saved") core the auto-save reuses.
async function saveSelected() {
    const ctx = activeContext();
    const selected = contextRecord(ctx);
    if (!selected) {
        return;
    }
    // Save is single-record: it persists ONE record's bare edit. A group's edits are
    // committed only through an explicit verdict (which fans out per member), never a
    // save — so ⌘Enter in a group panel does nothing.
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

// Auto-save the main detail edit when the focus is about to leave it (navigate to
// another row, or dismiss to the empty state). Fires ONLY when the owner genuinely
// changed an editable field from the record's current value — a stray keystroke that
// nets back to the original writes nothing. A verdict (accept/drop/flag) already
// persisted and stepped, so it suppresses this via verdictInFlight. The write reuses
// saveSelected's writePatch("saved", …) exactly, targeting the leaving record's OWN
// anchor, so it is independent of wherever the cursor lands next.
function autoSaveMainEdit() {
    if (verdictInFlight || isModalEditorOpen()) {
        return;
    }
    const ctx = state.mainContext;
    if (!ctx || ctx.mode === CREATE_MODE || !contextRecord(ctx)) {
        return;
    }
    // Auto-save-on-leave is a SINGLE-record concept: it persists one record's bare edit
    // when the cursor moves off it. A group edit has no single record to auto-save (its
    // "multiple" boxes read empty and would spuriously fail requireShaw); a group's edits
    // are committed only through an explicit verdict, never on navigate. Skip for N>=2.
    if (ctx.group.length > 1) {
        return;
    }
    // Only trust a harvest while the context's inputs still describe its record. After a
    // write, applyWriteResult replaces state.records[i] but the context's record/DOM lag
    // behind; that path runs under verdictInFlight, so it is already excluded above.
    if (!mainEditIsDirty(ctx)) {
        return;
    }
    const selected = contextRecord(ctx);
    const record = harvestRecord(ctx);
    if (!requireShaw(record) || !requireFreq(record)) {
        // An empty/invalid Shavian or frequency is not a valid save — leave the edit
        // unsaved (the toast says why) rather than shipping a bad value. Navigation
        // still proceeds.
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

// Has an editable field (or an additive merger/variant flag) actually diverged from
// the record the detail is currently showing? The dirty-check that gates auto-save:
// harvest the live inputs and compare field-for-field against the record's own values,
// so a no-net-change edit saves nothing.
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

// The group a verdict acts on: the active context's group, narrowed to the members still
// present in the working set (a picked anchor that fell out on a re-run is skipped, as
// selectedRecords already does). N=1 is the single focused/modal record; N>=2 is the
// multi-selection. The verdict fans out to one patch per member (§1.3).
function verdictGroup(ctx) {
    if (!ctx || !ctx.group) {
        return [];
    }
    // A modal edit acts on its own group — a related entry or a related node's
    // members — which need not sit in state.records; trust the context group directly
    // there. The main context's group is drawn from the working set — which carries
    // every member of every served group (§3.2, D7) — so narrow it to what is still
    // live.
    if (ctx === state.modalEditor) {
        return ctx.group;
    }
    const live = new Set(state.records.map((record) => anchorKey(record.anchor)));
    return ctx.group.filter((member) => live.has(anchorKey(member.anchor)));
}

// Run a verdict over the active context's group. At N=1 it is the ordinary single-record
// flow (steps to the next record, per-record toast). At N>=2 it fans out to one write per
// member with the group's harvested edits overlaid, one summary toast and one refresh
// (runGroup). The overlay — the fields the owner actually touched — is harvested ONCE and
// applied per member, so untouched fields keep each member's own value (§1.3).
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

// Accept one member: promote its fields with a sanctioned status. Its patch body is the
// member's OWN fields with the group's touched edits overlaid (groupMemberRecord) — at
// N=1 the overlay is the full editable surface, so this reproduces the single-record
// accept exactly. Returns the daemon result; throws so the caller can fail loud.
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

// A verdict (accept/drop/edit) produces a patch. It records an undo frame (whether
// the anchor already had a patch, so undo restores the right prior state) and
// re-annotates the row in place. `step`/`toast` are on for a single verdict and off
// per record in a group run (the run does one summary toast, no stepping). Returns
// the daemon result; throws on failure so the group loop can fail loud per record.
async function writePatch(anchor, record, verb, selected, { step = true, toast = true, refocus = true, dirty = false, deferRender = false } = {}) {
    const priorReviewed = selected ? selected.reviewed : false;
    // A bare edit persisted on navigate is DIRTY (op="edit" server-side): the
    // daemon records it but does NOT review or ship it. Only an explicit Accept
    // (dirty omitted) writes op="accept". A manual edit-on-navigate stays
    // authorship (re-authored in place, anchor null) and carries dirty the same
    // way — never auto-accepted by leaving the row.
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

// Flag: "looked at, no verdict yet". The daemon writes a flag patch carrying the
// source record unchanged; it counts as reviewed but not decided, and is a no-op
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

// Unflag: remove the flag patch, reverting to unreviewed. Distinct from undo — an
// explicit "actually, back to the pool" on a flagged row.
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

// Clear: the general "reset this entry's state" — delete WHATEVER patch it holds
// (accept/edit/drop/flag/authorship, this session or a prior one), reverting a
// basis record to its untouched source, or removing a manual record outright.
// Shown whenever the entry is reviewed. A manual record has no anchor, so it is
// cleared by its patch id; the daemon then returns no record and the row is dropped.
async function clearSelected() {
    // Clear reverts in place (it does not advance the review cursor to a next record).
    await groupVerdict("cleared", clearOne, { step: false });
}

// A record a group verdict passed over without writing (not an error, not a write) —
// e.g. Clear on an unreviewed row, which holds no patch. runGroup tallies these apart
// from the writes so the summary count is honest.
const GROUP_SKIPPED = Symbol("bulk-skipped");

// Clear one record. Only a truly unreviewed record holds no patch to clear — a
// no-op the bulk run counts as skipped, not done. A dirty record is unreviewed BY
// VERDICT but carries an unshipped edit patch, which Clear deletes like any other
// (so C reverts an unwanted edit — the reviewed bit would wrongly skip it). A
// manual record clears by patch id and its row is dropped (its patch IS the
// record); a basis record clears by anchor and reverts in place.
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
// Run a verdict over every member of the group. Each member goes through the SAME
// single-write path (writePatch/unpatch → the daemon's validated write) as a single
// verdict, with stepping, per-record toasts, and per-record re-render OFF
// (refocus:false); the loop does one summary toast and one ledger refresh at the end.
// The group's harvested edits (overlay) are overlaid onto each member (§1.3). A large
// group asks for confirmation first. A member that fails is collected and reported,
// never silently skipped — the run continues so one bad row doesn't strand the rest.
// The review cursor is preserved across the run, and the selection is cleared afterwards
// (the class has been triaged).

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
    // Clear the set silently — the DOM may be out of step with state.records mid-run
    // (deferred re-render), so the one authoritative rebuild is refreshAfterBulk.
    // A modal-scope run (a related group) triaged the MODAL's group, not the main
    // selection: the workbench pick stays, matching the single related modal.
    if (ctx.scope !== "modal") {
        state.multi.clear();
        state.lastToggledKey = null;
        state.touchMulti = false;
    }
    refreshAfterBulk(focusedAnchor);
    reportBulk(verb, done, skipped, failures);
    // One refresh for the whole run, not per record — the store changed.
    await refreshCommitStatus();
    await refreshPatchCounts();
}

// Rebuild the ledger once after a group run (rows may have been re-annotated or
// removed) and restore the review cursor to the entry it was on — or its nearest
// surviving neighbour if that entry was itself dropped. A cursor whose record re-folds
// into a COLLAPSED multi-member group is restored as that group's HEADER stop (a
// collapsed group is ONE cursor stop; select() would auto-expand the fold to reveal
// the record). Otherwise select() renders the single-record card, back in the
// ordinary review flow.
function refreshAfterBulk(focusedAnchor) {
    // The partition is fixed at materialise time (the daemon re-groups on the next
    // re-query), so a group run only re-annotated members in place — re-render and
    // restore the cursor; expansion state stays valid as-is.
    renderLedger();
    let index = focusedAnchor
        ? state.records.findIndex((r) => sameAnchor(r.anchor, focusedAnchor))
        : state.selected;
    if (index < 0) {
        index = Math.min(state.selected, state.records.length - 1);
    }
    // "collapsed here" ⇔ "was collapsed before the verdict" (a verdict never re-keys
    // a group), so a whole-group verdict on a collapsed group lands back on its
    // header, fold untouched.
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
        renderGroupEditor(selectedGroup());
        return;
    }
    const index = state.records.findIndex((r) => sameAnchor(r.anchor, frame.anchor));
    if (index >= 0) {
        state.selected = index;
    }
    await single(() => unpatch(frame.anchor, "undone", { step: false, uncount: true }));
}

// Delete an entry's patch. Returns the daemon result and throws on failure, so a
// group loop can fail loud per record. `toast` is off inside a group run; the removed
// anchor (an authored entry the daemon returns nothing for) is dropped by anchor,
// not by state.selected, so it works whether or not it is the focused row.
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
// (a group run) mutates the set but defers the ledger re-render to the loop's end.
//
// A removal from an edit-modal (dropping/clearing an authored related entry) targets
// the modal record's anchor — NEVER state.selected, whose row must stay put — and
// closes the modal, since the record it hosted no longer exists. The row is removed
// only if that anchor is loaded in the working set; the main cursor stays put.
// `deferRender` is accepted for call-site symmetry with the write path but a removal
// already defers its render to the group loop's end via refocus:false (a removed row
// leaves the working set, so the re-fold is the same one refreshAfterBulk does).
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
    // A removal before the cursor shifts it down by one; keep the same entry
    // focused (or its neighbour if the focused row was itself removed).
    if (removed < state.selected) {
        state.selected -= 1;
    }
    refreshPacing();
    if (refocus) {
        renderLedger();
        select(Math.min(state.selected, state.records.length - 1));
    }
}

// Remove the (now-cleared) modal record's row from the working set if it is loaded,
// keeping the main cursor on its own entry, and close the modal. The ledger is rebuilt
// so indices stay contiguous; the row that held the cursor keeps the focus, shifted
// down by one only if the removed row sat above it. The detail's related list is then
// refreshed in place so the cleared sibling no longer lingers in it.
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

// The write response returns EVERY record on the daemon's (case-folded) anchor key —
// a case-variant sibling may ride along — so the written row is picked by `anchor`
// (the client's case-sensitive natural key). Update that row IN PLACE: it keeps its
// index, so it stays put in the working set showing its new content and stamp, even
// if it no longer matches the active filter. By default step to the next entry; a
// re-render in place (unflag/undo) stays put. `refocus:false` (a group run) updates
// the row but leaves the review cursor where it was — the loop restores focus once
// at the end.
//
// A write from an edit-modal is always a re-annotate-in-place against the modal
// record: the affected main row (if that anchor is loaded) is refreshed by anchor,
// but the MAIN cursor/scroll never moves and the modal re-renders from the fresh
// record — so stepping/re-selecting is skipped whatever the caller passed.
function applyWriteResult(records, anchor, { step: doStep = true, refocus = true, deferRender = false } = {}) {
    const replacement = records.find((r) => sameAnchor(r.anchor, anchor));
    // Place the re-annotated record on its OWN row (matched by anchor), not
    // blindly on state.selected — the affected row may not be the selected one
    // (e.g. an undo after the filter was re-run moved the selection elsewhere).
    const index = replacement
        ? state.records.findIndex((r) => sameAnchor(r.anchor, replacement.anchor))
        : state.selected;
    if (replacement && index >= 0) {
        state.records[index] = replacement;
        // The record is re-annotated IN PLACE within its served group: the partition
        // is the daemon's and fixed at materialise time, so even an edit that moves
        // a grouping axis (shaw, the variation set) re-groups only on the next
        // re-query — same policy as filter membership. A group run (deferRender)
        // defers its one rebuild to refreshAfterBulk; every other write re-renders
        // now and restores the cursor + selection wash (the modal path re-renders
        // too, so the main row behind the backdrop reflects the modal's verdict
        // before it dismisses).
        if (!deferRender) {
            renderLedger();
            paintLedgerSelection();
        }
    }
    refreshPacing();
    if (isModalEditorOpen()) {
        // In the edit modal the verdict IS the dismiss: applying a verdict closes the
        // modal in the same action (no separate save-then-close). The affected main row
        // was already re-annotated in place above; now return to the workbench and
        // refresh the detail's related list so the re-decided sibling reads current.
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

// The keyboard cursor's stops, in RENDER order — one stop per visible selectable row,
// derived from the SAME partition renderLedger paints (ledgerGroups +
// groupsExpanded), so stepping can never disagree with the screen. A singleton is
// one record stop. EVERY multi-member group's HEADER is a group stop that selects the
// whole group as a unit: a collapsed group is that one stop (its hidden members are
// not stops), an expanded group is its header stop followed by each child as a
// record stop, in rendered child order.
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

// The stop the review cursor sits on, or -1 when no cursor is set. A claimed header
// (state.cursorGroupKey) wins — it is what distinguishes "on the header" from "on the
// first child" of an EXPANDED group, where both stops exist for one working-set index.
// Otherwise the cursor's record resolves to its own record stop when visible, else to
// the group stop swallowing it (its record is folded inside a collapsed group).
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

// Land the cursor on a stop through the path the equivalent mouse gesture uses. A
// record stop is a plain select() (a live pick survives the cursor move — select()'s
// contract). A group stop lands on the HEADER — collapsed or expanded, WITHOUT
// touching the fold: with no pick live it mirrors a plain header click
// (selectWholeGroup — the group reviewed as a unit); with a live pick it is a pure
// cursor move instead, claiming nothing, so stepping never clobbers a hand-made
// selection. state.selected anchors on the group's first (group-rank) member so
// index-keyed flows stay valid, and the header — which has no data-index — scrolls
// into view by group key.
function selectStop(stop) {
    if (!stop.group) {
        select(stop.index);
        return;
    }
    state.selected = stop.group.members[0].index;
    if (state.multi.size) {
        autoSaveMainEdit();
        if (state.mainContext) {
            state.mainContext.editing = false;
        }
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

// Step the review cursor to the adjacent VISIBLE row in render order, clamped at the
// ends: a collapsed group counts once; an expanded group counts its header, then each
// child. With no cursor the first stop is the landing (the old from−1 clamp's
// behaviour); at a clamped end the step is a no-op, so holding the key is idempotent.
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

// Keyboard fold control (ArrowRight/+ expand, ArrowLeft/- collapse): acts on the
// group holding the review cursor's record — the same key a collapsed header lights
// up under — through the one toggle path the disclosure chevron uses. A no-op when
// the group is already in the requested state or the record is a singleton, so
// holding the key is idempotent and the fold set never collects N=1 keys.
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

// Enter edit mode: mark the card editing so Save works. Acts on the context that owns
// the screen (detail or an edit-mode modal); the detail-card mode class is toggled only
// for the main context, never reaching behind a modal backdrop. `focusShaw` moves the
// caret into the Shavian field — wanted ONLY from the "E" shortcut ("start editing the
// shaw"). It must stay false for the paths where the user is acting elsewhere: a field's
// own focus listener (the field already has focus) and a merger/variant toggle (flipping
// a flag must not yank the caret into shaw, which would swallow the next review key).
function enterEdit(ctx, { focusShaw = false } = {}) {
    if (isCreateMode(ctx) || (ctx === state.mainContext && state.selected < 0)) {
        return;
    }
    ctx.editing = true;
    if (ctx === state.mainContext) {
        setDetailMode();
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

// Leave edit mode without saving: blur the field and return to review mode, so
// single-key verdicts work again. The detail-card mode class is the main context's;
// an edit-modal just drops its edit flag and blurs.
function exitEdit(ctx) {
    ctx.editing = false;
    if (ctx.root.contains(document.activeElement)) {
        document.activeElement.blur();
    }
    if (ctx === state.mainContext) {
        setDetailMode();
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

// Review-mode single-key bindings. These fire ONLY when no field holds focus (the
// event target is not an input/select/textarea) — so typing Shavian never
// triggers a verdict. The legacy arrow steppers stay as aliases (J/K mirror them).
// Left/Right fold the cursor's group (the tree convention), with +/− as aliases
// (= and _ so the keys work unshifted and shifted alike).
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

// The review keys an edit-mode modal honours: the verdicts and edit toggle, routed
// through activeContext() to the MODAL record. Navigation (j/k/arrows) and bulk
// selection (v) are omitted — a modal reviews a single related entry, it does not
// step the main cursor or touch the selection. Undo (u) is also omitted: it walks the
// global undo stack and moves the main cursor, so it belongs to the main flow only —
// Clear (c) is the modal's in-place "reset this entry's patch".
const MODAL_REVIEW_KEYS = new Set(["a", "x", "e", "f", "c"]);

// The keyboard while a modal owns the screen. A create modal takes only Escape
// (dismiss/Cancel) and Enter (Accept — author the entry) — its fields carry no
// listeners, so those keys reach here regardless of focus. Enter honours the
// distinctness guard: a collision-blocked dialog does not author on Enter, exactly as
// the disabled Accept button does not. An edit modal (a related entry opened for review)
// behaves like the main review flow but scoped to the modal record: with a field focused
// the field's own onFieldKey runs (Enter=accept/save, Escape=exit edit), so this leaves
// it alone — mirroring the main flow, where field-focused keys are never global
// verdicts; with no field focused, the verdict keys act via activeContext() and Escape
// dismisses.
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
        // While the dialog is open only its own keys act — Escape or ? close it;
        // review verdicts must not leak through to the entry behind the backdrop.
        if (event.key === "Escape" || event.key === "?") {
            event.preventDefault();
            toggleCheatsheet(false);
        }
        return;
    }
    if (isDefinitionModalOpen()) {
        // The definition-correction modal owns the screen: only Escape acts (dismiss);
        // its Shavian field and Save button handle their own keys. Workbench verdicts
        // must not leak to the record behind the backdrop.
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
// when the active Review filter is exactly "unreviewed". GROUP-denominated, like
// the total it nets against: a group is decided once every member is.
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
// field the registry no longer knows (a field renamed or retired) and folding in the
// always-shown pinned fields (a session saved before a field was pinned, or with a
// pinned field removed, still gets it back). Categorical values outside the field's
// current vocabulary are dropped too — a retired value (e.g. Review's former
// authored/orphaned, now Data's manual/orphaned) would otherwise wedge the session:
// the daemon rejects it loudly and its checkbox no longer exists to unpick. Called
// on load before the first query.
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

// Off-canvas ledger drawer for narrow screens. On wide screens the list is always
// visible and the toggle is hidden by CSS, so this only bites on mobile.
function setDrawer(open) {
    WORKBENCH.classList.toggle("drawer-open", open);
    DRAWER_TOGGLE.setAttribute("aria-expanded", String(open));
}

function toggleDrawer() {
    setDrawer(!WORKBENCH.classList.contains("drawer-open"));
}

// ---- ledger/detail splitter ----
// Draggable divider between the list and the detail pane, ported from the shave
// GUI's splitter idiom: a pointer-captured drag whose position persists as a
// FRACTION of the container width, so the split scales with window resizes.
// Adapted to this grid layout — the drag drives --ledger-w on the workbench
// (whose template reads it for the first column) rather than a flex-basis.
// Wide screens only: the mobile drawer layout hides the splitter and replaces
// the grid template in CSS, making a remembered width inert there.

// The remembered ledger share (0..1). An in-memory shadow of SPLIT_FRACTION_KEY
// (seeded at init, updated at drag end) so resize re-apply never re-parses
// storage — the same shape as shave's savedFraction and sectionPrefsCache above.
let splitFraction = null;

function workbenchPx(property) {
    return parseFloat(getComputedStyle(WORKBENCH).getPropertyValue(property)) || 0;
}

// Set the ledger column to a pixel width, clamped so neither pane dips below its
// floor (--ledger-min / --detail-min on .workbench — drag clamps only; the
// undragged default template is not bound by them). Returns the fraction of the
// workbench width actually applied, so callers persist what was applied rather
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

// Re-applied on every window resize: the remembered fraction keeps the panes'
// proportions, and a narrow-to-wide crossing recomputes from the wide width.
// Skipped on narrow viewports — the drawer layout ignores --ledger-w, so
// applying would only thrash layout on the device least able to afford it.
function applySavedSplit() {
    if (splitFraction === null || window.innerWidth <= NARROW_BREAKPOINT_PX) {
        return;
    }
    applyLedgerWidth(splitFraction * WORKBENCH.getBoundingClientRect().width);
}

// Collapse tucks the ledger behind a thin rail (wide screens; CSS scopes it) —
// double-click the divider to hide the list, the rail's chevron brings it back.
// Apply and persist are separate so the boot-time restore doesn't write the
// stored value straight back.
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
    if (isError) return; // errors stay up (readable, copyable) until tapped away
    toastTimer = setTimeout(() => TOAST.classList.remove("show"), 2400);
}

TOAST.addEventListener("click", () => {
    // A click that ends a text selection is a copy, not a dismissal.
    if (window.getSelection().toString()) return;
    TOAST.classList.remove("show");
});

// ---- commit ----
// The owner banks their accumulated decisions (data/patches/patches.jsonl) as a git
// commit, without depending on anyone else. The button's label carries the live
// uncommitted count; it disables at zero. The daemon is the single source of truth
// for the count (patches.jsonl lines not yet in HEAD), refreshed on boot and after
// every write so the label stays honest.

function paintCommitButton(uncommitted) {
    const count = Number.isFinite(uncommitted) ? uncommitted : 0;
    COMMIT_DECISIONS.textContent = count > 0
        ? `Commit ${count.toLocaleString()} decision${count === 1 ? "" : "s"}`
        : "Commit";
    COMMIT_DECISIONS.disabled = count === 0;
    COMMIT_DECISIONS.hidden = false;
}

// Query the daemon for the uncommitted count and repaint the button. Committing is
// unavailable on a tarball deploy (no repo) — the daemon says so via
// commit_available:false; we HIDE the button and stay silent (it is a state, not an
// error). A genuine status failure is non-fatal to the review flow (the count is
// advisory), so it hides the button quietly rather than toasting on every write.
async function refreshCommitStatus() {
    try {
        const status = await callDaemon({ op: "commit_status" });
        if (status.commit_available === false) {
            COMMIT_DECISIONS.hidden = true;
            return;
        }
        paintCommitButton(status.uncommitted);
    } catch (_error) {
        COMMIT_DECISIONS.hidden = true;
    }
}

// ---- patch counts ----
// The masthead shows the patch store's size: TOTAL banked patches + how many were
// EDITED TODAY (the server's local calendar day). This is the batch signal the
// Commit button's label used to carry; it lives independently now so it survives on
// a repo-less tarball deploy, where Commit is hidden. The daemon is the single
// source of truth (counted from patches.jsonl, never git), refreshed on boot and
// after every write so the numbers stay live — the same cadence as refreshCommitStatus.

function paintPatchCounts(counts) {
    if (!counts || !Number.isFinite(counts.total)) {
        PATCH_COUNTS.textContent = "";
        return;
    }
    const total = counts.total.toLocaleString();
    const today = Number.isFinite(counts.today) ? counts.today : 0;
    // Two stacked lines (CSS column) so the pair costs one label's width, not two.
    const totalLine = document.createElement("span");
    totalLine.textContent = `${total} patch${counts.total === 1 ? "" : "es"}`;
    const todayLine = document.createElement("span");
    todayLine.className = "today-count";
    todayLine.textContent = `${today.toLocaleString()} today`;
    PATCH_COUNTS.replaceChildren(totalLine, todayLine);
}

// Query the daemon for the store counts and repaint. Non-fatal to the review flow
// (the count is advisory): a failure clears the element quietly rather than toasting.
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
initWorkbenchSplitter();
FILTERS_TOGGLE.addEventListener("click", toggleFilters);
HELP_TOGGLE.addEventListener("click", () => toggleCheatsheet(true));
// Masthead ‹ › pair: the ArrowUp/ArrowDown cursor step as tappable buttons (phone
// ergonomics) — same step() path as the keys, so traversal stays single-sourced.
STEP_PREV.addEventListener("click", () => step(-1));
STEP_NEXT.addEventListener("click", () => step(1));
NEW_ENTRY.addEventListener("click", openCreateForm);
COMMIT_DECISIONS.addEventListener("click", () => commitDecisions());
// Backdrop click dismisses the modal, like the cheatsheet — only a click on the
// backdrop itself (not the card) counts.
CREATE_MODAL.addEventListener("click", (event) => {
    if (event.target === CREATE_MODAL) {
        // The shared shell hosts either the record modal or the definition-correction
        // modal; dismiss whichever is open.
        if (isDefinitionModalOpen()) {
            closeDefinitionModal();
        } else {
            closeModal();
        }
    }
});
ADD_FILTER.addEventListener("click", () => toggleAddMenu());
// Masthead ⋯ overflow menu: a static .facet-panel holding the occasional controls
// (whoami, shortcut help, keyboard settings, sign-out). Same open/close machinery
// as the chip pickers; a click on any item closes the menu after the item's own
// handler has run (bubbling order).
MASTHEAD_MENU.addEventListener("click", () => togglePicker(MASTHEAD_MENU_PANEL, MASTHEAD_MENU));
MASTHEAD_MENU_PANEL.addEventListener("click", (event) => {
    if (event.target.closest("button")) {
        closePopovers();
    }
});

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
// the daemon facets op (data-derived vocabularies for pos/var/source). Runs
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
    const pinned = meta.dataset.pinned === "true";
    if (kind === "categorical") {
        const entries = field in derived
            ? derived[field].map((value) => ({ value, label: value }))
            : harvestVocab(meta);
        // Multi-valued facets (source, attributes) can carry several values per
        // record, so their picker offers the any/all mode toggle; scalar facets
        // (one relevant value per record) omit it — ALL there matches nothing.
        const multi = meta.dataset.multi === "true";
        return { field, kind, label, pinned, entries, multi };
    }
    if (kind === "text") {
        return {
            field, kind, label, pinned,
            placeholder: meta.dataset.placeholder || "",
            shavian: meta.dataset.shavian === "true",
            // An inline text field (Search) renders as a bare toolbar box, not a
            // removable chip with a popover.
            inline: meta.dataset.inline === "true",
        };
    }
    // A numeric field may bound its input via data-min/data-max (confidence is
    // 0..100, "days back" is 1..365); absent, the picker leaves the input unbounded.
    return {
        field, kind, label, pinned,
        min: meta.dataset.min ?? null,
        max: meta.dataset.max ?? null,
    };
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
    // Inline fields (the Search box) render into their own toolbar slot, not as a
    // chip; everything else becomes a chip in activeFilters order.
    const inline = state.activeFilters.filter((entry) => fieldSpec(entry.field).inline);
    const chips = state.activeFilters.filter((entry) => !fieldSpec(entry.field).inline);
    SEARCH_INLINE.replaceChildren(...inline.map(inlineSearchBox));
    CHIP_STRIP.replaceChildren(...chips.map(filterChip));
    syncAddFilterEnabled();
}

// The inline Search box: a bare toolbar text input (Latin OR Shaw, always regex +
// case-insensitive). Typing re-queries debounced; the box carries data-field so
// markInvalidRegex can flag it red when the pattern fails to compile.
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

    wrap.append(trigger, panel);
    // Pinned (always-shown) chips carry no remove control — they are permanent.
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

// The chip's one-line summary: "POS: NN1, AJ0" for a set categorical, "POS: any" when
// none picked; "Word: cat" for text, "Word: …" when blank; "Conf ≥ 60" for a set
// numeric, "Conf ≥ any" when blank. The label prefix is the field's human name.
function renderChipLabel(entry) {
    const spec = fieldSpec(entry.field);
    if (spec.kind === "categorical") {
        const labels = entry.value.map((value) => vocabLabel(spec, value));
        if (!labels.length) {
            return `${spec.label}: any`;
        }
        // In ALL mode name it in the prefix so "Source all: wordnet, wiktionary"
        // reads as agreement, distinct from the default ANY combine.
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
    if (isPinned(entry.field)) {
        throw new Error(`pinned filter ${entry.field} cannot be removed`);
    }
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

    // The free-text search bar is gone (only the combined toolbar Search box has
    // one now); the reclaimed space holds the any/all MATCH toggle on multi-valued
    // facets. All / None act on the whole value list. These are two axes: which
    // values are checked, and how they combine.
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
    // The any/all radio pair — only on MULTI-VALUED facets (source, attributes),
    // where a record can carry several values. Scalar facets show no toggle (ALL
    // there matches nothing by construction).
    if (spec.multi) {
        fragment.append(modeToggle(spec, entry));
    }
    fragment.append(list);
    return fragment;
}

// The MATCH any/all radio pair for a multi-valued facet: ANY (a record matches one
// of the checked values, the default OR) vs ALL (a record carries EVERY checked
// value — set superset). Switching re-queries and refreshes the chip label.
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
    // Bounds come from the field's registry spec (data-min/data-max in the CGI):
    // confidence is 0..100, "days back" is 1..365. Absent bounds leave it unbounded.
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
    item.className = "menu-item";
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
    // Focus a text/number input if the picker has one (text/numeric pickers) so a
    // keyboard user types straight in; categorical pickers (checkboxes/radios) have
    // none, so nothing is focused and the single-key verdicts stay armed.
    const focusable = panel.querySelector('input[type="text"], input[type="number"]');
    if (focusable) {
        focusable.focus();
    }
}

// Close every open popover: the static panels (chip pickers, the masthead ⋯ menu —
// kept in the DOM, whose trigger is the preceding sibling) and the +Add menu
// (removed, since it is rebuilt each open to reflect the current inactive set). Their
// triggers' aria-expanded is reset.
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

// Tap/click outside any open popover closes it (touch-friendly: no hover involved);
// Esc closes it too. A click on a chip trigger, the +Add button or the masthead ⋯
// toggles via its own handler, so those are excluded here.
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
    await initAuth();
    buildCheatsheet();
    collapseFiltersOnNarrow();
    await buildFieldRegistry();
    const stored = loadSession();
    const restored = stored ? restoreSession(stored) : false;
    if (!restored) {
        // No session: seed the always-shown pinned fields as the starting strip.
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
