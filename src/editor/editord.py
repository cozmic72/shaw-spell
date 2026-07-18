#!/usr/bin/env python3
"""
editord — backing daemon for the Shaw-Spell editorial editor UI.

The read-write sibling of suggestd. It holds the editorial BASIS (upstream
ReadLex + the wordnet/wiktionary supplements) overlaid with the patch store
(data/patches/patches.jsonl), each basis record annotated with its patch-state,
and serves the editor's filter/step/accept/reject ops. It NEVER touches suggestd
or the read-only production spell-check path.

The basis is large (~189K anchors); it is loaded once at startup, like suggestd
loads its indexes, and filtered in memory per request. A write updates only the
affected anchor's annotation in the in-memory view (not a full reload), so the
next read reflects the new patch-state without a ~1s rebuild.

Protocol (line-oriented, UTF-8, one request -> one response, then close):

    Request:   {"op": "entries", "filters": {...}, "sort": "confidence_desc",
                "offset": 0, "limit": 50}
                # Categorical facets take a LIST, OR-ed within the facet and
                # AND-ed across facets, e.g. {"source": ["wordnet","wiktionary"],
                # "novelty": ["new-word"]}; an empty/absent list is unconstrained.
                # word/shaw are substring scalars; confidence_min/max are numeric.
                # word/shaw each take optional companion booleans in the same
                # filters dict: "<field>_regex" (match the value as a Python
                # re.search pattern instead of a plain substring) and "<field>_ci"
                # (case-insensitive). Absent flags = plain substring, word
                # case-insensitive / shaw case-sensitive (backward-compatible).
    Response:  {"total": 1234, "offset": 0, "limit": 50, "records": [...],
                "invalid_regex": ["word"]}
                # invalid_regex names the substring field(s) whose regex value
                # failed to compile (absent/empty when all compiled). A field
                # with an invalid regex matches nothing rather than 500-ing.

    Request:   {"op": "facets"}
    Response:  {"pos": [...]}   # the distinct POS tags present, sorted — the
                # open-ended facet's filter chips (fixed-enum facets are in the page)

    Request:   {"op": "entry", "anchor": {"word","pos","shaw","var"}}
    Response:  {"records": [...]}   # the record on that natural key

    Request:   {"op": "related", "word": "polish", "shaw"?: "..."}
    Response:  {"records": [...]}   # every record sharing the Latin word (case-
                # insensitively) OR the Shavian spelling — the related-entries
                # context for a landing. The shaw union brings in variant siblings
                # (same shaw, different word — estrogen/oestrogen). Deduped.

    Request:   {"op": "patch", "anchor": {"word","pos","shaw","var"} | null,
                "record": {...} | null, "author": "…", "replaces"?: "p_…"}
    Response:  {"result": "appended"|"replaced", "id": "p_…",
                "records": [...]}   # the anchor re-annotated after the write
                # The client sends the COMPLETE wanted `record`; the daemon
                # diffs its intrinsic fields against the live basis and persists a
                # minimal-diff patch {anchor, op, changes} (accept, or drop when
                # record is null). anchor null (record supplied) = authorship.
                # anchor null + replaces = re-decide an AUTHORED entry: edits that
                # authorship patch in place (anchor stays null), never an anchored
                # patch (which would orphan the decision — see _reauthor).

    Request:   {"op": "flag", "anchor": {"word","pos","shaw","var"}, "author": "…"}
             | {"op": "flag", "anchor": null, "replaces": "p_…", "author": "…"}
    Response:  {"result": …, "id": "p_…", "records": [...]}   # flagged, a no-op
                for production (see is_flag_patch). anchor null + replaces flags an
                AUTHORED entry, keeping anchor null (see _flag_authored)

    Request:   {"op": "unpatch", "anchor": {"word","pos","shaw","var"}}
             | {"op": "unpatch", "patch_id": "p_…"}
    Response:  {"result": "deleted", "id": null, "records": [...]}   # patch removed;
                a basis record reverts to its untouched source (undo / unflag /
                clear), keyed by anchor; an authorship record (anchor null) is
                cleared by patch_id and its row removed (records empty)

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
import re
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

from basis import (INTRINSIC_FIELDS, OP_ACCEPT, OP_DROP, OP_FLAG,  # noqa: E402
                   UPSTREAM_SOURCE, anchor_key)
from dialect_mergers import MERGER_SWAPS                         # noqa: E402
from overlay import (NOVELTY_NEW_POS, NOVELTY_NEW_SPELLING,      # noqa: E402
                     NOVELTY_NEW_WORD, PATCH_STATE_FLAGGED, load_view)
from patchstore import (                                        # noqa: E402
    delete_patch, delete_patch_by_id, make_patch, replace_authored_patch,
    upsert_patch)

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class State:
    """The annotated view for the daemon's lifetime. A write updates the affected
    anchor in the view incrementally (see AnnotatedView.apply_patch); rebuild()
    reloads the whole view from disk and is kept for startup only."""

    def __init__(self, view):
        self.view = view

    def rebuild(self):
        self.view = load_view()


# The two free-text filters that match a substring (default) or a regex against a
# single record field. Each carries optional "<field>_regex" / "<field>_ci"
# companion booleans in the filters dict rather than being its own filter key.
SUBSTRING_FIELDS = ("word", "shaw")

# word is case-insensitive by default (its historical behaviour); shaw is case-
# sensitive by default (Shavian has no case). The _ci companion flag forces
# case-insensitive regardless.
SUBSTRING_DEFAULT_CI = {"word": True, "shaw": False}


def _substring_predicate(field, value, filters):
    """Resolve one substring field (word/shaw) to a (predicate, valid) pair for
    the current query. `predicate(record)` tests the field; `valid` is False when
    a regex value failed to compile — the caller reports that field as invalid and
    the predicate matches nothing (never raises, never 500s). Companion flags
    "<field>_regex" / "<field>_ci" live in `filters`."""
    case_insensitive = bool(filters.get(f"{field}_ci", SUBSTRING_DEFAULT_CI[field]))
    if filters.get(f"{field}_regex"):
        try:
            pattern = re.compile(value, re.IGNORECASE if case_insensitive else 0)
        except re.error:
            return (lambda record: False), False
        return (lambda record: pattern.search(record[field]) is not None), True
    needle = value.lower() if case_insensitive else value
    if case_insensitive:
        return (lambda record: needle in record[field].lower()), True
    return (lambda record: needle in record[field]), True


class QueryFilters:
    """The supplied filters resolved for one query: the categorical/numeric filters
    pass through unchanged, while the substring fields (word/shaw) are pre-compiled
    once into predicates so a regex compiles a single time, not per record. Any
    field whose regex failed to compile is named in `invalid_regex`; its predicate
    matches nothing. The "<field>_regex"/"<field>_ci" companion keys are consumed
    here, so `matches` never sees them as filters."""

    def __init__(self, filters):
        self._other = {}
        self._substring_predicates = {}
        self.invalid_regex = []
        for key, value in filters.items():
            if value in (None, "", []):
                continue
            if key in SUBSTRING_FIELDS:
                predicate, valid = _substring_predicate(key, value, filters)
                self._substring_predicates[key] = predicate
                if not valid:
                    self.invalid_regex.append(key)
            elif key.endswith("_regex") or key.endswith("_ci"):
                continue  # companion flag, consumed alongside its substring field
            else:
                self._other[key] = value


# The categorical facets are multi-select: the request carries a LIST of values
# per facet (source, status, pos, var, patch_state, reviewed, word_kind,
# novelty), and a record matches the facet if its value is ANY of them (OR).
# Facets still AND across each other. The substring (word/shaw) and numeric
# (confidence_min/max) filters stay scalar. An empty list is no constraint.
def matches(record, query, established):
    """Whether an annotated record passes every supplied filter. Absent filters
    do not constrain; a present filter that the record fails excludes it. `query`
    is a QueryFilters carrying the pre-compiled substring predicates and the
    remaining categorical/numeric filters. `established` is the view's
    EstablishedIndex, needed by the novelty filter."""
    for predicate in query._substring_predicates.values():
        if not predicate(record):
            return False
    for key, value in query._other.items():
        if not _field_matches(record, key, value, established):
            return False
    return True


# A categorical facet matches if ANY selected value matches (OR within the facet).
# The equality facets test membership; the custom matchers are asked per value.
# word/shaw are handled by QueryFilters' pre-compiled predicates, not here.
def _field_matches(record, key, value, established):
    if key in ("source", "status", "pos", "var", "patch_state"):
        if not isinstance(value, list):
            raise ValueError(f"{key} filter wants a list, got {value!r}")
        return record.get(key) in value
    if key == "mergers":
        return any(_matches_merger(record, v) for v in value)
    if key == "variant":
        return any(_matches_variant(record, v) for v in value)
    if key == "reviewed":
        return any(_matches_review_state(record, v) for v in value)
    if key == "word_kind":
        return any(_matches_word_kind(record, v) for v in value)
    if key == "novelty":
        return any(_matches_novelty(record, v, established) for v in value)
    if key == "confidence_min":
        conf = record.get("confidence")
        return conf is not None and conf >= value
    if key == "confidence_max":
        conf = record.get("confidence")
        return conf is not None and conf <= value
    raise ValueError(f"unknown filter: {key}")


# The reviewed filter is three-way: a flag ("looked at, no verdict yet") is
# reviewed but distinct from a real verdict, so "decided" excludes it while
# "flagged" isolates it for a later sweep.
def _matches_review_state(record, value):
    reviewed = record["reviewed"]
    flagged = record["patch_state"] == PATCH_STATE_FLAGGED
    if value in ("unreviewed", "false", "0", False):
        return not reviewed
    if value == "flagged":
        return flagged
    if value == "decided":
        return reviewed and not flagged
    if value in ("reviewed", "true", "1", True):
        return reviewed
    raise ValueError(
        f"reviewed filter wants unreviewed/flagged/decided/reviewed, got {value!r}")


# A multi-word phrase is a Latin word carrying an internal whitespace after
# trimming (e.g. "a priori", "outer space"). Hyphens do not count — only
# whitespace splits a phrase into words.
def _matches_word_kind(record, value):
    multi = any(ch.isspace() for ch in record["word"].strip())
    if value == "multi":
        return multi
    if value == "single":
        return not multi
    raise ValueError(f"word_kind filter wants multi/single, got {value!r}")


# Novelty classifies an UNREVIEWED supplement candidate by its relationship to
# the upstream ReadLex corpus for its word — a genuinely new word, a new spelling
# of a known word, or a new POS of a known word+shaw. It is measured against
# upstream ONLY (never sanctioned patches), so sanctioning a candidate never
# changes its novelty. Upstream and reviewed rows are not candidates, so they
# never match a novelty value (they are excluded whenever the filter is set). A
# "known" candidate — word+shaw+pos all present upstream — would be a duplicate
# the B1 filter removes; it never matches new-* here, so it too is excluded.
NOVELTY_VALUES = (NOVELTY_NEW_WORD, NOVELTY_NEW_SPELLING, NOVELTY_NEW_POS)


def _matches_novelty(record, value, established):
    if value not in NOVELTY_VALUES:
        raise ValueError(
            f"novelty filter wants {'/'.join(NOVELTY_VALUES)}, got {value!r}")
    if record["reviewed"] or record.get("source") == UPSTREAM_SOURCE:
        return False
    novelty = established.classify(record["word"], record["shaw"], record["pos"])
    return novelty == value


# The mergers facet matches by membership: a record matches a selected merger if
# it carries it. The "(none)" sentinel is the canonical partition — records with
# no merger — which no real merger value can express (an empty list is absence,
# not a value). The real values are the code-defined vocabulary (trap-bath/
# cot-caught), so a chip outside {MERGER_NONE} ∪ MERGER_SWAPS fails loud.
MERGER_NONE = "(none)"
MERGER_FILTER_VALUES = frozenset(MERGER_SWAPS) | {MERGER_NONE}


def _matches_merger(record, value):
    if value not in MERGER_FILTER_VALUES:
        raise ValueError(
            f"mergers filter wants {'/'.join(sorted(MERGER_FILTER_VALUES))}, "
            f"got {value!r}")
    mergers = record.get("mergers") or []
    if value == MERGER_NONE:
        return not mergers
    return value in mergers


# The variant facet partitions on the boolean `variant` marker: a free-variation
# alternate spelling within the same accent ("variant") versus the canonical
# spelling ("canonical"). A chip outside this closed pair fails loud.
VARIANT_HAS = "variant"
VARIANT_NONE = "canonical"
VARIANT_FILTER_VALUES = frozenset({VARIANT_HAS, VARIANT_NONE})


def _matches_variant(record, value):
    if value not in VARIANT_FILTER_VALUES:
        raise ValueError(
            f"variant filter wants {'/'.join(sorted(VARIANT_FILTER_VALUES))}, "
            f"got {value!r}")
    is_variant = bool(record.get("variant"))
    if value == VARIANT_HAS:
        return is_variant
    return not is_variant


def filter_records(records, query, established):
    return [r for r in records if matches(r, query, established)]


# The list's natural key — the deterministic tiebreak under every sort, and the
# order the UI mirrors to place a dropped-out anchor among its neighbours.
def _natural_key(record):
    return (record["word"].lower(), record["pos"], record["shaw"], record["var"])


# Confidence is only carried by supplemental review candidates; upstream ReadLex
# records have none. A confidence sort ranks the CANDIDATES; records with no
# confidence are not review targets, so the leading 0/1 pushes them to the END
# under either direction (0 = has confidence, sorts first).
def _confidence_desc_key(record):
    conf = record.get("confidence")
    has = conf is not None
    return (0 if has else 1, -conf if has else 0, _natural_key(record))


def _confidence_asc_key(record):
    conf = record.get("confidence")
    has = conf is not None
    return (0 if has else 1, conf if has else 0, _natural_key(record))


SORTS = {
    "confidence_desc": _confidence_desc_key,
    "confidence_asc": _confidence_asc_key,
    "freq_desc": lambda r: (-_record_freq(r), _natural_key(r)),
    "word": _natural_key,
}
DEFAULT_SORT = "word"


def _record_freq(record):
    freq = record.get("freq")
    return freq if isinstance(freq, (int, float)) else 0


def sort_records(records, sort):
    key = SORTS.get(sort)
    if key is None:
        raise ValueError(f"unknown sort: {sort}")
    return sorted(records, key=key)


def serialisable(record):
    """The record without the raw patch object (the UI reads patch_state and,
    when it needs the patch itself, the fields it carries)."""
    result = {k: v for k, v in record.items() if k != "patch"}
    patch = record.get("patch")
    result["patch_id"] = patch["id"] if patch else None
    return result


def handle_entries(state, request):
    query = QueryFilters(request.get("filters") or {})
    offset = int(request.get("offset", 0))
    limit = min(int(request.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)

    matched = filter_records(state.view.records, query, state.view.established)
    matched = sort_records(matched, request.get("sort") or DEFAULT_SORT)
    page = matched[offset:offset + limit]
    return {
        "total": len(matched),
        "offset": offset,
        "limit": limit,
        "records": [serialisable(r) for r in page],
        "invalid_regex": query.invalid_regex,
    }


# The data-derived facets — pos, var, status, source — take their chips from the
# distinct values actually present in the view, sorted, rather than a hardcoded
# subset that would drift from the data (an unenumerated var like RRPVar becomes
# unfilterable; a dead chip like source=pos-gap matches nothing). POS is the long
# tail (100+ CLAWS tags); var/status/source are small but drift as upstream data
# and cleanup targets come and go. The closed vocabularies the code itself defines
# (reviewed/word_kind/novelty/patch_state) can't drift, so they stay in the page.
DATA_DERIVED_FACETS = ("pos", "var", "status", "source")


def handle_facets(state, _request):
    return {facet: _distinct_values(state.view, facet)
            for facet in DATA_DERIVED_FACETS}


def _distinct_values(view, field):
    """The sorted distinct non-empty values of `field` across the view. Read-only;
    takes the view lock (like by_word) since it iterates the shared index while a
    concurrent write may mutate it."""
    with view._lock:
        values = {record[field]
                  for group in view.by_anchor_index.values()
                  for record in group
                  if record[field]}
    return sorted(values)


def handle_entry(state, request):
    anchor = request.get("anchor")
    if not anchor:
        return {"error": "entry requires an anchor"}
    records = state.view.by_anchor(anchor_key(anchor))
    return {"records": [serialisable(r) for r in records]}


def handle_related(state, request):
    """Every annotated record sharing the focused entry's Latin word (matched
    case-insensitively) OR its Shavian spelling — the related-entries context.
    The shaw union pulls in variant siblings whose Latin word differs but whose
    spelling is identical (estrogen/oestrogen). Read-only; the UI labels each row
    by its already-carried provenance/patch-state. A record matching on both word
    and shaw appears once (deduped by its anchor)."""
    word = request.get("word")
    if not word:
        return {"error": "related requires a word"}
    shaw = request.get("shaw")
    records = state.view.by_word(word)
    if shaw:
        records += state.view.by_shaw(shaw)
    seen = set()
    deduped = []
    for record in records:
        key = anchor_key(record["anchor"])
        if key not in seen:
            seen.add(key)
            deduped.append(record)
    return {"records": [serialisable(r) for r in deduped]}


ANCHOR_FIELDS = ("word", "pos", "shaw", "var")
RECORD_REQUIRED_FIELDS = ("word", "pos", "shaw", "var")
RECORD_ALLOWED_FIELDS = {"word", "pos", "shaw", "var", "ipa", "freq",
                         "source", "status", "confidence", "note", "mergers",
                         "variant"}


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
        merger_error = _validate_mergers(record.get("mergers"))
        if merger_error:
            return merger_error
        variant_error = _validate_variant(record.get("variant"))
        if variant_error:
            return variant_error
    return None


# mergers is additive: absent or an empty list means canonical. When present it
# must be a list of the code-defined merger names (trap-bath/cot-caught) — an
# invalid value or a non-list is rejected at the write, not deferred to a build.
def _validate_mergers(mergers):
    if mergers is None:
        return None
    if not isinstance(mergers, list):
        return f"patch record mergers must be a list, got {mergers!r}"
    unknown = [m for m in mergers if m not in MERGER_SWAPS]
    if unknown:
        return f"patch record has unknown mergers: {', '.join(map(str, unknown))}"
    return None


# variant is an additive boolean: absent means canonical spelling. When present
# it must be exactly True (a free-variation alternate) — any other value is
# rejected at the write, not deferred to a build.
def _validate_variant(variant):
    if variant is None:
        return None
    if variant is not True:
        return f"patch record variant must be true, got {variant!r}"
    return None


def handle_patch(state, request):
    anchor = request.get("anchor")
    record = request.get("record")
    author = request.get("author")
    replaces = request.get("replaces")
    if not author:
        return {"error": "patch requires an author"}
    if anchor is None and record is None:
        return {"error": "patch must supply anchor (edit/drop) or record (authorship)"}
    error = _validate_patch(anchor, record)
    if error:
        return {"error": error}

    # Re-deciding an AUTHORED entry (anchor null, replacing a prior authorship
    # patch) stays authorship: it edits that patch in place rather than minting an
    # anchored patch, which would orphan the decision (an authored word has no
    # basis record for the anchor to resolve against).
    if anchor is None and replaces:
        return _reauthor(state, record, _meta(author, request.get("note")), replaces)

    meta = _meta(author, request.get("note"))

    # Authorship (anchor null, record supplied): the record is self-contained, so
    # `changes` IS the whole record and there is no op to resolve.
    if anchor is None:
        patch = make_patch(None, None, record, meta)
        key = anchor_key(record)
    else:
        # An accept/drop must anchor to a record that exists in the basis right
        # now. Writing an anchor that resolves to nothing would create an orphan
        # the build later fails on; reject it here where the actor can fix it.
        basis = state.view.basis_record(anchor_key(anchor))
        if basis is None:
            return {"error": f"anchor resolves to no basis record: {anchor}"}
        if record is None:
            patch = make_patch(anchor, OP_DROP, {}, meta)
        else:
            changes = _compute_changes(record, basis)
            patch = make_patch(anchor, OP_ACCEPT, changes, meta)
        key = anchor_key(anchor)

    result, _previous = upsert_patch(patch)
    state.view.apply_patch(patch)
    return _write_result(state, key, result, patch["id"])


def _compute_changes(record, basis):
    """The minimal intrinsic diff of the client's wanted `record` against the
    untouched `basis` record — the only fields an accept persists. Everything
    else (source/confidence/freq/status) is derived at apply, never stored, so a
    non-intrinsic key on the client record is simply ignored. Empty diff == the
    client accepted the basis record unchanged (accept-as-is)."""
    changes = {}
    for field in INTRINSIC_FIELDS:
        wanted = _intrinsic_value(record, field)
        if wanted != _intrinsic_value(basis, field):
            changes[field] = wanted
    return changes


# mergers defaults to [] and variant to False when absent; the other intrinsics
# default to "" — so an absent field on one side and its default on the other are
# NOT a change. This mirrors record_to_output/output_to_record, which emit these
# only when non-default.
def _intrinsic_value(record, field):
    if field == "mergers":
        return record.get("mergers") or []
    if field == "variant":
        return bool(record.get("variant"))
    return record.get(field, "")


def _reauthor(state, record, meta, prior_id):
    """Persist an authored re-decision (accept / edit) as a replacement of the
    prior authorship patch, keeping anchor null. Fails loud if the prior patch is
    not there (surfaced to the actor, never a silent new-patch fallback)."""
    if record is None:
        return {"error": "authored re-decision requires a record"}
    patch = make_patch(None, None, record, meta)
    try:
        replace_authored_patch(patch, prior_id)
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}
    state.view.apply_reauthor(patch, prior_id)
    return _write_result(state, anchor_key(record), "replaced", patch["id"])


def handle_flag(state, request):
    """Flag an anchor "looked at, no verdict yet". The flag patch is
    {anchor, op:"flag", changes:{}} — it leaves the anchored basis record
    untouched. It replaces any prior verdict on the anchor (upsert by anchor),
    and the applicator treats it as a no-op."""
    anchor = request.get("anchor")
    author = request.get("author")
    replaces = request.get("replaces")
    if not author:
        return {"error": "flag requires an author"}

    # Flagging an AUTHORED entry re-authors it with op flag, keeping anchor null —
    # never an anchored flag patch that would orphan the decision.
    if anchor is None and replaces:
        return _flag_authored(state, author, request.get("note"), replaces)

    if not anchor:
        return {"error": "flag requires an anchor or a prior authored patch"}
    error = _validate_patch(anchor, None)
    if error:
        return {"error": error}

    if state.view.basis_record(anchor_key(anchor)) is None:
        return {"error": f"anchor resolves to no basis record: {anchor}"}

    patch = make_patch(anchor, OP_FLAG, {}, _meta(author, request.get("note")))
    result, _previous = upsert_patch(patch)
    state.view.apply_patch(patch)
    return _write_result(state, anchor_key(anchor), result, patch["id"])


def _flag_authored(state, author, note, prior_id):
    """Flag an authored entry: re-author it with the SAME record the prior patch
    holds (a flag leaves the entry unchanged), with op flag. The record is read
    from the prior authored patch, not the client, so it provably equals it.
    Fails loud if the prior patch is not there."""
    prior = state.view.authored_patch(prior_id)
    if prior is None:
        return {"error": f"no authored patch with id: {prior_id}"}
    patch = make_patch(None, OP_FLAG, prior["changes"], _meta(author, note))
    try:
        replace_authored_patch(patch, prior_id)
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}
    state.view.apply_reauthor(patch, prior_id)
    return _write_result(state, anchor_key(prior["changes"]), "replaced", patch["id"])


def handle_unpatch(state, request):
    """Clear the patch on an entry, reverting it to its untouched source (undo a
    decision / unflag / general clear). A basis record is cleared by its `anchor`;
    an authorship record — whose stored anchor is null — has no source to revert
    to and is cleared by its `patch_id`, removing the row entirely. Fails loud if
    the target patch is not there."""
    anchor = request.get("anchor")
    patch_id = request.get("patch_id")
    if anchor:
        error = _validate_patch(anchor, None)
        if error:
            return {"error": error}
        key = anchor_key(anchor)
        store_delete, view_revert = lambda: delete_patch(anchor), \
            lambda: state.view.apply_unpatch_anchor(anchor)
    elif patch_id:
        key = None
        store_delete, view_revert = lambda: delete_patch_by_id(patch_id), \
            lambda: state.view.apply_unpatch_id(patch_id)
    else:
        return {"error": "unpatch requires an anchor or patch_id"}
    try:
        store_delete()
    except KeyError as exc:
        return {"error": str(exc)}
    view_revert()
    records = state.view.by_anchor(key) if key is not None else []
    return {"result": "deleted", "id": None,
            "records": [serialisable(r) for r in records]}


def _meta(author, note):
    meta = {"author": author, "origin": "editor", "ts": _now_iso()}
    if note:
        meta["note"] = note
    return meta


def _write_result(state, key, result, patch_id):
    """The response every write op returns: the re-annotated anchor plus the
    outcome, so the UI updates the row in place."""
    return {
        "result": result,
        "id": patch_id,
        "records": [serialisable(r) for r in state.view.by_anchor(key)],
    }


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


HANDLERS = {
    "entries": handle_entries,
    "facets": handle_facets,
    "entry": handle_entry,
    "related": handle_related,
    "patch": handle_patch,
    "flag": handle_flag,
    "unpatch": handle_unpatch,
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
    """Threaded so a slow client can't block others. A patch write updates the
    view in place under the server's single-writer assumption (this is a
    single-user editor); concurrent writers are a Phase-2 concern, not handled
    here."""
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
