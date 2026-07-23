#!/usr/bin/env python3
"""
The definitions index: a read-only, word-keyed view of the definitions corpus for
the editor's inline sense summary (docs/definitions-editor-design.md §5b, phase P2).

The corpus is split across two files per dialect, joined on the identical
`lemma|synset` key:
    data/definitions-latin-{gb,us}.json     SOURCE   (English gloss, POS, examples)
    data/definitions-shavian-{gb,us}.json    DERIVED  (Shavian transliteration)

This is a SEPARATE index from the annotated basis (overlay.py). The basis is the
reviewable dictionary the owner edits; the definitions corpus is machine-produced
gloss data the editor merely SHOWS beside a word. Keeping them apart means loading
the corpus never touches the basis, and the read-only view can never mutate a patch
or a record.

Corpus shapes (per dialect):
    latin[key]   -> {definition,                # English gloss
                     pos,                        # WordNet POS tag (n/v/a/r/s, or n-1 …)
                     examples[, source][, confidence]}
    shavian[key] -> {transliterated_definition,  # Shavian transliteration of the gloss
                     transliterated_pos,         # Shavian transliteration of the POS word
                     transliterated_examples}    # (design drops examples — ignored)

The design (§6a owner decisions) scopes the editor to the SHAVIAN definitions
only and to per-sense senses; examples are dropped ("we want definitions not
examples"). So this index carries, per sense: the English gloss, the Shavian
transliterated_definition, the POS tag, and the Shavian transliterated_pos.

gb/us handling (§6 Q1, my lean (c) — confirmed as the build's default): the two
dialect files carry the SAME sense keys and identical glosses; only the Shavian
transliteration diverges (~18% of senses). So a sense is presented ONCE, and the
US Shavian is attached only where it genuinely differs from the GB Shavian —
"one view, both shown only on divergence". The English gloss and POS are shared.

Source provenance (owner, 2026-07-19): each sense carries a `source` so a reviewer
can distinguish a machine-generated gloss from a WordNet/Wiktionary one and judge
trust. The Shavian corpus itself carries NO source field, but its key IS the
signal: every key's synset is a WordNet synset offset (########-x — verified: 100%
of the ~88K keys), so every sense in the corpus today is WordNet-derived. Provenance
is therefore DERIVED from the synset-id shape (see _sense_source): a WordNet offset
=> "wordnet"; a future generated/function-word batch or Wiktionary transliteration
would carry a non-offset synset id and classify accordingly (extensible without a
schema change to the corpus).

Editing (§5c): a correction targets ONE dialect's transliteration. The index keeps
BOTH dialects' raw Shavian per sense (shaw by dialect), so a correction to "us"
targets the US string even when it currently equals GB; the UI-facing shaw_gb /
shaw_us (US only on divergence) is derived from these on serialisation. correct()
overlays a definition patch onto the matching sense in place.
"""

import json
import re
import threading
from pathlib import Path

from basis import PROJECT_ROOT

LATIN_GB_PATH = PROJECT_ROOT / "data" / "definitions-latin-gb.json"
LATIN_US_PATH = PROJECT_ROOT / "data" / "definitions-latin-us.json"
SHAVIAN_GB_PATH = PROJECT_ROOT / "data" / "definitions-shavian-gb.json"
SHAVIAN_US_PATH = PROJECT_ROOT / "data" / "definitions-shavian-us.json"

# A WordNet synset offset: 8 digits, a dash, and a POS letter (n/v/a/s/r). Every
# key in the Shavian corpus today matches this, so every sense is WordNet-derived.
# The discriminator the owner wants: a future generated/function-word batch or a
# Wiktionary transliteration would carry a synset id that does NOT match this, and
# classify as its own source below.
_WORDNET_SYNSET = re.compile(r"[0-9]{8}-[nvasr]$")

SOURCE_WORDNET = "wordnet"
SOURCE_GENERATED = "generated"


def _sense_source(synset):
    """The provenance of a sense, DERIVED from its synset id (the corpus carries no
    source field). A WordNet synset offset => "wordnet"; anything else is treated as
    a generated/drafted gloss => "generated" (the function-word batch the design
    anticipates would land here). This is the trust discriminator the reviewer sees;
    it is derived, never stored in the corpus."""
    return SOURCE_WORDNET if _WORDNET_SYNSET.match(synset or "") else SOURCE_GENERATED


def _split_key(key):
    """The (headword, synset-id) of a corpus key `word|synset-id`. The headword is
    returned as-is (its case varies in the corpus — CAT vs cat); the caller
    lowercases for indexing. Fails loud on a malformed key rather than silently
    dropping a sense."""
    word, sep, synset = key.partition("|")
    if not sep:
        raise ValueError(f"malformed definitions key (no '|'): {key!r}")
    return word, synset


def _sense(word_lower, synset, latin_entry, gb_shaw, us_shaw):
    """One internal sense, joining the Latin source (English gloss/POS, shared across
    dialects) with the per-dialect Shavian transliterations. The Shavian gloss is kept
    RAW PER DIALECT in `shaw` (a {gb, us} map) so a correction can target one dialect
    even when the two currently match. The UI-facing shape (shaw_gb, shaw_us only on
    divergence) is derived on demand by _serialise_sense. Empty strings are normalised
    to None (the "absent" signal the view renders as a coverage gap). `word_lower` is
    retained as the anchor's word.

    Note: the internal sense is a mutable working copy the overlay corrects in
    place; `_serialise_sense` produces the read-only public shape the daemon
    returns, never the internal object."""
    gb_shaw_def = _clean(gb_shaw.get("transliterated_definition", ""))
    us_shaw_def = _clean(us_shaw.get("transliterated_definition", "")) if us_shaw else None
    # The Shavian POS is shared across dialects (static POS map); take it from GB.
    shaw_pos = _clean(gb_shaw.get("transliterated_pos", ""))
    return {
        "word_lower": word_lower,
        "synset": synset,
        "gloss": latin_entry.get("definition", ""),
        "pos": latin_entry.get("pos", ""),
        "shaw_pos": shaw_pos,
        "source": _sense_source(synset),
        "shaw": {"gb": gb_shaw_def, "us": us_shaw_def},
        # The PRISTINE machine transliteration per dialect, never mutated. `shaw` is
        # the working copy the overlay corrects; `_pristine` lets revert() restore
        # the original when a correction is removed, without re-reading the corpus.
        "_pristine": {"gb": gb_shaw_def, "us": us_shaw_def},
    }


def _serialise_sense(sense):
    """The public UI shape of an internal sense. The GB Shavian is `shaw_gb`; the US
    Shavian (`shaw_us`) is attached ONLY when it genuinely differs from GB, so the
    view shows a single line where they match ("one view, both shown only on
    divergence"). `source` is the derived provenance the reviewer sees. This reads
    the possibly-corrected `shaw` map, so an overlaid correction shows through."""
    shaw_gb = sense["shaw"]["gb"]
    shaw_us_raw = sense["shaw"]["us"]
    shaw_us = shaw_us_raw if shaw_us_raw != shaw_gb else None
    return {
        "synset": sense["synset"],
        "gloss": sense["gloss"],
        "pos": sense["pos"],
        "shaw_pos": sense["shaw_pos"],
        "source": sense["source"],
        "shaw_gb": shaw_gb,
        "shaw_us": shaw_us,
    }


def _clean(value):
    """A corpus string normalised for the UI: stripped, and an empty string mapped
    to None (the "absent" signal the view renders as a coverage gap)."""
    if value is None:
        return None
    value = value.strip()
    return value or None


class DefinitionsIndex:
    """The Shavian definitions corpus indexed by lowercased headword -> [internal
    senses]. Loaded once at daemon startup. The definition-patch overlay corrects
    senses in place (correct()); after that the index is read-only for the daemon's
    lifetime. A lock guards reads/corrections for uniformity with the rest of the
    daemon."""

    def __init__(self, by_word):
        self._by_word = by_word
        self._lock = threading.Lock()

    def senses(self, word):
        """The senses for `word` (case-insensitive), each in the public UI shape
        (source + shaw_gb, shaw_us only on divergence). An empty list when the
        corpus holds no definition for the word — the coverage gap the view renders
        as "no definition". Reflects any overlaid correction."""
        with self._lock:
            return [_serialise_sense(s) for s in self._by_word.get(word.lower(), ())]

    def _find(self, word, synset):
        """The internal sense matching (lowercased word, synset), or None. Caller
        holds the lock."""
        for sense in self._by_word.get((word or "").lower(), ()):
            if sense["synset"] == synset:
                return sense
        return None

    def correct(self, anchor, changes):
        """Overlay one definition-patch correction onto the matching sense IN PLACE:
        set the anchored dialect's Shavian to changes["shaw"]. Returns True when the
        anchor resolved to a sense and the correction applied, or False when it
        resolved to NOTHING (an orphan — the corpus drifted). Never raises on a
        missing sense (soft-fail is the caller's to record); fails loud only on a
        malformed anchor (bad dialect / missing field), which is a bug, not drift."""
        dialect = anchor.get("dialect")
        if dialect not in ("gb", "us"):
            raise ValueError(f"definition anchor dialect must be gb/us: {anchor!r}")
        word, synset = anchor.get("word"), anchor.get("synset")
        if not word or not synset:
            raise ValueError(f"definition anchor missing word/synset: {anchor!r}")
        shaw = changes.get("shaw")
        with self._lock:
            sense = self._find(word, synset)
            if sense is None:
                return False
            sense["shaw"][dialect] = _clean(shaw)
            return True

    def revert(self, anchor):
        """Undo a correction on the anchored sense: restore the anchored dialect's
        Shavian to its PRISTINE machine transliteration. Returns True when the
        anchor resolved to a sense, else False (the sense is gone — a benign no-op,
        the correction it undid was already an orphan). Fails loud on a malformed
        anchor."""
        dialect = anchor.get("dialect")
        if dialect not in ("gb", "us"):
            raise ValueError(f"definition anchor dialect must be gb/us: {anchor!r}")
        word, synset = anchor.get("word"), anchor.get("synset")
        with self._lock:
            sense = self._find(word, synset)
            if sense is None:
                return False
            sense["shaw"][dialect] = sense["_pristine"][dialect]
            return True


def _require(path):
    """Load a definitions file, failing LOUD if it is missing (project rule: no
    silent fallback). A missing corpus is a deployment error the owner must see,
    not a degraded-but-quiet editor."""
    if not path.exists():
        raise FileNotFoundError(
            f"definitions corpus missing: {path} — the definitions viewer "
            "requires data/definitions-{latin,shavian}-{gb,us}.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_definitions_index():
    """Build the word-keyed definitions index by joining the Latin source (English
    gloss/POS) with the per-dialect Shavian transliterations on the identical
    `lemma|synset` key.

    The GB Latin source drives the key set (both dialects' Latin files carry the same
    keys). The Shavian transliteration is looked up per key per dialect; a key present
    in Latin but absent from a Shavian file is tolerated (that dialect's Shavian is
    simply omitted) — a benign data condition, not a fallback around a precondition."""
    latin = _require(LATIN_GB_PATH)
    gb_shaw = _require(SHAVIAN_GB_PATH)
    us_shaw = _require(SHAVIAN_US_PATH)

    by_word = {}
    for key, latin_entry in latin.items():
        word, synset = _split_key(key)
        word_lower = word.lower()
        sense = _sense(word_lower, synset, latin_entry,
                       gb_shaw.get(key, {}), us_shaw.get(key))
        by_word.setdefault(word_lower, []).append(sense)
    return DefinitionsIndex(by_word)
