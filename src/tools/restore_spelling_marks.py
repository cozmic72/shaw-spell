#!/usr/bin/env python3
"""
Restore the Latin word's apostrophes and hyphens onto converter-generated Shavian.

Our own supplement records get their Shavian by converting IPA, and IPA
transcriptions carry no orthography — so `e-mail` comes out 𐑰𐑥𐑱𐑤 and `'bout`
comes out 𐑚𐑬𐑑, the mark silently lost (upstream ReadLex ships its own Shavian
and is untouched here). This stage puts the mark back where the LATIN says it
belongs. It is MECHANISM only: which words should ultimately drop a mark
(don't/can't house style, say) is an editorial decision the owner makes against
data that carries it — nothing here encodes such a policy.

HOUSE CHARACTERS. Hyphen U+002D, matching upstream ReadLex's own Shavian (7,413
ASCII hyphens, no alternatives). Apostrophe U+0027: upstream Shavian contains NO
apostrophes at all (it drops them — deliberately, which is exactly the editorial
call this stage refuses to bake in), so the house precedent is its ASCII
punctuation plus our own Latin (U+0027 exclusively). Curly ' / ' are accepted on
input and normalised away.

ALIGNMENT — conservative, all-or-nothing per record; a wrongly placed mark
asserts a boundary that is not there, so anything unplaceable HOLDS the record
unchanged and is tallied:

  1. SUBSTITUTION: equal separator counts (spaces, hyphens, apostrophes) on the
     two sides mean the boundaries already correspond 1:1 in order — any faithful
     conversion preserves segment order — so the Latin's separators are written
     over the Shavian's (`1-2-3`: 𐑢𐑳𐑯 𐑑𐑵 𐑔𐑮𐑰 -> 𐑢𐑳𐑯-𐑑𐑵-𐑔𐑮𐑰).
  2. DECOMPOSITION: otherwise spaces must pair 1:1 and anchor space-delimited
     chunks; a chunk's missing marks are placed only where the chunk splits into
     segments each ATTESTED as the Shavian of its Latin counterpart — by
     upstream ReadLex, or by the closed contraction-tail set below — with at
     most one unattested remainder (which only lexicon-attested neighbours may
     anchor; see decompose), and only when exactly one split qualifies
     (fully-attested splits outrank one-free ones). Edge marks (`'bout`) fall
     out of the same rule via empty edge segments.

A restoration whose new (word, pos, shaw, var) identity is already occupied is
held: it means the marked form already exists (usually upstream house-style) and
un-hiding it is the duplicate filter's / owner's call, not a rename this late in
the chain.

Runs LAST in build_supplement's chain: every earlier judge (duplicate filter,
variant flagging, phrase divergence, confidence votes) compares mark-free
converter output against the record's Shaw, so restoring any earlier would turn
each restored mark into a phantom disagreement. Respells are recorded via
mark_original(orig_shaw) so editorial patches auto-re-anchor, and lemma links
follow the moved identities (basis.repoint_lemmas).

Usage:
    python3 src/tools/restore_spelling_marks.py [--out PATH]

Without --out this is a dry run: it reports what a regeneration would change.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations_with_replacement
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from basis import (LEMMA_FIELD, PROJECT_ROOT, is_upstream, lemma_slot,
                   load_upstream, mark_original, repoint_lemmas, self_lemma)
from combine_supplements import output_bucket_key
from ipa_to_shavian import SHAVIAN_BLOCK, ipa_to_shavian

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-filtered.json"

APOSTROPHES = frozenset("'’‘")
APOSTROPHE = "'"
HYPHEN = "-"
NAMING_DOT = "·"
SEPARATORS = APOSTROPHES | {HYPHEN, " "}

# The grammatical contraction tails and their possible phonetic realisations.
# A closed morphological set, not a which-words-keep-the-mark policy: the
# lexicon cannot attest sub-word morphs like 've, so their Shavian shapes are
# derived through the converter itself (kept DRY with the phoneme tables).
TAIL_IPA = {
    "s": ("s", "z", "ɪz", "əz"),
    "ve": ("v", "əv"),
    "ll": ("l", "əl"),
    "re": ("ə", "ər"),
    "d": ("d", "əd", "ɪd"),
    "m": ("m", "əm"),
    "t": ("t",),
    "n": ("n", "ən"),
    "em": ("əm", "ɛm"),
}
TAIL_SPELLINGS = {tail: frozenset(ipa_to_shavian(ipa) for ipa in ipas)
                  for tail, ipas in TAIL_IPA.items()}

ALREADY_CORRECT = "already-correct"
RESTORED_SUBSTITUTED = "restored-substituted"
RESTORED_ALIGNED = "restored-aligned"
HELD_EXTRA_SEPS = "held-extra-separators"
HELD_SPACE_MISMATCH = "held-space-mismatch"
HELD_PARTIAL_CHUNK = "held-partial-chunk"
HELD_UNPLACED = "held-unplaced"
HELD_AMBIGUOUS = "held-ambiguous"
HELD_OVERSIZE = "held-oversize"
HELD_COLLISION = "held-collision"
HELD = (HELD_EXTRA_SEPS, HELD_SPACE_MISMATCH, HELD_PARTIAL_CHUNK,
        HELD_UNPLACED, HELD_AMBIGUOUS, HELD_OVERSIZE, HELD_COLLISION)

# Decomposition search bounds; a chunk beyond them is held, never guessed at.
MAX_CHUNK_LETTERS = 40
MAX_CHUNK_MARKS = 4

SAMPLE_LIMIT = 8


def build_spelling_index(upstream):
    """latn_lower -> the set of pure-Shavian spellings upstream ReadLex attests
    for it (naming dot stripped; entries with internal separators can never
    match a separator-free chunk part, so they are skipped)."""
    index = defaultdict(set)
    for entries in upstream.values():
        for entry in entries:
            shaw = entry.get("Shaw", "").lstrip(NAMING_DOT)
            if shaw and all(ord(ch) in SHAVIAN_BLOCK for ch in shaw):
                index[entry["Latn"].lower()].add(shaw)
    return index


def tokenize(text):
    """(segments, separators): text split at every separator, apostrophes
    normalised, so interleave(segments, separators) rebuilds a normalised text.
    len(segments) == len(separators) + 1; edge/doubled marks yield empty
    segments."""
    segments, separators, current = [], [], []
    for ch in text:
        if ch in SEPARATORS:
            segments.append("".join(current))
            current = []
            separators.append(APOSTROPHE if ch in APOSTROPHES else ch)
        else:
            current.append(ch)
    segments.append("".join(current))
    return segments, separators


def interleave(segments, separators):
    parts = [segments[0]]
    for separator, segment in zip(separators, segments[1:]):
        parts.append(separator)
        parts.append(segment)
    return "".join(parts)


def chunks_of(segments, separators):
    """The space-delimited chunks as (segments, separators) pairs — spaces are
    the chunk boundaries, never part of a chunk."""
    chunks, segs, seps = [], [segments[0]], []
    for separator, segment in zip(separators, segments[1:]):
        if separator == " ":
            chunks.append((segs, seps))
            segs, seps = [segment], []
        else:
            seps.append(separator)
            segs.append(segment)
    chunks.append((segs, seps))
    return chunks


def decompose(chunk, segments, separators, index):
    """(outcome, text): the chunk with `separators` placed at its segment
    boundaries, or (held-reason, None). A split qualifies when every part is an
    attested spelling of its Latin segment — empty exactly where the segment is
    empty — with at most one unattested remainder, and it is used only when it
    is the unique qualifier at its tier (fully-attested beats one-free). A
    contraction-tail shape may corroborate a fully-attested split but never
    anchors an unattested remainder: a one-letter tail like possessive 𐑟 too
    easily coincides with the tail of the remainder itself (Jones's over a
    truncated 𐑡𐑴𐑯𐑟 must hold, not split off the 𐑟 of Jones)."""
    dotted = chunk.startswith(NAMING_DOT)
    body = chunk[1:] if dotted else chunk
    if NAMING_DOT in body:
        return HELD_UNPLACED, None
    if len(body) > MAX_CHUNK_LETTERS or len(separators) > MAX_CHUNK_MARKS:
        return HELD_OVERSIZE, None
    lexicon = [index.get(segment.lower(), frozenset()) for segment in segments]
    tails = [TAIL_SPELLINGS.get(segment.lower(), frozenset())
             for segment in segments]
    exact, loose = [], []
    for cuts in combinations_with_replacement(range(len(body) + 1),
                                              len(separators)):
        bounds = (0, *cuts, len(body))
        parts = [body[start:end] for start, end in zip(bounds, bounds[1:])]
        free = tail_anchored = 0
        for segment, lex, tail, part in zip(segments, lexicon, tails, parts):
            if segment == "":
                if part != "":
                    break
            elif part == "":
                break
            elif part not in lex:
                if part in tail:
                    tail_anchored += 1
                else:
                    free += 1
                    if free > 1:
                        break
        else:
            if free == 0:
                exact.append(parts)
            elif not tail_anchored:
                loose.append(parts)
    candidates = exact or loose
    if not candidates:
        return HELD_UNPLACED, None
    if len(candidates) > 1:
        return HELD_AMBIGUOUS, None
    text = interleave(candidates[0], separators)
    return None, NAMING_DOT + text if dotted else text


def restore_marks(latn, shaw, index):
    """(outcome, new_shaw): the record's Shavian with the Latin's marks restored,
    or (outcome, None) when there is nothing to do (no Latin marks -> (None,
    None); already correct; held)."""
    latn_segments, latn_separators = tokenize(latn)
    if not any(sep != " " for sep in latn_separators):
        return None, None
    shaw_segments, shaw_separators = tokenize(shaw)
    if len(latn_separators) == len(shaw_separators):
        restored = interleave(shaw_segments, latn_separators)
        if restored == shaw:
            return ALREADY_CORRECT, None
        return RESTORED_SUBSTITUTED, restored
    if len(shaw_separators) > len(latn_separators):
        return HELD_EXTRA_SEPS, None
    if latn_separators.count(" ") != shaw_separators.count(" "):
        return HELD_SPACE_MISMATCH, None
    rebuilt = []
    for (lsegs, lseps), (ssegs, sseps) in zip(
            chunks_of(latn_segments, latn_separators),
            chunks_of(shaw_segments, shaw_separators)):
        if len(lseps) == len(sseps):
            rebuilt.append(interleave(ssegs, lseps))
            continue
        if sseps:
            return HELD_PARTIAL_CHUNK, None
        outcome, text = decompose(ssegs[0], lsegs, lseps, index)
        if text is None:
            return outcome, None
        rebuilt.append(text)
    restored = " ".join(rebuilt)
    if restored == shaw:
        return ALREADY_CORRECT, None
    return RESTORED_ALIGNED, restored


def identity_of(record, shaw):
    return (record["Latn"].lower(), record["pos"], shaw,
            record.get("var", ""))


def restore_supplement(supplement, tallies, samples, upstream=None):
    """A copy of the supplement dict with every own record's lost Latin marks
    restored where placement is certain, re-bucketed for the moved shaws.
    Count-preserving: rewrites Shaw only, never drops or splits. Upstream
    ReadLex records pass through verbatim."""
    if upstream is None:
        upstream = load_upstream()
    index = build_spelling_index(upstream)
    records = [record for entries in supplement.values() for record in entries]

    proposals = []
    for record in records:
        if is_upstream(record):
            continue
        outcome, restored = restore_marks(record["Latn"], record["Shaw"], index)
        if outcome is None:
            continue
        if restored is None:
            tallies[outcome] += 1
            if len(samples[outcome]) < SAMPLE_LIMIT:
                samples[outcome].append((record["Latn"], record["Shaw"]))
        else:
            proposals.append((record, outcome, restored))

    occupied = {identity_of(record, record["Shaw"]) for record in records}
    targets = defaultdict(set)
    for record, _, restored in proposals:
        targets[identity_of(record, restored)].add(
            identity_of(record, record["Shaw"]))

    moved = defaultdict(dict)
    for record, outcome, restored in proposals:
        target = identity_of(record, restored)
        if target in occupied or len(targets[target]) > 1:
            tallies[HELD_COLLISION] += 1
            if len(samples[HELD_COLLISION]) < SAMPLE_LIMIT:
                samples[HELD_COLLISION].append((record["Latn"], record["Shaw"]))
            continue
        old_shaw = record["Shaw"]
        record["Shaw"] = restored
        mark_original(record, "shaw", old_shaw)
        old_slot = (record["Latn"].lower(), record["pos"], old_shaw)
        if lemma_slot(record.get(LEMMA_FIELD)) == old_slot:
            record[LEMMA_FIELD] = self_lemma(record)
        moved[old_slot][lemma_slot(record)] = self_lemma(record)
        tallies[outcome] += 1
        if len(samples[outcome]) < SAMPLE_LIMIT:
            samples[outcome].append((record["Latn"], old_shaw, restored))

    repoint_lemmas(records, moved, tallies, "restore_spelling_marks")
    rebucketed = defaultdict(list)
    for record in records:
        rebucketed[output_bucket_key(record)].append(record)
    return {key: rebucketed[key] for key in sorted(rebucketed)}


def report(tallies, samples):
    print("\n=== Latin spelling-mark restoration report ===")
    restored = tallies[RESTORED_SUBSTITUTED] + tallies[RESTORED_ALIGNED]
    held = sum(tallies[outcome] for outcome in HELD)
    print(f"Already correct:            {tallies[ALREADY_CORRECT]:,}")
    print(f"Restored:                   {restored:,}")
    print(f"  by substitution:          {tallies[RESTORED_SUBSTITUTED]:,}")
    print(f"  by aligned decomposition: {tallies[RESTORED_ALIGNED]:,}")
    print(f"Held (left unchanged):      {held:,}")
    for outcome in HELD:
        print(f"  {outcome:24}  {tallies[outcome]:,}")
    print(f"Lemma links re-pointed:     {tallies['lemma-repointed']:,}")
    for outcome in (RESTORED_SUBSTITUTED, RESTORED_ALIGNED, *HELD):
        if samples[outcome]:
            print(f"\n  {outcome} samples:")
            for sample in samples[outcome]:
                print("   ", " | ".join(sample))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.strip().splitlines()[0])
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--out", type=Path, default=None,
                        help="write the restored pool (default: dry-run report)")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as handle:
        supplement = json.load(handle)
    tallies, samples = Counter(), defaultdict(list)
    restored = restore_supplement(supplement, tallies, samples)
    report(tallies, samples)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(restored, handle, ensure_ascii=False, indent=4)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
