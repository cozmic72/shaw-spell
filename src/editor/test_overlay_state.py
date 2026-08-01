#!/usr/bin/env python3
"""Characterization tests for the overlay state-derivation engine (overlay.py) —
the editor's most intricate logic, previously untested.

These LOCK IN the current (correct) behaviour so a future edit can't silently
break a subtle invariant. Everything runs over SMALL SYNTHETIC basis dicts and
patch dicts built by hand — no basis load, no build, no live store, no Shavian
bulk. AnnotatedView is constructed directly from (basis_index, basis_source,
patches, authored_bases), exactly as load_view assembles it.

Covers:
  - every patch_state: unreviewed, accepted, edited, dirty, dropped, flagged,
    orphaned — a basis+patch that should yield each, asserting the derived
    patch_state (and the reviewed flag that partitions the review pool)
  - MANUAL rows (authorship patches, anchor null): manual-ness is an origin
    (`manual: True`), not a state — the row's patch_state is derived from the
    patch op like any other (op None = accepted/ships, op "edit" = dirty/
    unreviewed, op "flag" = flagged)
  - accept-with-edits layering: accept = basis record + intrinsic `changes` laid
    over it (the `edited` state), vs an accept-as-is (`accepted`, empty changes)
  - a FLAG is a review no-op: reviewed=True but the shown content is the untouched
    basis record (no edits laid over it), distinct from an accept
  - the orphan sub-classification the audit called out:
      lost-accept      an accept whose anchor vanished (word/pos/shaw wholly gone)
      resurfaced-drop  a drop whose anchor var vanished but the same word/pos/shaw
                       returned under a different var (the suppressed junk is back)
    plus the two BENIGN no-ops that must NOT surface: a satisfied drop (record
    wholly gone) and a flag of a vanished anchor
  - THE big invariant: incremental-apply == full-rebuild. A sequence of writes
    applied in place must yield a view byte-identical to a from-scratch rebuild
    over the same basis + final patch set (records AND the word/shaw indexes).
  - the word/shaw indexes track the DISPLAYED record (task #119): a patch that
    respells the word (or shaw) re-files its anchor under the value the client
    shows, with no stale registrations left across a mutation sequence — while
    the case-only path (the owner's `i` -> `I` fix) keeps resolving.

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import overlay
from basis import authored_pool
from overlay import (PATCH_STATE_ACCEPTED, PATCH_STATE_DIRTY,
                     PATCH_STATE_DROPPED, PATCH_STATE_EDITED,
                     PATCH_STATE_FLAGGED, PATCH_STATE_ORPHANED,
                     PATCH_STATE_UNREVIEWED, ORPHAN_LOST_ACCEPT,
                     ORPHAN_RESURFACED_DROP, AnnotatedView)

# A Shavian glyph, used opaquely — these tests never inspect Shavian, they only
# need distinct spelling strings for distinct anchors.
SHAW_A = "\U00010450"
SHAW_B = "\U00010451"


# ---- synthetic-fixture helpers (the canonical on-disk shape the basis holds) ----

def entry(latn, pos, shaw, var, source, ipa="", freq=0):
    """A canonical basis entry (Latn/Shaw/... shape), as build_basis would yield."""
    return {"Latn": latn, "pos": pos, "Shaw": shaw, "ipa": ipa, "freq": freq,
            "var": var, "source": list(source)}


def anchor_key_of(latn, pos, shaw, var):
    return (latn.lower(), pos, shaw, var)


def basis_of(*entries):
    """(index, source) over synthetic entries — the two structures AnnotatedView
    consumes, keyed the way build_basis keys them."""
    index, source = {}, {}
    for candidate in entries:
        key = anchor_key_of(candidate["Latn"], candidate["pos"],
                            candidate["Shaw"], candidate["var"])
        index[key] = candidate
        source[key] = list(candidate.get("source", []))
    return index, source


def anchor(word, pos, shaw, var):
    return {"word": word, "pos": pos, "shaw": shaw, "var": var}


def anchored_patch(op, word, pos, shaw, var, changes=None, pid="p_test"):
    return {"id": pid, "anchor": anchor(word, pos, shaw, var), "op": op,
            "changes": changes or {}, "meta": {"author": "joro", "origin": "editor",
                                               "ts": "2026-01-01T00:00:00Z"}}


def authored_patch(record, pid="p_auth", op=None):
    """An authorship patch: anchor null, `changes` is the whole self-contained
    record (word/shaw/pos/var — the natural-key fields at minimum). `op` picks
    the manual record's verdict: None = accepted (ships), "edit" = dirty
    (unreviewed, ships nothing), "flag" = flagged."""
    return {"id": pid, "anchor": None, "op": op, "changes": record,
            "meta": {"author": "joro", "origin": "editor",
                     "ts": "2026-01-01T00:00:00Z"}}


def view_of(entries, patches):
    """A fresh AnnotatedView (full rebuild) over synthetic entries + patches.
    The authored wing is built by the real helper (basis.authored_pool), exactly
    as load_view assembles it — unenriched here (no corpus in these tests)."""
    index, source = basis_of(*entries)
    return AnnotatedView(index, source, patches, authored_pool(patches))


def only_record_for(view, word):
    matches = [rec for rec in view.records if rec["word"] == word]
    assert len(matches) == 1, f"expected exactly one {word!r} row, got {matches}"
    return matches[0]


# ---- the seven+ patch states ----

def test_unreviewed_state_when_no_patch():
    view = view_of([entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])], [])
    rec = only_record_for(view, "cat")
    assert rec["patch_state"] == PATCH_STATE_UNREVIEWED, rec["patch_state"]
    assert rec["reviewed"] is False


def test_accepted_state_when_accept_with_no_edits():
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])]
    patch = anchored_patch("accept", "cat", "NN", SHAW_A, "RRP", changes={})
    rec = only_record_for(view_of(entries, [patch]), "cat")
    assert rec["patch_state"] == PATCH_STATE_ACCEPTED, rec["patch_state"]
    assert rec["reviewed"] is True


def test_edited_state_when_accept_carries_intrinsic_edits():
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"], ipa="kat")]
    patch = anchored_patch("accept", "cat", "NN", SHAW_A, "RRP",
                           changes={"ipa": "kæt"})
    rec = only_record_for(view_of(entries, [patch]), "cat")
    assert rec["patch_state"] == PATCH_STATE_EDITED, rec["patch_state"]
    assert rec["reviewed"] is True


def test_dirty_state_when_edit_not_yet_accepted():
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"], ipa="kat")]
    patch = anchored_patch("edit", "cat", "NN", SHAW_A, "RRP",
                           changes={"ipa": "kæt"})
    rec = only_record_for(view_of(entries, [patch]), "cat")
    assert rec["patch_state"] == PATCH_STATE_DIRTY, rec["patch_state"]
    # A dirty edit is NOT reviewed: its edits are shown but do not ship.
    assert rec["reviewed"] is False


def test_dropped_state_shows_source_content_still_reviewed():
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"], ipa="kat")]
    patch = anchored_patch("drop", "cat", "NN", SHAW_A, "RRP")
    rec = only_record_for(view_of(entries, [patch]), "cat")
    assert rec["patch_state"] == PATCH_STATE_DROPPED, rec["patch_state"]
    assert rec["reviewed"] is True
    # A drop still DISPLAYS the source content (flagged, not hidden).
    assert rec["ipa"] == "kat"


def test_flagged_state_is_reviewed_but_undecided():
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])]
    patch = anchored_patch("flag", "cat", "NN", SHAW_A, "RRP")
    rec = only_record_for(view_of(entries, [patch]), "cat")
    assert rec["patch_state"] == PATCH_STATE_FLAGGED, rec["patch_state"]
    assert rec["reviewed"] is True


def test_manual_record_with_null_anchor_is_accepted_and_marked_manual():
    # op None: the manual record ships, so its verdict is ACCEPTED; manual-ness
    # is the `manual` origin marker, never a patch_state of its own.
    record = {"word": "newword", "shaw": SHAW_B, "pos": "NN", "var": "RRP",
              "ipa": "nuː"}
    view = view_of([entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])],
                   [authored_patch(record)])
    rec = only_record_for(view, "newword")
    assert rec["patch_state"] == PATCH_STATE_ACCEPTED, rec["patch_state"]
    assert rec["manual"] is True
    assert rec["reviewed"] is True
    # A manual source is normalised to a one-element list.
    assert isinstance(rec["source"], list)


def test_manual_record_created_dirty_is_unreviewed():
    # op "edit": a NEW manual record enters the review queue unreviewed —
    # verdict dirty, reviewed False, still marked manual.
    record = {"word": "newword", "shaw": SHAW_B, "pos": "NN", "var": "RRP"}
    view = view_of([entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])],
                   [authored_patch(record, op="edit")])
    rec = only_record_for(view, "newword")
    assert rec["patch_state"] == PATCH_STATE_DIRTY, rec["patch_state"]
    assert rec["manual"] is True
    assert rec["reviewed"] is False


def test_manual_record_flagged_is_flagged():
    # op "flag": a flagged manual record wears the FLAGGED verdict (it used to be
    # swallowed by the retired blanket "authored" state).
    record = {"word": "newword", "shaw": SHAW_B, "pos": "NN", "var": "RRP"}
    view = view_of([entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])],
                   [authored_patch(record, op="flag")])
    rec = only_record_for(view, "newword")
    assert rec["patch_state"] == PATCH_STATE_FLAGGED, rec["patch_state"]
    assert rec["manual"] is True
    assert rec["reviewed"] is True


def test_basis_rows_carry_no_manual_marker():
    view = view_of([entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])], [])
    assert "manual" not in only_record_for(view, "cat")


def test_authored_row_displays_pool_derived_freq():
    """The #115 fix: an authored row shows the freq the pool pass derived onto
    its base (the authored wing), not the 0 a pre-fix client baked into the
    patch — display and the applicator share basis.authored_freq."""
    record = {"word": "zebra", "shaw": SHAW_B, "pos": "NN", "var": "RRP",
              "freq": 0}
    patches = [authored_patch(record)]
    index, source = basis_of(entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"]))
    bases = authored_pool(patches)
    # Simulate the startup pool pass having enriched the authored base.
    bases[("zebra", "NN", SHAW_B, "RRP")]["freq"] = 4321
    view = AnnotatedView(index, source, patches, bases)
    assert only_record_for(view, "zebra")["freq"] == 4321


def test_authored_row_own_nonzero_freq_wins_over_derived():
    """A patch that asserts its own freq is the last word over the derivation."""
    record = {"word": "zebra", "shaw": SHAW_B, "pos": "NN", "var": "RRP",
              "freq": 9}
    patches = [authored_patch(record)]
    index, source = basis_of(entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"]))
    bases = authored_pool(patches)
    bases[("zebra", "NN", SHAW_B, "RRP")]["freq"] = 4321
    view = AnnotatedView(index, source, patches, bases)
    assert only_record_for(view, "zebra")["freq"] == 9


# ---- accept layering: accept = basis record + intrinsic changes ----

def test_accept_lays_changes_over_basis_not_replacing_untouched_fields():
    # The accept edits only ipa; the basis freq/var/pos must survive unchanged.
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"], ipa="kat", freq=99)]
    patch = anchored_patch("accept", "cat", "NN", SHAW_A, "RRP",
                           changes={"ipa": "kæt"})
    rec = only_record_for(view_of(entries, [patch]), "cat")
    assert rec["ipa"] == "kæt"       # the edit laid over
    assert rec["freq"] == 99          # untouched basis field survives
    assert rec["var"] == "RRP"
    assert rec["status"] == "sanctioned"


def test_flag_is_a_production_no_op_vs_accept():
    # A flag leaves the shown record identical to the untouched basis (no edits, no
    # sanction status), where an accept-as-is stamps it sanctioned.
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"], ipa="kat")]
    flagged = only_record_for(view_of(entries, [anchored_patch(
        "flag", "cat", "NN", SHAW_A, "RRP")]), "cat")
    accepted = only_record_for(view_of(entries, [anchored_patch(
        "accept", "cat", "NN", SHAW_A, "RRP", changes={})]), "cat")
    # Flag shows the raw basis content; its status is the basis default, NOT the
    # accept's "sanctioned" stamp.
    assert flagged["ipa"] == "kat"
    assert flagged["status"] != "sanctioned"
    assert accepted["status"] == "sanctioned"


# ---- orphan sub-classification (the trickiest, audit-flagged) ----

def test_orphan_lost_accept_when_anchor_wholly_vanished():
    # An accept anchored to word/pos/shaw that is NOWHERE in the basis: a lost
    # verdict. Surfaced as orphaned/lost-accept.
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])]
    patch = anchored_patch("accept", "ghost", "NN", SHAW_B, "RSSB")
    rec = only_record_for(view_of(entries, [patch]), "ghost")
    assert rec["patch_state"] == PATCH_STATE_ORPHANED, rec["patch_state"]
    assert rec["orphan_kind"] == ORPHAN_LOST_ACCEPT, rec["orphan_kind"]


def test_orphan_resurfaced_drop_when_same_word_returns_under_different_var():
    # The drop was anchored to shed/RSSB; shed/RRP (same word,pos,shaw, different
    # var) is back in the basis. The suppressed record RESURFACED. The view holds
    # BOTH the live RRP row (unreviewed) AND the synthesized orphan drop row (RSSB)
    # — surfacing the orphan is the whole point; the live record stays visible too.
    entries = [entry("shed", "NN", SHAW_A, "RRP", ["wiktionary"])]
    patch = anchored_patch("drop", "shed", "NN", SHAW_A, "RSSB")
    records = view_of(entries, [patch]).records
    orphans = [rec for rec in records if rec["patch_state"] == PATCH_STATE_ORPHANED]
    assert len(orphans) == 1, orphans
    assert orphans[0]["var"] == "RSSB"
    assert orphans[0]["orphan_kind"] == ORPHAN_RESURFACED_DROP, orphans[0]["orphan_kind"]
    # The relabelled live record is still present under its new var.
    live = [rec for rec in records if rec["patch_state"] == PATCH_STATE_UNREVIEWED]
    assert len(live) == 1 and live[0]["var"] == "RRP", live


def test_satisfied_drop_is_not_surfaced():
    # A drop whose word/pos/shaw is WHOLLY absent from the basis is SATISFIED (the
    # record it wanted gone IS gone) — it must not appear as an orphan.
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])]
    patch = anchored_patch("drop", "ghost", "NN", SHAW_B, "RSSB")
    orphans = [rec for rec in view_of(entries, [patch]).records
               if rec["patch_state"] == PATCH_STATE_ORPHANED]
    assert orphans == [], orphans


def test_vanished_flag_is_not_surfaced():
    # A flag of a vanished anchor shipped nothing and is never a lost verdict.
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])]
    patch = anchored_patch("flag", "ghost", "NN", SHAW_B, "RSSB")
    orphans = [rec for rec in view_of(entries, [patch]).records
               if rec["patch_state"] == PATCH_STATE_ORPHANED]
    assert orphans == [], orphans


# ---- THE invariant: incremental-apply == full-rebuild ----

def test_incremental_apply_equals_full_rebuild_over_same_patches():
    """A sequence of in-place writes must yield a view identical to a from-scratch
    rebuild over the same basis + FINAL patch set. This is the invariant most
    likely to silently break: apply_patch re-annotates one anchor in place, and it
    must reproduce exactly what _build_records would emit for that anchor.

    It is not a tautology: annotate_basis_record threads the anchor, source, and
    novelty through the SAME functions in both paths, but the incremental path
    mutates a shared index (position, word/shaw sub-indexes, orphan handling). A
    regression that, say, appended a re-annotated row instead of replacing it, or
    dropped the novelty badge on the in-place path, would make records diverge and
    fail this test."""
    entries = [
        entry("cat", "NN", SHAW_A, "RRP", ["readlex"], ipa="kat"),
        entry("dog", "NN", SHAW_B, "RRP", ["wiktionary"], ipa="dog"),
        entry("fox", "VB", SHAW_A, "GenAm", ["wordnet"]),
    ]
    authored = {"word": "zebra", "shaw": SHAW_B, "pos": "NN", "var": "RRP",
                "ipa": "zeb"}
    final_patches = [
        anchored_patch("accept", "cat", "NN", SHAW_A, "RRP",
                       changes={"ipa": "kæt"}, pid="p_cat"),
        anchored_patch("drop", "dog", "NN", SHAW_B, "RRP", pid="p_dog"),
        anchored_patch("flag", "fox", "VB", SHAW_A, "GenAm", pid="p_fox"),
        authored_patch(authored, pid="p_zebra"),
    ]

    rebuilt = view_of(copy.deepcopy(entries), copy.deepcopy(final_patches))

    index, source = basis_of(*copy.deepcopy(entries))
    incremental = AnnotatedView(index, source, [], {})
    for patch in copy.deepcopy(final_patches):
        incremental.apply_patch(patch)

    assert incremental.records == rebuilt.records, (
        "incremental view diverged from full rebuild:\n"
        f"  incremental={incremental.records}\n  rebuild={rebuilt.records}")
    assert incremental.by_word_index == rebuilt.by_word_index, (
        f"word index diverged: {incremental.by_word_index} != "
        f"{rebuilt.by_word_index}")
    assert incremental.by_shaw_index == rebuilt.by_shaw_index, (
        f"shaw index diverged: {incremental.by_shaw_index} != "
        f"{rebuilt.by_shaw_index}")


def test_incremental_reversal_matches_rebuild_without_the_patch():
    """Applying then reverting a patch must return the view to the from-scratch
    rebuild with NO patch — the unpatch path is the inverse of the apply path."""
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"], ipa="kat")]
    patch = anchored_patch("accept", "cat", "NN", SHAW_A, "RRP",
                           changes={"ipa": "kæt"})

    clean_rebuild = view_of(copy.deepcopy(entries), [])

    index, source = basis_of(*copy.deepcopy(entries))
    live = AnnotatedView(index, source, [], {})
    live.apply_patch(copy.deepcopy(patch))
    live.apply_unpatch_anchor(patch["anchor"])

    assert live.records == clean_rebuild.records, (
        f"after apply+unpatch: {live.records} != clean {clean_rebuild.records}")


# ---- the word/shaw indexes follow the DISPLAYED record (task #119) ----
# A patch may respell the Latin word (or shaw) while the anchor stays pinned;
# the related read queries with the word the client DISPLAYS, so the indexes
# must be keyed by the effective record, not the anchor.

def test_respelled_word_found_by_displayed_word_at_build():
    entries = [entry("recieve", "VB", SHAW_A, "RRP", ["wiktionary"])]
    patches = [anchored_patch("accept", "recieve", "VB", SHAW_A, "RRP",
                              changes={"word": "receive"})]
    view = view_of(entries, patches)
    assert [r["word"] for r in view.by_word("receive")] == ["receive"]
    assert view.by_word("recieve") == [], "old word must no longer resolve"


def test_respelled_word_found_by_displayed_word_after_apply():
    entries = [entry("recieve", "VB", SHAW_A, "RRP", ["wiktionary"])]
    view = view_of(entries, [])
    view.apply_patch(anchored_patch("accept", "recieve", "VB", SHAW_A, "RRP",
                                    changes={"word": "receive"}))
    assert [r["word"] for r in view.by_word("receive")] == ["receive"]
    assert view.by_word("recieve") == [], "old word must no longer resolve"
    # The pinned ANCHOR still finds the row — anchor lookups are untouched.
    row = view.by_anchor(("recieve", "VB", SHAW_A, "RRP"))
    assert [r["word"] for r in row] == ["receive"]


def test_case_only_edit_resolves_under_both_cases():
    """Regression lock on the owner's `i` -> `I` fix: a case-only respell keeps
    resolving (anchor words and queries are both lowercased, so the displayed
    word and the anchor word coincide once lowercased)."""
    entries = [entry("i", "PPSS", SHAW_A, "RRP", ["readlex"])]
    view = view_of(entries, [])
    view.apply_patch(anchored_patch("accept", "i", "PPSS", SHAW_A, "RRP",
                                    changes={"word": "I"}))
    assert [r["word"] for r in view.by_word("I")] == ["I"]
    assert [r["word"] for r in view.by_word("i")] == ["I"]


def test_word_index_stays_clean_across_edit_revert_remove():
    """No stale registrations across a mutation sequence: respell, respell back,
    revert the patch, and (for an authored row) remove entirely."""
    key = ("recieve", "VB", SHAW_A, "RRP")
    entries = [entry("recieve", "VB", SHAW_A, "RRP", ["wiktionary"])]
    view = view_of(entries, [])

    view.apply_patch(anchored_patch("accept", "recieve", "VB", SHAW_A, "RRP",
                                    changes={"word": "receive"}))
    assert view.by_word_index == {"receive": {key}}

    view.apply_patch(anchored_patch("accept", "recieve", "VB", SHAW_A, "RRP"))
    assert view.by_word_index == {"recieve": {key}}

    view.apply_unpatch_anchor(anchor("recieve", "VB", SHAW_A, "RRP"))
    assert view.by_word_index == {"recieve": {key}}

    view.apply_patch(authored_patch({"word": "Zebra", "shaw": SHAW_B,
                                     "pos": "NN", "var": "RRP"}, pid="p_z"))
    assert [r["word"] for r in view.by_word("zebra")] == ["Zebra"]
    view.apply_unpatch_id("p_z")
    assert view.by_word("zebra") == []
    assert view.by_word_index == {"recieve": {key}}
    assert view.by_shaw_index == {SHAW_A: {key}}


def test_respelled_shaw_found_by_displayed_spelling():
    """The shaw index mirrors the word index: an edit that respells the Shavian
    re-files the anchor under the spelling the client displays."""
    entries = [entry("cat", "NN", SHAW_A, "RRP", ["wiktionary"])]
    view = view_of(entries, [])
    view.apply_patch(anchored_patch("accept", "cat", "NN", SHAW_A, "RRP",
                                    changes={"shaw": SHAW_B}))
    assert [r["shaw"] for r in view.by_shaw(SHAW_B)] == [SHAW_B]
    assert view.by_shaw(SHAW_A) == [], "old spelling must no longer resolve"


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
