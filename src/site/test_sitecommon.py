#!/usr/bin/env python3
"""Tests for the ordering rule the page and its preview card share.

searched_first returns a LIST. A caller that treats it as a single summary
shipped a 500 on every entry page (6120f63), so the shape is asserted here
as well as the ordering.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sitecommon import contains_shavian, searched_first


def _summary(latin, shaw):
    return {"latin": latin, "shaw": shaw, "ipa": "", "forms": [], "pos": []}


SPELL = _summary("spell", "𐑕𐑐𐑧𐑤")
SPELLING = _summary("spelling", "𐑕𐑐𐑧𐑤𐑦𐑙")


def test_returns_a_list_not_a_summary():
    out = searched_first("spell", [SPELL])
    assert isinstance(out, list), type(out)
    assert out[0]["latin"] == "spell"


def test_searched_inflection_leads_its_lemma():
    out = searched_first("spelling", [SPELL, SPELLING])
    assert [s["latin"] for s in out] == ["spelling", "spell"]


def test_lemma_search_keeps_the_lemma_first():
    out = searched_first("spell", [SPELL, SPELLING])
    assert [s["latin"] for s in out] == ["spell", "spelling"]


def test_latin_match_is_case_insensitive():
    out = searched_first("SPELLING", [SPELL, SPELLING])
    assert out[0]["latin"] == "spelling"


def test_shavian_search_matches_on_shaw():
    out = searched_first("𐑕𐑐𐑧𐑤𐑦𐑙", [SPELL, SPELLING])
    assert out[0]["shaw"] == "𐑕𐑐𐑧𐑤𐑦𐑙"


def test_every_summary_survives_the_reorder():
    pool = [SPELL, SPELLING, _summary("spelled", "𐑕𐑐𐑧𐑤𐑛")]
    out = searched_first("spelling", pool)
    assert sorted(s["latin"] for s in out) == ["spell", "spelled", "spelling"]


def test_no_match_preserves_input_order():
    out = searched_first("unrelated", [SPELL, SPELLING])
    assert [s["latin"] for s in out] == ["spell", "spelling"]


def test_contains_shavian_discriminates_the_scripts():
    assert contains_shavian("𐑕𐑐𐑧𐑤")
    assert contains_shavian("row 𐑮𐑬")
    assert not contains_shavian("spell")
    assert not contains_shavian("")


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
