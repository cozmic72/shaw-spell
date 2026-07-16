#!/usr/bin/env python3
"""
The annotated view: the basis with every record labelled by its patch-state.

This is the one non-trivial piece of the editor (see
docs/editorial-overlay-design.md). It overlays data/patches/patches.jsonl on
the basis, resolving each patch's `anchor` against the basis by the SAME natural
key (word, pos, shaw, var) the applicator uses — imported from src/tools/basis.py,
never re-implemented here.

Under the settled model a patch's `record` is complete and authoritative, so an
annotated row's DISPLAYED content is simply the patch's `record` when a patch
exists on its anchor, else the untouched source record. There is no source+patch
merge — that merge was the source of the "edit invisible in the UI" bug.

Each annotated record carries the displayed content (word/shaw/pos/ipa/freq/var
plus provenance), its stable `anchor` (immutable identity, so an edited row never
moves), a `reviewed` flag (a patch exists — the primary filter partition), and a
`patch_state` for the ledger stamp:

    unreviewed  no patch resolves to this anchor
    edited      a patch supplies a record (accept / edit / respell)
    dropped     a patch drops it (record is null)
    authored    a standalone record no basis anchor attests (anchor is null)

`dropped` rows still DISPLAY the source content (flagged, not hidden — the editor
must see a drop to roll it back). `authored` rows are not in the basis; they are
synthesized into the view so the editor sees everything a human has ruled on.
"""

from basis import anchor_key, build_basis, output_to_record

PATCH_STATE_UNREVIEWED = "unreviewed"
PATCH_STATE_EDITED = "edited"
PATCH_STATE_DROPPED = "dropped"
PATCH_STATE_AUTHORED = "authored"

UPSTREAM_STATUS = "sanctioned"
SUPPLEMENT_STATUS = "supplement"
AUTHORED_STATUS = "manual"


def _ui_record(record, anchor, source, default_status, reviewed, patch_state, patch):
    """One annotated row in the UI record shape (word/shaw/...). Provenance the
    record carries (source/status/confidence) wins; the origin-derived defaults
    stand in otherwise.

    `anchor` is the record's stable natural key {word, pos, shaw, var}. It never
    changes when the record is edited, so an edited row keeps its place and is
    still found by the anchor the patch was written against."""
    return {
        "word": record.get("word", ""),
        "shaw": record.get("shaw", ""),
        "pos": record.get("pos", ""),
        "ipa": record.get("ipa", ""),
        "freq": record.get("freq", 0),
        "var": record.get("var", ""),
        "source": record.get("source", source),
        "confidence": record.get("confidence"),
        "status": record.get("status", default_status),
        "anchor": anchor,
        "reviewed": reviewed,
        "patch_state": patch_state,
        "patch": patch,
    }


def annotate_basis_record(candidate, source, patch):
    """One annotated row for a basis candidate under its overlaid patch.

    Unpatched: displays the source record, unreviewed. Patched with a record:
    displays that record (accept/edit/respell), reviewed. Patched to a drop:
    displays the source record, flagged dropped."""
    anchor = {"word": candidate["Latn"], "pos": candidate["pos"],
              "shaw": candidate["Shaw"], "var": candidate.get("var", "")}
    default_status = UPSTREAM_STATUS if source == "readlex" else SUPPLEMENT_STATUS

    if patch is None:
        shown, reviewed, state = output_to_record(candidate), False, PATCH_STATE_UNREVIEWED
    elif patch["record"] is None:
        shown, reviewed, state = output_to_record(candidate), True, PATCH_STATE_DROPPED
    else:
        shown, reviewed, state = patch["record"], True, PATCH_STATE_EDITED

    return _ui_record(shown, anchor, source, default_status, reviewed, state, patch)


def annotate_authored_record(patch):
    """One annotated row from an authorship patch (anchor is null): the record a
    human invented, which has no basis anchor. Its displayed content IS the
    record; its stable anchor is that record's own natural key."""
    record = patch["record"]
    anchor = {"word": record["word"], "pos": record["pos"],
              "shaw": record["shaw"], "var": record.get("var", "")}
    return _ui_record(record, anchor, record.get("source", AUTHORED_STATUS),
                      AUTHORED_STATUS, True, PATCH_STATE_AUTHORED, patch)


class AnnotatedView:
    """The basis overlaid with the patch store. Loaded once; filtered in memory
    per request. Rebuilt only when patches change."""

    def __init__(self, basis_index, basis_source, patches):
        self.records = _build_records(basis_index, basis_source, patches)

    def by_anchor(self, key):
        return [r for r in self.records if anchor_key(r["anchor"]) == key]


def _index_patches_by_anchor(patches):
    """Map (word_lower, pos, shaw, var) -> patch, for patches acting on the basis
    (anchor present). Authorship patches (anchor null) are returned separately."""
    anchored = {}
    authored = []
    for patch in patches:
        if patch["anchor"] is None:
            authored.append(patch)
        else:
            anchored[anchor_key(patch["anchor"])] = patch
    return anchored, authored


def _build_records(basis_index, basis_source, patches):
    anchored, authored = _index_patches_by_anchor(patches)

    records = []
    for key, candidate in basis_index.items():
        records.append(
            annotate_basis_record(candidate, basis_source[key], anchored.get(key)))

    for patch in authored:
        records.append(annotate_authored_record(patch))

    return records


def load_view():
    """Build the annotated view from the current basis and patch store."""
    from patchstore import load_patches

    basis_index, basis_source = build_basis()
    return AnnotatedView(basis_index, basis_source, load_patches())
