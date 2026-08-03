#!/usr/bin/env python3
"""Unit tests for the lemma-anchor migration planner (migrate_patch_lemmas)
and combine's lemma-aware wordform-union rule — pure functions over synthetic
fixtures; the live store, basis and upstream are never touched.

Run:
    python3 src/tools/test_migrate_patch_lemmas.py
"""

import sys
import traceback
from collections import Counter

from combine_supplements import combine_sources
from migrate_patch_lemmas import (KIND_AMBIGUOUS, KIND_BASIS, KIND_UNRESOLVED,
                                  KIND_UPSTREAM, basis_wordform_map,
                                  plan_migration, resolve_lemma, stamped_patch)
from basis import anchor_of

SHAW = "\U00010450"
SHAW2 = "\U00010451"


def lemma(latn, pos="NN1", shaw=SHAW):
    return {"Latn": latn, "pos": pos, "Shaw": shaw}


def entry(latn, pos, shaw, var="RRP", lem=None):
    e = {"Latn": latn, "pos": pos, "Shaw": shaw, "ipa": "", "freq": 0,
         "var": var}
    if lem:
        e["lemma"] = lem
    return e


def patch(word, pos, shaw, var="RRP", op="accept", lem=None, pid="p_t"):
    anchor = {"word": word, "pos": pos, "shaw": shaw, "var": var}
    if lem:
        anchor["lemma"] = lem
    return {"id": pid, "anchor": anchor, "op": op, "changes": {}, "meta": {}}


WF = ("axes", "VVZ", SHAW, "RRP")


def test_resolve_upstream_unique():
    kind, lem = resolve_lemma(WF, {WF: [lemma("ax")]}, {})
    assert (kind, lem) == (KIND_UPSTREAM, lemma("ax"))


def test_resolve_upstream_ambiguous():
    kind, lems = resolve_lemma(WF, {WF: [lemma("ax"), lemma("axe")]}, {})
    assert kind == KIND_AMBIGUOUS and len(lems) == 2


def test_resolve_basis_uses_stored_lemma_not_self():
    # A var-relabelled upstream inflection misses the raw-upstream map but
    # resolves in the basis WITH a stated (non-self) lemma: that stored lemma
    # must be stamped, never a computed self-reference.
    e = entry("axes", "VVZ", SHAW, lem=lemma("ax"))
    basis_map = basis_wordform_map({anchor_of(e): e})
    kind, lem = resolve_lemma(WF, {}, basis_map)
    assert (kind, lem) == (KIND_BASIS, lemma("ax"))


def test_resolve_basis_self_fallback_on_prelemma_artifact():
    e = entry("axes", "VVZ", SHAW)  # no stored lemma (un-regenerated pool)
    basis_map = basis_wordform_map({anchor_of(e): e})
    kind, lem = resolve_lemma(WF, {}, basis_map)
    assert (kind, lem) == (KIND_BASIS, lemma("axes", "VVZ"))


def test_resolve_unresolved():
    assert resolve_lemma(WF, {}, {}) == (KIND_UNRESOLVED, None)


def test_plan_partitions_all_classes():
    upstream_map = {("dogs", "NN2", SHAW, "RRP"): [lemma("dog")],
                    WF: [lemma("ax"), lemma("axe")]}
    e = entry("solo", "NN1", SHAW2)
    basis_map = basis_wordform_map({anchor_of(e): e})
    patches = [
        patch("dogs", "NN2", SHAW, pid="p_up"),
        patch("axes", "VVZ", SHAW, pid="p_amb"),
        patch("solo", "NN1", SHAW2, pid="p_self"),
        patch("gone", "NN1", SHAW2, pid="p_gone"),
        patch("dogs", "NN2", SHAW, lem=lemma("dog"), pid="p_done"),
        patch("dogs", "NN2", SHAW, lem=lemma("hound"), pid="p_conf"),
        {"id": "p_auth", "anchor": None, "op": None, "changes": {}, "meta": {}},
    ]
    stamps, ambiguous, unresolved, conflicts, counts = plan_migration(
        patches, upstream_map, basis_map)
    assert [(p["id"], kind) for _i, p, kind, _l in stamps] == \
        [("p_up", KIND_UPSTREAM), ("p_self", KIND_BASIS)]
    assert [p["id"] for _i, p, _l in ambiguous] == ["p_amb"]
    assert [p["id"] for _i, p in unresolved] == ["p_gone"]
    assert [p["id"] for _i, p, _l in conflicts] == ["p_conf"]
    assert counts == {"manual": 1, "already": 1}


def test_stamped_patch_touches_only_the_anchor_lemma():
    original = patch("dogs", "NN2", SHAW, pid="p_up")
    stamped = stamped_patch(original, lemma("dog"))
    assert stamped["anchor"].pop("lemma") == lemma("dog")
    assert stamped["anchor"] == original["anchor"]
    assert {k: v for k, v in stamped.items() if k != "anchor"} == \
        {k: v for k, v in original.items() if k != "anchor"}


def test_combine_unions_lemmaless_arrival_onto_every_wordform_twin():
    ax = entry("axes", "VVZ", SHAW, lem=lemma("ax"))
    axe = entry("axes", "VVZ", SHAW, lem=lemma("axe"))
    wordnet = entry("axes", "VVZ", SHAW)  # lemma-less supplement attestation
    merged = combine_sources(
        [("readlex", {"a": [ax, axe]}), ("wordnet", {"b": [wordnet]})],
        Counter())
    records = list(merged.values())
    assert len(records) == 2, "both lemma twins survive, no third record"
    assert all(r["source"] == ["readlex", "wordnet"] for r in records)


def test_combine_self_references_a_novel_lemmaless_record():
    novel = entry("brandnew", "NN1", SHAW2)
    merged = combine_sources([("wordnet", {"b": [novel]})], Counter())
    (record,) = merged.values()
    assert record["lemma"] == lemma("brandnew", "NN1", SHAW2)


def main():
    tests = sorted((name, fn) for name, fn in globals().items()
                   if name.startswith("test_") and callable(fn))
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
