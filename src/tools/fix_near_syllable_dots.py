#!/usr/bin/env python3
"""
Correct NEAR (𐑽/𐑾) records that a lost syllable dot mis-collapsed, routing them
into the review pool as moderate-confidence candidates.

Wiktionary marks the happier /ˈhæp.i.ə/ syllable break with a dot; the stored
supplement doesn't, so the generator collapsed `i.ə` to NEAR (𐑣𐑨𐑐𐑽) instead of
the two-syllable 𐑣𐑨𐑐𐑦𐑼. The converter is now fixed (ipa_to_shavian.py routes
`[iɪ].ə` through the affix boundary), but the committed reliable set predates the
fix and MUST NOT be regenerated (the generator consults the non-deterministic
shave tool and would orphan the owner's patches).

This additive post-pass repairs those records without regenerating. For each
stored record whose Shaw contains a NEAR letter, it re-finds the SAME word's
kaikki sound by (word, pos) + dialect and re-derives Shaw — but ONLY from a sound
whose RAW DOTTED ipa carries the `[iɪ].ə` signature. A record with no such dotted
sound is genuine NEAR (here, weird, beer, year) and is SKIPPED: a naive re-derive
would rewrite those too.

It sits in the pruning chain right after the proper-noun rescue, reading the
rescued set (reliable + rescued NP0 records) so both post-passes compose:

    reliable -> rescued -> HERE (neardot) -> deduped -> ... -> filtered -> basis

CRITICAL — the corrections are REVIEW CANDIDATES, not asserted truth. Authoritative
ReadLex is editorially inconsistent here (carrier→𐑒𐑨𐑮𐑦𐑼 agrees, but linear→𐑤𐑦𐑯𐑽,
premier→𐑐𐑮𐑧𐑥𐑽, imperial→𐑦𐑥𐑐𐑽𐑾𐑤 KEEP NEAR), so the mechanical rule will disagree
with ReadLex on some words. Corrected records are therefore capped into the
needs-review band and tagged with provenance so the owner adjudicates them — the
UI is the sieve.

Patch-anchored records are exempt (the owner already owns them); they are left
verbatim for the owner to correct by hand.

Inputs:  data/supplement-wiktionary-rescued.json (the STARTING dict — the rescue
         pass's output), external/wiktionary/kaikki.org-dictionary-English.jsonl
         (streamed for the dotted sounds), data/patches/patches.jsonl (exemption).
Outputs: data/supplement-wiktionary-neardot.json — the rescued set with the
         NEAR-dot records corrected. -rescued.json is left untouched.

Usage:
    python3 src/tools/fix_near_syllable_dots.py
"""

import json
import re
import sys
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, anchor_of
from filter_supplement_duplicates import anchored_keys, load_patches
from generate_wiktionary_supplement import (
    POS_MAP, VAR_TO_NORM_SOURCE, classify_sound, clean_ipa, make_key,
    strip_ipa_delimiters,
)
from ipa_to_shavian import ipa_to_shavian, normalize_ipa, score_confidence

RESCUED_INPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-rescued.json"
NEARDOT_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-neardot.json"
WIKTIONARY_JSONL = (PROJECT_ROOT / "external" / "wiktionary"
                    / "kaikki.org-dictionary-English.jsonl")

# NEAR letters: NEAR+R compound (𐑽) and bare NEAR (𐑾). A record whose Shaw holds
# either MIGHT be a dot-collapse victim and is a re-match candidate. The dot-fix
# expands a collapsed NEAR to its two-syllable form: 𐑽 -> 𐑦𐑼, 𐑾 -> 𐑦𐑩.
NEAR_LETTERS = ("𐑽", "𐑾")
NEAR_EXPANSIONS = {"𐑽": "𐑦𐑼", "𐑾": "𐑦𐑩"}

# The dotted signature the generator lost: weak/kit vowel, syllable dot, schwa.
DOTTED_NEAR_RE = re.compile(r'[iɪ]\.ə')

# Provenance: survives through the pruning chain to the basis and UI so the owner
# can see and filter these mechanical corrections.
SHAW_SOURCE_FIELD = "shaw_source"
SHAW_SOURCE_VALUE = "near-dot-fixed"
REVIEW_NOTE = "near_dot_fixed"

# The correction is a review candidate, not truth (ReadLex disagrees on some
# words), so confidence is capped into the 30-79 needs-review band. Mirrors the
# rescue's cap; a broken conversion may score lower still, so take the minimum.
NEARDOT_CONFIDENCE = 40


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def norm_source_of_var(var):
    """The normalize_ipa source a stored var re-matches against, or None for vars
    that carry no re-derivation axis (UNC, etc.). The var IS the index bucket —
    the generator emits one record per accent var, and index_dotted_near_sounds
    buckets each dotted sound under every var it would have been emitted for."""
    return VAR_TO_NORM_SOURCE.get(var)


def index_dotted_near_sounds(jsonl_path):
    """(word_lower, pos_c5) -> {var: [raw_ipa, ...]} for kaikki sounds whose RAW
    ipa carries the [iɪ].ə dotted signature.

    Only dotted sounds are indexed — a (word, pos) absent here has no dot-collapse
    victim and its stored NEAR is genuine. File order is preserved so re-match is
    deterministic. Each sound is classified exactly as the generator does and
    indexed under EVERY accent var it would have been emitted for (a sound tagged
    for several keep-accents lands in each); a dropped-geo sound is skipped, and an
    untagged sound lands under SSB — mirroring process_entry."""
    index = defaultdict(lambda: defaultdict(list))
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("lang_code") != "en":
                continue
            word = entry.get("word", "")
            if not word or word.startswith("-") or word.endswith("-"):
                continue
            pos_c5 = POS_MAP.get(entry.get("pos", ""), "UNC")
            for sound in entry.get("sounds", []):
                ipa_raw = sound.get("ipa")
                if not ipa_raw or not DOTTED_NEAR_RE.search(ipa_raw):
                    continue
                stripped = strip_ipa_delimiters(ipa_raw)
                if stripped.startswith("-") or stripped.endswith("-"):
                    continue  # fragment IPA, as the generator skips
                accents, _info, drop = classify_sound(sound.get("tags", []))
                if drop:
                    continue
                for var, _norm_source in accents:
                    index[(word.lower(), pos_c5)][var].append(ipa_raw)
    return index


def rederive_shaw(ipa_raw, word, norm_source):
    """Run a raw kaikki ipa through the SAME deterministic pipeline the generator
    uses, now with the dot-routing fix in place."""
    ipa_normalized = normalize_ipa(clean_ipa(ipa_raw), word=word, source=norm_source)
    return ipa_normalized, ipa_to_shavian(ipa_normalized)


def near_masked(shaw):
    """Shaw with every NEAR letter and its two-syllable expansion reduced to one
    placeholder, so two spellings can be compared 'modulo the NEAR collapse'."""
    for near, expansion in NEAR_EXPANSIONS.items():
        shaw = shaw.replace(expansion, "⊙").replace(near, "⊙")
    return shaw


def select_dot_fix(stored_shaw, dotted_sounds, word, norm_source):
    """The (normalized ipa, re-derived Shaw) of the dotted sound that fixes ONLY
    the NEAR collapse — i.e. re-derives to a Shaw that equals the stored one
    everywhere except at NEAR positions, where a collapse became an expansion.

    Requiring a NEAR-modulo match keeps the fix surgical: a dotted sound that is
    a genuinely different pronunciation of the word (a different vowel elsewhere,
    another variant) is NOT imported wholesale. Deterministic: first match in
    kaikki file order. Returns None if no dotted sound fixes exactly the collapse."""
    stored_mask = near_masked(stored_shaw)
    for ipa_raw in dotted_sounds:
        ipa_normalized, new_shaw = rederive_shaw(ipa_raw, word, norm_source)
        if new_shaw and new_shaw != stored_shaw \
                and near_masked(new_shaw) == stored_mask:
            return ipa_normalized, new_shaw
    return None


def correct_entry(entry, dotted_index, exempt_keys, stats):
    """Rewrite a NEAR record in place if a matching dotted kaikki sound re-derives
    a Shaw that fixes ONLY the NEAR collapse. Returns True if rewritten.

    Skips records without a NEAR letter, patch-anchored records, records whose
    (word, pos, dialect) has no dotted sound, and dotted sounds that would change
    more than the NEAR collapse (a different pronunciation, not this bug)."""
    shaw = entry.get("Shaw", "")
    if not any(letter in shaw for letter in NEAR_LETTERS):
        return False

    if anchor_of(entry) in exempt_keys:
        stats["exempted"] += 1
        return False

    word = entry["Latn"]
    var = entry.get("var", "")
    norm_source = norm_source_of_var(var)
    if norm_source is None:
        return False  # no re-derivation axis for this var

    dotted = dotted_index.get((word.lower(), entry["pos"]), {}).get(var)
    if not dotted:
        stats["skipped_genuine_near"] += 1
        return False  # genuine NEAR — no dot-collapse victim for this scope

    fix = select_dot_fix(shaw, dotted, word, norm_source)
    if fix is None:
        stats["skipped_no_clean_fix"] += 1
        return False
    ipa_normalized, new_shaw = fix

    conf_pct, notes = score_confidence(word, ipa_normalized, new_shaw, None)
    conf_pct = min(conf_pct, NEARDOT_CONFIDENCE)
    notes = [note for note in notes if note]
    notes.append(REVIEW_NOTE)

    entry["Shaw"] = new_shaw
    entry["ipa"] = ipa_normalized  # keep ipa in step so the record round-trips
    entry["confidence"] = conf_pct
    entry["review"] = "; ".join(notes)
    entry[SHAW_SOURCE_FIELD] = SHAW_SOURCE_VALUE
    stats["corrected"] += 1
    return True


def correct_supplement(supplement, dotted_index, exempt_keys, stats):
    """Return the supplement dict with NEAR-dot records corrected and re-bucketed.

    A corrected Shaw changes the record's word_POS_shaw key, so the whole dict is
    rebuilt under freshly-made keys. Emission is sorted for deterministic output."""
    corrected = defaultdict(list)
    for entries in supplement.values():
        for entry in entries:
            correct_entry(entry, dotted_index, exempt_keys, stats)
            key = make_key(entry["Latn"], entry["pos"], entry["Shaw"])
            bucket = corrected[key]
            if entry not in bucket:
                bucket.append(entry)
    return {key: corrected[key] for key in sorted(corrected)}


def report(stats):
    print("\n=== NEAR syllable-dot correction report ===")
    print(f"Corrected (dot re-routed):     {stats['corrected']:,}")
    print(f"Exempted (patch-anchored):     {stats['exempted']:,}")
    print(f"Skipped (genuine NEAR):        {stats['skipped_genuine_near']:,}")
    print(f"Skipped (no clean dot-only fix): {stats['skipped_no_clean_fix']:,}")


def main():
    if not WIKTIONARY_JSONL.exists():
        print(f"ERROR: kaikki dump not found: {WIKTIONARY_JSONL}", file=sys.stderr)
        sys.exit(1)

    rescued = load_json(RESCUED_INPUT)
    exempt_keys = anchored_keys(load_patches())
    dotted_index = index_dotted_near_sounds(WIKTIONARY_JSONL)

    stats = Counter()
    corrected = correct_supplement(rescued, dotted_index, exempt_keys, stats)

    with open(NEARDOT_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(corrected, f, ensure_ascii=False, indent=4)
    print(f"Wrote {NEARDOT_OUTPUT.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in corrected.values()):,} records")

    report(stats)


if __name__ == "__main__":
    main()
