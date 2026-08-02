#!/usr/bin/env python3
"""
Combine upstream ReadLex core and the per-source supplement candidates into ONE
pool before pruning, so every downstream filter runs on the union rather than
per-source in parallel.

ReadLex core is JUST DATA here — the best Shavian-spelling source there is — and
it enters the pool as ordinary bucketed records like any other source, FIRST in
precedence: on a same-anchor collision core wins content and a later source only
adds its label. Core records are flagged by their `readlex` source label (the
basis.is_upstream test, which doubles as the editor's not-new novelty marker) and
ride the whole pruning chain untouched: every downstream stage may read them (the
RRP-lane occupancy guard, established scopes, canonical attestations) but never
drops, relabels, respells or flag-mutates one. Folding core in HERE is what lets
reclassify_rrp's pool-only occupancy guard see core RRP lanes without any stage
side-loading readlex.json.

Historically each source (wordnet, wiktionary) was threaded through the whole
pruning chain independently and only met at the basis. That let a cross-source
duplicate slip through: the identical-spelling dialect prune (collapse_identical_
dialects.py) runs per group and could not see that one source's GenAm spelling
and another source's RSSB spelling of the SAME word were the same fact. Combining
first puts both in one group, so the prune collapses them to one record.

Merge key = the FULL anchor (word.lower(), pos, Shaw, var, lemma), exactly the
identity basis.anchor_of computes. Two records sharing all five slots are ONE
record and their `source` labels union; two records sharing (word, pos, shaw)
but differing in `var` are KEPT SEPARATE — the dialect prune adjudicates those
downstream. Records differing only in lemma (`axes` under both `ax` and `axe`
upstream) are likewise distinct facts and both survive. A LEMMA-LESS arrival
(every supplement source) attests the WORDFORM, not a lemma, so it unions its
label onto every record already carrying its (word, pos, shaw, var) — whatever
their lemmas — and only becomes a record of its own (self-referenced) when no
one does.

Records gain a `source` LIST field here (they carry none in their input files).
Sources are iterated in canonical order; the first to attest an anchor keeps its
record verbatim (readlex wins on content, then wordnet), and every later source
that also attests the anchor only adds its label to the list.

Inputs:  external/readlex/readlex.json (upstream core, reinterpreted onto the
         dialect model at load — basis.load_upstream),
         data/supplement-wordnet-reliable.json (wordnet uses reliable directly),
         data/supplement-wiktionary-neardot.json (wiktionary after rescue +
         NEAR syllable-dot correction), and data/supplement-names.json (the
         curated proper-name slice).
Output:  data/supplement-combined-raw.json  — the duplicate filter reads this
         next. The input files are left untouched.

Usage:
    python3 src/tools/combine_supplements.py
"""

import json
from collections import Counter

from basis import (LEMMA_FIELD, PROJECT_ROOT, UPSTREAM_PATH, UPSTREAM_SOURCE,
                   anchor_of, load_upstream, self_lemma)

# Canonical source order: the first source to attest an anchor keeps its record
# verbatim. ReadLex core is FIRST — the sanctioned dictionary wins content on
# any same-anchor collision (owner: given readlex vs wordnet, readlex wins) —
# then wordnet, matching the pre-fold load order among the supplements.
SOURCES = [
    # Upstream ReadLex core, collated into the pool as ordinary records. Its
    # `readlex` label is the upstream flag (basis.is_upstream) every downstream
    # stage consults: core records are never dropped, relabelled or flag-mutated,
    # and they seed the RRP-lane occupancy guard by pure existence.
    (UPSTREAM_SOURCE, UPSTREAM_PATH),
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-neardot.json"),
    # Curated proper-name slice (shave+CMUdict agreement, synthetic). Its own
    # `names` label keeps the name flood filterable in the review surface. These
    # are wiktionary-dropped names, but the label reflects what they are (names).
    # Records carry synthetic/tier/shaw_source through to the basis. Read via
    # the CMUdict IPA-fill pass (fill_names_ipa.py): supplement-names.json plus
    # round-trip-confirmed `ipa`/`ipa_source` where CMU knows the name.
    ("names", PROJECT_ROOT / "data" / "supplement-names-ipa.json"),
    # Shave-generated slice: net-new WordNet words with a gloss+POS but no IPA
    # (dropped into supplement-wordnet-speculative), attested in the frequency
    # corpus, spelled by shave (Roman->Shavian G2P). Its own `generated` label
    # keeps the synthetic G2P flood filterable in the review surface. Records
    # carry synthetic/tier/shaw_source/origin through to the basis. See
    # src/tools/generate_supplement_speculative.py. Read via the neural G2P
    # IPA-fill pass (fill_generated_ipa.py): supplement-generated.json plus
    # voter-gated (round-trip + likelihood) `ipa`/`ipa_source`/`confidence`.
    ("generated", PROJECT_ROOT / "data" / "supplement-generated-ipa.json"),
]

OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-raw.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_source(label, path):
    """Load one source pool. The upstream ReadLex source is reinterpreted onto
    the dialect model at this consumption seam (basis.load_upstream — TrapBath ->
    RRP+mergers, RRPVar -> RRP+variant, the Gen Am typo), exactly the shape every
    pipeline reader sees; supplement sources load verbatim."""
    if label == UPSTREAM_SOURCE:
        return load_upstream()
    return load_json(path)


def load_sources():
    """Every source pool loaded in canonical order — the single load edge the
    orchestrator (build_supplement.py) and the CLI main share."""
    return [(label, load_source(label, path)) for label, path in SOURCES]


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def combine_sources(sources_data, tallies):
    """Merge already-loaded per-source supplements into one anchor-keyed pool.
    `sources_data` is a list of (label, supplement_dict) in canonical source order.
    Returns an anchor -> record map in first-seen order; each record carries a
    `source` list accumulating every origin that attested its anchor, deduped and
    order-stable. Pure over its inputs (no disk I/O).

    A record arriving with no `lemma` (every supplement source: they have no
    upstream bucket structure to state one) attests the WORDFORM: its label
    unions onto every record already on its (word, pos, shaw, var), whatever
    their lemmas. Only when none exists does it become a record of its own, as
    its OWN lemma — self-reference, not a guess at which other record it might
    belong under (that inference is a separate future job). This leans on
    SOURCES order: the lemma-stating source (upstream) precedes every lemma-less
    one, so a wordform's lemma-carrying records all exist before any lemma-less
    arrival is judged — reordering would mint self-referenced twins."""
    merged = {}
    by_wordform = {}
    for label, supplement in sources_data:
        for entries in supplement.values():
            for entry in entries:
                anchor = anchor_of(entry)
                if anchor in merged:
                    targets = [merged[anchor]]
                elif not entry.get(LEMMA_FIELD):
                    targets = [merged[full] for full
                               in by_wordform.get(anchor[:4], ())]
                else:
                    targets = []
                if targets:
                    for record in targets:
                        sources = record["source"]
                        if label not in sources:
                            sources.append(label)
                    tallies["merged"] += 1
                else:
                    record = dict(entry)
                    record["source"] = [label]
                    if not record.get(LEMMA_FIELD):
                        record[LEMMA_FIELD] = self_lemma(record)
                    full = anchor_of(record)
                    merged[full] = record
                    by_wordform.setdefault(full[:4], []).append(full)
                    tallies["records"] += 1
    return merged


def bucket(merged):
    """Group the merged records into the `word_pos_shaw` buckets the pruning chain
    reads, buckets sorted and records in first-seen order for a byte-stable file."""
    buckets = {}
    for record in merged.values():
        buckets.setdefault(output_bucket_key(record), []).append(record)
    return {key: buckets[key] for key in sorted(buckets)}


def build_combined(sources_data, tallies):
    """Combine already-loaded sources into the bucketed `word_pos_shaw` dict the
    pruning chain consumes. The in-memory entry point the orchestrator calls."""
    return bucket(combine_sources(sources_data, tallies))


def report(tallies):
    print("\n=== supplement combine report ===")
    print(f"Distinct anchors (records): {tallies['records']:,}")
    print(f"Cross-anchor attestations merged into source lists: "
          f"{tallies['merged']:,}")


def main():
    tallies = Counter()
    sources_data = load_sources()
    buckets = build_combined(sources_data, tallies)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(buckets, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in buckets.values()):,} records")
    report(tallies)


if __name__ == "__main__":
    main()
