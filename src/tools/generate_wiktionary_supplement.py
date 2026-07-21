#!/usr/bin/env python3
"""
Extract pronunciation data from Wiktionary JSONL dump and produce
ReadLex-format JSON supplement files.

Two output files:
  - data/supplement-wiktionary-reliable.json: entries with dialect-labelled IPA
  - data/supplement-wiktionary-speculative.json: entries with IPA but no dialect
    label (var RSSB, the unconfirmed-British bucket). Consumed by
    rescue_proper_nouns.py, which folds them into the live pruning chain.

Usage:
    python3 src/tools/generate_wiktionary_supplement.py
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from collections import Counter

# Add tools directory to path for ipa_to_shavian
sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import (contains_shavian, ipa_to_shavian, normalize_ipa,
                            score_confidence, upgrade_confidence_shave)
from ml_ipa_normalizer import ml_normalize_ipa, load_model, strip_stress

PROJECT_ROOT = Path(__file__).parent.parent.parent
WIKTIONARY_JSONL = PROJECT_ROOT / "external" / "wiktionary" / "kaikki.org-dictionary-English.jsonl"
RELIABLE_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"
SPECULATIVE_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-speculative.json"

# POS mapping: Wiktionary → CLAWS C5
POS_MAP = {
    "noun": "NN1",
    "verb": "VVI",
    "adj": "AJ0",
    "adv": "AV0",
    "prep": "PRP",
    "conj": "CJC",
    "pron": "PNP",
    "det": "DT0",
    "intj": "ITJ",
    "name": "NP0",
    "particle": "AV0",
    "num": "CRD",
    "phrase": "UNC",
    "prefix": "UNC",
    "suffix": "UNC",
    "infix": "UNC",
    "affix": "UNC",
    "abbrev": "UNC",
    "contraction": "UNC",
    "character": "UNC",
    "symbol": "UNC",
    "punct": "UNC",
}

# Shave labels its homograph-disambiguation diagnostics "Homograph:" (older
# builds said "WSD:" — accept both so the protection can't silently die).
_WSD_RE = re.compile(
    r"^(?:WSD|Homograph):\s+(\S+)\s+->\s+(\S+)\s+(\d+)%\s+/\s+(\S+)\s+(\d+)%")


def _batch_shave(words: list[str], dialect: str = "british") -> tuple[dict[str, str], dict[str, int]]:
    """Run words through the `shave` tool.

    Returns (word->shavian, word_lower->wsd_top_percent). WSD lines come from
    shave's stderr when it has to disambiguate a homograph; absence means
    shave was certain about that token.
    """
    try:
        # Separate words with BLANK lines so shave treats each as an isolated
        # token. Plain newlines make shave read the batch as a SENTENCE, whose
        # POS/phrase heuristics contaminate homograph disambiguation across word
        # boundaries (e.g. 'bow' 𐑚𐑴↔𐑚𐑬).
        input_text = "\n\n".join(words)
        flag = "--readlex-british" if dialect == "british" else "--readlex-american"
        result = subprocess.run(
            ["shave", flag],   # NOT -q: we want WSD diagnostics on stderr
            input=input_text,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # shave ECHOES the blank separators, so filter empty output lines before
        # zipping. One non-blank line per input word — assert so a mismatch fails
        # loud instead of silently mis-aligning every word to the wrong spelling.
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) != len(words):
            raise RuntimeError(
                f"shave output/input count mismatch: {len(lines)} output "
                f"lines for {len(words)} input words")
        mapping = {}
        for word, shaw_line in zip(words, lines):
            shaw = shaw_line.strip()
            # A line with no Shavian letters is shave's unknown-word/digit
            # echo, not an opinion — see contains_shavian.
            if shaw and contains_shavian(shaw):
                mapping[word] = shaw
        wsd: dict[str, int] = {}
        for line in result.stderr.split("\n"):
            m = _WSD_RE.match(line)
            if m:
                w = m.group(1).lower()
                top = int(m.group(3))
                wsd[w] = min(wsd[w], top) if w in wsd else top
        return mapping, wsd
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  Warning: shave tool unavailable: {e}", file=sys.stderr)
        return {}, {}


def _compute_ml_shaw(word: str, ipa: str, norm_source: str,
                     have_ml: bool, ml_model) -> str | None:
    """Get ML model's Shavian prediction, or None if unavailable.

    Only applies ML to the non-rhotic (UK-model) normalisation pathway — the
    model is UK-trained. For the rhotic (GenAm/Canada/Ireland) path, returns None.
    """
    if norm_source != "wiktionary_rp" or not have_ml or not ml_model:
        return None
    ipa_stripped = strip_stress(ipa)
    ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
    return ipa_to_shavian(ml_ipa)


# ---------------------------------------------------------------------------
# Accent / dialect tag classification (multi-accent harvest, phase 1)
#
# Each Wiktionary `sound` carries geographic `tags`. We KEEP an allowlisted set
# of standard NATIONAL accents, each with its own var; a sound tagged with more
# than one keep-accent (e.g. ['General-American','Received-Pronunciation']) emits
# ONE record per accent (phase 2's hierarchy collapse dedups the identical ones).
# Any sub-national / finer geography that is NOT a keep-accent DROPS the sound.
# A sound with no accent tag at all becomes RSSB — the pipeline's existing
# "unconfirmed British" bucket (SSB run through the non-rhotic normalisation's
# R-restoration, exactly what these records are). RSSB is the var the flat
# dialect collapse, the merger classifier and the RRP reclassifier all already
# process, so the untagged lane flows downstream and the reclassifier
# canonicalizes to RRP the records the Guide's rules permit — NOT the old
# default-guess RP, and NOT a terminal bucket.
#
# `norm_source` selects the IPA-normalisation pathway in ipa_to_shavian:
#   "wiktionary_rp"  — non-rhotic: R-restoration + SSB monophthong conventions
#   "wiktionary_gam" — rhotic: no R-restoration, GenAm vowel rewrites
# Rhotic accents (GenAm, Canada, Ireland) MUST use the rhotic path so the
# R-restorer does not double-insert an R the transcription already carries.
# (Ireland is rhotic but not a GenAm vowel system — the GenAm vowel rewrites are
# an imperfect fit; it rides at review confidence and is flagged for the owner.)
# ---------------------------------------------------------------------------

# var -> (tags that select it, norm_source pathway). Order is the deterministic
# emission order when a sound carries several keep-accents.
KEEP_ACCENTS: list[tuple[str, set[str], str]] = [
    ("RRP",    {"Received-Pronunciation", "UK", "British"}, "wiktionary_rp"),
    ("GenAm",  {"General-American", "US"},                  "wiktionary_gam"),
    ("GenAus", {"General-Australian", "Australia"},         "wiktionary_rp"),
    ("GenCan", {"Canada", "Canadian"},                      "wiktionary_gam"),
    ("SthAfr", {"General-South-African", "South-African"},  "wiktionary_rp"),
    ("NZ",     {"New-Zealand"},                             "wiktionary_rp"),
    ("IrEng",  {"Ireland", "Irish"},                        "wiktionary_gam"),
]

# The untagged / accent-less bucket. Non-rhotic British normalisation.
# "RSSB" (SSB made rhotic) is the pipeline's unconfirmed-British var: choosing it
# merges same-anchor attestations with wordnet's RSSB records at combine time and
# puts the untagged lane in front of every stage that already handles RSSB.
UNTAGGED_VAR = "RSSB"
UNTAGGED_NORM_SOURCE = "wiktionary_rp"

# var -> the normalize_ipa source the generator used for it. The single source of
# truth for var->norm_source, consumed by process_entry AND by downstream
# re-derivation passes (fix_near_syllable_dots) so they normalise identically.
VAR_TO_NORM_SOURCE = {var: norm_source for var, _sel, norm_source in KEEP_ACCENTS}
VAR_TO_NORM_SOURCE[UNTAGGED_VAR] = UNTAGGED_NORM_SOURCE

# var -> which `shave` dialect model reviews low-confidence records of that var.
# Derived from each accent's norm_source: the non-rhotic (wiktionary_rp) accents
# take the British model, the rhotic (wiktionary_gam) accents the American one.
VAR_SHAVE_DIALECT = {
    var: ("british" if norm_source == "wiktionary_rp" else "american")
    for var, _sel, norm_source in KEEP_ACCENTS
}

# Quality / register tags → the record's `info` list (surfaced for review; the
# owner chose schema-over-drop). They do NOT drop a record and do NOT pick an
# accent.
QUALITY_TAGS = {
    "obsolete", "dialectal", "dated", "rare", "archaic",
    "nonstandard", "proscribed", "colloquial",
}

# Sub-national / finer geographic tags. A sound carrying one of these but NO
# keep-accent is DROPPED (it is the "specific geographical variation" we filter
# out). If a keep-accent is ALSO present the sound is kept under that accent and
# the finer geo is simply ignored. Derived from the observed kaikki tag census;
# any geographic tag not in the keep-set belongs here.
DROP_GEO_TAGS = {
    "Scotland", "Northern-England", "India", "Singapore", "Philippines",
    "Northumbria", "Northern-Ireland", "Multicultural-London-English",
    "Southern-US", "New-York-City", "Wales", "Midlands", "Hong-Kong",
    "Philadelphia", "Malaysia", "New-England", "Southern-England", "England",
    "Boston", "Inland-Northern-American", "Northern-US", "Ontario",
    "Caribbean", "Northwestern", "Jamaica", "Geordie", "California",
    "Estuary-English", "Appalachia", "West-Country", "Pakistan", "Ulster",
    "Yorkshire", "Midwestern-US", "Tasmanian", "Nigeria", "Cockney",
    "Eastern-New-England", "Wearside", "Germany", "West-Midlands",
    "South-Wales", "East-Coast", "Northeastern", "North-American",
    "Hiberno-English", "Atlantic-Canada", "Virginia", "Western",
    "African-American-Vernacular-English", "Southern", "North", "South",
    "East", "West",
}


def classify_sound(tags: list[str]) -> tuple[list[tuple[str, str]], list[str], bool]:
    """Classify one sound's tags into emission instructions.

    Returns (accents, info, drop):
      accents  list of (var, norm_source) records to emit for this sound.
      info     quality/register tags to attach to every emitted record.
      drop     True if the sound should be dropped entirely (no record).

    Decision order:
      1. Any keep-accent tag  -> one record per matched accent (info attached).
      2. Else any drop-geo tag -> drop (no record).
      3. Else (no accent, no drop-geo) -> SSB (info attached).
    Quality tags never select an accent and never cause a drop; a dropped sound
    simply discards them with the record.
    """
    tag_set = set(tags) if tags else set()
    info = sorted(tag_set & QUALITY_TAGS)

    matched = [(var, norm_source) for var, sel, norm_source in KEEP_ACCENTS
               if tag_set & sel]
    if matched:
        return matched, info, False

    if tag_set & DROP_GEO_TAGS:
        return [], info, True

    return [(UNTAGGED_VAR, UNTAGGED_NORM_SOURCE)], info, False


def strip_ipa_delimiters(ipa: str) -> str:
    """Strip surrounding /.../ or [...] from IPA string."""
    ipa = ipa.strip()
    if len(ipa) >= 2:
        if (ipa[0] == '/' and ipa[-1] == '/') or (ipa[0] == '[' and ipa[-1] == ']'):
            ipa = ipa[1:-1]
    return ipa


def clean_ipa(ipa: str) -> str:
    """Clean Wiktionary IPA for use with ipa_to_shavian converter.

    Strips delimiters, removes syllable dots, and handles common
    Wiktionary conventions.
    """
    ipa = strip_ipa_delimiters(ipa)
    # Route the [iɪ].ə syllable break through the affix boundary (+) so it stays
    # two syllables (𐑦𐑼) not NEAR (𐑽) — see normalize_ipa in ipa_to_shavian.py.
    # Must run before the dot strip. (The GenAm .ɚ/.ɹ sibling is out of scope.)
    ipa = re.sub(r'([iɪ])\.(ə)', r'\1+\2', ipa)
    # Remove syllable boundary dots
    ipa = ipa.replace('.', '')
    # Remove tie bars
    ipa = ipa.replace('͡', '')
    # Remove parenthesized optional segments like (ə) — keep the content
    ipa = re.sub(r'\(([^)]*)\)', r'\1', ipa)
    return ipa


def is_broad_transcription(ipa_raw: str) -> bool:
    """Check if this is a broad (phonemic) transcription in slashes."""
    ipa_raw = ipa_raw.strip()
    return ipa_raw.startswith('/') and ipa_raw.endswith('/')


def make_key(word: str, pos: str, shaw: str) -> str:
    """Create a ReadLex-format key: word_POS_shaw"""
    return f"{word}_{pos}_{shaw}"


def process_entry(entry: dict, reliable: dict, speculative: dict, stats: Counter,
                   have_ml: bool = False, ml_model=None):
    """Process a single Wiktionary entry, adding to reliable or speculative dicts."""
    word = entry.get("word", "")
    pos_raw = entry.get("pos", "")
    sounds = entry.get("sounds", [])

    if not word or not sounds:
        return

    # Skip affix entries (e.g. "-ity", "giga-") — these aren't real words
    if word.startswith("-") or word.endswith("-"):
        stats["skipped_affix"] += 1
        return

    pos = POS_MAP.get(pos_raw, "UNC")
    stats["total_entries"] += 1

    # Collect IPA entries, preferring broad transcriptions
    for sound in sounds:
        ipa_raw = sound.get("ipa")
        if not ipa_raw:
            continue

        tags = sound.get("tags", [])

        # Prefer broad transcription (slashes) over narrow (brackets)
        # but accept narrow if that's all we have
        is_broad = is_broad_transcription(ipa_raw)

        # Skip fragment IPA (e.g. "-di", "ə-", "-ˌbiːoʊ-") — Wiktionary uses
        # leading/trailing hyphens to indicate partial pronunciations
        ipa_stripped = strip_ipa_delimiters(ipa_raw)
        if ipa_stripped.startswith("-") or ipa_stripped.endswith("-"):
            stats["skipped_fragment_ipa"] += 1
            continue

        ipa_clean = clean_ipa(ipa_raw)
        if not ipa_clean:
            continue

        stats["with_ipa"] += 1

        # Classify this sound's tags into accent records / info / drop.
        accents, info, drop = classify_sound(tags)
        if drop:
            stats["dropped_subnational_geo"] += 1
            continue

        # Emit one record per accent the sound is tagged with (a sound tagged
        # for several keep-accents, e.g. [GenAm, RP], produces one record each —
        # phase 2's hierarchy collapse dedups the identical ones). The IPA is
        # normalised per-accent because rhotic vs non-rhotic accents take
        # different normalisation pathways.
        for var, norm_source in accents:
            # Normalize IPA to ReadLex conventions
            ipa_normalized = normalize_ipa(ipa_clean, word=word, source=norm_source)

            # Generate Shavian
            try:
                shaw = ipa_to_shavian(ipa_normalized)
            except Exception:
                stats["shavian_errors"] += 1
                continue

            if not shaw:
                continue

            # ML confidence comparison only for the non-rhotic (UK-model) path.
            ml_shaw = _compute_ml_shaw(word, ipa_normalized, norm_source,
                                       have_ml, ml_model)

            # Score confidence as percentage
            conf_pct, notes = score_confidence(word, ipa_normalized, shaw, ml_shaw)

            entry_data = {
                "Latn": word,
                "Shaw": shaw,
                "pos": pos,
                "ipa": ipa_normalized,
                "freq": 0,
                "var": var,
                "confidence": conf_pct,
            }
            if info:
                entry_data["info"] = list(info)
                stats["records_with_info"] += 1
            if notes:
                entry_data["review"] = "; ".join(notes)
            # Stash ml_shaw for shave consultation later
            entry_data["_ml_shaw"] = ml_shaw

            # Bucket for initial stats
            if conf_pct >= 80:
                stats["confidence_high"] += 1
            elif conf_pct >= 30:
                stats["confidence_medium"] += 1
            else:
                stats["confidence_low"] += 1

            key = make_key(word, pos, shaw)
            stats[f"var_{var}"] += 1

            # Untagged (RSSB) records carry no explicit accent tag → the
            # speculative FILE, preserving the "unlabelled kept separate" split
            # for diagnostics. NOT a terminal bucket: rescue_proper_nouns folds
            # the speculative file into the live chain (rescued -> neardot ->
            # combine), so these are ordinary review candidates downstream.
            # Accent-tagged records → reliable.
            if var == UNTAGGED_VAR:
                stats["speculative_entries"] += 1
                target = speculative
            else:
                stats["reliable_entries"] += 1
                target = reliable

            if key not in target:
                target[key] = []
            # Avoid exact duplicates
            if entry_data not in target[key]:
                target[key].append(entry_data)


def main():
    if not WIKTIONARY_JSONL.exists():
        print(f"ERROR: Input file not found: {WIKTIONARY_JSONL}", file=sys.stderr)
        sys.exit(1)

    reliable = {}
    speculative = {}
    stats = Counter()

    # Load ML model for confidence comparison
    ml_model = None
    have_ml = False
    try:
        ml_model = load_model()
        have_ml = True
        print("Loaded ML model for confidence scoring.")
    except FileNotFoundError:
        print("Warning: ML model not found, skipping ML confidence comparison.")

    print(f"Processing {WIKTIONARY_JSONL}...")
    print("This may take a few minutes for ~1.45M lines.")
    print()

    with open(WIKTIONARY_JSONL, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i > 0 and i % 200000 == 0:
                print(f"  ...processed {i:,} lines ({stats['total_entries']:,} English entries with sounds)")

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                stats["json_errors"] += 1
                continue

            # Only English
            if entry.get("lang_code") != "en":
                stats["non_english"] += 1
                continue

            process_entry(entry, reliable, speculative, stats,
                          have_ml=have_ml, ml_model=ml_model)

    total_lines = i + 1
    print(f"  ...done. {total_lines:,} total lines.")
    print()

    print(f"  Initial confidence: high={stats['confidence_high']:,}, "
          f"medium={stats['confidence_medium']:,}, low={stats['confidence_low']:,}")

    # Consult `shave` tool for entries below 89% confidence in reliable dict
    review_british = set()
    review_american = set()
    for key, entries in reliable.items():
        for e in entries:
            if e.get("confidence", 89) < 89:
                shave_dialect = VAR_SHAVE_DIALECT.get(e.get("var"))
                if shave_dialect == "british":
                    review_british.add(e["Latn"])
                elif shave_dialect == "american":
                    review_american.add(e["Latn"])

    shave_results_british = {}
    shave_results_american = {}
    wsd_british: dict[str, int] = {}
    wsd_american: dict[str, int] = {}

    if review_british:
        print(f"\n  Consulting `shave` tool for {len(review_british):,} RSSB review words...")
        review_list = sorted(review_british)
        BATCH_SIZE = 5000
        for batch_start in range(0, len(review_list), BATCH_SIZE):
            batch = review_list[batch_start:batch_start + BATCH_SIZE]
            batch_results, batch_wsd = _batch_shave(batch, dialect="british")
            shave_results_british.update(batch_results)
            for w, pct in batch_wsd.items():
                wsd_british[w] = min(wsd_british[w], pct) if w in wsd_british else pct
            if batch_start > 0 and batch_start % 10000 == 0:
                print(f"    ...shave processed {batch_start:,}/{len(review_list):,}")
        print(f"  Got shave results for {len(shave_results_british):,} RSSB words "
              f"({len(wsd_british):,} WSD-ambiguous).")

    if review_american:
        print(f"\n  Consulting `shave` tool for {len(review_american):,} GenAm review words...")
        review_list = sorted(review_american)
        BATCH_SIZE = 5000
        for batch_start in range(0, len(review_list), BATCH_SIZE):
            batch = review_list[batch_start:batch_start + BATCH_SIZE]
            batch_results, batch_wsd = _batch_shave(batch, dialect="american")
            shave_results_american.update(batch_results)
            for w, pct in batch_wsd.items():
                wsd_american[w] = min(wsd_american[w], pct) if w in wsd_american else pct
            if batch_start > 0 and batch_start % 10000 == 0:
                print(f"    ...shave processed {batch_start:,}/{len(review_list):,}")
        print(f"  Got shave results for {len(shave_results_american):,} GenAm words "
              f"({len(wsd_american):,} WSD-ambiguous).")

    if review_british or review_american:
        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in reliable.items():
            for e in entries:
                if e.get("confidence", 89) >= 89:
                    continue
                shave_dialect = VAR_SHAVE_DIALECT.get(e.get("var"))
                if shave_dialect == "british":
                    shave_results = shave_results_british
                    wsd_dict = wsd_british
                elif shave_dialect == "american":
                    shave_results = shave_results_american
                    wsd_dict = wsd_american
                else:
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue
                shave_shaw = shave_results[w]
                ml_shaw = e.pop("_ml_shaw", None)
                notes = [n for n in e.get("review", "").split("; ") if n]

                phrase_wsd = None
                for token in w.lower().split():
                    pct = wsd_dict.get(token)
                    if pct is not None:
                        phrase_wsd = pct if phrase_wsd is None else min(phrase_wsd, pct)

                new_pct, notes, override = upgrade_confidence_shave(
                    e["confidence"], notes, e["Shaw"], shave_shaw, ml_shaw,
                    wsd_confidence=phrase_wsd,
                )
                e["confidence"] = new_pct
                e["review"] = "; ".join(notes) if notes else ""
                if override:
                    e["Shaw"] = override
                    shave_overridden += 1
                elif new_pct > e.get("confidence", 0):
                    shave_upgraded += 1

        # Fix keys for overridden entries in reliable dict
        new_reliable = {}
        for key, entries in reliable.items():
            new_key = make_key(entries[0]["Latn"], entries[0]["pos"], entries[0]["Shaw"])
            new_reliable[new_key] = entries
        reliable = new_reliable

        print(f"  Upgraded {shave_upgraded:,} entries based on shave agreement")
        print(f"  Overrode {shave_overridden:,} entries based on shave+ML consensus")

    # Clean up internal fields and compute final stats
    conf_buckets = {"high (>=80)": 0, "medium (30-79)": 0, "low (<30)": 0}
    for d in (reliable, speculative):
        for key, entries in d.items():
            for e in entries:
                e.pop("_ml_shaw", None)
                if not e.get("review"):
                    e.pop("review", None)
                pct = e.get("confidence", 89)
                if pct >= 80:
                    conf_buckets["high (>=80)"] += 1
                elif pct >= 30:
                    conf_buckets["medium (30-79)"] += 1
                else:
                    conf_buckets["low (<30)"] += 1

    print(f"\n  Final confidence: {conf_buckets}")

    # Write outputs
    print(f"Writing reliable supplement ({len(reliable):,} keys)...")
    RELIABLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(RELIABLE_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(reliable, f, ensure_ascii=False, indent=2)
    print(f"  -> {RELIABLE_OUTPUT}")

    print(f"Writing speculative supplement ({len(speculative):,} keys)...")
    with open(SPECULATIVE_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(speculative, f, ensure_ascii=False, indent=2)
    print(f"  -> {SPECULATIVE_OUTPUT}")

    print()
    print("=== Summary ===")
    print(f"Total lines in JSONL:       {total_lines:,}")
    print(f"Non-English skipped:        {stats['non_english']:,}")
    print(f"English entries with sounds: {stats['total_entries']:,}")
    print(f"Sound items with IPA:       {stats['with_ipa']:,}")
    print(f"Skipped affix words:        {stats['skipped_affix']:,}")
    print(f"Skipped fragment IPA:       {stats['skipped_fragment_ipa']:,}")
    print(f"Dropped sub-national geo:   {stats['dropped_subnational_geo']:,}")
    print(f"Shavian conversion errors:  {stats['shavian_errors']:,}")
    print(f"JSON parse errors:          {stats['json_errors']:,}")
    print()
    print(f"Reliable entries (accent-labelled):")
    print(f"  Total:  {stats['reliable_entries']:,}")
    for var, _sel, _ns in KEEP_ACCENTS:
        print(f"  {var:7} {stats[f'var_{var}']:,}")
    print(f"  Keys:   {len(reliable):,}")
    print()
    print(f"Speculative entries ({UNTAGGED_VAR}, no accent label):")
    print(f"  Total:  {stats['speculative_entries']:,}")
    print(f"  {UNTAGGED_VAR:7} {stats[f'var_{UNTAGGED_VAR}']:,}")
    print(f"  Keys:   {len(speculative):,}")
    print(f"  Records carrying info quality-tags: "
          f"{stats['records_with_info']:,}")
    print()
    print(f"Confidence breakdown (final):")
    print(f"  {conf_buckets}")


if __name__ == "__main__":
    main()
