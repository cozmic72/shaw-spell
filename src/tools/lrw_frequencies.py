#!/usr/bin/env python3
"""BNC1994 Leech/Rayson/Wilson (LRW) POS-frequency list: parser + C5 mapping.

Loads data/bncfreq/1_1_all_fullalpha.txt (kept verbatim; see the README there)
into the two structures the frequency stage's POS-split pass consumes
(apply_frequency_data.py):

  surface_readings: lookup key -> {lrw_tag: per_million}
      Every surface form the list attests — lemma rows AND their inflected
      continuation rows — with its per-POS frequency readings.
  parent_lemmas: continuation-form key -> {parent lemma key, ...}
      Which lemma(s) a surface form was filed under, for lemma-ratio
      inheritance when the surface's own readings cannot discriminate.

File facts the parser encodes (all verified against the shipped file):
  - latin-1 encoded; tab-separated; exactly 7 columns:
    [blank, word, PoS, form/marker, perMillion, range, dispersion].
    The shipped file parses completely clean, so ANY malformed row aborts the
    load: a deviation means corruption or a changed upstream re-download,
    exactly what must be noticed rather than skipped over.
  - A row with word=="@" and pos=="@" is a CONTINUATION row: the marker column
    holds an inflected surface form, which inherits the PRECEDING lemma row's
    POS and carries its OWN perMillion. 116,560 of the 794,771 rows are
    continuations and they are load-bearing for surface coverage.
  - Accented words are stored as HTML entities (&aacute; etc., 50,745 rows),
    so every word/form is html.unescape()d before anything else.
  - perMillion 0 means "attested below 0.5 per million", NOT unattested — a
    0 reading is kept (the surface exists) but carries no usable magnitude.

Lookup keys are html-unescaped, lowercased, accent-stripped (NFD-decompose,
drop combining marks). LRW capitalisation encodes proper-noun-hood only (the
pronoun I is stored as lowercase `i`), so case variants of one surface MUST
merge: their per-POS readings union into one entry, duplicate (key, tag)
readings keeping the max per_million.
"""

import html
import sys
import unicodedata
from collections import namedtuple

from basis import PROJECT_ROOT

LRW_PATH = PROJECT_ROOT / "data" / "bncfreq" / "1_1_all_fullalpha.txt"

# Columns of a well-formed row (leading tab yields an empty first field).
_LRW_COLUMNS = 7

# BNC C5 base tag -> acceptable LRW coarse tags. None marks degenerate C5 tags
# (typos/degenerates in our data) that never resolve. This is the final map
# validated by the join analysis — including the DetP/Neg/Ex/Inf/Gen/ClO
# refinements — ported verbatim; do not "simplify" it.
C5_TO_LRW = {
    'NN0': {'NoC'}, 'NN1': {'NoC'}, 'NN2': {'NoC'}, 'NP0': {'NoP'},
    'AJ0': {'Adj'}, 'AJC': {'Adj'}, 'AJS': {'Adj'},
    'AV0': {'Adv'}, 'AVP': {'Adv', 'Prep'}, 'AVQ': {'Adv'},
    'VVB': {'Verb'}, 'VVD': {'Verb'}, 'VVG': {'Verb'}, 'VVI': {'Verb'},
    'VVN': {'Verb'}, 'VVZ': {'Verb'},
    'VBB': {'Verb'}, 'VBD': {'Verb'}, 'VBG': {'Verb'}, 'VBI': {'Verb'},
    'VBN': {'Verb'}, 'VBZ': {'Verb'},
    'VDB': {'Verb'}, 'VDD': {'Verb'}, 'VDG': {'Verb'}, 'VDI': {'Verb'},
    'VDN': {'Verb'}, 'VDZ': {'Verb'},
    'VHB': {'Verb'}, 'VHD': {'Verb'}, 'VHG': {'Verb'}, 'VHI': {'Verb'},
    'VHN': {'Verb'}, 'VHZ': {'Verb'},
    'VM0': {'VMod'},
    'PNP': {'Pron'}, 'PNI': {'Pron', 'DetP'}, 'PNQ': {'Pron'}, 'PNX': {'Pron'},
    'DT0': {'Det', 'DetP'}, 'DTQ': {'Det', 'DetP', 'Pron'}, 'DPS': {'Det'},
    'AT0': {'Det'},
    'PRP': {'Prep'}, 'PRF': {'Prep'},
    'CJC': {'Conj'}, 'CJS': {'Conj', 'ClO'}, 'CJT': {'Conj'},
    'ITJ': {'Int'}, 'INT': {'Int'},
    'CRD': {'Num'}, 'ORD': {'Num', 'Adj'},
    'ZZ0': {'Lett'},
    'EX0': {'Ex'}, 'TO0': {'Inf'}, 'XX0': {'Neg'}, 'POS': {'Gen'},
    'UNC': {'Uncl', 'Fore', 'Form'},
    'PRE': None, 'P0': None, 'NPO': None,
}

# LRW catch-all classes the join analysis proved are spurious as POS evidence
# (unclassified / foreign / erroneous / formulaic tokens): a reading in one of
# these says nothing about which of OUR records the frequency belongs to, so
# they are excluded from ALL weight computation.
UNINFORMATIVE_LRW_TAGS = frozenset({"Uncl", "Fore", "Err", "Form"})

LrwData = namedtuple("LrwData", ["surface_readings", "parent_lemmas"])


def _deacc(text):
    """Strip accents: NFD-decompose and drop combining marks."""
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(c))


def lrw_key(word):
    """The ONE lookup-key normalisation, applied to LRW surfaces at load time
    and to headwords at join time: lowercase + accent-strip. (LRW words are
    html-unescaped before this; headwords carry no entities.)"""
    return _deacc(word.lower())


def load_lrw(path=LRW_PATH):
    """Parse the LRW list into LrwData. Fails loud on a missing or empty file,
    and on ANY malformed row — the shipped list parses clean, so a deviation
    means file corruption or a changed upstream re-download."""
    if not path.exists():
        sys.exit(
            f"LRW frequency list not found at {path}.\n"
            "Download https://ucrel.lancs.ac.uk/bncfreq/lists/"
            "1_1_all_fullalpha.zip (4.4 MB) and unzip its single file "
            "1_1_all_fullalpha.txt to that location.")

    surface_readings = {}
    parent_lemmas = {}
    malformed = 0

    def add_reading(key, tag, per_million):
        readings = surface_readings.setdefault(key, {})
        # Case variants of one surface merge here; duplicate (key, tag)
        # readings keep the max per_million (the dominant casing's figure).
        if per_million > readings.get(tag, -1):
            readings[tag] = per_million

    current_lemma_key = None
    current_pos = None
    with open(path, "r", encoding="latin-1") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != _LRW_COLUMNS:
                malformed += 1
                continue
            _, word, pos, marker, per_million, _range, _dispersion = parts
            if word == "@" and pos == "@":
                if current_lemma_key is None:
                    malformed += 1  # continuation before any lemma row
                    continue
                key = lrw_key(html.unescape(marker))
                add_reading(key, current_pos, int(per_million))
                if key != current_lemma_key:
                    parent_lemmas.setdefault(key, set()).add(current_lemma_key)
            else:
                key = lrw_key(html.unescape(word))
                current_lemma_key, current_pos = key, pos
                add_reading(key, pos, int(per_million))

    if malformed:
        sys.exit(
            f"LRW frequency list at {path}: {malformed} malformed row(s). "
            "The shipped file parses clean, so this means corruption or a "
            "changed upstream re-download. Re-fetch https://ucrel.lancs.ac.uk/"
            "bncfreq/lists/1_1_all_fullalpha.zip and unzip 1_1_all_fullalpha.txt "
            "to that location.")
    if not surface_readings:
        sys.exit(f"LRW frequency list at {path} parsed to empty.")
    return LrwData(surface_readings, parent_lemmas)
