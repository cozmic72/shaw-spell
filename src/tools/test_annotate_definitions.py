#!/usr/bin/env python3
"""Focused tests for annotate_definitions.annotate — the pure has_definition pass.

has_definition tests the shipped definition ARTIFACT (the lowercased headword
set of definitions-latin-{gb,us}.json): true iff an entry exists for the
record's word — exactly what the editor and dictionaries display. Source
attestation and POS are deliberately not consulted (the editor looks up by
lowercased headword alone). These tests pin that: artifact-backed goes True
regardless of source, artifact-absent goes False even when WordNet-attested,
and lookup is case-insensitive.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import annotate_definitions as ad


def _record(latn, pos, source):
    return {"Latn": latn, "pos": pos, "source": source}


def test_annotate_artifact_membership_semantics():
    # The artifact carries cat and widget; robot has no entry anywhere.
    def_lemmas = {"cat", "widget"}

    supplement = {
        "cat": [_record("cat", "NN1", ["wordnet"])],
        "widget": [_record("widget", "NN1", ["wiktionary"])],
        "robot": [_record("robot", "NN1", ["wordnet", "generated"])],
    }
    ad.annotate(supplement, def_lemmas)

    # In the artifact -> True, whatever the attesting source.
    assert supplement["cat"][0]["has_definition"] is True
    assert supplement["widget"][0]["has_definition"] is True

    # NOT in the artifact -> False, even though WordNet-attested (the fix:
    # upstream provenance must never over-claim what is displayable).
    assert supplement["robot"][0]["has_definition"] is False


def test_artifact_lemma_matches_lowercased_word():
    # The artifact headword set is lowercased; a capitalised record matches.
    def_lemmas = {"paris"}
    supplement = {"Paris": [_record("Paris", "NP0", ["wordnet"])]}
    ad.annotate(supplement, def_lemmas)
    assert supplement["Paris"][0]["has_definition"] is True


def test_build_def_lemmas_reads_artifact_headwords():
    # The real artifact: keys are `lemma|synset`, lemmas come back lowercased.
    def_lemmas = ad.build_def_lemmas()
    assert "aioli" in def_lemmas


if __name__ == "__main__":
    test_annotate_artifact_membership_semantics()
    test_artifact_lemma_matches_lowercased_word()
    test_build_def_lemmas_reads_artifact_headwords()
    print("all tests passed")
