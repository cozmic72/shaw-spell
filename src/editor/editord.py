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
                # word/shaw are substring scalars; confidence_min/max and patch_days
                # (a record's patch made within the last N days) are numeric;
                # patch_author is a categorical facet on the patch's meta.author.
                # word/shaw each take optional companion booleans in the same
                # filters dict: "<field>_regex" (match the value as a Python
                # re.search pattern instead of a plain substring) and "<field>_ci"
                # (case-insensitive). Absent flags = plain substring, word
                # case-insensitive / shaw case-sensitive (backward-compatible).
                # Filtering is GROUP-AWARE: a group (group_key) whose ANY member
                # matches is served whole, non-matching siblings included.
                # Pagination is GROUP-DENOMINATED: offset/limit/total COUNT
                # GROUPS, and a group is never split across pages.
    Response:  {"total": 1234, "offset": 0, "limit": 50,
                "groups": [{"key": "…", "records": [...]}, …],
                "invalid_regex": ["word"]}
                # Each group is served WHOLE: groups are ranked by their
                # best-sorted member under the active sort (a stable total
                # order — the flat sort's natural-key tiebreak carries over),
                # members inside a group in that same flat-sort order. `key` is
                # the serialised group_key, OPAQUE to the client (view state —
                # expansion, cursor — keys off it; only the daemon computes
                # grouping). A group of ONE is still a group. Every serialised
                # record — in EVERY op returning records — also carries its own
                # `group_key`, so a write response can place a fresh record
                # (authorship) into the served partition.
                # invalid_regex names the substring field(s) whose regex value
                # failed to compile (absent/empty when all compiled). A field
                # with an invalid regex matches nothing rather than 500-ing.

    Request:   {"op": "facets"}
    Response:  {"pos": [...], "var": [...], "source": [...],
                "patch_author": [...]}   # the distinct values present, sorted —
                # the data-derived facets' filter chips (fixed-enum facets are
                # in the page)

    Request:   {"op": "entry", "anchor": {"word","pos","shaw","var"}}
    Response:  {"records": [...]}   # the record on that natural key

    Request:   {"op": "related", "word": "polish", "shaw"?: "..."}
    Response:  {"records": [...]}   # every record sharing the Latin word (case-
                # insensitively) OR the Shavian spelling — the related-entries
                # context for a landing. The shaw union brings in variant siblings
                # (same shaw, different word — estrogen/oestrogen). Deduped.

    Request:   {"op": "definitions", "word": "cat"}
    Response:  {"word": "cat", "senses": [
                  {"synset": "02123649-n", "gloss": "any of various …",
                   "pos": "n", "shaw_pos": "…",
                   "shaw_gb": "…", "shaw_us": "…"|null}, …]}
                # READ-ONLY inline sense summary (definitions viewer, phase P2). The
                # Shavian definitions corpus keyed by lowercased headword -> its
                # senses. Per sense: English gloss + GB Shavian transliteration
                # (shaw_gb), US Shavian ONLY where it diverges (shaw_us, else null),
                # POS tag + its Shavian (shaw_pos). A null shaw_* / an empty senses
                # list is a coverage gap the UI renders explicitly. Reads a SEPARATE
                # index, never the basis or the patch store. Each sense also carries
                # `source` (derived provenance: "wordnet" today — every synset is a
                # WordNet offset — or "generated" for a future drafted batch), the
                # discriminator between a machine-drafted gloss and a WordNet one.

    Request:   {"op": "definition_patch",
                "anchor": {"word","synset","dialect"}, "changes": {"shaw": "…"},
                "author": "…", "note"?: "…"}
    Response:  {"result": "appended"|"replaced", "id": "dp_…", "senses": [...]}
                # Correct ONE sense's Shavian transliteration — the primary edit
                # (design §5c). anchor = per-sense key (word LOWERCASED, WordNet
                # synset, dialect gb|us); the only editable field is `shaw` (gloss +
                # synset are stable identity, read-only). Written to the SEPARATE
                # data/patches/definition-patches.jsonl store (NEVER the word
                # patches.jsonl) and overlaid onto the definitions index so the
                # inline view shows the correction. Owner's edit wins silently. No
                # accept/flag/drop — definitions are canonical by default; a
                # correction is an edit, not a sanction. `senses` is the word's
                # senses re-serialised after overlay.

    Request:   {"op": "definition_unpatch", "anchor": {"word","synset","dialect"}}
    Response:  {"result": "deleted", "id": null, "senses": [...]}
                # Remove a correction; the sense reverts to its machine
                # transliteration. Fails loud if no correction holds that anchor.

    Request:   {"op": "patch", "anchor": {"word","pos","shaw","var"} | null,
                "record": {...} | null, "author": "…", "replaces"?: "p_…",
                "dirty"?: bool}
    Response:  {"result": "appended"|"replaced", "id": "p_…",
                "records": [...]}   # the anchor re-annotated after the write
                # The client sends the COMPLETE wanted `record`; the daemon
                # diffs its intrinsic fields against the live basis and persists a
                # minimal-diff patch {anchor, op, changes} (accept, or drop when
                # record is null). `dirty` marks a bare edit-on-navigate: the patch
                # op is "edit" (DIRTY — not reviewed, not shipped) instead of
                # "accept"; only an explicit Accept (dirty omitted) reviews/ships.
                # anchor null (record supplied) = authorship (a MANUAL record).
                # `dirty` applies there too: a new manual record is created dirty
                # (unreviewed, shipping nothing) and reviews like any other row.
                # anchor null + replaces = re-decide a MANUAL entry: edits that
                # authorship patch in place (anchor stays null), never an anchored
                # patch (which would orphan the decision — see _reauthor).

    Request:   {"op": "flag", "anchor": {"word","pos","shaw","var"}, "author": "…"}
             | {"op": "flag", "anchor": null, "replaces": "p_…", "author": "…"}
    Response:  {"result": …, "id": "p_…", "records": [...]}   # flagged, a no-op
                for production (see is_flag_patch). anchor null + replaces flags a
                MANUAL entry, keeping anchor null (see _flag_authored)

    Request:   {"op": "unpatch", "anchor": {"word","pos","shaw","var"}}
             | {"op": "unpatch", "patch_id": "p_…"}
    Response:  {"result": "deleted", "id": null, "records": [...]}   # patch removed;
                a basis record reverts to its untouched source (undo / unflag /
                clear), keyed by anchor; an authorship record (anchor null) is
                cleared by patch_id and its row removed (records empty)

    Request:   {"op": "commit_status"}
    Response:  {"uncommitted": N, "head": "<short-sha>"|null,
                "subject": "<last commit subject>"|null}   # N = patch lines in the
                store not yet in HEAD, so the UI labels/enables the Commit button

    Request:   {"op": "commit"}
    Response:  {"result": "committed", "message": "…", "sha": "<short>",
                "uncommitted": 0}
             | {"result": "nothing-to-commit"}   # store unchanged vs HEAD
                Commits ONLY data/patches/patches.jsonl (the owner's own commit) —
                never sweeps the rest of the working tree.

    Errors:    {"error": "<message>"}

An anchor is the reviewed record's IMMUTABLE natural key (word, pos, shaw, var,
lemma?): it is unchanged when the record is edited, so an entry never moves as a
result of being edited. A `record` is the COMPLETE wanted record; null drops it. anchor null
is authorship.

Usage:
    editord.py --socket /run/shaw-spell/editord.sock

Run under systemd (see shaw-spell-editord.service).
"""

import argparse
import calendar
import functools
import json
import logging
import os
import re
import signal
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

# The shared basis/overlay/patch modules live in src/tools and src/editor. Put
# both on the path so `import basis` / `import overlay` resolve regardless of
# the working directory the daemon is launched from.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

from basis import (ACCEPTED_STATUS, INTRINSIC_FIELDS, OP_ACCEPT,  # noqa: E402
                   OP_DROP, OP_EDIT, OP_FLAG, PROJECT_ROOT, UPSTREAM_SOURCE,
                   anchor_key, collapse_readlex, published_entry)
from definitions import load_definitions_index                   # noqa: E402
import definition_patches                                        # noqa: E402
from dialect_mergers import MERGER_LABELS, MERGER_SWAPS           # noqa: E402
from overlay import (AUTHORED_STATUS, NOVELTY_NEW_POS,           # noqa: E402
                     NOVELTY_NEW_SPELLING, NOVELTY_NEW_WORD, ORPHANED_STATUS,
                     PATCH_STATE_ACCEPTED, PATCH_STATE_DIRTY,
                     PATCH_STATE_DROPPED, PATCH_STATE_EDITED,
                     PATCH_STATE_FLAGGED, PATCH_STATE_ORPHANED,
                     PATCH_STATE_UNREVIEWED, load_view, verdict_state)
from patchstore import (                                        # noqa: E402
    PATCHES_PATH, _store_path, delete_patch, delete_patch_by_id, make_patch,
    replace_authored_patch, upsert_patch)

# Entries-page size, in GROUPS (the entries op pages by group, never splitting one) —
# or in RECORDS when the request asks for the flat (ungrouped) partition.
DEFAULT_LIMIT = 50
MAX_LIMIT = 500

# The patch-states a live, sanctioned record carries — an accept whose changes
# are empty (ACCEPTED) or non-empty (EDITED). A manual record shipping to the
# dictionary is ACCEPTED too (see overlay.annotate_authored_record), so both
# reach the shipped dictionary and a canonical conflict is drawn from either.
ACCEPTED_STATES = (PATCH_STATE_ACCEPTED, PATCH_STATE_EDITED)


class State:
    """The annotated view for the daemon's lifetime. A write updates the affected
    anchor in the view incrementally (see AnnotatedView.apply_patch); rebuild()
    reloads the whole view from disk and is kept for startup only.

    `definitions` is a SEPARATE, read-only index of the Shavian definitions corpus
    (definitions.py) — the inline sense summary reads it, but it never touches the
    basis or the patch store. Held here so it lives for the daemon's lifetime like
    the view, loaded once at startup."""

    def __init__(self, view, definitions):
        self.view = view
        self.definitions = definitions

    def rebuild(self):
        self.view = load_view()


# The two per-field free-text filters that match a substring (default) or a regex
# against a SINGLE record field. Each carries optional "<field>_regex" / "<field>_ci"
# companion booleans in the filters dict rather than being its own filter key. These
# remain for backward compatibility (saved sessions, direct protocol use); the editor
# UI now sends the combined `search` filter below instead.
SUBSTRING_FIELDS = ("word", "shaw")

# word is case-insensitive by default (its historical behaviour); shaw is case-
# sensitive by default (Shavian has no case). The _ci companion flag forces
# case-insensitive regardless.
SUBSTRING_DEFAULT_CI = {"word": True, "shaw": False}

# The combined free-text filter the editor toolbar sends: ALWAYS a regex, ALWAYS
# case-insensitive, matched against the Latin word OR the Shavian spelling OR the
# IPA. One box, no per-box toggles — a record passes when the pattern hits ANY of the
# three fields. Reported under the name "search" in invalid_regex when the pattern
# fails to compile.
SEARCH_FIELD = "search"
SEARCH_FIELDS = ("word", "shaw", "ipa")


def _search_predicate(value):
    """Resolve the combined `search` value to a (predicate, valid) pair: an
    always-IGNORECASE regex matched against word OR shaw OR ipa. `valid` is False
    when the pattern fails to compile (the predicate then matches nothing, never
    raising). `ipa` is optional on a record, so a missing one reads as empty rather
    than raising."""
    try:
        pattern = re.compile(value, re.IGNORECASE)
    except re.error:
        return (lambda record: False), False
    return (lambda record: pattern.search(record["word"]) is not None
            or pattern.search(record["shaw"]) is not None
            or pattern.search(record.get("ipa") or "") is not None), True


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
    here, so `matches` never sees them as filters.

    The review facet's "mixed" value (REVIEW_MIXED) is GROUP-level: it is
    stripped from the per-record review values here and recorded as
    `review_mixed` for filter_records to evaluate per group. `review_only_mixed`
    marks a review facet left with NO record-level value — its record-level leg
    then matches nothing (never everything)."""

    def __init__(self, filters):
        self._other = {}
        self._substring_predicates = {}
        self.invalid_regex = []
        self.review_mixed = False
        self.review_only_mixed = False
        for key, value in filters.items():
            if value in (None, "", []):
                continue
            if key == SEARCH_FIELD:
                predicate, valid = _search_predicate(value)
                self._substring_predicates[key] = predicate
                if not valid:
                    self.invalid_regex.append(key)
            elif key in SUBSTRING_FIELDS:
                predicate, valid = _substring_predicate(key, value, filters)
                self._substring_predicates[key] = predicate
                if not valid:
                    self.invalid_regex.append(key)
            elif key.endswith("_regex") or key.endswith("_ci"):
                continue  # companion flag, consumed alongside its substring field
            elif key == "review":
                self._add_review(value)
            else:
                self._other[key] = value

    def _add_review(self, value):
        values, mode = _categorical_values_mode("review", value)
        self.review_mixed = REVIEW_MIXED in values
        remaining = [v for v in values if v != REVIEW_MIXED]
        if remaining:
            self._other["review"] = {"values": remaining, "mode": mode}
        else:
            self.review_only_mixed = True


# The categorical facets are multi-select: the request carries either a bare LIST
# of values per facet (source, pos, var, review, data, word_kind, novelty, mergers,
# variant, attributes) — matched ANY (OR) for backward compatibility — or a
# {"values": [...], "mode": "any"|"all"} object making the combining rule explicit.
# ANY = the record matches at least one selected value (OR, the default and the
# only meaningful mode on a SCALAR facet — one relevant value per record). ALL =
# the record matches EVERY selected value, meaningful only on a MULTI-VALUED facet
# (source, attributes) where a record can carry several: source ALL = the record's
# source-set is a SUPERSET of the selected atomic sources (agreement); ALL on a
# scalar facet with >1 value matches nothing by construction.
# Facets still AND across each other. The substring (word/shaw) and numeric
# (confidence_min/max) filters stay scalar. An empty list is no constraint.
#
# The three primary facets are ORTHOGONAL AXES (the owner's review lenses):
#   review  — process status, the review lifecycle (axis 1)
#   data    — data predicates, the origin/nature of the record (axis 2)
#   novelty — word-newness against upstream ReadLex (axis 3)
# OR within an axis, AND across axes: 'generated AND unreviewed' is
# data=[generated] + review=[unreviewed].
FILTER_MODE_ANY = "any"
FILTER_MODE_ALL = "all"
FILTER_MODES = (FILTER_MODE_ANY, FILTER_MODE_ALL)


def _categorical_values_mode(key, value):
    """Normalise a categorical filter value to (values, mode). A bare list stays
    ANY (back-compat); a {"values", "mode"} object carries an explicit mode. Fails
    loud on a malformed shape or an unknown mode — never silently coerces."""
    if isinstance(value, list):
        return value, FILTER_MODE_ANY
    if isinstance(value, dict):
        values = value.get("values")
        if not isinstance(values, list):
            raise ValueError(
                f"{key} filter object wants a values list, got {values!r}")
        mode = value.get("mode", FILTER_MODE_ANY)
        if mode not in FILTER_MODES:
            raise ValueError(
                f"{key} filter mode wants {'/'.join(FILTER_MODES)}, got {mode!r}")
        return values, mode
    raise ValueError(f"{key} filter wants a list or {{values, mode}}, got {value!r}")


def _combine(values, mode, predicate):
    """Combine a per-value predicate under the facet's mode: ANY = at least one
    value matches (OR), ALL = every value matches (AND)."""
    if mode == FILTER_MODE_ALL:
        return all(predicate(v) for v in values)
    return any(predicate(v) for v in values)


def matches(record, query, established, review=True):
    """Whether an annotated record passes every supplied filter. Absent filters
    do not constrain; a present filter that the record fails excludes it. `query`
    is a QueryFilters carrying the pre-compiled substring predicates and the
    remaining categorical/numeric filters. `established` is the view's
    EstablishedIndex, needed by the novelty filter. `review=False` skips the
    record-level review facet — the group-level mixed leg matches members on
    every OTHER facet (see filter_records)."""
    for predicate in query._substring_predicates.values():
        if not predicate(record):
            return False
    for key, value in query._other.items():
        if key == "review" and not review:
            continue
        if not _field_matches(record, key, value, established):
            return False
    return True


# The scalar (non-categorical) facets: word/shaw are handled by QueryFilters'
# pre-compiled predicates, not here; these three carry a bare scalar value rather
# than a {values, mode} facet, so they dispatch before the categorical table.
def _confidence_min(record, value):
    conf = record.get("confidence")
    return conf is not None and conf >= value


def _confidence_max(record, value):
    conf = record.get("confidence")
    return conf is not None and conf <= value


def _patch_days(record, value):
    # A SCALAR "days back" filter: the record's patch was made within the last N
    # days. A record with no patch (no patch_ts — an unreviewed/basis row) is
    # excluded, like a numeric sort excludes records missing the value.
    return _within_days(record.get("patch_ts"), value)


SCALAR_MATCHERS = {
    "confidence_min": _confidence_min,
    "confidence_max": _confidence_max,
    "patch_days": _patch_days,
}


# The categorical facets: each maps to a per-value predicate that _combine folds
# under the facet's mode (ANY = one selected value matches; ALL = every selected
# value matches). The scalar facets above stay outside this table.
#   patch_author  the record's patch author (meta.author) is one of those
#                 selected. A record with no patch carries no patch_author and
#                 matches no value. Scalar per record — ALL with >1 matches nothing.
#   pos/var       one relevant value per record: ANY = the record's value is one of
#                 those selected; ALL with >1 value matches nothing.
#   source        a LIST (the atomic origins that attested the anchor). A record
#                 matches a selected atomic source when that origin is in its
#                 source-set; ANY = the sets intersect, ALL = the record's set is a
#                 SUPERSET of the selected origins (multi-source agreement). This
#                 replaces the former exact-combo equality: selecting "wiktionary"
#                 now catches every anchor carrying wiktionary, alone or in a combo.
CATEGORICAL_MATCHERS = {
    "patch_author": lambda record, v, established: record.get("patch_author") == v,
    "pos": lambda record, v, established: record.get("pos") == v,
    "var": lambda record, v, established: record.get("var") == v,
    "source": lambda record, v, established: v in set(record.get("source", ())),
    "attributes": lambda record, v, established: _matches_attribute(record, v),
    "mergers": lambda record, v, established: _matches_merger(record, v),
    "variant": lambda record, v, established: _matches_variant(record, v),
    "review": lambda record, v, established: _matches_review(record, v),
    "data": lambda record, v, established: _matches_data(record, v),
    "word_kind": lambda record, v, established: _matches_word_kind(record, v),
    "novelty": lambda record, v, established: _matches_novelty(record, v, established),
}


def _field_matches(record, key, value, established):
    scalar = SCALAR_MATCHERS.get(key)
    if scalar is not None:
        return scalar(record, value)
    values, mode = _categorical_values_mode(key, value)
    matcher = CATEGORICAL_MATCHERS.get(key)
    if matcher is None:
        raise ValueError(f"unknown filter: {key}")
    return _combine(values, mode, lambda v: matcher(record, v, established))


# AXIS 1 — process status. The Review facet is the review-lifecycle filter: the
# verdicts a record can be in (matched on patch_state). Manual rows carry a real
# verdict like any other (their origin lives in the data facet as `manual`);
# orphaned is a patch_state too, but it describes the record's LIFECYCLE, not a
# review verdict, so it lives in the data facet (axis 2) as `orphaned` — an
# orphaned row matches NO review value. A chip outside the closed vocabulary
# fails loud.
#
# REVIEW_MIXED is the one GROUP-level review value: it selects groups whose
# members do NOT all share one verdict (verdict_state — the same collapse the
# client's verdictConsensus applies). It is never matched per record; QueryFilters
# strips it from the review facet and filter_records evaluates it per group,
# OR-ed with the record-level review values (see filter_records).
REVIEW_MIXED = "mixed"
REVIEW_FILTER_VALUES = (
    PATCH_STATE_UNREVIEWED, PATCH_STATE_ACCEPTED, PATCH_STATE_EDITED,
    PATCH_STATE_DIRTY, PATCH_STATE_DROPPED, PATCH_STATE_FLAGGED)


def _matches_review(record, value):
    if value not in REVIEW_FILTER_VALUES:
        raise ValueError(
            f"review filter wants {'/'.join(REVIEW_FILTER_VALUES)}, got {value!r}")
    return record["patch_state"] == value


# AXIS 2 — data predicates: the origin/nature of the record, one consolidated
# facet absorbing the former `status` and `has_definition` filters plus the
# authored/orphaned values pulled out of Review. The values are NON-mutually-
# exclusive predicates (a record can be generated AND have a definition), OR-ed
# within the facet like every other; the AND-usecases come from crossing axes.
#   manual         a human authored the record (the row's `manual` origin marker
#                  — anchor-null patch; the old status="manual")
#   orphaned       an anchored patch whose basis anchor is gone (patch_state
#                  orphaned — the old status="orphaned" / Review "orphaned")
#   generated      the RRP generator synthesized it (source CONTAINS "generated",
#                  so wiktionary+generated combos count — unlike the exact-set
#                  source facet)
#   supplement     harvested from a supplement source (source CONTAINS an origin
#                  outside NON_SUPPLEMENT_ORIGINS — wordnet/wiktionary/names/
#                  any future harvest label). A generated+wiktionary record is
#                  BOTH generated and supplement.
#   promoted       a pipeline transform relabelled its var (orig_var present —
#                  the reclassifier's [WAS X] RRP-promotion marker)
#   has-definition / no-definition
#                  the upstream-definition partition (the old has_definition
#                  facet, absorbed whole so the no-definition gap-hunt survives)
GENERATED_ORIGIN = "generated"
# Origins that are NOT harvested-supplement attestations: the upstream core, the
# generator's synthesized label, and the pseudo-origins authored/orphaned rows
# carry in their source list (overlay's AUTHORED_STATUS/ORPHANED_STATUS).
NON_SUPPLEMENT_ORIGINS = frozenset(
    {UPSTREAM_SOURCE, GENERATED_ORIGIN, AUTHORED_STATUS, ORPHANED_STATUS})

DATA_MANUAL = "manual"
DATA_ORPHANED = "orphaned"
DATA_GENERATED = "generated"
DATA_SUPPLEMENT = "supplement"
DATA_PROMOTED = "promoted"
DATA_HAS_DEFINITION = "has-definition"
DATA_NO_DEFINITION = "no-definition"
DATA_FILTER_VALUES = (
    DATA_MANUAL, DATA_ORPHANED, DATA_GENERATED, DATA_SUPPLEMENT,
    DATA_PROMOTED, DATA_HAS_DEFINITION, DATA_NO_DEFINITION)


def _matches_data(record, value):
    if value == DATA_MANUAL:
        return bool(record.get("manual"))
    if value == DATA_ORPHANED:
        return record["patch_state"] == PATCH_STATE_ORPHANED
    if value == DATA_GENERATED:
        return GENERATED_ORIGIN in record.get("source", ())
    if value == DATA_SUPPLEMENT:
        return any(origin not in NON_SUPPLEMENT_ORIGINS
                   for origin in record.get("source", ()))
    if value == DATA_PROMOTED:
        return bool(record.get("orig_var"))
    if value == DATA_HAS_DEFINITION:
        return bool(record.get("has_definition"))
    if value == DATA_NO_DEFINITION:
        return not record.get("has_definition")
    raise ValueError(
        f"data filter wants {'/'.join(DATA_FILTER_VALUES)}, got {value!r}")


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


# AXIS 3 — novelty classifies a supplement record by its relationship to the
# upstream ReadLex corpus for its word — a genuinely new word, a new spelling of
# a known word, or a new POS of a known word+shaw. It is measured against
# upstream ONLY (never sanctioned patches), so sanctioning a record never
# changes its novelty, and a reviewed row keeps the novelty it always had.
# Novelty is orthogonal to the review and data axes, which AND with this one.
# The fourth value, `upstream`, is the baseline itself: a ReadLex-core row
# (source contains "readlex") — the not-new complement of the new-* values.
# Upstream rows never match new-* (they ARE the measure; the short-circuit
# spares ~111K rows a classify() call). A non-upstream "known" candidate —
# word+shaw+pos all present upstream — would be a duplicate the B1 filter
# removes; it classifies as `known` and matches neither new-* nor upstream.
NOVELTY_UPSTREAM = "upstream"
NOVELTY_FILTER_VALUES = (
    NOVELTY_NEW_WORD, NOVELTY_NEW_SPELLING, NOVELTY_NEW_POS, NOVELTY_UPSTREAM)


def _matches_novelty(record, value, established):
    if value not in NOVELTY_FILTER_VALUES:
        raise ValueError(
            f"novelty filter wants {'/'.join(NOVELTY_FILTER_VALUES)}, "
            f"got {value!r}")
    is_upstream = UPSTREAM_SOURCE in record.get("source", ())
    if value == NOVELTY_UPSTREAM:
        return is_upstream
    if is_upstream:
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


# The attributes facet is the has-many union of the (flattened, on-disk) mergers
# list + the variant boolean: a record's attribute-set is its mergers plus the
# pseudo-member "variant" when variant is true. It mirrors the editor's unified
# attributes chips control, and merges the former Mergers + Variant facets into
# one filter. Its vocabulary is the merger names plus "variant"; "(none)" is the
# canonical partition (empty attribute-set), which no real value can express (an
# empty list is absence, not a value). A chip outside the vocabulary fails loud.
ATTRIBUTE_VARIANT = VARIANT_HAS
ATTRIBUTE_NONE = MERGER_NONE
ATTRIBUTE_FILTER_VALUES = frozenset(MERGER_SWAPS) | {ATTRIBUTE_VARIANT, ATTRIBUTE_NONE}

# The attributes facet's chips, labelled: MERGER_SWAPS already reflects
# MERGER_ENABLED, so a disabled merger drops out here with no separate check.
# "other" (the variant pseudo-member) and "(none)" are this facet's own fixed
# extras, not part of the merger vocabulary, so their labels live here rather
# than in dialect_mergers.
_ATTRIBUTE_LABELS = {ATTRIBUTE_VARIANT: "other", ATTRIBUTE_NONE: "(none / canonical)"}


def _attribute_facet_entries():
    entries = [{"value": name, "label": MERGER_LABELS[name]} for name in MERGER_SWAPS]
    entries.append({"value": ATTRIBUTE_VARIANT, "label": _ATTRIBUTE_LABELS[ATTRIBUTE_VARIANT]})
    entries.append({"value": ATTRIBUTE_NONE, "label": _ATTRIBUTE_LABELS[ATTRIBUTE_NONE]})
    return entries


def _record_attributes(record):
    """A record's attribute-set: its mergers plus "variant" when the variant flag
    is set. The has-many view the editor edits as chips and the facet filters on."""
    attributes = set(record.get("mergers") or [])
    if record.get("variant"):
        attributes.add(ATTRIBUTE_VARIANT)
    return attributes


def _matches_attribute(record, value):
    if value not in ATTRIBUTE_FILTER_VALUES:
        raise ValueError(
            f"attributes filter wants "
            f"{'/'.join(sorted(ATTRIBUTE_FILTER_VALUES))}, got {value!r}")
    attributes = _record_attributes(record)
    if value == ATTRIBUTE_NONE:
        return not attributes
    return value in attributes


# The date filter is RELATIVE ("last N days"): a record matches when its patch was
# made no more than N days before now. `patch_ts` is ISO-8601 UTC (patchstore
# _now_iso); the cutoff is computed in UTC too, so the comparison is timezone-clean
# (unlike the "today" count below, which is a local-calendar-day question). A record
# with no patch_ts (unreviewed/basis) never matches — there is no decision to date.
def _within_days(patch_ts, days):
    if not patch_ts:
        return False
    made = _parse_iso_utc(patch_ts)
    cutoff = time.time() - float(days) * 86400.0
    return made >= cutoff


def _parse_iso_utc(ts):
    """Epoch seconds for an ISO-8601 UTC timestamp of the form _now_iso emits
    (YYYY-MM-DDTHH:MM:SSZ). Fails loud on a shape it cannot parse rather than
    silently reading as 0 (the epoch) and mis-dating the record."""
    return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))


# The record-list group identity — the ONE grouping notion (the client renders the
# partition it is sent, never recomputes it): Latin word (lowercased) + Shavian +
# variation set (the mergers plus the "variant" pseudo-member, i.e.
# _record_attributes). Identity ONLY — editorial state never partitions.
def group_key(record):
    return (record["word"].lower(), record["shaw"],
            frozenset(_record_attributes(record)))


def filter_records(records, query, established):
    """Group-aware filtering: a group (group_key) is served WHOLE when at least
    one member matches the active filters — a matching record pulls its
    non-matching siblings into the result, so the whole group reaches the
    client together (handle_entries pages by GROUP, so it arrives unsplit).
    Record order is preserved (the caller sorts). With no active filters every
    record matches, so this degenerates to the identity.

    Review "mixed" is the one GROUP-level value: its leg serves the groups whose
    members span more than one verdict AND hold a member matching every
    non-review facet, UNIONED with the record-level leg — OR within the review
    axis, AND across axes, exactly the per-record composition lifted to the
    group. A review facet reduced to mixed alone offers no record-level value,
    so that leg matches nothing (review_only_mixed), never everything."""
    keyed = [(group_key(record), record) for record in records]
    if query.review_only_mixed:
        matched_groups = set()
    else:
        matched_groups = {key for key, record in keyed
                          if matches(record, query, established)}
    if query.review_mixed:
        matched_groups |= _mixed_group_keys(keyed, query, established)
    return [record for key, record in keyed if key in matched_groups]


def _mixed_group_keys(keyed, query, established):
    """The group keys the review "mixed" leg serves: members spanning more than
    one verdict (verdict_state — the same collapse the client's verdictConsensus
    applies, so filter and group stamp can never disagree), with at least one
    member passing every NON-review facet (the mixed leg IS these groups' review
    constraint)."""
    members_by_key = {}
    for key, record in keyed:
        members_by_key.setdefault(key, []).append(record)
    return {key for key, members in members_by_key.items()
            if len({verdict_state(record) for record in members}) > 1
            and any(matches(record, query, established, review=False)
                    for record in members)}


# The list's natural key — the deterministic tiebreak under every sort, and the
# order the UI mirrors to place a dropped-out anchor among its neighbours.
def _natural_key(record):
    return (record["word"].lower(), record["pos"], record["shaw"], record["var"])


# Numeric columns (confidence, freq) are only carried by supplemental review
# candidates; upstream ReadLex records have none. Such a sort ranks the CANDIDATES,
# so records missing the value are not review targets: the leading 0/1 pushes them
# to the END under either direction (0 = has value, sorts first). The _natural_key
# tail makes every key a TOTAL ORDER, so offset paging over the sorted corpus never
# shuffles tied records between page requests (no duplicates, no gaps).
def _numeric_key(record, field, descending):
    value = record.get(field)
    has = value is not None
    ranked = (-value if descending else value) if has else 0
    return (0 if has else 1, ranked, _natural_key(record))


# Text columns sort by one field, then _natural_key as tiebreak. A tuple key can't
# mix directions, and the tiebreak must stay ASCENDING even when the primary is
# descending (else paging is unstable), so a comparator is the only stable option:
# primary in the requested direction, _natural_key always ascending.
def _field_sort(field, descending):
    def compare(left, right):
        left_primary, right_primary = _text_primary(left, field), _text_primary(right, field)
        if left_primary != right_primary:
            ordered = left_primary < right_primary
            return -1 if ordered != descending else 1
        left_tie, right_tie = _natural_key(left), _natural_key(right)
        if left_tie == right_tie:
            return 0
        return -1 if left_tie < right_tie else 1
    return functools.cmp_to_key(compare)


def _text_primary(record, field):
    # The state column sorts by the DISPLAYED verdict (edited/dirty collapse onto
    # accepted/unreviewed), so identically-stamped rows stay adjacent; the word
    # column collates case-insensitively (its natural-key tail is already
    # lowercased); the rest compare on their raw field, mirroring the client.
    if field == STATE_FIELD:
        return verdict_state(record)
    value = record[field]
    return value.lower() if field == "word" else value


# The client composes `${column}_${dir}`; STATE_FIELD maps the state column to its
# backing field. Every sortable column has both directions so paging inherits the
# active header sort. DEFAULT_SORT is the malformed-request fallback.
STATE_FIELD = "patch_state"
TEXT_SORT_COLUMNS = ("state", "word", "shaw", "var", "pos")
NUMERIC_SORT_COLUMNS = ("confidence", "freq")
DEFAULT_SORT = "word"


def _build_sorts():
    sorts = {}
    for column in TEXT_SORT_COLUMNS:
        field = STATE_FIELD if column == "state" else column
        sorts[f"{column}_asc"] = _text_sorter(field, descending=False)
        sorts[f"{column}_desc"] = _text_sorter(field, descending=True)
    for column in NUMERIC_SORT_COLUMNS:
        sorts[f"{column}_asc"] = _numeric_sorter(column, descending=False)
        sorts[f"{column}_desc"] = _numeric_sorter(column, descending=True)
    # "word" (no direction) is the natural-key order and the default landing sort.
    sorts["word"] = lambda records: sorted(records, key=_natural_key)
    return sorts


def _text_sorter(field, descending):
    return lambda records: sorted(records, key=_field_sort(field, descending))


def _numeric_sorter(field, descending):
    return lambda records: sorted(
        records, key=lambda record: _numeric_key(record, field, descending))


SORTS = _build_sorts()


def sort_records(records, sort):
    sorter = SORTS.get(sort)
    if sorter is None:
        raise ValueError(f"unknown sort: {sort}")
    return sorter(records)


def serialisable(record):
    """The record without the raw patch object (the UI reads patch_state and,
    when it needs the patch itself, the fields it carries). Every serialised
    record carries its wire group key, so a write response can place a fresh
    record (authorship) into the client's served partition — the client never
    computes grouping."""
    result = {k: v for k, v in record.items() if k != "patch"}
    patch = record.get("patch")
    result["patch_id"] = patch["id"] if patch else None
    result["group_key"] = wire_group_key(group_key(record))
    return result


# Partition the SORTED flat list into groups, order-preserving: a group ranks at
# its FIRST (best-under-the-active-sort) member's position, and its members keep
# their flat-sort relative order. The flat sort is a deterministic TOTAL order
# (every sorter tiebreaks on _natural_key), each record belongs to exactly one
# group, and distinct groups have distinct first members — so the group sequence
# is itself a deterministic total order, and offset paging over it is stable
# across requests (no duplicates, no gaps).
def group_sorted(records):
    ordered = []
    by_key = {}
    for record in records:
        key = group_key(record)
        members = by_key.get(key)
        if members is None:
            by_key[key] = members = []
            ordered.append((key, members))
        members.append(record)
    return ordered


# The group key on the wire: an opaque string token (the client's expansion and
# cursor state key off it, nothing parses it). NUL separators cannot occur in a
# component (a word may contain spaces), so distinct keys never collide — the
# "+"-joined attribute set relies on no merger name ever containing "+"
# (MERGER_SWAPS' vocabulary is hyphenated).
def wire_group_key(key):
    word, shaw, attributes = key
    return "\0".join((word, shaw, "+".join(sorted(attributes))))


def handle_entries(state, request):
    query = QueryFilters(request.get("filters") or {})
    offset = int(request.get("offset", 0))
    limit = min(int(request.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)

    matched = filter_records(state.view.records, query, state.view.established)
    matched = sort_records(matched, request.get("sort") or DEFAULT_SORT)
    # Flat mode (the ledger's ungrouped view) pages by RECORD: each record is its
    # own singleton group, so offset/limit slice the flat list directly rather
    # than group_sorted's group runs. The client never re-partitions what it is
    # sent, so this is the only place flat pagination can live.
    groups = [(group_key(r), [r]) for r in matched] if request.get("flat") \
        else group_sorted(matched)
    page = groups[offset:offset + limit]
    return {
        "total": len(groups),
        "offset": offset,
        "limit": limit,
        "groups": [{"key": wire_group_key(key),
                    "records": [serialisable(r) for r in members]}
                   for key, members in page],
        "invalid_regex": query.invalid_regex,
    }


# The data-derived facets — pos, var, source — take their chips from the
# distinct values actually present in the view, sorted, rather than a hardcoded
# subset that would drift from the data (an unenumerated var like RRPVar becomes
# unfilterable; a dead chip like source=pos-gap matches nothing). POS is the long
# tail (100+ CLAWS tags); var/source are small but drift as upstream data
# and cleanup targets come and go. The closed vocabularies the code itself defines
# (review/data/word_kind/novelty) can't drift, so they stay hardcoded client-side.
# The former `status` facet is DISSOLVED: status is fully derived, so each of its
# values maps onto the axes — manual = data:manual, orphaned = data:orphaned,
# sanctioned = novelty:upstream ∪ review:accepted/edited, supplement = the rest.
DATA_DERIVED_FACETS = ("pos", "var", "source")

# `attributes` is a THIRD kind: a closed vocabulary, like review/data/novelty —
# but one that DOES drift, via MERGER_ENABLED (env-overridable, no code edit). A
# data-derived facet would hide an enabled-but-not-yet-attested merger; a
# hardcoded client chip is exactly the drift bug this replaces. So it ships
# labelled value/label pairs (dialect_mergers.MERGER_LABELS), not bare strings
# like DATA_DERIVED_FACETS — the client tells the two kinds apart by shape.
def handle_facets(state, _request):
    facets = {facet: _distinct_values(state.view, facet)
              for facet in DATA_DERIVED_FACETS}
    facets["attributes"] = _attribute_facet_entries()
    # patch_author is present only on patched rows (absent on unreviewed/basis
    # ones), so it cannot go through _distinct_values' record[field] access; it is
    # collected with .get so unreviewed rows contribute nothing.
    facets["patch_author"] = _distinct_authors(state.view)
    return facets


def _distinct_authors(view):
    """The sorted distinct patch authors across the view — the author facet's chips.
    Read under the view lock (like _distinct_values), collecting patch_author with
    .get since it is absent on unreviewed/basis rows."""
    with view._lock:
        authors = {record.get("patch_author")
                   for group in view.by_anchor_index.values()
                   for record in group}
    authors.discard(None)
    return sorted(authors)


def _distinct_values(view, field):
    """The sorted distinct non-empty values of `field` across the view. Read-only;
    takes the view lock (like by_word) since it iterates the shared index while a
    concurrent write may mutate it.

    `source` is list-valued (the origins that attested each anchor). Its facet
    values are now the ATOMIC origins present across the data (readlex, wordnet,
    wiktionary, names, generated, ...), NOT the "+"-joined combos — matching the
    set-membership semantics of the source filter (_field_matches): selecting an
    atomic origin catches every anchor carrying it, and multi-source agreement is
    that origin-set in ALL mode."""
    with view._lock:
        values = set()
        for group in view.by_anchor_index.values():
            for record in group:
                if field == "source":
                    for origin in record.get("source", ()):
                        if origin:
                            values.add(origin)
                elif record[field]:
                    values.add(record[field])
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


def handle_definitions(state, request):
    """The Shavian definitions senses for a word (case-insensitive), for the
    editor's inline read-only sense summary. Each sense carries the English gloss,
    its Shavian transliteration (GB, plus US only where it diverges), and the POS
    tag with its Shavian transliteration. An empty list = no definition for the
    word (the coverage gap the view renders explicitly). Read-only: it reads the
    separate definitions index, never the basis or the patch store."""
    word = request.get("word")
    if not word:
        return {"error": "definitions requires a word"}
    return {"word": word, "senses": state.definitions.senses(word)}


# The definition-patch anchor identity (per-sense): word LOWERCASED, WordNet synset
# offset, dialect. The word is lowercased so the anchor is stable regardless of the
# corpus headword's case (CAT vs cat) — the index is lowercased too.
DEFINITION_ANCHOR_FIELDS = ("word", "synset", "dialect")


def _normalise_definition_anchor(anchor):
    """The def-patch anchor with its word lowercased and its fields validated. The
    anchor is the sense's immutable identity; the correction is keyed on it. Returns
    (normalised_anchor, error): error is a string on a malformed anchor, else None."""
    if not isinstance(anchor, dict):
        return None, "definition_patch requires an anchor {word, synset, dialect}"
    missing = [f for f in DEFINITION_ANCHOR_FIELDS if not anchor.get(f)]
    if missing:
        return None, f"definition anchor missing {', '.join(missing)}"
    if anchor["dialect"] not in definition_patches.DIALECTS:
        return None, (f"definition anchor dialect must be one of "
                      f"{'/'.join(definition_patches.DIALECTS)}, got {anchor['dialect']!r}")
    normalised = {"word": anchor["word"].lower(),
                  "synset": anchor["synset"],
                  "dialect": anchor["dialect"]}
    return normalised, None


def handle_definition_patch(state, request):
    """Correct one sense's Shavian transliteration. Writes a minimal-diff patch to
    the SEPARATE definition-patches store and overlays it onto the index so the
    inline view shows the correction. The word patches.jsonl is never touched.

    v1 edits the Shavian only (`changes.shaw`); the gloss + synset are stable
    identity, read-only. The anchor names ONE dialect, so a correction targets that
    dialect's transliteration — the daemon does not fan a gb edit onto us (the UI
    decides whether an edit covers one dialect or both, per the design's lean (c)).
    A correction whose anchor resolves to no live sense is rejected here, where the
    actor can fix it, rather than written as an immediate orphan."""
    author = request.get("author")
    if not author:
        return {"error": "definition_patch requires an author"}
    anchor, error = _normalise_definition_anchor(request.get("anchor"))
    if error:
        return {"error": error}

    changes = request.get("changes")
    if not isinstance(changes, dict):
        return {"error": "definition_patch requires changes {shaw: …}"}
    unknown = set(changes) - set(definition_patches.CHANGE_FIELDS)
    if unknown:
        return {"error": f"definition_patch changes has unknown keys: "
                f"{', '.join(sorted(unknown))} (only shaw is editable)"}
    shaw = changes.get("shaw")
    if not shaw or not str(shaw).strip():
        return {"error": "definition_patch changes.shaw must be non-empty"}
    changes = {"shaw": str(shaw).strip()}

    # The anchor must resolve to a live corpus sense right now — writing a
    # correction that resolves to nothing would create an orphan at the next
    # startup. _find takes the index lock; reject here where the actor can fix it.
    with state.definitions._lock:
        if state.definitions._find(anchor["word"], anchor["synset"]) is None:
            return {"error": f"anchor resolves to no definition sense: {anchor}"}

    patch = definition_patches.make_patch(anchor, changes, _meta(author, request.get("note")))
    result, _previous = definition_patches.upsert_patch(patch)
    # Overlay onto the in-memory index so the next read reflects the correction
    # without a reload (mirrors the word view's incremental apply_patch).
    state.definitions.correct(anchor, changes)
    return {"result": result, "id": patch["id"],
            "senses": state.definitions.senses(anchor["word"])}


def handle_definition_unpatch(state, request):
    """Remove a correction, reverting the sense to its machine transliteration.
    Fails loud if no correction holds that anchor. The in-memory revert reloads the
    sense's original Shavian from the untouched corpus files — the index was
    corrected in place, so the source string must be re-read to undo it."""
    anchor, error = _normalise_definition_anchor(request.get("anchor"))
    if error:
        return {"error": error}
    try:
        definition_patches.delete_patch(anchor)
    except KeyError as exc:
        return {"error": str(exc)}
    state.definitions.revert(anchor)
    return {"result": "deleted", "id": None,
            "senses": state.definitions.senses(anchor["word"])}


ANCHOR_FIELDS = ("word", "pos", "shaw", "var")
RECORD_REQUIRED_FIELDS = ("word", "pos", "shaw", "var")
RECORD_ALLOWED_FIELDS = {"word", "pos", "shaw", "var", "ipa", "freq",
                         "source", "status", "confidence", "note", "mergers",
                         "variant", "lemma"}


def _validate_patch(state, anchor, record):
    """The applicator's precondition, enforced at the write so a malformed patch
    is rejected where the actor can fix it — never deferred to a build that
    crashes on an incomplete record. The record is self-contained, so every core
    field must be present. Returns an error string or None."""
    if anchor is not None:
        missing = [f for f in ANCHOR_FIELDS if not anchor.get(f)]
        if missing:
            return f"patch anchor missing {', '.join(missing)}"
        if anchor.get("lemma") is not None:
            shape_error = _lemma_shape_error(anchor["lemma"])
            if shape_error:
                return f"patch anchor {shape_error}"
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
        if "freq" in record:
            freq_error = _validate_freq(record["freq"])
            if freq_error:
                return freq_error
        if "lemma" in record:
            lemma_error = _validate_lemma(state, record)
            if lemma_error:
                return lemma_error
    return None


# lemma is a {Latn, pos, Shaw} pointer to another record. A SELF-reference
# (the record naming its own word/pos/shaw as its lemma) is always valid —
# checked WITHOUT a view lookup, so authoring a brand-new root record never
# deadlocks on a lookup for a record that only exists once this very patch is
# written. Anything else must resolve to a record the CURRENT view already
# displays: an owner can point a lemma at a record they just accepted this
# session, not only a pristine basis candidate, so the check reads the live
# view (by_word), not the raw basis alone.
def _lemma_shape_error(lemma):
    """The malformed-lemma rejection message, or None for a well-formed
    {Latn, pos, Shaw} object — shared by the anchor and record validations so
    the two can never phrase the shape apart."""
    if not isinstance(lemma, dict) or set(lemma) != {"Latn", "pos", "Shaw"}:
        return f"lemma must be a {{Latn, pos, Shaw}} object, got {lemma!r}"
    if not (lemma["Latn"] and lemma["pos"] and lemma["Shaw"]):
        return f"lemma has empty Latn/pos/Shaw: {lemma!r}"
    return None


def _validate_lemma(state, record):
    lemma = record["lemma"]
    if lemma is None:
        return None
    shape_error = _lemma_shape_error(lemma)
    if shape_error:
        return f"patch record {shape_error}"
    latn, pos, shaw = lemma["Latn"], lemma["pos"], lemma["Shaw"]
    if (latn.lower(), pos, shaw) == (record["word"].lower(), record["pos"],
                                     record["shaw"]):
        return None
    if not any(candidate["pos"] == pos and candidate["shaw"] == shaw
              for candidate in state.view.by_word(latn)):
        return (f"patch record lemma does not resolve to an existing record: "
                f"{latn!r} {pos} {shaw!r}")
    return None


# freq is an INTEGER count (patchable — the corpus derivation runs before the
# overlay, so a patched freq is the last word). A string, float, bool or
# negative is rejected at the write, never silently coerced.
def _validate_freq(freq):
    if isinstance(freq, bool) or not isinstance(freq, int) or freq < 0:
        return f"patch record freq must be a non-negative integer, got {freq!r}"
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
    error = _validate_patch(state, anchor, record)
    if error:
        return {"error": error}

    # Re-deciding a MANUAL entry (anchor null, replacing a prior authorship
    # patch) stays authorship: it edits that patch in place rather than minting an
    # anchored patch, which would orphan the decision (a manual word has no
    # basis record for the anchor to resolve against).
    if anchor is None and replaces:
        return _reauthor(state, record, _meta(author, request.get("note")),
                         replaces, request.get("dirty"))

    meta = _meta(author, request.get("note"))
    patch, key, error = _build_patch(state, anchor, record, meta, request.get("dirty"))
    if error:
        return {"error": error}

    # Enforce the one-canonical-per-(word,pos,var) invariant on any canonical
    # accept (authorship or anchored). A drop, a DIRTY edit (op="edit" ships
    # nothing, so cannot create a canonical clash), or an accept carrying a
    # merger/variant flag, is exempt (see _canonical_conflict). Nothing is written
    # if a different-shaw canonical already exists.
    if patch["op"] != OP_EDIT:
        error = _canonical_conflict_error(state, record)
        if error:
            return {"error": error}

    result, _previous = upsert_patch(patch)
    state.view.apply_patch(patch)
    return _write_result(state, key, result, patch["id"])


def _build_patch(state, anchor, record, meta, dirty):
    """Construct the (patch, key) an accept/drop/authorship persists. Returns
    (patch, key, None) on success, or (None, None, error) when the anchor
    resolves to no basis record. `dirty` selects op=edit vs op=accept for an
    anchored change, and op=edit vs op None for an authorship."""
    # Authorship (anchor null, record supplied): the record is self-contained, so
    # `changes` IS the whole record. Creating a record IS a verdict — Create
    # sends no `dirty` and the record is accepted and shipped, exactly as Accept
    # does elsewhere. `dirty` (op="edit") is for an edit persisted on navigate.
    if anchor is None:
        op = OP_EDIT if dirty else None
        return make_patch(None, op, record, meta), anchor_key(record), None
    # An accept/drop must anchor to a record that exists in the basis right now.
    # Writing an anchor that resolves to nothing would create an orphan the build
    # later fails on; reject it here where the actor can fix it.
    basis = state.view.basis_record(anchor_key(anchor))
    if basis is None:
        return None, None, f"anchor resolves to no basis record: {anchor}"
    if record is None:
        patch = make_patch(anchor, OP_DROP, {}, meta)
    else:
        changes = _compute_changes(record, basis)
        # A bare edit persisted on navigate (autoSaveMainEdit) sends
        # dirty=true -> op="edit" (DIRTY: edited, not reviewed, not shipped).
        # Explicit Accept omits it -> op="accept" (reviewed, shipped, carrying
        # any accumulated edits). Acceptance is the ONLY thing that reviews.
        op = OP_EDIT if dirty else OP_ACCEPT
        patch = make_patch(anchor, op, changes, meta)
    return patch, anchor_key(anchor), None


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


# mergers defaults to [] and variant to False when absent, freq to 0, lemma to
# None (a dict field — "" would never equal it, so an absent-on-both-sides
# comparison would always register a spurious change); the other intrinsics
# default to "" — so an absent field on one side and its default on the other
# are NOT a change. This mirrors record_to_output/output_to_record, which emit
# these defaults for absent fields.
def _intrinsic_value(record, field):
    if field == "mergers":
        return record.get("mergers") or []
    if field == "variant":
        return bool(record.get("variant"))
    if field == "freq":
        return record.get("freq", 0)
    if field == "lemma":
        return record.get("lemma") or None
    return record.get(field, "")


# A record is CANONICAL when it carries no additive flag: empty mergers AND
# variant not true. A record with any merger or variant:true is a sanctioned
# ALTERNATE, exempt from the one-canonical-per-(word,pos,var) invariant.
def _is_canonical(record):
    return not _intrinsic_value(record, "mergers") \
        and not _intrinsic_value(record, "variant")


# The one-canonical-per-(word,pos,var) invariant: for a given (word, pos, var)
# there may be only ONE accepted canonical entry (different shaws are fine as
# candidates, but only one may be sanctioned). The anchor key includes shaw, so
# the anchor check does not catch this; enforce it here before the write.
#
# `wanted` is the client's wanted record. If it is not itself a canonical accept
# (it carries a merger/variant flag, or it is a drop — record is None) it is
# exempt: return None. Otherwise scan the other records on the same (word, pos,
# var) with a DIFFERENT shaw and return the first that is itself a live accepted
# canonical (an existing sanctioned entry the wanted one would duplicate), or
# None. `exclude_patch_id` spares the row a re-authorship is about to replace —
# its own prior version is not a rival. A read against the current view, taking
# the view's own lock via by_word; it never mutates.
def _canonical_conflict(state, wanted, exclude_patch_id=None):
    if wanted is None or not _is_canonical(wanted):
        return None
    word, pos, var = wanted["word"], wanted["pos"], wanted.get("var", "")
    shaw = wanted["shaw"]
    for other in state.view.by_word(word):
        if other["pos"] != pos or other.get("var", "") != var:
            continue
        if other["shaw"] == shaw:
            continue
        patch = other.get("patch")
        if exclude_patch_id and patch and patch["id"] == exclude_patch_id:
            continue
        if other["patch_state"] in ACCEPTED_STATES and _is_canonical(other):
            return other["shaw"]
    return None


def _canonical_conflict_error(state, record, exclude_patch_id=None):
    """The one-canonical invariant as a write-rejection message, or None when the
    write is clean — shared by the anchored/authorship accept and the manual
    re-decision accept, so the two can never phrase the rule apart."""
    conflict = _canonical_conflict(state, record, exclude_patch_id)
    if conflict is None:
        return None
    return (f"a canonical {record.get('var', '')} entry already exists "
            f"for {record['word']}/{record['pos']} ({conflict}) — "
            "flag one as a variant/merger first")


def _reauthor(state, record, meta, prior_id, dirty=False):
    """Persist a manual re-decision as a replacement of the prior authorship
    patch, keeping anchor null. `dirty` keeps it an unshipped edit (op="edit",
    verdict unreviewed); otherwise the re-decision is an ACCEPT (op None — the
    record ships), gated by the one-canonical invariant like any other accept
    (excluding the very patch being replaced). Fails loud if the prior patch is
    not there (surfaced to the actor, never a silent new-patch fallback)."""
    if record is None:
        return {"error": "manual re-decision requires a record"}
    op = OP_EDIT if dirty else None
    if op != OP_EDIT:
        error = _canonical_conflict_error(state, record, exclude_patch_id=prior_id)
        if error:
            return {"error": error}
    patch = make_patch(None, op, record, meta)
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

    # Flagging a MANUAL entry re-authors it with op flag, keeping anchor null —
    # never an anchored flag patch that would orphan the decision.
    if anchor is None and replaces:
        return _flag_authored(state, author, request.get("note"), replaces)

    if not anchor:
        return {"error": "flag requires an anchor or a prior authored patch"}
    error = _validate_patch(state, anchor, None)
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
        error = _validate_patch(state, anchor, None)
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


# The patch store lives inside the `data/` git SUBMODULE, so a commit runs git in
# the submodule's working tree — not PROJECT_ROOT, where `data/` is only a gitlink.
# The commit stages EXACTLY TWO pathspecs — the store (_commit_pathspec) and the
# readlex.json artifact published from it (_publish_pathspec) — and nothing else:
# the submodule tree carries other regenerated data that must never be swept into
# the owner's decision commit.
def _commit_repo_root():
    """The git working tree that TRACKS the patch store, or None when committing is
    not supported.

    The store lives under the `data/` submodule, so the commit root is that
    submodule's toplevel — resolved with `git rev-parse --show-toplevel` run from the
    store's own directory, which works whether `.git` is a dir (plain repo) or a file
    (submodule gitlink). Returns None (→ commit unavailable, button hidden) when the
    store is not inside any git checkout, so a tarball deploy degrades cleanly.

    Anchoring on the store's directory is also the test guard: a store redirected to a
    bare temp file sits in no repo, so rev-parse fails and we return None (that test
    cannot commit); a test that points the store INTO a throwaway repo resolves that
    repo's toplevel and can exercise the commit path. We double-check the resolved
    toplevel is actually an ancestor of the store, never committing to a stray repo
    git happened to find above an unrelated temp dir."""
    store = _store_path().resolve()
    toplevel = _run_git(store.parent, "rev-parse", "--show-toplevel")
    if toplevel.returncode != 0 or not toplevel.stdout.strip():
        return None
    root = Path(toplevel.stdout.strip()).resolve()
    if root not in store.parents:
        return None
    return root


def _commit_pathspec(root):
    """The patch store as a pathspec relative to the commit root — the file whose
    uncommitted lines gate a commit. Derived (not hardcoded) so it stays correct
    wherever _commit_repo_root points (the real `data/` submodule, or a test repo)."""
    return str(_store_path().resolve().relative_to(Path(root).resolve()))


# The editor is the SOLE publisher of data/readlex.json: `make` no longer builds
# it, it just depends on the committed file. Deriving it here — from the same
# on-disk store the commit is about to stage — and committing the two together
# means the published artifact can never drift out of sync with the patches that
# produced it.
def _publish_pathspec(root):
    """data/readlex.json as a pathspec relative to the commit root, or None when
    the artifact lives outside that repo — a store redirected into a throwaway
    test repo has no readlex beside it, so there is nothing to publish there. In
    the real `data/` submodule the artifact always resolves."""
    from apply_patches import OUTPUT_PATH

    output = OUTPUT_PATH.resolve()
    root = Path(root).resolve()
    if root not in output.parents:
        return None
    return str(output.relative_to(root))


class PublishError(Exception):
    """A publish precondition failed with a message meant for the owner verbatim
    (not a raw stack/sys.exit). handle_commit surfaces it as the commit error."""


# The provenance statuses that mean "vetted": an accept's sanction and an
# authored (owner-minted) record. Anything else — including the absent status of
# an unvetted supplement-pool record — publishes as supplement=true.
_VETTED_STATUSES = (ACCEPTED_STATUS, AUTHORED_STATUS)


def to_published_entry(entry, sources):
    """The PUBLISHED shape of one applicator output entry: the shared whitelist
    shaping (basis.PUBLISH_FIELDS / basis.published_entry) plus the daemon-side
    supplement VERDICT — a bare `supplement: true` flag on a not-yet-vetted
    record: one neither sanctioned/authored by a patch (status, see
    basis.ACCEPTED_STATUS / overlay AUTHORED_STATUS) nor attested by upstream
    ReadLex core (`sources`, the basis origin list for its anchor — the same
    derivation as the overlay's UPSTREAM_STATUS/SUPPLEMENT_STATUS split). Any
    `supplement` value already on the entry is discarded: the verdict computed
    here is authoritative. Used ONLY by _publish_readlex; the editor's internal
    round-trip shapes (basis.record_to_output) are untouched."""
    verdict_entry = dict(entry)
    verdict_entry.pop("supplement", None)
    if (entry.get("status") not in _VETTED_STATUSES
            and UPSTREAM_SOURCE not in sources):
        verdict_entry["supplement"] = True
    return published_entry(verdict_entry)


def _publish_readlex(view):
    """Derive readlex.json from the on-disk patch store and write it to its
    canonical path — the offline applicator's derivation (the pre-patch corpus
    frequency stage, then apply_patches; see apply_patches.main) run over the
    daemon's RESIDENT basis (view.basis_index / basis_source, built and
    freq-enriched once at startup) instead of a fresh minutes-long
    build_basis(), then serialised through the publish whitelist
    (to_published_entry) and the ReadLex-compatibility collapse
    (basis.collapse_readlex). Orphaned patches soft-fail exactly as in the
    offline applicator: skipped, retained in the store, summarised in one log
    line — never a blocked publish. Raises on any genuine derivation error (the
    caller aborts the commit)."""
    from apply_patches import (IDENTITY_MISMATCH_WARNING, OUTPUT_PATH,
                               apply_patches, enrich_upstream, load_patches)
    from apply_frequency_data import CORPUS_PATH, load_corpus
    from basis import anchor_of, authored_pool, load_upstream
    from lrw_frequencies import load_lrw

    # The frequency corpus is REQUIRED to publish: a published readlex.json must
    # match production, so a freq-less fallback (which basis.py deliberately
    # allows for the review pool at STARTUP) is not acceptable here. Fail loud and
    # early with an actionable message rather than letting load_corpus sys.exit
    # with a cryptic one mid-derivation.
    if not CORPUS_PATH.exists():
        raise PublishError(
            f"Cannot publish readlex.json: frequency corpus missing "
            f"({CORPUS_PATH.name}). The editor can run without it, but "
            f"committing requires it so the published dictionary matches "
            f"production. Run `make setup` to fetch the corpus, then retry.")
    # Anchored accepts inherit the RESIDENT basis's freq, so that basis must
    # actually be on the corpus scale — a daemon that started before the
    # frequency data existed skipped the startup pool pass and must restart.
    if not view.freq_enriched:
        raise PublishError(
            "Cannot publish readlex.json: the daemon started without frequency "
            "data, so its basis carries no corpus freq. Run `make setup` and "
            "restart the editor, then retry.")

    output = load_upstream()
    patches = load_patches()
    authored_bases = authored_pool(patches)

    # FREQUENCY BEFORE PATCHES — the corpus derivation is an upstream stage, so
    # it runs over the PRE-PATCH record set (the upstream output plus the
    # authored wing; anchored accepts inherit the startup-enriched basis) and
    # the patch overlay is the last word: a patched freq ships verbatim because
    # nothing recomputes it afterwards.
    # Unlike the corpus, the LRW list (POS split, pass 2) has no graceful
    # skip: load_lrw fails loud with download instructions if it is missing.
    enrich_upstream(output, authored_bases, load_corpus(), load_lrw())

    stats, orphans = apply_patches(output, view.basis_index, view.basis_source,
                                   patches, authored_bases)
    if stats["skipped_duplicate"]:
        logging.warning(
            "publish: dropped %d record(s) whose emitted identity duplicates an "
            "existing output record (e.g. a word edit landed on an existing entry)",
            stats["skipped_duplicate"])
    if stats["upstream_removal_missed"]:
        logging.warning("publish: %d %s", stats["upstream_removal_missed"],
                        IDENTITY_MISMATCH_WARNING)
    if orphans:
        accepts = sum(1 for p in orphans if p.get("op") == OP_ACCEPT)
        drops = sum(1 for p in orphans if p.get("op") == OP_DROP)
        logging.warning(
            "publish: skipped %d orphaned patch(es) (%d accept, %d drop) — "
            "see the editor 'orphaned' filter",
            len(orphans), accepts, drops)
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            for patch in orphans:
                anchor = patch["anchor"]
                logging.debug(
                    "publish: orphaned patch skipped: %r pos=%s shaw=%s var=%s "
                    "(id=%s)", anchor["word"], anchor["pos"], anchor["shaw"],
                    anchor["var"], patch["id"])

    published = {
        bucket_key: [
            to_published_entry(
                entry, view.basis_source.get(anchor_of(entry), ()))
            for entry in entries]
        for bucket_key, entries in output.items()}
    published, collapse_stats = collapse_readlex(published)
    if collapse_stats:
        logging.info(
            "publish: readlex-compat collapse: %s",
            ", ".join(f"{action}={count}"
                      for action, count in sorted(collapse_stats.items())))
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(published, f, ensure_ascii=False, indent=4)


def _run_git(root, *args):
    """Run git in `root`, returning the CompletedProcess. Never raises on non-zero
    exit — the caller inspects returncode and surfaces stderr to the client."""
    return subprocess.run(
        ["git", *args], cwd=str(root),
        capture_output=True, text=True, check=False,
    )


def _uncommitted_patch_count(root, pathspec):
    """Patch lines in the store not yet in HEAD: the added-line count of the store's
    diff against the HEAD blob. `git diff HEAD` omits a store absent from HEAD (never
    committed, or no commits yet), so that case is counted as every line added — the
    diff against an empty tree — rather than silently reported as zero."""
    in_head = _run_git(root, "cat-file", "-e", f"HEAD:{pathspec}")
    if in_head.returncode != 0:
        return _store_line_count(root, pathspec)
    result = _run_git(root, "diff", "--numstat", "HEAD", "--", pathspec)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    line = result.stdout.strip()
    if not line:
        return 0
    added = line.split("\t", 1)[0]
    return int(added) if added.isdigit() else 0


def _store_line_count(root, pathspec):
    store = root / pathspec
    with open(store, "r", encoding="utf-8") as handle:
        return sum(1 for stored in handle if stored.strip())


def handle_commit_status(_state, _request):
    root = _commit_repo_root()
    if root is None:
        # No repo (tarball deploy / redirected store): committing is simply
        # unavailable here — a STATE, not an error. The UI hides the button and
        # stays quiet; erroring would toast on every write for a non-problem.
        return {"commit_available": False}
    try:
        uncommitted = _uncommitted_patch_count(root, _commit_pathspec(root))
    except RuntimeError as exc:
        return {"error": str(exc)}
    head = _run_git(root, "log", "-1", "--format=%h\t%s")
    if head.returncode != 0 or not head.stdout.strip():
        return {"commit_available": True, "uncommitted": uncommitted,
                "head": None, "subject": None}
    short_sha, _, subject = head.stdout.strip().partition("\t")
    return {"commit_available": True, "uncommitted": uncommitted,
            "head": short_sha, "subject": subject}


def handle_commit(state, _request):
    root = _commit_repo_root()
    if root is None:
        return {"error": "commit is only supported for the default patch store"}
    pathspec = _commit_pathspec(root)
    try:
        uncommitted = _uncommitted_patch_count(root, pathspec)
    except RuntimeError as exc:
        return {"error": str(exc)}
    if uncommitted == 0:
        return {"result": "nothing-to-commit"}

    # Publish readlex.json BEFORE git touches anything: a derivation failure
    # aborts the whole commit with nothing staged, so the store is never
    # committed ahead of the artifact it ships with. Both the pathspec resolution
    # (imports apply_patches at call time) and the derivation are inside the try,
    # so a missing module surfaces as a clean error, not a 500. A PublishError
    # carries an owner-facing message verbatim (e.g. the corpus precheck); other
    # failures (including load_corpus's sys.exit backstop) get the generic wrap.
    try:
        published = _publish_pathspec(root)
        if published is not None:
            _publish_readlex(state.view)
    except PublishError as exc:
        return {"error": str(exc)}
    except (SystemExit, Exception) as exc:
        # Unexpected: the client message alone is undiagnosable — keep the traceback.
        logging.exception("commit: readlex publish failed")
        return {"error": f"readlex publish failed, nothing committed: {exc}"}

    pathspecs = [pathspec] if published is None else [pathspec, published]
    staged = _run_git(root, "add", "--", *pathspecs)
    if staged.returncode != 0:
        return {"error": staged.stderr.strip() or "git add failed"}

    message = f"Editorial decisions from review session ({uncommitted} patches)"
    if published is not None:
        message += "; publishes readlex.json"
    committed = _run_git(root, "commit", "-m", message, "--", *pathspecs)
    if committed.returncode != 0:
        return {"error": committed.stderr.strip() or "git commit failed"}

    head = _run_git(root, "rev-parse", "--short", "HEAD")
    sha = head.stdout.strip() if head.returncode == 0 else None

    # Sync the decision off-host. The commit is already durable locally, so a push
    # failure (no remote, offline, auth, non-fast-forward) must NOT fail the commit
    # or crash — we report it so the UI can say "committed locally, push failed: …".
    # `git push` with no args pushes the current branch to its configured upstream
    # (origin on the owner's laptop; a local bare repo via submodule URL override on
    # the server), so the same call works either place.
    pushed = _run_git(root, "push")
    result = {"result": "committed", "message": message, "sha": sha, "uncommitted": 0}
    if pushed.returncode == 0:
        result["pushed"] = True
    else:
        result["pushed"] = False
        result["push_error"] = (pushed.stderr.strip() or pushed.stdout.strip()
                                or "git push failed")
        logging.warning("commit: committed %s but push failed: %s",
                        sha, result["push_error"])
    return result


# The revert footgun: `git checkout -- <pathspec>` discards uncommitted store
# changes only — never touches other files, never rewrites history. Requires a
# committed HEAD blob to check out (a store never yet committed has nothing to
# revert TO, so that case is a loud error, not a silent no-op).
def handle_revert_uncommitted(state, _request):
    root = _commit_repo_root()
    if root is None:
        return {"error": "revert is only supported for the default patch store"}
    pathspec = _commit_pathspec(root)
    try:
        uncommitted = _uncommitted_patch_count(root, pathspec)
    except RuntimeError as exc:
        return {"error": str(exc)}
    if uncommitted == 0:
        return {"result": "nothing-to-revert"}
    in_head = _run_git(root, "cat-file", "-e", f"HEAD:{pathspec}")
    if in_head.returncode != 0:
        return {"error": f"{pathspec} has no committed version to revert to"}
    reverted = _run_git(root, "checkout", "--", pathspec)
    if reverted.returncode != 0:
        return {"error": reverted.stderr.strip() or "git checkout failed"}
    state.rebuild()
    return {"result": "reverted", "discarded": uncommitted}


HANDLERS = {
    "entries": handle_entries,
    "facets": handle_facets,
    "entry": handle_entry,
    "related": handle_related,
    "definitions": handle_definitions,
    "definition_patch": handle_definition_patch,
    "definition_unpatch": handle_definition_unpatch,
    "patch": handle_patch,
    "flag": handle_flag,
    "unpatch": handle_unpatch,
    "commit_status": handle_commit_status,
    "commit": handle_commit,
    "revert_uncommitted": handle_revert_uncommitted,
}


def handle_request(state, request):
    op = request.get("op")
    handler = HANDLERS.get(op)
    if handler is None:
        return {"error": f"unknown op: {op!r}"}
    return handler(state, request)


class RequestHandler(socketserver.StreamRequestHandler):

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
        if "error" in response:
            # Every error response aborts something the owner attempted; the
            # transient client toast must never be the only trace of it.
            logging.error("%s error: %s", op, response["error"])
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
    view = load_view()
    logging.info("view ready: %d annotated records", len(view.records))

    logging.info("loading Shavian definitions corpus (gb + us)")
    definitions = load_definitions_index()
    def_patches = definition_patches.load_patches()
    orphans = definition_patches.overlay_corpus(definitions, def_patches)
    logging.info("definitions ready: %d correction(s) overlaid, %d orphaned",
                 len(def_patches) - len(orphans), len(orphans))
    if orphans:
        # Soft-fail: an orphaned correction (its sense left the corpus) is LOGGED
        # and RETAINED, never dropped — mirrors the word applicator. The store is
        # untouched; the owner can re-anchor or clear it.
        logging.warning("%d orphaned definition correction(s) — anchor no longer "
                        "resolves against the corpus; retained in the store:",
                        len(orphans))
        for patch in orphans:
            a = patch["anchor"]
            logging.warning("    word=%r synset=%s dialect=%s (id=%s)",
                            a.get("word"), a.get("synset"), a.get("dialect"),
                            patch.get("id"))
    state = State(view, definitions)

    socket_path = args.socket
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)

    server = Server(socket_path, state)
    os.chmod(socket_path, int(args.socket_mode, 8))
    logging.info("listening on %s", socket_path)

    shutting_down = threading.Event()

    def _shutdown(signum, _frame):
        logging.info("signal %d — shutting down", signum)
        # server.shutdown() BLOCKS until serve_forever() returns and MUST run on a
        # different thread than the one running serve_forever() (see stdlib docs).
        # The signal handler fires on the MAIN thread — the same thread serving —
        # so calling shutdown() inline deadlocks: it waits for a serve loop that
        # can't proceed until the handler returns. systemd then SIGKILLs after
        # TimeoutStopSec. Spawn it off-thread so serve_forever() can unwind. The
        # flag makes a second signal a no-op (one shutdown thread, not a race).
        if shutting_down.is_set():
            return
        shutting_down.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

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
