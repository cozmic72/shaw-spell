#!/usr/bin/env python3
"""The publish stage order: FREQUENCY BEFORE PATCHES, patches are the last word.

Runs editord._publish_readlex hermetically — synthetic upstream, corpus, LRW and
patch store, a temp output path — by rebinding the module attributes it imports
at call time. Locks in the invariants the reorder established:

  - a PATCHED freq survives publish verbatim (the regression that would return
    silently if a frequency pass ever ran after apply_patches again)
  - an un-patched upstream record ships the corpus-derived freq (the upstream
    enrichment stage did run — just before the overlay, not after)
  - an accept without a freq edit inherits the startup-enriched BASIS freq
  - a MANUAL record ships a real corpus freq (#115), including one
    whose stored changes carry the legacy baked `freq: 0`; a non-zero manual
    freq is an owner override and wins
  - a daemon whose basis was never enriched (started without frequency data)
    refuses to publish (PublishError), never ships un-scaled freqs silently

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import apply_frequency_data
import apply_patches as apply_patches_module
import basis
import lrw_frequencies
import editord

SHAW_CAT = "\U00010450"
SHAW_DOG = "\U00010451"
SHAW_Z1 = "\U00010452"
SHAW_Z2 = "\U00010453"
SHAW_Z3 = "\U00010454"

CORPUS = {"cat": 100, "dog": 50, "zebra": 77, "okapi": 66, "quagga": 55}


def upstream_entry(latn, pos, shaw, freq=1):
    """An upstream ReadLex entry as load_upstream yields it (ReadLex-scale freq
    the enrichment stage must replace)."""
    return {"Latn": latn, "Shaw": shaw, "pos": pos, "ipa": "", "freq": freq,
            "var": "RRP"}


def make_upstream():
    return {
        f"cat_NN1_{SHAW_CAT}": [upstream_entry("cat", "NN1", SHAW_CAT)],
        f"dog_NN1_{SHAW_DOG}": [upstream_entry("dog", "NN1", SHAW_DOG)],
    }


def make_view():
    """The daemon's resident, startup-enriched basis: upstream rides in it, and
    the pool pass already put every record on the corpus scale."""
    index, source = {}, {}
    for bucket in make_upstream().values():
        for entry in bucket:
            entry = dict(entry, freq=CORPUS[entry["Latn"].lower()])
            key = basis.anchor_of(entry)
            index[key] = entry
            source[key] = ["readlex"]
    return SimpleNamespace(basis_index=index, basis_source=source,
                           freq_enriched=True)


def manual_changes(word, shaw, freq=None):
    changes = {"word": word, "shaw": shaw, "pos": "NN1", "var": "RRP",
               "status": "manual"}
    if freq is not None:
        changes["freq"] = freq
    return changes


PATCHES = [
    # A freq override on an accepted upstream record: MUST ship verbatim.
    {"id": "p_cat", "op": "accept", "changes": {"freq": 5},
     "anchor": {"word": "cat", "pos": "NN1", "shaw": SHAW_CAT, "var": "RRP"},
     "meta": {"author": "joro", "ts": "2026-01-01T00:00:00Z"}},
    # An accept with no freq edit: inherits the startup-enriched basis freq.
    {"id": "p_dog", "op": "accept", "changes": {},
     "anchor": {"word": "dog", "pos": "NN1", "shaw": SHAW_DOG, "var": "RRP"},
     "meta": {"author": "joro", "ts": "2026-01-01T00:00:00Z"}},
    # Manual records: no stored freq, the legacy baked 0, and an owner override.
    {"id": "p_zebra", "anchor": None, "op": None,
     "changes": manual_changes("zebra", SHAW_Z1),
     "meta": {"author": "joro", "ts": "2026-01-01T00:00:00Z"}},
    {"id": "p_okapi", "anchor": None, "op": None,
     "changes": manual_changes("okapi", SHAW_Z2, freq=0),
     "meta": {"author": "joro", "ts": "2026-01-01T00:00:00Z"}},
    {"id": "p_quagga", "anchor": None, "op": None,
     "changes": manual_changes("quagga", SHAW_Z3, freq=9),
     "meta": {"author": "joro", "ts": "2026-01-01T00:00:00Z"}},
]


class _rebound:
    """Rebind module attributes for the duration of the block, restoring them
    on exit — _publish_readlex imports these at call time, so the rebinding is
    what it sees."""

    def __init__(self, bindings):
        self._bindings = bindings

    def __enter__(self):
        self._saved = [(mod, name, getattr(mod, name))
                       for mod, name, _ in self._bindings]
        for mod, name, value in self._bindings:
            setattr(mod, name, value)

    def __exit__(self, *_exc):
        for mod, name, value in self._saved:
            setattr(mod, name, value)
        return False


def run_publish(view, tmp):
    """_publish_readlex over the synthetic world; returns the published dict."""
    corpus_file = tmp / "corpus.txt"
    corpus_file.write_text("stub\n", encoding="utf-8")
    out_path = tmp / "readlex.json"
    store = tmp / "patches.jsonl"
    store.write_text("".join(json.dumps(p) + "\n" for p in PATCHES),
                     encoding="utf-8")
    lrw_stub = SimpleNamespace(surface_readings={}, parent_lemmas={})
    bindings = [
        (apply_patches_module, "OUTPUT_PATH", out_path),
        (apply_frequency_data, "CORPUS_PATH", corpus_file),
        (apply_frequency_data, "load_corpus", lambda: dict(CORPUS)),
        (lrw_frequencies, "load_lrw", lambda: lrw_stub),
        (basis, "load_upstream", make_upstream),
    ]
    prev_store = os.environ.get("SHAW_SPELL_PATCH_STORE")
    os.environ["SHAW_SPELL_PATCH_STORE"] = str(store)
    try:
        with _rebound(bindings):
            editord._publish_readlex(view)
    finally:
        if prev_store is None:
            os.environ.pop("SHAW_SPELL_PATCH_STORE", None)
        else:
            os.environ["SHAW_SPELL_PATCH_STORE"] = prev_store
    return json.loads(out_path.read_text(encoding="utf-8"))


def freq_of(published, word):
    matches = [entry for bucket in published.values() for entry in bucket
               if entry["Latn"] == word]
    assert len(matches) == 1, f"expected exactly one {word!r}, got {matches}"
    return matches[0]["freq"]


def test_publish_freq_order_and_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        published = run_publish(make_view(), Path(tmp))
    # The patched freq is the LAST WORD: a post-patch frequency pass would
    # overwrite this back to the corpus 100 — the silent regression this locks out.
    assert freq_of(published, "cat") == 5, freq_of(published, "cat")
    # An accept with no freq edit inherits the startup-enriched basis freq.
    assert freq_of(published, "dog") == 50, freq_of(published, "dog")
    # Manual records ship a real corpus freq (#115) — the pre-patch pass covers
    # the manual wing; the legacy baked `freq: 0` is "no data", not an override.
    assert freq_of(published, "zebra") == 77, freq_of(published, "zebra")
    assert freq_of(published, "okapi") == 66, freq_of(published, "okapi")
    # A non-zero manual freq IS an owner override and wins.
    assert freq_of(published, "quagga") == 9, freq_of(published, "quagga")


def test_publish_refuses_unenriched_basis():
    view = make_view()
    view.freq_enriched = False
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_publish(view, Path(tmp))
        except editord.PublishError:
            return
    raise AssertionError("publish over an unenriched basis must raise PublishError")


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
