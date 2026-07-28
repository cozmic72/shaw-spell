"""
Shared noun-inflection rules for Shavian/Latin word forms.

Single source of truth for the noun plural/possessive morphology used by
the Apple-dictionary generator (paired d:index derivation) and the
hunspell spellcheck generator (SFX affix classes).

Voicing classes (last char of the stem, Shavian script):
  voiceless non-sibilant: 𐑐 𐑑 𐑒 𐑓 𐑔   (p t k f θ) → suffix 𐑕
  sibilant:               𐑕 𐑟 𐑖 𐑠 𐑗 𐑡  (s z ʃ ʒ tʃ dʒ) → suffix 𐑩𐑟
  else (voiced consonant or vowel) → suffix 𐑟
"""

VOICELESS_NON_SIBILANT = '𐑐𐑑𐑒𐑓𐑔'
SIBILANT = '𐑕𐑟𐑖𐑠𐑗𐑡'

_LATIN_VOWELS = 'aeiou'


def _shavian_sibilant_suffix(shaw):
    """Pick the voicing-correct sibilant suffix (𐑩𐑟 / 𐑕 / 𐑟) for a stem.

    Assumes a non-empty stem: the public entry point (derive_noun_index_pairs)
    raises on a falsy shaw before this is reached, so it is never called with "".
    """
    last = shaw[-1]
    if last in SIBILANT:
        return '𐑩𐑟'
    if last in VOICELESS_NON_SIBILANT:
        return '𐑕'
    return '𐑟'


def _latin_plural(latin, shaw):
    """
    Pluralise a Latin stem, using the Shavian last char as the phonemic
    oracle for the sibilant decision ('box'/𐑚𐑪𐑒𐑕 → 'boxes').
    """
    if shaw[-1] in SIBILANT:
        return latin + ('s' if latin.endswith('e') else 'es')
    if len(latin) >= 2 and latin[-1] == 'y' and latin[-2] not in _LATIN_VOWELS:
        return latin[:-1] + 'ies'
    return latin + 's'


def _is_singular_noun(pos):
    """NN1 or a proper noun (NP0, including combined tags like NP0+NN1)."""
    return pos == 'NN1' or (bool(pos) and 'NP0' in pos)


def derive_noun_index_pairs(latin, shaw, pos, derive_plural=True):
    """
    Derive the default noun inflections for a (latin, shaw) stem, paired.

    For singular nouns (NN1/NP0), with the paired Shavian alongside:
      - singular possessive:  dog → dog's / 𐑛𐑪𐑜'𐑟
      - plural:               dog → dogs / 𐑛𐑪𐑜𐑟 (also the apostrophe-free
                              possessive homograph in Shavian)
      - plural possessive:    dog → dogs' / 𐑛𐑪𐑜𐑟'
      The plural pair (and with it the plural possessive) is derived only
      when `derive_plural` — the caller gates on explicit-slot occupancy:
      an explicit plural record (NN2) or an invariant lemma (NN0) closes
      the plural slot.

    For plural-only NN2 stems:
      - plural possessive only: alms → alms' / 𐑭𐑥𐑟'

    Returns a set of (latin_form, shavian_form) tuples, excluding the
    input stem itself. Raises if either script is missing — the pairing
    is the point, a one-legged stem is a data bug.
    """
    if not latin or not shaw:
        raise ValueError(
            f"noun derivation needs both scripts: latin={latin!r} pos={pos!r}"
        )

    pairs = set()
    if _is_singular_noun(pos):
        pairs.add((latin + "'s", shaw + "'𐑟"))
        if derive_plural:
            latin_plural = _latin_plural(latin, shaw)
            shaw_plural = shaw + _shavian_sibilant_suffix(shaw)
            pairs.add((latin_plural, shaw_plural))
            pairs.add((latin_plural + "'", shaw_plural + "'"))
    elif pos == 'NN2':
        pairs.add((latin + "'", shaw + "'"))

    return pairs
