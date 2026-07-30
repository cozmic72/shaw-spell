#!/usr/bin/env python3
"""Focused unit tests for the patch-meta editor features (author filter, relative
date filter, masthead patch counts) — all daemon-side.

Pure functions over SYNTHETIC patches and annotated records: no basis load, no
build, no live store. The patch-count test redirects the store to a temp file via
SHAW_SPELL_PATCH_STORE, so the real data/patches/patches.jsonl is never touched.

Covers:
  - overlay surfaces patch_author/patch_ts onto a patched record, and leaves them
    absent on an unreviewed (patchless) one
  - the author facet matcher (record's patch_author ∈ selected)
  - the relative "days back" matcher (_within_days: patched within N days; a
    patchless record never matches)
  - the today-count semantics (_is_local_today: a UTC ts on the server's LOCAL
    calendar day counts; a two-day-old one does not)
  - _patch_counts over a synthetic store (total + today)
  - _distinct_authors ignores patchless rows
  - group-aware filter_records (a matching member serves its whole group; the
    group_key partitions mirror the client's groupKey)

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import calendar
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import editord
import patchstore


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


# ---- today-count semantics (local calendar day) ----

def test_is_local_today_now_counts():
    now = time.time()
    today = (time.localtime().tm_yday, time.localtime().tm_year)
    assert editord._is_local_today(_iso(now), today)


def test_is_local_today_two_days_ago_misses():
    old = time.time() - 2 * 86400
    today = (time.localtime().tm_yday, time.localtime().tm_year)
    assert not editord._is_local_today(_iso(old), today)


# ---- patch_counts over a synthetic store ----

def test_patch_counts_total_and_today():
    now = time.time()
    patches = [
        {"id": "p_a", "anchor": {"word": "a", "pos": "NN", "shaw": "x", "var": ""},
         "op": "accept", "changes": {},
         "meta": {"author": "joro", "origin": "editor", "ts": _iso(now)}},
        {"id": "p_b", "anchor": {"word": "b", "pos": "NN", "shaw": "y", "var": ""},
         "op": "accept", "changes": {},
         "meta": {"author": "joro", "origin": "editor",
                  "ts": _iso(now - 3 * 86400)}},
        {"id": "p_c", "anchor": {"word": "c", "pos": "NN", "shaw": "z", "var": ""},
         "op": "flag", "changes": {},
         "meta": {"author": "ann", "origin": "editor", "ts": _iso(now)}},
    ]
    with _redirected_store(patches) as _path:
        counts = editord._patch_counts()
    assert counts["total"] == 3, counts
    assert counts["today"] == 2, counts  # the two "now" patches, not the 3-day-old


def test_patch_counts_empty_store():
    with _redirected_store([]) as _path:
        counts = editord._patch_counts()
    assert counts == {"total": 0, "today": 0}, counts


class _redirected_store:
    """Write `patches` to a temp store and point SHAW_SPELL_PATCH_STORE at it for
    the duration of the block, so load_patches (and thus _patch_counts) reads the
    synthetic store, never the live one."""

    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        path = Path(self._dir.name) / "patches.jsonl"
        patchstore.write_patches(self._patches, path=path)
        self._prev = os.environ.get("SHAW_SPELL_PATCH_STORE")
        os.environ["SHAW_SPELL_PATCH_STORE"] = str(path)
        return path

    def __exit__(self, *_exc):
        if self._prev is None:
            os.environ.pop("SHAW_SPELL_PATCH_STORE", None)
        else:
            os.environ["SHAW_SPELL_PATCH_STORE"] = self._prev
        self._dir.cleanup()
        return False


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

def _grouped(**kw):
    """A group-key-complete record: group_key needs patch_state (the verdict
    axis) on top of the _annotated basics."""
    base = _annotated(patch_state=editord.PATCH_STATE_UNREVIEWED)
    base.update(kw)
    return base


def test_filter_serves_whole_group_when_one_member_matches():
    # Same group (word+shaw+variation+verdict), different pos: a pos filter
    # hitting ONE member must serve BOTH, in the incoming order; the unrelated
    # group is excluded entirely.
    sibling_hit = _grouped(word="run", pos="NN")
    sibling_miss = _grouped(word="run", pos="VB")
    unrelated = _grouped(word="walk", pos="JJ")
    query = editord.QueryFilters({"pos": ["NN"]})
    result = editord.filter_records(
        [sibling_hit, sibling_miss, unrelated], query, None)
    assert result == [sibling_hit, sibling_miss]


def test_filter_no_filters_is_identity():
    records = [_grouped(word="run", pos="NN"), _grouped(word="walk", pos="JJ")]
    result = editord.filter_records(records, editord.QueryFilters({}), None)
    assert result == records


def test_group_key_splits_on_verdict_and_variation():
    base = _grouped(word="run", pos="NN")
    assert editord.group_key(base) != editord.group_key(
        _grouped(word="run", pos="NN", patch_state=editord.PATCH_STATE_ACCEPTED))
    assert editord.group_key(base) != editord.group_key(
        _grouped(word="run", pos="NN", mergers=["trap-bath"]))
    assert editord.group_key(base) != editord.group_key(
        _grouped(word="run", pos="NN", variant=True))


def test_group_key_collapses_verdict_like_client():
    # edited folds onto accepted, dirty onto unreviewed — the same collapse the
    # client's verdictState applies, so daemon groups and client folds agree.
    assert editord.group_key(
        _grouped(patch_state=editord.PATCH_STATE_EDITED)) == editord.group_key(
        _grouped(patch_state=editord.PATCH_STATE_ACCEPTED))
    assert editord.group_key(
        _grouped(patch_state=editord.PATCH_STATE_DIRTY)) == editord.group_key(
        _grouped(patch_state=editord.PATCH_STATE_UNREVIEWED))


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
