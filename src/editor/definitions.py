#!/usr/bin/env python3
"""
The definitions index: a read-only, word-keyed view of the Shavian definitions
corpus (data/definitions-shavian-{gb,us}.json) for the editor's inline sense
summary (docs/definitions-editor-design.md §5b, phase P2).

This is a SEPARATE index from the annotated basis (overlay.py). The basis is the
reviewable dictionary the owner edits; the definitions corpus is machine-produced
gloss data the editor merely SHOWS beside a word. Keeping them apart means loading
the ~88K-key corpus never touches the basis, and the read-only view can never
mutate a patch or a record.

Corpus shape (per dialect file):
    "word|synset-id" -> {
        definition,                 # English gloss
        transliterated_definition,  # Shavian transliteration of the gloss
        pos,                        # WordNet POS tag (n/v/a/r/s, or n-1 …)
        transliterated_pos,         # Shavian transliteration of the POS word
        examples, transliterated_examples,  # (design drops examples — ignored)
    }

The design (§6a owner decisions) scopes the editor to the SHAVIAN definitions
only and to per-sense senses; examples are dropped ("we want definitions not
examples"). So this index carries, per sense: the English gloss, the Shavian
transliterated_definition, the POS tag, and the Shavian transliterated_pos.

gb/us handling (§6 Q1, my lean (c) — confirmed as the build's default): the two
dialect files carry the SAME sense keys and identical glosses; only the Shavian
transliteration diverges (~18% of senses). So a sense is presented ONCE, and the
US Shavian is attached only where it genuinely differs from the GB Shavian —
"one view, both shown only on divergence". The English gloss and POS are shared.
"""

import json
import threading
from pathlib import Path

from basis import PROJECT_ROOT

DEFINITIONS_GB_PATH = PROJECT_ROOT / "data" / "definitions-shavian-gb.json"
DEFINITIONS_US_PATH = PROJECT_ROOT / "data" / "definitions-shavian-us.json"


def _split_key(key):
    """The (headword, synset-id) of a corpus key `word|synset-id`. The headword is
    returned as-is (its case varies in the corpus — CAT vs cat); the caller
    lowercases for indexing. Fails loud on a malformed key rather than silently
    dropping a sense."""
    word, sep, synset = key.partition("|")
    if not sep:
        raise ValueError(f"malformed definitions key (no '|'): {key!r}")
    return word, synset


def _sense(synset, gb_entry, us_entry):
    """One sense in the UI shape, merging the gb and us corpus entries for the same
    key. The English gloss, POS tag and Shavian POS are shared (identical across
    dialects); the Shavian gloss is carried as `shaw_gb`, with `shaw_us` attached
    ONLY when the US transliteration genuinely differs (else null — the view shows
    a single Shavian). Empty strings are normalised to None so the UI's
    "no transliteration yet" state is a simple null check."""
    gloss = gb_entry.get("definition", "")
    pos = gb_entry.get("pos", "")
    shaw_pos = _clean(gb_entry.get("transliterated_pos", ""))
    shaw_gb = _clean(gb_entry.get("transliterated_definition", ""))
    shaw_us_raw = _clean(us_entry.get("transliterated_definition", "")) if us_entry else None
    shaw_us = shaw_us_raw if shaw_us_raw != shaw_gb else None
    return {
        "synset": synset,
        "gloss": gloss,
        "pos": pos,
        "shaw_pos": shaw_pos,
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
    """The Shavian definitions corpus indexed by lowercased headword -> [senses].
    Loaded once at daemon startup, read-only for the daemon's lifetime. A lock
    guards reads for uniformity with the rest of the daemon, though the index is
    never mutated after construction."""

    def __init__(self, by_word):
        self._by_word = by_word
        self._lock = threading.Lock()

    def senses(self, word):
        """The senses for `word` (case-insensitive), each in UI shape. An empty
        list when the corpus holds no definition for the word — the coverage gap
        the view renders as "no definition"."""
        with self._lock:
            return list(self._by_word.get(word.lower(), ()))


def _require(path):
    """Load a definitions file, failing LOUD if it is missing (project rule: no
    silent fallback). A missing corpus is a deployment error the owner must see,
    not a degraded-but-quiet editor."""
    if not path.exists():
        raise FileNotFoundError(
            f"definitions corpus missing: {path} — the definitions viewer "
            "requires data/definitions-shavian-{gb,us}.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_definitions_index():
    """Build the word-keyed definitions index from the gb and us Shavian corpora.

    Both files carry the SAME sense keys (verified: identical key sets); the us
    entry is looked up per key to attach a divergent US Shavian where present. A
    key in gb but absent from us is tolerated (the US Shavian is simply omitted for
    that sense) — a benign data condition, not a fallback around a precondition."""
    gb = _require(DEFINITIONS_GB_PATH)
    us = _require(DEFINITIONS_US_PATH)

    by_word = {}
    for key, gb_entry in gb.items():
        word, synset = _split_key(key)
        sense = _sense(synset, gb_entry, us.get(key))
        by_word.setdefault(word.lower(), []).append(sense)
    return DefinitionsIndex(by_word)
