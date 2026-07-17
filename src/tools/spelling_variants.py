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
correspondences, not per-word exceptions.
"""

import re

_VARIANT_RULES = [
    (r"our\b", "or"),                                   # colour  -> color
    (r"or\b", "our"),                                   # color   -> colour
    (r"ise\b", "ize"),                                  # organise-> organize
    (r"ize\b", "ise"),
    (r"isation\b", "ization"),                          # organisation -> organization
    (r"ization\b", "isation"),
    (r"yse\b", "yze"),                                  # analyse -> analyze
    (r"yze\b", "yse"),
    (r"([bcdfghjklmnpqrstvwxz])re\b", r"\1er"),          # centre  -> center
    (r"([bcdfghjklmnpqrstvwxz])er\b", r"\1re"),
    (r"ogue\b", "og"),                                  # catalogue -> catalog
    (r"og\b", "ogue"),
    (r"lled\b", "led"),                                 # travelled -> traveled
    (r"led\b", "lled"),
    (r"lling\b", "ling"),
    (r"ling\b", "lling"),
    (r"ller\b", "ler"),
    (r"ler\b", "ller"),
    (r"aemia\b", "emia"),                               # anaemia -> anemia
    (r"emia\b", "aemia"),
    (r"oe", "e"),                                        # oestrogen -> estrogen
    (r"ae", "e"),                                        # encyclopaedia -> encyclopedia
    (r"ence\b", "ense"),                                # licence -> license
    (r"ense\b", "ence"),
    (r"mme\b", "m"),                                     # programme -> program
    (r"m\b", "mme"),
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
