#!/usr/bin/env python3
"""Focused unit tests for the patch-meta editor features (author filter, relative
date filter) — all daemon-side.

Pure functions over SYNTHETIC patches and annotated records: no basis load, no
build, no live store.

Covers:
  - overlay surfaces patch_author/patch_ts onto a patched record, and leaves them
    absent on an unreviewed (patchless) one
  - the author facet matcher (record's patch_author ∈ selected)
  - the relative "days back" matcher (_within_days: patched within N days; a
    patchless record never matches)
  - _distinct_authors ignores patchless rows
  - group-aware filter_records (a matching member serves its whole group)
  - the review "mixed" GROUP-level filter (REVIEW_MIXED): serves groups whose
    members span >1 verdict (verdict_state collapse), ANDs with the other
    facets, ORs with the record-level review values, and never matches
    everything when review is reduced to mixed alone
  - group-denominated entries paging (handle_entries: total/offset/limit count
    GROUPS, a group is never split across pages, groups rank by their best
    member under every sort, and offset paging is stable — no dups, no gaps)

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import calendar
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import editord


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _annotated(**kw):
    """A minimal annotated-record dict as the matchers see it."""
    base = {"word": "x", "shaw": "\U00010450", "pos": "NN", "var": ""}
    base.update(kw)
    return base


# ---- overlay surfacing (patch_author / patch_ts) ----

def test_overlay_surfaces_author_and_ts_on_patch():
    import overlay

    patch = {
        "op": "accept", "changes": {},
        "meta": {"author": "joro", "origin": "editor",
                 "ts": "2026-07-22T03:12:31Z"},
    }
    ui = overlay._ui_record(
        {"word": "cat", "shaw": "\U00010450", "pos": "NN"},
        {"word": "cat", "pos": "NN", "shaw": "\U00010450", "var": ""},
        ["wiktionary"], "supplement", True, "accepted", patch,
        _StubEstablished())
    assert ui["patch_author"] == "joro", ui.get("patch_author")
    assert ui["patch_ts"] == "2026-07-22T03:12:31Z", ui.get("patch_ts")


def test_overlay_omits_author_and_ts_when_unreviewed():
    import overlay

    ui = overlay._ui_record(
        {"word": "cat", "shaw": "\U00010450", "pos": "NN"},
        {"word": "cat", "pos": "NN", "shaw": "\U00010450", "var": ""},
        ["readlex"], "sanctioned", False, "unreviewed", None,
        _StubEstablished())
    assert "patch_author" not in ui
    assert "patch_ts" not in ui


class _StubEstablished:
    def classify(self, *_a):
        return "known"


# ---- author facet matcher ----

def test_author_matcher_hits_selected():
    rec = _annotated(patch_author="joro")
    assert editord._field_matches(rec, "patch_author", ["joro"], None)
    assert editord._field_matches(rec, "patch_author", ["ann", "joro"], None)


def test_author_matcher_misses_unselected():
    rec = _annotated(patch_author="joro")
    assert not editord._field_matches(rec, "patch_author", ["ann"], None)


def test_author_matcher_excludes_patchless():
    rec = _annotated()  # no patch_author
    assert not editord._field_matches(rec, "patch_author", ["joro"], None)


# ---- relative days-back matcher ----

def test_within_days_recent_matches():
    ts = _iso(time.time() - 2 * 86400)  # 2 days ago
    assert editord._within_days(ts, 7)


def test_within_days_old_misses():
    ts = _iso(time.time() - 10 * 86400)  # 10 days ago
    assert not editord._within_days(ts, 7)


def test_within_days_patchless_misses():
    assert not editord._within_days(None, 7)
    assert not editord._within_days("", 7)


def test_days_matcher_via_field_matches():
    recent = _annotated(patch_ts=_iso(time.time() - 1 * 86400))
    old = _annotated(patch_ts=_iso(time.time() - 30 * 86400))
    assert editord._field_matches(recent, "patch_days", 7, None)
    assert not editord._field_matches(old, "patch_days", 7, None)
    assert not editord._field_matches(_annotated(), "patch_days", 7, None)


def test_parse_iso_utc_roundtrip():
    epoch = calendar.timegm(time.strptime("2026-07-22T03:12:31Z",
                                          "%Y-%m-%dT%H:%M:%SZ"))
    assert editord._parse_iso_utc("2026-07-22T03:12:31Z") == epoch


# ---- distinct authors (facets op helper) ----

def test_distinct_authors_ignores_patchless():
    view = _StubView([
        [_annotated(patch_author="joro"), _annotated()],           # one patched
        [_annotated(patch_author="ann"), _annotated(patch_author="joro")],
    ])
    assert editord._distinct_authors(view) == ["ann", "joro"]


class _StubView:
    """The minimum AnnotatedView surface _distinct_authors touches: a lock and a
    by_anchor_index of record groups."""

    def __init__(self, groups):
        import threading
        self._lock = threading.Lock()
        self.by_anchor_index = {i: group for i, group in enumerate(groups)}


# ---- group-aware filtering (filter_records / group_key) ----

def test_filter_serves_whole_group_when_one_member_matches():
    # Same group (word+shaw+variation), different pos: a pos filter hitting ONE
    # member must serve BOTH, in the incoming order; the unrelated group is
    # excluded entirely.
    sibling_hit = _annotated(word="run", pos="NN")
    sibling_miss = _annotated(word="run", pos="VB")
    unrelated = _annotated(word="walk", pos="JJ")
    query = editord.QueryFilters({"pos": ["NN"]})
    result = editord.filter_records(
        [sibling_hit, sibling_miss, unrelated], query, None)
    assert result == [sibling_hit, sibling_miss]


def test_filter_no_filters_is_identity():
    records = [_annotated(word="run", pos="NN"), _annotated(word="walk", pos="JJ")]
    result = editord.filter_records(records, editord.QueryFilters({}), None)
    assert result == records


def test_group_key_splits_on_variation_never_on_verdict():
    # Identity only: variations partition; editorial state never does — a manual
    # record and a reviewed one with the same word+shaw+variations group together.
    base = _annotated(word="run", pos="NN",
                      patch_state=editord.PATCH_STATE_UNREVIEWED)
    assert editord.group_key(base) != editord.group_key(
        _annotated(word="run", pos="NN", mergers=["trap-bath"]))
    assert editord.group_key(base) != editord.group_key(
        _annotated(word="run", pos="NN", variant=True))
    assert editord.group_key(base) == editord.group_key(
        _annotated(word="run", pos="NN",
                   patch_state=editord.PATCH_STATE_ACCEPTED))


# ---- the review "mixed" group-level filter (REVIEW_MIXED) ----

def _mixed_corpus():
    """Two groups: `run` spans two verdicts (mixed); `walk` is uniformly accepted
    (its edited member collapses onto accepted — verdict_state)."""
    return [
        _annotated(word="run", pos="NN", patch_state="accepted"),
        _annotated(word="run", pos="VB", patch_state="unreviewed"),
        _annotated(word="walk", pos="NN", patch_state="accepted"),
        _annotated(word="walk", pos="VB", patch_state="edited"),
    ]


def test_queryfilters_strips_mixed_into_the_group_leg():
    only = editord.QueryFilters({"review": ["mixed"]})
    assert only.review_mixed and only.review_only_mixed
    both = editord.QueryFilters({"review": ["mixed", "flagged"]})
    assert both.review_mixed and not both.review_only_mixed
    without = editord.QueryFilters({"review": ["flagged"]})
    assert not without.review_mixed and not without.review_only_mixed


def test_mixed_serves_only_groups_spanning_verdicts():
    result = editord.filter_records(
        _mixed_corpus(), editord.QueryFilters({"review": ["mixed"]}), None)
    assert [r["word"] for r in result] == ["run", "run"], result


def test_mixed_uses_the_verdict_collapse_not_raw_patch_state():
    # dirty collapses onto unreviewed (verdict_state): two raw states, ONE
    # verdict — not mixed, matching the client's verdictConsensus exactly.
    records = [
        _annotated(word="run", pos="NN", patch_state="unreviewed"),
        _annotated(word="run", pos="VB", patch_state="dirty"),
    ]
    result = editord.filter_records(
        records, editord.QueryFilters({"review": ["mixed"]}), None)
    assert result == [], result


def test_mixed_ands_with_the_other_axes():
    # AND across axes: the mixed group must also hold a member matching the other
    # facets (which then serves the group whole, non-matching siblings included).
    query = editord.QueryFilters({"review": ["mixed"], "pos": ["VB"]})
    result = editord.filter_records(_mixed_corpus(), query, None)
    assert [r["word"] for r in result] == ["run", "run"], result
    none = editord.QueryFilters({"review": ["mixed"], "pos": ["JJ"]})
    assert editord.filter_records(_mixed_corpus(), none, None) == []


def test_mixed_ors_with_record_level_review_values():
    # OR within the review axis: mixed groups ∪ groups holding a flagged member.
    records = _mixed_corpus() + [
        _annotated(word="cat", pos="NN", patch_state="flagged"),
    ]
    result = editord.filter_records(
        records, editord.QueryFilters({"review": ["mixed", "flagged"]}), None)
    assert [r["word"] for r in result] == ["run", "run", "cat"], result


def test_review_without_mixed_stays_record_level():
    result = editord.filter_records(
        _mixed_corpus(), editord.QueryFilters({"review": ["accepted"]}), None)
    assert [r["word"] for r in result] == ["run", "run", "walk", "walk"], result


def test_entries_serves_mixed_groups_via_the_review_filter():
    # End-to-end through handle_entries: `cat` spans unreviewed+flagged verdicts,
    # the other two groups are uniform — only cat is served, whole.
    page = _entries(_grouped_corpus(), filters={"review": ["mixed"]})
    assert page["total"] == 1
    assert [[member[0] for member in members]
            for members in _group_anchors(page)] == [["cat", "cat", "cat"]]


# ---- manual-create op selection (_build_patch, anchor null) ----

def test_manual_dirty_selects_op_edit_never_born_accepted():
    # A NEW manual record is created dirty (op "edit": unreviewed, ships nothing)
    # — accepting it is a separate explicit act (op None via _redecide_manual).
    record = {"word": "newword", "pos": "NN", "shaw": "\U00010451", "var": "RRP"}
    meta = {"author": "joro", "ts": "2026-01-01T00:00:00Z"}
    dirty, _key, error = editord._build_patch(None, None, record, meta, True)
    assert error is None
    assert dirty["op"] == "edit" and dirty["anchor"] is None
    accepted, _key, error = editord._build_patch(None, None, record, meta, False)
    assert error is None
    assert accepted["op"] is None and accepted["anchor"] is None


# ---- group-denominated entries paging (handle_entries) ----

def _entries(records, **request):
    """handle_entries over a stub daemon state (the .view surface it touches)."""
    state = SimpleNamespace(view=SimpleNamespace(records=records, established=None))
    return editord.handle_entries(state, request)


def _grouped_corpus():
    """Three groups over six records, sizes 3 (cat), 2 (run), 1 (walk) in natural
    order. Group identity is (word_lower, shaw, variation-set): var/pos/verdict
    differences stay IN a group, they never split one."""
    return [
        _annotated(word="run", pos="NN", var="RRP",
                   patch_state="unreviewed", confidence=90),
        _annotated(word="run", pos="VB", var="RSSB",
                   patch_state="unreviewed", confidence=10, freq=2),
        _annotated(word="walk", pos="NN", var="RRP",
                   patch_state="accepted", confidence=50),
        _annotated(word="cat", pos="NN", var="RRP",
                   patch_state="unreviewed", confidence=70, freq=5),
        _annotated(word="cat", pos="NN", var="GenAm",
                   patch_state="flagged", confidence=40),
        _annotated(word="cat", pos="VB", var="RSSB",
                   patch_state="unreviewed"),
    ]


def _group_anchors(response):
    """Per served group, its members' natural keys, in served order."""
    return [
        [(r["word"], r["pos"], r["shaw"], r["var"]) for r in group["records"]]
        for group in response["groups"]
    ]


def test_entries_pages_by_group_never_splitting():
    # Natural (default) sort: cat < run < walk. limit counts GROUPS, and the
    # 3-member cat group rides on the first page WHOLE.
    page = _entries(_grouped_corpus(), limit=2)
    assert page["total"] == 3
    assert page["limit"] == 2
    assert [len(members) for members in _group_anchors(page)] == [3, 2]
    for group in page["groups"]:
        assert len({editord.group_key(r) for r in group["records"]}) == 1
        # Every serialised record carries its own wire group key (the write ops
        # share serialisable, so manual-create responses can join the partition).
        assert all(r["group_key"] == group["key"] for r in group["records"])
    assert len({group["key"] for group in page["groups"]}) == 2


def test_entries_offset_counts_groups():
    page = _entries(_grouped_corpus(), offset=2, limit=2)
    assert page["offset"] == 2
    assert [[member[0] for member in members]
            for members in _group_anchors(page)] == [["walk"]]


def test_entries_ranks_groups_by_best_member_under_the_sort():
    response = _entries(_grouped_corpus(), sort="confidence_desc")
    groups = _group_anchors(response)
    # Best members: run 90 > cat 70 > walk 50 — the run group leads even though
    # its OTHER member (10) is the weakest scored record in the corpus.
    assert [members[0][0] for members in groups] == ["run", "cat", "walk"]
    # Members keep flat-sort order within their group: 90 before 10; the
    # confidence-less cat member sorts to its group's end.
    assert [member[1] for member in groups[0]] == ["NN", "VB"]
    assert groups[1][-1][1] == "VB"


def test_entries_filtered_groups_arrive_whole():
    # pos=VB matches ONE member each of run and cat; both groups are served
    # whole (non-matching siblings included), and total counts the two groups.
    response = _entries(_grouped_corpus(), filters={"pos": ["VB"]}, limit=500)
    assert response["total"] == 2
    assert sorted(len(members) for members in _group_anchors(response)) == [2, 3]


def test_entries_offset_paging_is_stable_under_every_sort():
    # Walking the corpus one group at a time must reproduce the one-shot order
    # exactly — no duplicates, no gaps — for EVERY sort enum, both directions.
    corpus = _grouped_corpus()
    for sort in editord.SORTS:
        whole = _entries(corpus, sort=sort, limit=500)
        walked = []
        for offset in range(whole["total"]):
            walked.extend(_entries(corpus, sort=sort, offset=offset,
                                   limit=1)["groups"])
        assert [g["key"] for g in walked] == [
            g["key"] for g in whole["groups"]], sort
        assert _group_anchors({"groups": walked}) == _group_anchors(whole), sort
        flat = [anchor for members in _group_anchors(whole) for anchor in members]
        assert len(flat) == len(set(flat)) == len(corpus), sort


def test_entries_flat_paginates_by_record_not_group():
    # The 3-member cat group would ride whole on page 1 in grouped mode; flat
    # mode instead slices the flat record list, so a limit of 2 splits it.
    page = _entries(_grouped_corpus(), flat=True, limit=2)
    assert page["total"] == 6, page["total"]
    assert [len(members) for members in _group_anchors(page)] == [1, 1]
    second = _entries(_grouped_corpus(), flat=True, offset=2, limit=2)
    assert [len(members) for members in _group_anchors(second)] == [1, 1]
    # Same natural order as the grouped flat-member walk (cat x3, run x2, walk x1).
    flat_words = [members[0][0] for members in
                  _group_anchors(page)] + [members[0][0] for members in
                                           _group_anchors(second)]
    assert flat_words == ["cat", "cat", "cat", "run"], flat_words


def test_entries_flat_filters_at_record_level_no_sibling_widening():
    # pos=VB matches one member each of run and cat (test_entries_filtered_
    # groups_arrive_whole widens both groups whole in grouped mode). Flat mode
    # must return exactly those two matching records — no pulled-in siblings —
    # and total/pagination must count the matching RECORDS, not the widened ones.
    response = _entries(_grouped_corpus(), flat=True, filters={"pos": ["VB"]}, limit=500)
    assert response["total"] == 2, response["total"]
    anchors = _group_anchors(response)
    assert [len(members) for members in anchors] == [1, 1]
    assert [members[0][1] for members in anchors] == ["VB", "VB"], anchors


def test_entries_flat_review_mixed_still_widens_to_group_members():
    # "mixed" is inherently a group property (members disagree); in flat mode
    # it is read as "show me the records inside contested groups", so it keeps
    # serving every member of a mixed group even though flat mode otherwise
    # returns only self-matching records.
    response = _entries(_grouped_corpus(), flat=True, filters={"review": ["mixed"]})
    assert response["total"] == 3, response["total"]
    words = sorted(members[0][0] for members in _group_anchors(response))
    assert words == ["cat", "cat", "cat"], words


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
