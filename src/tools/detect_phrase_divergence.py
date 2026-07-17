#!/usr/bin/env python3
"""
Phrase divergence detection for the supplement candidates.

A multi-word phrase in the Wiktionary supplement earns a dictionary entry only
when its pronunciation is NOT simply its component words glued together. "a
priori" is a keeper — the "a" is not the reduced article schwa — whereas "outer
space" or "false friend" are just their words concatenated, so they are noise.

The signal is computed in SHAVIAN, not raw IPA. The project's IPA-to-Shavian
converter (ipa_to_shavian) already normalizes away exactly the noise that makes
a naive IPA string comparison useless: it strips stress marks and syllable
separators, drops length marks, and folds dialect-notation variants (oʊ/əʊ,
ɛ/e, ɑ/ɑː) onto one segmental representation. classify_shaw_difference goes
further and knows the weak-vowel alternations that are ACCEPTABLE across a word
boundary (kit/schwa, trap/schwa, foot/schwa) — precisely the reductions a phrase
undergoes when its parts are spoken together. So the comparison reuses the
project's phonology wholesale rather than inventing a parallel IPA comparator.

Per phrase:
  1. Split Latn on whitespace into component words.
  2. Look up each component's canonical citation IPA (ReadLex first, then the
     supplements), honouring the dialect model: prefer an entry in the phrase's
     own var, else fall back to RRP (which is universal), highest freq wins.
  3. Convert each component IPA to Shavian and concatenate: the expected phrase.
  4. Convert the phrase's own ipa to Shavian: the actual phrase.
  5. Classify:
       divergent  — segmental content differs beyond tolerance → KEEPER
       matches    — same as sum-of-parts → droppable noise
       unknown    — a component could not be resolved (do NOT guess)

The heuristic leans toward divergent/unknown when uncertain: a wrongly-hidden
keeper is worse than a wrongly-shown droppable. Known limitations are documented
in docs/phrase-divergence.md.

Outputs (both deterministic):
  data/phrase-divergence.tsv   inspection report, one row per phrase record
  data/phrase-divergence.json  the classification keyed by anchor, for consumers

Usage:
    python3 src/tools/detect_phrase_divergence.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ipa_to_shavian import ipa_to_shavian, classify_shaw_difference

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
SUPPLEMENT_PATHS = [
    PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json",
    PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json",
]
REPORT_PATH = PROJECT_ROOT / "data" / "phrase-divergence.tsv"
TAGGED_PATH = PROJECT_ROOT / "data" / "phrase-divergence.json"

# RRP is ReadLex's universal dialect: an RRP entry covers every accent, so it is
# the citation baseline for every component word regardless of the phrase's var.
UNIVERSAL_VAR = "RRP"

# The phrases carry supplement var labels (RSSB/GenAm); ReadLex labels its
# British-standard citations RRP. RSSB is that same universal British standard,
# so an RSSB phrase's var-specific citation IS the RRP one — no separate lookup.
PHRASE_VAR_TO_READLEX = {"RSSB": UNIVERSAL_VAR, "GenAm": "GenAm"}

# Classification labels (also the divergence values written to the tagged file).
DIVERGENT = "divergent"
MATCHES = "matches"
UNKNOWN = "unknown"

# classify_shaw_difference verdicts that mean "same as sum-of-parts". A pure
# match, or a difference only in weak-vowel boundary alternations, is droppable.
SUM_OF_PARTS_VERDICTS = {"match", "acceptable_alternation"}

# TRAP-BATH (𐑨 TRAP / 𐑭 PALM) is a DIALECTAL split, not a lexical difference: a
# component word cited in its BATH-long form against a phrase transcribed with
# the short form (or vice versa) is the same word in a different accent, not a
# divergent pronunciation. classify_shaw_difference deliberately omits this pair
# (it is a real error elsewhere in the pipeline), so the tolerance is applied
# here only, on top of that verdict.
TRAP_BATH_PAIR = frozenset({"𐑨", "𐑭"})


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def index_source(path):
    """word_lower -> {var -> highest-freq IPA} for one source file.

    When a source attests the same (word, var) twice, the higher freq wins;
    ties resolve to the first seen, keeping selection deterministic.
    """
    best_ipa = defaultdict(dict)
    best_freq = defaultdict(dict)
    for entries in load_json(path).values():
        for entry in entries:
            word = entry["Latn"].lower()
            if " " in word.strip():
                continue  # component citations are single words only
            var = entry["var"]
            freq = entry.get("freq", 0)
            if var not in best_freq[word] or freq > best_freq[word][var]:
                best_freq[word][var] = freq
                best_ipa[word][var] = entry["ipa"]
    return best_ipa


def build_citation_index(readlex_path, supplement_paths):
    """A precedence-ordered list of per-source indexes.

    ReadLex is the sanctioned dictionary; the supplements are unreviewed
    candidates whose function-word citations are noisy (freq-0 letter-name and
    interjection senses that would shadow a real one). So a component word is
    cited from the FIRST source that attests it — ReadLex if it can, else the
    supplements — never mixing an authoritative citation with a candidate one.
    """
    return [index_source(path) for path in (readlex_path, *supplement_paths)]


def citation_ipa(word, phrase_var, citation_indexes):
    """The canonical citation IPA for a component word, or None if unresolved.

    Consults the sources in precedence order (ReadLex first) and takes the
    citation from the first that attests the word at all. Within that source it
    honours the dialect model: prefer the phrase's own var, else RRP, which is
    universal and covers every accent. A word a source attests only in some
    third var (e.g. a GenAm-only exception, for an RSSB phrase) is not a valid
    citation, so that source is skipped for it.
    """
    if phrase_var not in PHRASE_VAR_TO_READLEX:
        raise ValueError(f"unexpected phrase var: {phrase_var!r}")
    readlex_var = PHRASE_VAR_TO_READLEX[phrase_var]
    for per_word in citation_indexes:
        per_var = per_word.get(word.lower())
        if not per_var:
            continue
        if readlex_var in per_var:
            return per_var[readlex_var]
        if UNIVERSAL_VAR in per_var:
            return per_var[UNIVERSAL_VAR]
    return None


def segmental(shavian):
    """The bare segmental content: separators removed so word-boundary spacing
    and hyphenation cannot mask an otherwise-identical pronunciation."""
    return shavian.replace(" ", "").replace("-", "").replace("'", "")


def is_sum_of_parts(expected_shaw, actual_shaw):
    """Whether the phrase is just its components glued together.

    First defers to the pipeline's classify_shaw_difference, then applies the
    phrase-local TRAP-BATH tolerance: an otherwise character-aligned pair that
    differs only in 𐑨/𐑭 is the same word in a different accent, not divergence.
    """
    expected = segmental(expected_shaw)
    actual = segmental(actual_shaw)
    if classify_shaw_difference(expected, actual) in SUM_OF_PARTS_VERDICTS:
        return True
    if len(expected) != len(actual):
        return False
    return all(
        e == a or frozenset({e, a}) == TRAP_BATH_PAIR
        for e, a in zip(expected, actual)
    )


def classify_phrase(phrase, citation_indexes):
    """Classify one phrase record. Returns (label, expected_ipa, expected_shaw).

    expected_ipa is the space-joined component citations (for the report);
    expected_shaw is their concatenated Shavian (the comparison basis). Both are
    empty when a component is unresolved.
    """
    components = phrase["Latn"].split()
    if len(components) < 2:
        raise ValueError(f"not a multi-word phrase: {phrase['Latn']!r}")

    var = phrase["var"]
    component_ipas = [citation_ipa(word, var, citation_indexes) for word in components]
    if any(ipa is None for ipa in component_ipas):
        return UNKNOWN, "", ""

    expected_ipa = " ".join(component_ipas)
    expected_shaw = "".join(ipa_to_shavian(ipa) for ipa in component_ipas)
    actual_shaw = ipa_to_shavian(phrase["ipa"])

    label = MATCHES if is_sum_of_parts(expected_shaw, actual_shaw) else DIVERGENT
    return label, expected_ipa, expected_shaw


def iter_phrase_records(supplement_paths):
    """Every multi-word phrase record across the reliable supplements, in file
    then file-order — deterministic given the on-disk JSON."""
    for source in supplement_paths:
        for entries in load_json(source).values():
            for entry in entries:
                if " " in entry["Latn"].strip():
                    yield entry


def anchor_of(record):
    """The natural key a consumer joins on: (word_lower, pos, shaw, var). Matches
    the basis anchor shape (src/tools/basis.py) so the tag file lines up."""
    return f"{record['Latn'].lower()}\t{record['pos']}\t{record['Shaw']}\t{record['var']}"


def main():
    citation_indexes = build_citation_index(READLEX_PATH, SUPPLEMENT_PATHS)

    report_rows = []
    tagged = {}
    counts = defaultdict(int)

    for phrase in iter_phrase_records(SUPPLEMENT_PATHS):
        label, expected_ipa, expected_shaw = classify_phrase(phrase, citation_indexes)
        counts[label] += 1
        report_rows.append((
            phrase["Latn"], phrase["pos"], phrase["var"],
            phrase["ipa"], expected_ipa,
            ipa_to_shavian(phrase["ipa"]), expected_shaw,
            label,
        ))
        tagged[anchor_of(phrase)] = label

    header = ("phrase", "pos", "var", "phrase_ipa", "expected_ipa",
              "phrase_shaw", "expected_shaw", "classification")
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in report_rows:
            handle.write("\t".join(row) + "\n")

    with open(TAGGED_PATH, "w", encoding="utf-8") as handle:
        json.dump(tagged, handle, ensure_ascii=False, indent=0, sort_keys=True)
        handle.write("\n")

    total = sum(counts.values())
    print(f"Phrases: {total}")
    for label in (DIVERGENT, MATCHES, UNKNOWN):
        print(f"  {label:9s} {counts[label]}")
    print(f"Report: {REPORT_PATH}")
    print(f"Tags:   {TAGGED_PATH}")


if __name__ == "__main__":
    main()
