#!/usr/bin/env python3
"""Unit tests for the anchored UK/US spelling-variant rules.

The negative cases are the 22 false rescues found by the three-way join audit
(readlex / OpenSubtitles / BNC-LRW): in each pair the target is a different
lexeme, so a rescue credits the headword with an unrelated word's corpus
frequency. The positive cases are genuine transatlantic twins and guard
against the anchors over-correcting.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from spelling_variants import spelling_variants


# Every hand-labelled false rescue from the join audit: (headword, wrong target).
FALSE_RESCUES = [
    ("stoep", "step"),          # Afrikaans loan; oe is its only vowel
    ("stoeps", "steps"),
    ("puled", "pulled"),        # monosyllabic stem: no UK/US l-doubling
    ("hulling", "huling"),
    ("waler", "waller"),
    ("realler", "realer"),
    ("eagre", "eager"),         # -gre is not an -re/-er alternant
    ("vinoes", "vines"),        # plural -oes is not a digraph
    ("bravoes", "braves"),
    ("lassoes", "lasses"),
    ("forgoes", "forges"),
    ("salvoes", "salves"),
    ("mottoes", "mottes"),
    ("negroes", "negres"),
    ("palmettoes", "palmettes"),
    ("viragoes", "virages"),
    ("volcanoes", "volcanes"),
    ("cooed", "coed"),          # medial oo+ed is not a digraph
    ("mooed", "moed"),
    ("shooed", "shoed"),
    ("aerations", "erations"),  # aer- is the "air" morpheme, not a digraph
    ("megaera", "megera"),
    ("acre", "acer"),           # -cre is not an -re/-er alternant
    ("ogre", "oger"),
    ("meagre", "meager"),       # documented casualty of the c/g exclusion
    ("no-balled", "no-baled"),  # hyphen must not join two vowel groups
    ("travelled", "travellled"),  # doubled words emit no triple-l junk
]

# Genuine UK/US twins, at least one per rule family kept or anchored.
GENUINE_PAIRS = [
    ("colour", "color"),
    ("color", "colour"),
    ("realise", "realize"),
    ("realize", "realise"),
    ("organisation", "organization"),
    ("analyse", "analyze"),
    ("centre", "center"),
    ("meter", "metre"),
    ("dioptre", "diopter"),
    ("catalogue", "catalog"),
    ("catalog", "catalogue"),
    ("travelled", "traveled"),
    ("traveled", "travelled"),
    ("levelling", "leveling"),
    ("fueling", "fuelling"),        # disyllabic ue stem passes the doubling anchor
    ("dialled", "dialed"),          # disyllabic ia stem likewise
    ("dialing", "dialling"),
    ("court-martialed", "court-martialled"),
    ("leveller", "leveler"),
    ("modeler", "modeller"),
    ("anaemia", "anemia"),
    ("oestrogen", "estrogen"),
    ("oesophaguses", "esophaguses"),
    ("foetor", "fetor"),
    # Exercises the oe rule alone; standard "manoeuvre" -> "maneuver" needs
    # two rules composed, which the one-rule-at-a-time design never does.
    ("manoeuver", "maneuver"),
    ("anaesthesia", "anesthesia"),
    ("hyaenas", "hyenas"),          # y before ae stays eligible
    ("paeony", "peony"),
    ("palaeocene", "paleocene"),
    ("licence", "license"),
    ("programme", "program"),
]


def test_false_rescues_blocked():
    for word, wrong in FALSE_RESCUES:
        assert wrong not in spelling_variants(word), f"{word} -> {wrong} must not fire"


def test_genuine_pairs_survive():
    for word, twin in GENUINE_PAIRS:
        assert twin in spelling_variants(word), f"{word} -> {twin} must fire"


def test_no_m_to_mme_reverse():
    # The m -> mme rule was dropped: it fired on every -m word and never
    # produced a genuine rescue. programme-type words rescue via mme -> m.
    assert "programme" not in spelling_variants("program")
    assert "jamme" not in spelling_variants("jam")


def test_unchanged_word_yields_no_candidate():
    assert spelling_variants("table") == set()


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
