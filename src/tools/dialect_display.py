"""Presentation model for the dialect `var` codes and the additive
variations fields (`mergers`, `variant`).

TWO LAYERS (owner's model):

  * UNDER THE HOOD the data + the editor keep the full-fidelity internal vars —
    RRP, RSSB, SSB, GenAm, GenAus, GenCan, NZ, SthAfr, IrEng. Nothing here
    rewrites them; this module never touches stored data.

  * TO THE USER the shipped products (the web + Apple reference dictionaries)
    collapse each internal var to a familiar PRESENTATION DIALECT tag — the
    reader sees GB / US / AU / NZ / ZA / IE, never an internal code like "RSSB"
    or a coinage like "Southern British". See presentation_dialect().

The canonical var set the harvest + pipeline emit (see
generate_wiktionary_supplement.KEEP_ACCENTS): RRP is the canonical British base;
RSSB is rhotic-restored "unconfirmed British" (the untagged-Wiktionary lane);
GenAm is the American base; GenAus/GenCan/NZ/SthAfr/IrEng are the harvested
national accents. Legacy SSB records (pre-rhotic-restoration Southern British)
still occur and are treated as British.

trap-bath is NO LONGER a var: ReadLex's upstream `var:"TrapBath"` is reinterpreted
to `var:"RRP"` + `mergers:["trap-bath"]` (basis.reinterpret_upstream). Internally a
record's variations live in `mergers` (a list) and `variant` (a bool), never in
`var`. The PUBLISHED readlex.json folds variation back into the var as an
accent+"Var" suffix — RRPVar, GenAmVar, … (basis.collapse_readlex) — with
`mergers` shipped alongside. Everything in this module speaks plain accents;
consumers of readlex.json call split_var at their read boundary.

LABELS follow the project's established short-code convention (dialect tag is
lowercase gb/us; wordnet_dialect.py: US / GB / CA / AU). We prefer those concise
codes over spelled-out coinages so a var reads the same everywhere it surfaces.

SPELL-CHECK vs REFERENCE-DICTIONARY are two different products with two different
inclusion rules:
  * The reference dictionary shows every accent, each collapsed to its
    presentation tag (foreign accents surface as labelled variants, never as the
    plain headword).
  * The two shipped spell-check dictionaries are gb + us. Foreign national
    accents (AU/CA/NZ/ZA/IE) are their OWN dialect and NEVER become a gb or us
    headword. The gb dict ships British forms (RRP + RSSB/SSB, trap-bath riding
    under RRP); the us dict ships American forms (GenAm), plus the GB form as a
    marked alternative for any word America has no native form of (the US-gap
    fallback — see spellcheck_vars / US_GAP_FALLBACK_VARS).
"""

# ---------------------------------------------------------------------------
# WIRE FORM: the published var vocabulary (data/readlex.json).
# ---------------------------------------------------------------------------
# The suffix marking a published var as a variation record — upstream ReadLex's
# RRPVar convention, generalised to every accent. Shared with the producer
# (basis.collapse_readlex): the single representation of the wire convention.
VARIANT_SUFFIX = "Var"


def split_var(var_code):
    """(accent, has_variation) for a published var: "RRPVar" -> ("RRP", True),
    "GenAm" -> ("GenAm", False). A suffixed var with no `mergers` shipped
    alongside is a free-variation alternate (the internal `variant` flag)."""
    if var_code.endswith(VARIANT_SUFFIX):
        return var_code[:-len(VARIANT_SUFFIX)], True
    return var_code, False


# ---------------------------------------------------------------------------
# PRESENTATION LAYER: internal var -> user-facing dialect tag.
# ---------------------------------------------------------------------------
# The tag a reader sees in the shipped dictionaries. Every British var collapses
# to GB; the American family to US; each foreign national accent to its familiar
# region code. Codes match the project convention (gb/us dialect tags, wordnet
# AU/CA). ZA (South Africa) and IE (Ireland) are the standard ISO-style codes in
# the same short style.
PRESENTATION_DIALECT = {
    "RRP":    "GB",     # Received Pronunciation — British base
    "RSSB":   "GB",     # rhotic-restored unconfirmed Southern British
    "SSB":    "GB",     # legacy Standard Southern British
    "GenAm":  "US",     # General American
    "GenCan": "CA",     # Canadian — its own tag
    "GenAus": "AU",     # Australian
    "NZ":     "NZ",     # New Zealand
    "SthAfr": "SA",     # South African
    "IrEng":  "IE",     # Irish
    "GB":     "GB",     # legacy spelling-dialect tag
}


def presentation_dialect(var_code):
    """The user-facing dialect tag for an internal var (GB / US / AU / …), or the
    bare var code if unmapped (fail-visible). Empty var -> "" (the ReadLex core is
    RP; callers treat an unlabelled form as the home dialect)."""
    if not var_code:
        return ""
    return PRESENTATION_DIALECT.get(var_code, var_code)


# ACCENT FAMILIES for the REFERENCE DICTIONARY's home-vs-alt selection. The
# British base and its Southern-British siblings are the British family; GenAm is
# the American family. The foreign national accents are their OWN dialect
# (FOREIGN_VARS) — they belong to NEITHER family, so they never display as the
# plain home headword and never ship as a gb/us spell-check headword.
BRITISH_VARS = {"RRP", "RSSB", "SSB", "GB"}
AMERICAN_VARS = {"GenAm"}
FOREIGN_VARS = {"GenAus", "GenCan", "NZ", "SthAfr", "IrEng"}

# The British base var. RSSB is "a variant OF British" only when an RRP form for
# the same word also exists; when RSSB is the SOLE form it IS the British form
# (see rssb_role).
BRITISH_BASE_VAR = "RRP"

# Merger code -> friendly label. Mergers are additive on a base var.
MERGER_LABELS = {
    "trap-bath": "broad A",
    "cot-caught": "cot-caught merged",
    "lot-palm": "lot-palm merged",
}

# The friendly label for a `variant: true` record — the "other", disfavoured
# member of a pronunciation pair on the same base accent.
VARIANT_LABEL = "variant"


def var_label(var_code):
    """The user-facing dialect tag for a var code (presentation layer). Alias of
    presentation_dialect for call sites that read as "the label for this var"."""
    return presentation_dialect(var_code)


def is_british(var_code):
    """Whether a var belongs to the British accent family. An empty/absent var is
    British (the ReadLex core is RP)."""
    return not var_code or var_code in BRITISH_VARS


def is_american(var_code):
    """Whether a var belongs to the American accent family."""
    return var_code in AMERICAN_VARS


def is_foreign(var_code):
    """Whether a var is a foreign national accent (AU/CA/NZ/ZA/IE) — its OWN
    dialect, belonging to neither the British nor the American family."""
    return var_code in FOREIGN_VARS


def spellcheck_vars(dialect):
    """The var set that may become a HEADWORD in a shipped spell-check dictionary.

    dialect is 'gb' or 'us'. gb = the British family; us = the American family.
    Foreign national accents are DELIBERATELY excluded from both — they are their
    own dialect and must never pollute the gb/us wordlists. The us dict's coverage
    of British-only words is handled separately as a marked alternative
    (US_GAP_FALLBACK_VARS), NOT by admitting British vars as us headwords.
    """
    if dialect == 'gb':
        return set(BRITISH_VARS)
    if dialect == 'us':
        return set(AMERICAN_VARS)
    raise ValueError(f"unknown spell-check dialect: {dialect!r}")


# The us dict falls back to the British form for any word America has no native
# (GenAm) form of, displayed as an alternative. We do NOT fabricate an SSB entry
# — we reuse the existing GB form and mark it. These are the vars whose forms are
# eligible for that fallback.
US_GAP_FALLBACK_VARS = set(BRITISH_VARS)


def merger_label(merger_code):
    """The friendly label for a merger code, or the code itself if unmapped."""
    return MERGER_LABELS.get(merger_code, merger_code)


def variations_label(mergers=None, variant=False):
    """A friendly, comma-joined label for a record's variations (mergers +
    variant flag), or "" when it carries none. e.g. ["trap-bath"] -> "broad A";
    variant=True -> "variant"."""
    parts = [merger_label(m) for m in (mergers or [])]
    if variant:
        parts.append(VARIANT_LABEL)
    return ", ".join(parts)


def rssb_role(var_code, word_has_rrp):
    """How an RSSB (unconfirmed-British) record should be PRESENTED, per the
    owner's rule: RSSB is "a variant of British" UNLESS it is the only form for
    its word (no RRP entry), in which case it stands as THE British form.

    Returns "variant" (present as a British variant) or "sole" (present as the
    British form). Non-RSSB vars return None — the rule is RSSB-specific. Note
    the user-facing LABEL in both cases is the presentation tag "GB" (with the
    variant marking applied by the caller); this only decides variant-vs-sole.
    """
    if var_code not in ("RSSB", "SSB"):
        return None
    return "variant" if word_has_rrp else "sole"
