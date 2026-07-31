#!/usr/bin/env python3
"""
UK/US spelling-variant generation.

The OpenSubtitles-derived frequency list (external/frequency-words) is a single
mixed-dialect "en" corpus: it contains both "colour" and "color", "centre" and
"center", each with its own count. When one of our Latin headwords is absent
from the corpus, its transatlantic twin often is not, so we credit the twin's
frequency to the headword.

Each rule is a (regex, replacement) pair applied independently to the whole
lowercase headword. A rule that changes nothing contributes no candidate. Rules
are intentionally conservative: they encode well-known systematic UK/US
correspondences, not per-word exceptions. A wrong candidate that happens to
exist in the corpus credits the frequency of an unrelated lexeme, so the
anchors below err on the side of missing a rescue rather than faking one; each
non-obvious anchor is commented with the false rescue it prevents.
"""

import re

# The UK/US final-l doubling difference (travelled/traveled) exists only for
# polysyllabic stems ending in an unstressed vowel + l; monosyllabic stems
# (pule, hull, wale, real) spell identically in both dialects. Proxy for
# "polysyllabic": two vowel groups separated by a consonant letter before the
# l-suffix (an explicit letter class, so a hyphen cannot separate: no-balled
# stays monosyllabic). "ue" and "ia" also count as two groups because they
# are disyllabic before l (fuel, duel, dial, trial), unlike other
# adjacent-vowel digraphs (real). Other polysyllabic stems the proxy misses
# spell identically anyway.
_POLYSYLLABIC_STEM = r"([a-z]*(?:[aeiouy][bcdfghjklmnpqrstvwxz]+[aeiouy]|ue|ia)[a-z]*)"

# -re/-er alternation (centre/center): c and g are excluded from the consonant
# class because -cre/-gre words are not alternants (acre, lucre, ogre, and the
# false rescue eagre -> eager); the only genuine pair lost is meagre/meager.
_RE_ER_CONSONANT = r"([bdfhjklmnpqrstvwxz])"

_VARIANT_RULES = [
    (r"our\b", "or"),                                   # colour  -> color
    (r"or\b", "our"),                                   # color   -> colour
    (r"ise\b", "ize"),                                  # organise-> organize
    (r"ize\b", "ise"),
    (r"isation\b", "ization"),                          # organisation -> organization
    (r"ization\b", "isation"),
    (r"yse\b", "yze"),                                  # analyse -> analyze
    (r"yze\b", "yse"),
    (_RE_ER_CONSONANT + r"re\b", r"\1er"),              # centre  -> center
    (_RE_ER_CONSONANT + r"er\b", r"\1re"),
    (r"ogue\b", "og"),                                  # catalogue -> catalog
    (r"og\b", "ogue"),
    # The (?<!l) on the single-l directions stops already-doubled words from
    # emitting junk triple-l candidates (travelled -> travellled).
    (_POLYSYLLABIC_STEM + r"lled\b", r"\1led"),         # travelled -> traveled
    (_POLYSYLLABIC_STEM + r"(?<!l)led\b", r"\1lled"),   # (but not puled -> pulled)
    (_POLYSYLLABIC_STEM + r"lling\b", r"\1ling"),       # (but not hulling -> huling)
    (_POLYSYLLABIC_STEM + r"(?<!l)ling\b", r"\1lling"),
    (_POLYSYLLABIC_STEM + r"ller\b", r"\1ler"),         # (but not realler -> realer)
    (_POLYSYLLABIC_STEM + r"(?<!l)ler\b", r"\1ller"),   # (but not waler -> waller)
    (r"aemia\b", "emia"),                               # anaemia -> anemia
    (r"emia\b", "aemia"),
    # oe/ae digraph reduction (oestrogen -> estrogen, anaesthesia ->
    # anesthesia). Anchors: no vowel immediately before (cooed -> coed; y
    # stays allowed: hyaena) and a vowel somewhere after, which excludes both
    # plural -oes (volcanoes -> volcanes) and monosyllables whose only vowels
    # are the digraph itself (stoep -> step). ae additionally must not precede
    # r: aer- is the "air" morpheme (aerial, aeration), not a digraph
    # (aerations -> erations, megaera -> megera). Accepted losses: mediaeval
    # (vowel before ae) and chimaera (rare genuine digraph before r).
    (r"(?<![aeiou])oe(?=[a-z]*[aeiouy])", "e"),
    (r"(?<![aeiou])ae(?!r)(?=[a-z]*[aeiouy])", "e"),
    (r"ence\b", "ense"),                                # licence -> license
    (r"ense\b", "ence"),
    (r"mme\b", "m"),                                    # programme -> program
    # Deliberately no m -> mme reverse: it would fire on every -m word and
    # produced zero genuine rescues on the corpus join (audited 2026-07).
]

_COMPILED_RULES = [(re.compile(pattern), replacement) for pattern, replacement in _VARIANT_RULES]


def spelling_variants(word):
    """Return the set of transatlantic spelling variants of a lowercase word."""
    candidates = set()
    for pattern, replacement in _COMPILED_RULES:
        transformed = pattern.sub(replacement, word)
        if transformed != word:
            candidates.add(transformed)
    return candidates
