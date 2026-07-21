#!/usr/bin/env python3
"""
Fill missing `ipa` on the names supplement from CMUdict (ARPABET -> house IPA).

The names slice (data/supplement-names.json) carries Shaw but no IPA: the import
voted shave against CMUdict on Shavian only. CMUdict is an INDEPENDENT,
real-stress pronunciation source and ARPABET -> IPA is near-mechanical, so for
names CMU knows we can derive high-fidelity house IPA (capital-R rhotic
compounds, ˈ/ˌ stress) rather than wait for the owner-gated neural model.

COHERENCE GUARD — this feeds the dictionary, so only confirmed IPA ships: a
derived IPA is written ONLY if forward-converting it through ipa_to_shavian
reproduces the record's existing Shaw (independent round-trip confirmation).
Selection is deterministic: pronunciations are tried in CMU dict order, each
fanned over its ARPABET->house ambiguity sites preferred-first (candidate_ipas),
and the FIRST candidate whose Shaw matches wins. No match (or no CMU entry)
means the record keeps no `ipa` — nothing is invented. Filled records carry
`ipa_source: "cmu"` (mirroring the shaw_source provenance pattern).

It sits as an additive pre-combine pass on the names pool, mirroring where
rescued/neardot sit for wiktionary:

    supplement-names.json -> HERE (names-ipa) -> combine -> ... -> basis

Inputs:  data/supplement-names.json, external/cmudict/cmudict.dict.
Outputs: data/supplement-names-ipa.json — the names pool with confirmed IPA
         filled. supplement-names.json is left untouched.

Usage:
    python3 src/tools/fill_names_ipa.py
"""

import json
import re
import sys
from collections import Counter
from itertools import islice, product

from basis import PROJECT_ROOT
from ipa_to_shavian import ipa_to_shavian

NAMES_INPUT = PROJECT_ROOT / "data" / "supplement-names.json"
NAMES_IPA_OUTPUT = PROJECT_ROOT / "data" / "supplement-names-ipa.json"
CMUDICT_PATH = PROJECT_ROOT / "external" / "cmudict" / "cmudict.dict"

# ARPABET -> house IPA (ReadLex conventions: capital R for the rhotic-optional
# r, RRP vowel qualities). Covers the full 39-phone inventory in
# external/cmudict/cmudict.phones; stress digits are handled separately.
ARPABET_VOWELS = {
    "AA": "ɒ",   # father-bother merged in CMU; ɑːR when fused with R below
    "AE": "æ", "AH": "ʌ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "EH": "e", "ER": "ɜːR", "EY": "eɪ", "IH": "ɪ", "IY": "iː",
    "OW": "əʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "uː",
}
ARPABET_CONSONANTS = {
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ",
    "HH": "h", "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n",
    "NG": "ŋ", "P": "p", "R": "r", "S": "s", "SH": "ʃ", "T": "t",
    "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}
# vowel + R fusions to the house r-compounds (rhotic RRP)
R_FUSIONS = {
    "AA": "ɑːR", "AO": "ɔːR", "EH": "eəR", "IH": "ɪəR", "IY": "ɪəR",
    "UH": "ʊəR", "EY": "eəR",
}

PRIMARY_STRESS, SECONDARY_STRESS = "1", "2"
STRESS_MARKS = {PRIMARY_STRESS: "ˈ", SECONDARY_STRESS: "ˌ"}
MAX_CANDIDATES = 64

# Legal English syllable onsets (house IPA phonemes), for placing stress marks
# at the syllable boundary: a stress mark goes before the LONGEST legal onset
# preceding the stressed vowel (maximal onset principle). A naive "walk back
# over all consonants" walk mis-splits clusters like exhibit -> ɪˈɡzɪbɪt (ɡz is
# not a legal onset; house has ɪɡˈzɪbɪt). Tuples of phoneme pieces, since tʃ/dʒ
# are single phonemes.
LEGAL_ONSET_CLUSTERS = {
    ("p", "l"), ("p", "r"), ("p", "j"), ("b", "l"), ("b", "r"), ("b", "j"),
    ("t", "r"), ("t", "w"), ("t", "j"), ("d", "r"), ("d", "w"), ("d", "j"),
    ("k", "l"), ("k", "r"), ("k", "w"), ("k", "j"),
    ("ɡ", "l"), ("ɡ", "r"), ("ɡ", "w"), ("ɡ", "j"),
    ("f", "l"), ("f", "r"), ("f", "j"), ("v", "j"),
    ("θ", "r"), ("θ", "w"), ("θ", "j"),
    ("s", "l"), ("s", "m"), ("s", "n"), ("s", "p"), ("s", "t"), ("s", "k"),
    ("s", "w"), ("s", "f"), ("s", "j"), ("ʃ", "r"),
    ("m", "j"), ("n", "j"), ("l", "j"), ("h", "j"),
    ("s", "p", "l"), ("s", "p", "r"), ("s", "p", "j"),
    ("s", "t", "r"), ("s", "t", "j"),
    ("s", "k", "l"), ("s", "k", "r"), ("s", "k", "w"), ("s", "k", "j"),
}
MAX_ONSET_LEN = 3


def _vowel_alternatives(base, digit):
    """House-IPA readings of one ARPABET vowel, preferred first.

    Qualities follow the reduced/full split CMU encodes in the stress digit
    (AH0 -> ə, IY0/IH0 -> happy/kit weak vowels). Where American ARPABET
    genuinely underdetermines the house vowel — AO covers THOUGHT and
    CLOTH/LOT, AA is father-bother merged, AE sits on trap-bath, IH0 on the
    weak-vowel merger — each reading is offered and the round-trip gate picks
    whichever the record's Shaw attests (the same mergers the names import's
    "merger-tolerant" tier accepted).
    """
    if base == "ER":
        return ["əR", "ɜːR"] if digit == "0" else ["ɜːR"]
    if base == "AH":
        return ["ə"] if digit == "0" else ["ʌ"]
    if base == "AO":
        return ["ɔː", "ɒ"]
    if base == "AA":
        return ["ɒ", "ɑː"]
    if base == "AE":
        return ["æ", "ɑː"]
    if base == "IY" and digit == "0":
        return ["i"]
    if base == "IH" and digit == "0":
        return ["ɪ", "ə"]
    return [ARPABET_VOWELS[base]]


def _fused_alternatives(base, digit):
    """Vowel+R fusions to house r-compounds, or None when the vowel never
    fuses (AW/AY/OW/OY/UW/stressed-AH keep a separate r)."""
    if base == "AH" and digit == "0":
        return ["əR"]
    if base == "ER":
        return ["əR", "ɜːR"] if digit == "0" else ["ɜːR"]
    if base in R_FUSIONS:
        return [R_FUSIONS[base]]
    return None


def _phone_alternatives(phones, index):
    """Alternatives for the phone at index -> (piece-list options, advance).

    Each option is a list of (ipa, is_vowel, stress_digit) pieces, preferred
    option first. A vowel+R pair maps as one fused r-compound; when that R is
    intervocalic (onset of the next syllable) the unfused vowel + separate r
    reading is offered too, since names attest both (𐑚𐑸𐑺𐑩 vs 𐑚𐑸𐑧𐑮𐑩).
    """
    phone = phones[index]
    base = re.sub(r"\d", "", phone)
    digit = phone[-1] if phone[-1].isdigit() else None
    if base in ARPABET_CONSONANTS:
        return [[(ARPABET_CONSONANTS[base], False, None)]], 1
    if base not in ARPABET_VOWELS:
        raise ValueError(f"unknown ARPABET phone {phone}")
    next_base = (re.sub(r"\d", "", phones[index + 1])
                 if index + 1 < len(phones) else None)
    if next_base == "R":
        fused = _fused_alternatives(base, digit)
        if fused is not None:
            options = [[(ipa, True, digit)] for ipa in fused]
            after = phones[index + 2] if index + 2 < len(phones) else None
            r_is_onset = (after is not None
                          and re.sub(r"\d", "", after) in ARPABET_VOWELS)
            if r_is_onset:
                options += [[(ipa, True, digit), ("r", False, None)]
                            for ipa in _vowel_alternatives(base, digit)]
            return options, 2
    return [[(ipa, True, digit)] for ipa in _vowel_alternatives(base, digit)], 1


def candidate_ipas(phones):
    """Deterministic, preferred-first house-IPA candidates for one CMU pron.

    The first candidate takes the preferred reading at every ambiguity site;
    later candidates fan the sites out (itertools.product order, capped at
    MAX_CANDIDATES — the cap only bites on implausibly many-site words).
    """
    site_options = []
    index = 0
    while index < len(phones):
        options, advance = _phone_alternatives(phones, index)
        site_options.append(options)
        index += advance
    for combination in islice(product(*site_options), MAX_CANDIDATES):
        pieces = [piece for option in combination for piece in option]
        yield _stress_marked(pieces)


def arpabet_to_ipa(phones):
    """Preferred (first-candidate) house IPA for one CMU pronunciation."""
    return next(candidate_ipas(phones))


def _stress_marked(pieces):
    """Join pieces into house IPA with real stress marks.

    Stress: ˈ before the syllable onset of the first primary-stress vowel, ˌ
    before each secondary-stress vowel's onset — monosyllables carry no mark
    (house style). The onset is the longest legal English onset preceding the
    vowel (maximal onset principle, LEGAL_ONSET_CLUSTERS).
    """
    vowel_count = sum(1 for piece in pieces if piece[1])
    marks = {}
    if vowel_count > 1:
        primary_seen = False
        for index, (_, is_vowel, digit) in enumerate(pieces):
            if not is_vowel:
                continue
            if digit == PRIMARY_STRESS and not primary_seen:
                marks[_onset_of(pieces, index)] = STRESS_MARKS[PRIMARY_STRESS]
                primary_seen = True
            elif digit == SECONDARY_STRESS:
                onset = _onset_of(pieces, index)
                marks.setdefault(onset, STRESS_MARKS[SECONDARY_STRESS])
    return "".join(marks.get(index, "") + ipa
                   for index, (ipa, _, _) in enumerate(pieces))


def _onset_of(pieces, vowel_index):
    """Index of the longest legal onset preceding a vowel (maximal onset)."""
    run_start = vowel_index
    while run_start > 0 and not pieces[run_start - 1][1]:
        run_start -= 1
    run = tuple(piece[0] for piece in pieces[run_start:vowel_index])
    for length in range(min(MAX_ONSET_LEN, len(run)), 1, -1):
        if run[-length:] in LEGAL_ONSET_CLUSTERS:
            return vowel_index - length
    return vowel_index - min(1, len(run))


def load_cmudict(path):
    """word -> [phone list, ...] in dict order; (n) variant suffixes folded."""
    pronunciations = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            word, phones = line.split(" ", 1)
            word = re.sub(r"\(\d+\)$", "", word)
            phones = phones.split(" #")[0].strip().split()
            pronunciations.setdefault(word, []).append(phones)
    return pronunciations


def fill_record(record, cmu, stats):
    """Fill `ipa` on one record iff a CMU pronunciation round-trips to its Shaw."""
    if "ipa" in record:
        stats["already_has_ipa"] += 1
        return
    prons = cmu.get(record["Latn"].lower())
    if prons is None:
        stats["skipped_no_cmu"] += 1
        return
    for phones in prons:
        for ipa in candidate_ipas(phones):
            if ipa_to_shavian(ipa) == record["Shaw"]:
                record["ipa"] = ipa
                record["ipa_source"] = "cmu"
                stats["filled"] += 1
                return
    stats["skipped_shaw_mismatch"] += 1


def fill_supplement(supplement, cmu, stats):
    for records in supplement.values():
        for record in records:
            fill_record(record, cmu, stats)


def report(stats):
    print("\n=== CMUdict names IPA fill report ===")
    print(f"Filled (round-trip confirmed):   {stats['filled']:,}")
    print(f"Skipped (no CMU entry):          {stats['skipped_no_cmu']:,}")
    print(f"Skipped (no pron matches Shaw):  {stats['skipped_shaw_mismatch']:,}")
    if stats["already_has_ipa"]:
        print(f"Untouched (already had ipa):     {stats['already_has_ipa']:,}")


def main():
    if not CMUDICT_PATH.exists():
        print(f"ERROR: CMUdict not found: {CMUDICT_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(NAMES_INPUT, encoding="utf-8") as f:
        supplement = json.load(f)
    cmu = load_cmudict(CMUDICT_PATH)

    stats = Counter()
    fill_supplement(supplement, cmu, stats)

    with open(NAMES_IPA_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(supplement, f, ensure_ascii=False, indent=4)
    print(f"Wrote {NAMES_IPA_OUTPUT.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in supplement.values()):,} records")

    report(stats)


if __name__ == "__main__":
    main()
