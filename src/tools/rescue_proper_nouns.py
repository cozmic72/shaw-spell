#!/usr/bin/env python3
"""
Rescue IPA-less proper-noun (name) candidates by copying a same-spelling ReadLex
homograph's IPA, so they reach the review pool instead of being silently dropped.

Many kaikki `name` entries carry no IPA and the wiktionary generator drops them.
Yet a name very often shares its spelling (case-insensitive) with an ordinary
ReadLex word that DOES have IPA — `Baker`/`baker`, `Reading`/`reading`. Copying
the homograph's pronunciation is a coarse guess (a name may well be said
differently), so the rescued record is tagged with its provenance and capped to a
low, needs-review confidence: coverage over precision, the editor is the sieve.

Donor source is ReadLex ALONE (the authoritative same-spelling dictionary). The
copied IPA runs through the SAME deterministic normalize/convert path as a normal
ReadLex entry (normalize_ipa + ipa_to_shavian — rule-based, NOT the ML normalizer
and NOT the shave tool), so this stage is fully deterministic and cheap.

This is an ADDITIVE post-pass. It starts from the committed reliable set and
appends rescued NP0 records, writing an augmented copy — the reliable input is
left untouched. It sits at the head of the pruning chain:

    reliable -> HERE (rescued) -> deduped -> classified -> collapsed -> filtered
    -> basis

so a rescued name flows through duplicate-filtering, merger classification, the
identical-dialect collapse, and phrase pruning exactly like any other candidate.

Inputs:  data/supplement-wiktionary-reliable.json  (the STARTING dict, augmented
         in place), external/readlex/readlex.json  (donors),
         external/wiktionary/kaikki.org-dictionary-English.jsonl  (streamed for
         IPA-less `name` spellings).
Outputs: data/supplement-wiktionary-rescued.json  — the reliable set plus the
         rescued NP0 records. The Pass-1 dedup reads this next for wiktionary;
         WordNet keeps reading -reliable.json.

Usage:
    python3 src/tools/rescue_proper_nouns.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

from basis import PROJECT_ROOT
from ipa_to_shavian import ipa_to_shavian, normalize_ipa, score_confidence

RELIABLE_INPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"
RESCUED_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-rescued.json"
READLEX_JSON = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
WIKTIONARY_JSONL = (PROJECT_ROOT / "external" / "wiktionary"
                    / "kaikki.org-dictionary-English.jsonl")

# The kaikki POS whose IPA-less entries we rescue, and the CLAWS C5 tag we emit.
RESCUE_KAIKKI_POS = "name"
RESCUE_POS = "NP0"

# Additive provenance: the tag survives through the chain to the basis and UI so
# the owner can see, and later triage, that this Shavian was copied not derived.
RESCUE_IPA_SOURCE_FIELD = "ipa_source"
RESCUE_IPA_SOURCE_VALUE = "copied-homograph"

# Copied provenance caps confidence below the 80 "high" band, inside the 30-79
# "needs review" band. A broken conversion may score lower still; take the minimum.
RESCUED_NAME_CONFIDENCE = 40


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_key(word, pos, shaw):
    """The ReadLex-format `word_POS_shaw` key a supplement file buckets under."""
    return f"{word}_{pos}_{shaw}"


def build_readlex_donor_index(readlex_path):
    """spelling_lower -> (ipa, var) for single-word ReadLex entries with IPA.

    When a spelling has several entries, the donor is chosen deterministically:
    RRP (the universal dialect) is preferred, then highest freq, then file order.
    """
    donors = {}
    best_rank = {}
    readlex = load_json(readlex_path)
    for entries in readlex.values():
        for entry in entries:
            word = entry["Latn"]
            if " " in word.strip():
                continue  # names rescue to single-word homographs only
            ipa = entry.get("ipa")
            if not ipa:
                continue
            spelling = word.lower()
            # Lower rank tuple wins: RRP before other vars, then higher freq.
            rank = (0 if entry.get("var") == "RRP" else 1, -entry.get("freq", 0))
            if spelling not in best_rank or rank < best_rank[spelling]:
                best_rank[spelling] = rank
                donors[spelling] = (ipa, entry.get("var"))
    return donors


def covered_name_spellings(reliable):
    """Lower-cased spellings already carried by an NP0 record in the reliable set.

    These names already emitted usable IPA upstream, so they are not pending and
    must not be re-rescued from a homograph."""
    covered = set()
    for entries in reliable.values():
        for entry in entries:
            if entry.get("pos") == RESCUE_POS:
                covered.add(entry["Latn"].lower())
    return covered


def collect_pending_names(jsonl_path, covered):
    """The set of kaikki `name` spellings that carry no IPA and are not already
    covered by a reliable NP0 record. Affix pseudo-words are skipped as the
    generator does."""
    pending = set()
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("lang_code") != "en":
                continue
            if entry.get("pos") != RESCUE_KAIKKI_POS:
                continue
            word = entry.get("word", "")
            if not word:
                continue
            if word.startswith("-") or word.endswith("-"):
                continue  # affix pseudo-word, not a real name
            if entry.get("sounds"):
                continue  # has pronunciation data — not a rescue candidate
            if word.lower() in covered:
                continue
            pending.add(word)
    return pending


def rescue_names(pending_names, donors, augmented, stats):
    """Append an NP0 record for each pending name that has a ReadLex homograph.

    The donor's IPA runs through the deterministic normalize/convert path. The
    rescued record inherits the donor's dialect var (FAIL LOUD if it has none),
    is tagged with the provenance field, and its confidence is capped low."""
    for word in sorted(pending_names):  # sorted for deterministic output ordering
        donor = donors.get(word.lower())
        if donor is None:
            stats["unrescued"] += 1
            continue
        donor_ipa, donor_var = donor
        if not donor_var:
            raise ValueError(f"ReadLex donor for {word!r} has no var; cannot assign dialect")

        ipa_normalized = normalize_ipa(donor_ipa, word=word, source="readlex")
        shaw = ipa_to_shavian(ipa_normalized)
        if not shaw:
            stats["unrescued"] += 1
            continue

        conf_pct, notes = score_confidence(word, ipa_normalized, shaw, None)
        conf_pct = min(conf_pct, RESCUED_NAME_CONFIDENCE)
        notes = [note for note in notes if note]
        notes.append(f"{RESCUE_IPA_SOURCE_FIELD}:{RESCUE_IPA_SOURCE_VALUE}")

        entry_data = {
            "Latn": word,
            "Shaw": shaw,
            "pos": RESCUE_POS,
            "ipa": ipa_normalized,
            "freq": 0,
            "var": donor_var,
            "confidence": conf_pct,
            "review": "; ".join(notes),
            RESCUE_IPA_SOURCE_FIELD: RESCUE_IPA_SOURCE_VALUE,
        }

        bucket = augmented.setdefault(make_key(word, RESCUE_POS, shaw), [])
        if entry_data not in bucket:
            bucket.append(entry_data)
        stats["rescued"] += 1


def report(stats):
    print("\n=== proper-noun homograph rescue report ===")
    print(f"Pending IPA-less names:  {stats['pending']:,}")
    print(f"Rescued (donor found):   {stats['rescued']:,}")
    print(f"Unrescued (no donor):    {stats['unrescued']:,}")


def main():
    if not WIKTIONARY_JSONL.exists():
        print(f"ERROR: kaikki dump not found: {WIKTIONARY_JSONL}", file=sys.stderr)
        sys.exit(1)

    augmented = load_json(RELIABLE_INPUT)
    donors = build_readlex_donor_index(READLEX_JSON)
    covered = covered_name_spellings(augmented)
    pending_names = collect_pending_names(WIKTIONARY_JSONL, covered)

    stats = Counter()
    stats["pending"] = len(pending_names)
    rescue_names(pending_names, donors, augmented, stats)

    with open(RESCUED_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(augmented, f, ensure_ascii=False, indent=4)
    print(f"Wrote {RESCUED_OUTPUT.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in augmented.values()):,} records")

    report(stats)


if __name__ == "__main__":
    main()
