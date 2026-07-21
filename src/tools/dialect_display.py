"""Presentation model for the dialect `var` codes and the additive
variations fields (`mergers`, `variant`) — the SINGLE source of truth every
downstream PRODUCT (the XML dictionaries, the Hunspell spell-check wordlists,
anything that shows a var to a reader) shares so a var's friendly label and its
dialect family can never drift between consumers.

The canonical var set the harvest + pipeline emit (see
generate_wiktionary_supplement.KEEP_ACCENTS): RRP is the canonical British base;
RSSB is rhotic-restored "unconfirmed British" (the untagged-Wiktionary lane);
GenAm is the American base; GenAus/GenCan/NZ/SthAfr/IrEng are the harvested
national accents. Legacy SSB records (pre-rhotic-restoration Southern British)
still occur and are treated as British.

trap-bath is NO LONGER a var: ReadLex's upstream `var:"TrapBath"` is reinterpreted
to `var:"RRP"` + `mergers:["trap-bath"]` (basis.reinterpret_upstream). A record's
variations therefore live in `mergers` (a list) and `variant` (a bool), never in
`var`.
"""

# var code -> user-friendly label shown to a reader. British base and its
# national siblings read as accents of English; the merger/variant flags are
# NOT vars and are labelled separately (see merger_label / VARIANT_LABEL).
VAR_LABELS = {
    "RRP":    "RP",                 # Received Pronunciation — the British base
    "RSSB":   "Southern British",   # rhotic-restored unconfirmed British
    "SSB":    "Southern British",   # legacy Standard Southern British
    "GenAm":  "General American",
    "GenAus": "Australian",
    "GenCan": "Canadian",
    "NZ":     "New Zealand",
    "SthAfr": "South African",
    "IrEng":  "Irish",
    "GB":     "British",            # legacy spelling-dialect tag
}

# The two ACCENT FAMILIES, keyed off each var's normalisation pathway in the
# harvest (wiktionary_rp = non-rhotic British family; wiktionary_gam = rhotic
# American family). Drives home-vs-alt selection in the dictionaries and
# dialect inclusion in the spell-checker.
BRITISH_VARS = {"RRP", "RSSB", "SSB", "GenAus", "SthAfr", "NZ", "GB"}
AMERICAN_VARS = {"GenAm", "GenCan", "IrEng"}

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
    """The friendly label for a var code, or the code itself if unmapped
    (fail-visible: an unknown var shows as its bare code rather than being
    silently blanked)."""
    if not var_code:
        return ""
    return VAR_LABELS.get(var_code, var_code)


def is_british(var_code):
    """Whether a var belongs to the British (non-rhotic) accent family. An
    empty/absent var is British (the ReadLex core is RP)."""
    return not var_code or var_code in BRITISH_VARS


def is_american(var_code):
    """Whether a var belongs to the American (rhotic) accent family."""
    return var_code in AMERICAN_VARS


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
    British form). Non-RSSB vars return None — the rule is RSSB-specific.
    """
    if var_code not in ("RSSB", "SSB"):
        return None
    return "variant" if word_has_rrp else "sole"
