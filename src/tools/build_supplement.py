#!/usr/bin/env python3
"""
Supplement build orchestrator: LOAD sources once -> compose every preprocessing
transform IN MEMORY -> WRITE data/supplement-combined-filtered.json once.

This replaces the old disk-round-tripping pipeline of 9 standalone scripts glued
by hardcoded intermediate JSON paths (combined-raw -> combined-defs -> ... ->
combined-filtered). That chain was disk-bound, littered data/ with 8 throwaway
files, and LIED TO MAKE: the real ordering lived in the Python hardcoded paths,
not the Makefile prerequisites, so `make -j` could race and corrupt the build.

Here the orchestrator OWNS the ordering in memory. Each step module keeps a thin
CLI main() for single-stage debugging, but this orchestrator imports and calls
the modules' PURE record-transform functions directly, records flowing in memory
stage to stage, one read at the front and one write at the back.

THE CHAIN (identical order + behaviour to the old .mk chain):
  combine  -> annotate_definitions -> filter_duplicates -> classify_mergers ->
  reclassify_rrp -> generate_rrp -> collapse_dialects -> filter_contamination ->
  filter_phrases -> data/supplement-combined-filtered.json

Records are the bucketed `{word_pos_shaw: [record, ...]}` dict every stage
already reads/writes; each pure function takes that dict (+ its threaded deps)
and returns the next. File I/O is peeled to the edges of this module only.

DEPENDENCY EDGES (loaded once, threaded as arguments):
  - the three source pools (wordnet-reliable, wiktionary-neardot, names)   -> combine
  - WordNet YAML + Wiktionary JSONL definition key sets                    -> annotate
  - RAW upstream ReadLex + patches (established index, exempt anchors)      -> dedup
  - REINTERPRETED upstream ReadLex (load_upstream)                         -> classify, generate
  - the phrase label classifier (citation index over readlex + reliable)   -> phrases
  - shave (Roman->Shavian G2P for no-IPA names, non-deterministic)          -> generate
    ONLY when the shave/names path is enabled (see below) — OFF by default.

SHAVE/NAMES PATH (default OFF): generate_rrp's no-IPA proper-name path is an
OWNER-UNDECIDED feature and is DISABLED by default, so the committed build is
IPA-basis only. Enable it explicitly with SHAW_SPELL_ENABLE_SHAVE_NAMES=1 (or
build_supplement(enable_shave=True)); off, shave is never invoked and no-ipa
records pass through verbatim.

FAIL-FAST: any stage raising aborts the whole build (no silent fallbacks).
patches.jsonl is READ-ONLY here (dedup, contamination, phrases read it; nothing
writes it). Determinism: every stage is a pure, byte-deterministic function of its
input. The only exception is generate's shave/names path — and that is OFF by
default; when explicitly enabled its low-confidence name proposals can drift
run-to-run (documented in generate_rrp) and its shave call is injectable so a
parity harness can pin it.

--dump (debug only, OFF by default): also write each stage's intermediate to
data/supplement-combined-<stage>.json — the old on-disk artifacts — for single-
stage inspection. Make never depends on these; the orchestrator owns ordering.

Usage:
    python3 src/tools/build_supplement.py [--out PATH] [--dump]
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from basis import PROJECT_ROOT, load_json, load_upstream

import combine_supplements as combine_mod
import annotate_definitions as annotate_mod
import filter_supplement_duplicates as dedup_mod
import classify_dialect_mergers as classify_mod
import reclassify_rrp as reclassify_mod
import generate_rrp as generate_mod
import collapse_identical_dialects as collapse_mod
import filter_supplement_contamination as contam_mod
import filter_supplement_phrases as phrase_mod
from detect_phrase_divergence import build_label_classifier

OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-filtered.json"

# Debug intermediate names, matching the old per-stage .mk targets. Only written
# under --dump; Make never depends on them.
DUMP_NAMES = {
    "combined": "supplement-combined-raw.json",
    "defs": "supplement-combined-defs.json",
    "deduped": "supplement-combined-deduped.json",
    "classified": "supplement-combined-classified.json",
    "reclassified": "supplement-combined-reclassified.json",
    "generated": "supplement-combined-generated.json",
    "collapsed": "supplement-combined-collapsed.json",
    "decontaminated": "supplement-combined-decontaminated.json",
    "filtered": "supplement-combined-filtered.json",
}


def write_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=4)


def count(supplement):
    return sum(len(v) for v in supplement.values())


def build_supplement(shave_fn=None, enable_shave=None):
    """Run the full in-memory supplement build and return the final bucketed
    supplement dict (the thing data/supplement-combined-filtered.json holds).

    Yields (stage_name, supplement) as each stage completes, so a caller (main,
    a --dump run, a parity harness) can observe every intermediate WITHOUT the
    orchestrator writing anything itself. `shave_fn` is threaded into generate_rrp
    (None = the real shave subprocess); a parity harness pins it here.

    `enable_shave` gates the OWNER-UNDECIDED shave/names path in generate_rrp and
    DEFAULTS OFF: None resolves to SHAW_SPELL_ENABLE_SHAVE_NAMES in the environment
    (1/true/yes/on = enabled), else generate_rrp's ENABLE_SHAVE_NAMES (False). Off,
    shave is never invoked and the build is IPA-basis only.

    Fail-fast: any stage raising propagates out and aborts the build."""
    if enable_shave is None:
        env = os.environ.get("SHAW_SPELL_ENABLE_SHAVE_NAMES", "")
        enable_shave = env.strip().lower() in ("1", "true", "yes", "on")
    if enable_shave:
        print("generate_rrp: shave/names path ENABLED "
              "(SHAW_SPELL_ENABLE_SHAVE_NAMES)", file=sys.stderr)
    # --- LOAD EDGES (once) -------------------------------------------------
    print("Loading source pools...", file=sys.stderr)
    sources_data = [(label, load_json(path))
                    for label, path in combine_mod.SOURCES]

    print("Loading upstream ReadLex (raw + reinterpreted) and patches...",
          file=sys.stderr)
    raw_upstream = load_json(dedup_mod.UPSTREAM_PATH)
    reinterpreted_upstream = load_upstream()
    patches = dedup_mod.load_patches()
    established_index = dedup_mod.build_established_index(raw_upstream, patches)
    exempt_keys = dedup_mod.anchored_keys(patches)

    print("Building definition key sets (WordNet YAML + Wiktionary JSONL)...",
          file=sys.stderr)
    wn_keys, wikt_keys = annotate_mod.build_def_keys()

    print("Building phrase label classifier...", file=sys.stderr)
    label_of = build_label_classifier()

    # --- COMPOSE (in memory) ----------------------------------------------
    # 1. combine
    supplement = combine_mod.build_combined(sources_data, Counter())
    yield "combined", supplement

    # 2. annotate definitions (mutates in place)
    supplement = annotate_mod.annotate(supplement, wn_keys, wikt_keys)
    yield "defs", supplement

    # 3. duplicate filter
    supplement = dedup_mod.filter_supplement(
        supplement, established_index, exempt_keys,
        Counter(), {r: [] for r in ("exact-var", "rrp-wildcard", "pos-broadening")},
        {kind: [] for kind in dedup_mod.KEPT_CLOSE_KINDS})
    yield "deduped", supplement

    # 4. classify dialect mergers
    supplement = classify_mod.classify_supplement(
        supplement, Counter(), defaultdict(list),
        upstream=reinterpreted_upstream)
    yield "classified", supplement

    # 5. reclassify RRP (pure judge/relabel; count-preserving)
    #    Same fail-loud invariant the stage's CLI main() enforces: this stage
    #    relabels but never drops or merges, so a count change is a bug.
    supplement, n_in = reclassify_mod.reclassify_supplement(
        supplement, Counter(), defaultdict(list))
    n_out = count(supplement)
    if n_out != n_in:
        raise SystemExit(
            f"reclassify_rrp: record count changed ({n_in} -> {n_out}); this "
            f"stage relabels but never drops or merges — a count change is a bug")
    yield "reclassified", supplement

    # 6. generate RRP proposals + flag-gate (shave/names path threaded, gated off
    #    by default — IPA-basis only unless enable_shave is explicitly set)
    #    Count-preserving: only ADDS proposal fields and STRIPS gated flags, never
    #    drops or splits a record (mirrors the stage's CLI fail-loud guard).
    n_in = count(supplement)
    supplement = generate_mod.process(
        supplement, Counter(), defaultdict(list), Counter(), defaultdict(list),
        upstream=reinterpreted_upstream, shave_fn=shave_fn,
        enable_shave=enable_shave)
    n_out = count(supplement)
    if n_out != n_in:
        raise SystemExit(
            f"generate_rrp: record count changed ({n_in} -> {n_out}); this stage "
            f"only ADDS proposal fields and STRIPS gated flags — it never drops or "
            f"splits a record, so a count change is a bug")
    yield "generated", supplement

    # 7. collapse identical-spelling dialects
    supplement = collapse_mod.collapse_supplement(
        supplement, Counter(), [])
    yield "collapsed", supplement

    # 8. contamination prune
    supplement, _dropped = contam_mod.prune_supplement(
        supplement, exempt_keys, [])
    yield "decontaminated", supplement

    # 9. phrase prune
    supplement, _dropped = phrase_mod.prune_supplement(
        supplement, label_of, exempt_keys, [], [])
    yield "filtered", supplement


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUTPUT_PATH,
                    help="final output path (default supplement-combined-filtered.json)")
    ap.add_argument("--dump", action="store_true",
                    help="also write each stage's intermediate JSON (debug only)")
    args = ap.parse_args()

    data_dir = PROJECT_ROOT / "data"
    final = None
    for stage, supplement in build_supplement():
        n = count(supplement)
        print(f"[{stage:15}] {n:,} records", file=sys.stderr)
        if args.dump:
            dump_path = data_dir / DUMP_NAMES[stage]
            write_json(supplement, dump_path)
            print(f"    dumped -> {dump_path.relative_to(PROJECT_ROOT)}",
                  file=sys.stderr)
        final = supplement

    if final is None:
        raise SystemExit("build_supplement: pipeline produced no stages")

    write_json(final, args.out)
    print(f"Wrote {args.out}: {count(final):,} records")


if __name__ == "__main__":
    main()
