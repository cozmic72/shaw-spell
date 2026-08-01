"""RRP spelling generator.

The generative counterpart to the RRP classifier: where the classifier JUDGES
an existing candidate spelling ("does this pass as RRP?"), the generator
PRODUCES the canonical RRP Shavian spelling from scratch, given a word and
its pronunciation evidence — what ReadLex WOULD spell it, per the Guide's
stress-based rules (shavian-spelling skill).

Pipeline (IPA basis, the primary path):
  1. house_normalize_ipa   RRP-canonicalize the IPA itself (PRICE artifact,
                           GenAm stressed bare-i -> FLEECE, stressed -ure
                           lowered to FORCE -> CURE per the fixed rule)
  2. ipa_to_shavian        the repo converter (src/tools) does the category
                           mapping — compounds, linking R, word signs
  3. canonical_respell     Shavian-space house rules reused from the
                           classifier: the Guide's page-5 affix tables,
                           happY, un- prefix, stress-driven NURSE/lettER
  4. gates                 stress-dependent sites with unknown stress are
                           FLAGGED, never guessed; stressed schwa and
                           contamination cannot be RRP at all
  5. shave witness         shave -b is a second opinion (Roman->Shavian
                           G2P); agreement raises the tier, never gates

Where IPA is absent (names), shave -b IS the generator (basis "shave"),
single-option only; multi-option shave output is a flag, not a guess.

Outcomes:  GEN   proposal produced
           FLAG  proposal produced but a gated site needs editorial stress
           FAIL  no RRP spelling derivable (contamination / no evidence)

Tiers:  A  IPA basis, stress known, shave agrees
        B  IPA basis, stress known
        C  IPA basis, stress unknown but no stress-gated site
        D  shave-only basis (single option)
        F  flagged / failed

Pure logic, no I/O, mutates nothing. Reuses the classifier's rule tables
(src/tools/rrp_classifier.py) and the repo converter (ipa_to_shavian).

NOTE ON PIPELINE ORDER: the reclassify stage (reclassify_rrp.py) is the
CLASSIFIER — it judges existing candidate spellings and relabels the passing
ones to RRP. This module backs the SEPARATE generator stage (generate_rrp.py,
which runs live in the supplement chain immediately after reclassify); it is
not invoked by reclassify_rrp.py. The generator's shave-only path
(_generate_from_shave, for IPA-less names) is the sole non-deterministic
surface and belongs to the generator stage, never to the deterministic
reclassify stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ipa_to_shavian import contains_non_shavian, ipa_to_shavian  # noqa: E402
import rrp_classifier as C  # noqa: E402  (rule tables + stress helpers)

NUCLEI = "".join(C.IPA_NUCLEI)

# GenAm-normalized sources spell stressed FLEECE as bare i (ˈθri); the
# converter's weak-i convention would map it 𐑦. Stressed bare i IS FLEECE.
STRESSED_BARE_I = re.compile(r"(ˈ[^" + NUCLEI + r"ː]*)i(?![ːəʊ])")

# The [iɪ].ə syllable break marks a morpheme boundary that must stay two
# syllables (happier 𐑣𐑨𐑐𐑦𐑼, not NEAR 𐑣𐑨𐑐𐑽). The repo converter routes this
# through its + boundary inside normalize_ipa; the generator calls
# ipa_to_shavian directly (bypassing normalize_ipa), so it must reproduce the
# routing itself. Same regex as ipa_to_shavian.normalize_ipa's dot-route.
NEAR_SYLLABLE_DOT = re.compile(r"([iɪ])\.(ə)")

# -ier/-iest comparatives/superlatives: the -y root makes the i a SEPARATE
# syllable (classy -> classier 𐑦𐑼, not the NEAR compound 𐑽). The comparative
# POS tag (AJC/AJS) is the discriminator that no orthography or IPA shape can
# supply — classier /ˈklⱭːsɪəR/ and premier /ˈpremɪəR/ share an IPA shape but
# only the comparative is two-syllable. The NEAR compound (𐑽/𐑾) the converter
# produced is expanded to its two-syllable form, exactly as fix_near_syllable_
# dots.py expands a dot-collapse victim. Only the SUFFIX'S NEAR is flipped:
# beerier /ˈbɪərɪəR/ 𐑚𐑽𐑦𐑼 keeps the ROOT NEAR (beer 𐑚𐑽) and expands only the
# final -ier, so the match is anchored to the word-final suffix region (before
# any plural 𐑟 / superlative 𐑕𐑑 coda), never a medial root NEAR.
COMPARATIVE_POS = re.compile(r"^AJ[CS]$")
IER_IEST_LATIN = re.compile(r"i(?:er|est)s?$")
# NEAR compound -> two-syllable, anchored at the -ier/-iest suffix position:
# 𐑽 (-ier) optionally + 𐑟 plural; 𐑾 (-iest) + 𐑕𐑑 coda, optionally + 𐑟.
NEAR_SUFFIX_FLIP = [
    (re.compile(r"𐑽(𐑟?)$"), r"𐑦𐑼\1"),
    (re.compile(r"𐑾(𐑕𐑑𐑟?)$"), r"𐑦𐑩\1"),
]


@dataclass
class Proposal:
    shaw: str | None = None
    outcome: str = "GEN"          # GEN | FLAG | FAIL
    tier: str = "B"
    basis: str = "ipa"            # ipa | shave
    raw_shaw: str | None = None   # converter output before house respell
    flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    fired: list = field(default_factory=list)
    shave_opts: tuple = ()
    shave_agrees: bool | None = None  # None = no shave opinion


# --------------------------------------------------- IPA house normalization

def house_normalize_ipa(ipa: str, word: str, fired: list) -> str:
    """RRP-canonicalize an already-ReadLex-convention IPA string."""
    low = word.lower()

    # A [iɪ].ə syllable dot is a morpheme boundary: keep it two syllables (𐑦𐑼)
    # by routing it through the converter's + boundary, then drop the dot so no
    # literal '.' survives into the Shavian (ipa_to_shavian passes it through
    # verbatim). Mirrors ipa_to_shavian.normalize_ipa; the generator bypasses
    # that function so it must route the dot here.
    routed = NEAR_SYLLABLE_DOT.sub(r"\1+\2", ipa)
    if routed != ipa:
        ipa = routed
        fired.append("ipa:near-syllable-dot")
    if "." in ipa:
        ipa = ipa.replace(".", "")

    # SSB narrow PRICE (ʌɪ) — category letter is 𐑲.
    if "ʌɪ" in ipa:
        ipa = ipa.replace("ʌɪ", "aɪ")
        fired.append("ipa:price-artifact")

    # Stressed bare i (GenAm shorthand) is FLEECE, not weak i.
    new = STRESSED_BARE_I.sub(r"\1iː", ipa)
    if new != ipa:
        ipa = new
        fired.append("ipa:stressed-i-fleece")

    # Fixed rule: CURE is always 𐑫𐑼. An SSB source lowering stressed -ure
    # to FORCE (mature /məˈtʃɔː/) regenerates as CURE. Orthographic gate:
    # -ure family only (-oor stays: door/floor are legitimate FORCE).
    if re.search(r"ur(e[sd]?|ing)$", low) and re.search(r"ɔː[Rr]?[zd]?$", ipa):
        ipa = re.sub(r"ɔː[Rr]?(?=[zd]?$)", "ʊəR", ipa)
        fired.append("ipa:cure-restored")

    return ipa


# ------------------------------------------------- Shavian-space house rules

def near_comparative_flip(shaw: str, word: str, pos: str, ipa: str,
                          fired: list) -> str:
    """A -ier/-iest COMPARATIVE spells the NEAR region two-syllable (𐑦𐑼/𐑾→𐑦𐑩),
    not the NEAR compound (𐑽/𐑾): classy→classier 𐑒𐑤𐑭𐑕𐑦𐑼, not 𐑒𐑤𐑭𐑕𐑽.

    The comparative POS (AJC/AJS) is the only wordlist-free signal that
    separates these from genuine one-syllable NEAR nouns of identical IPA shape
    (premier /ˈpremɪəR/ 𐑐𐑮𐑧𐑥𐑽, cashier /kæˈʃɪəR/ 𐑒𐑨𐑖𐑽 — both NN1, never AJC/AJS).
    A dotted IPA already produced the two-syllable form upstream (near-syllable-
    dot); this handles the dot-less comparative the converter collapsed to NEAR.
    """
    if not COMPARATIVE_POS.match(pos) or not IER_IEST_LATIN.search(word.lower()):
        return shaw
    for pattern, replacement in NEAR_SUFFIX_FLIP:
        flipped = pattern.sub(replacement, shaw)
        if flipped != shaw:
            shaw = flipped
            fired.append("affix-fix:near-comparative")
            break
    return shaw


def canonical_respell(shaw: str, word: str, pos: str, ipa: str,
                      fired: list, notes: list) -> str:
    """Apply the Guide's affix tables + stress rules to the converter output.
    Reuses the classifier's SUFFIX_RULES fix patterns verbatim."""
    low = word.lower()
    syl = C.syllables(shaw)

    # NOTE: no NURSE/lettER respell here. The classifier's
    # nurse_letter_respells() second-guesses the converter using a backward
    # stress scan, but that is (a) wrong for the generator's basis — the
    # source IPA already encodes the decision (ɜː is NURSE, a full vowel; əR
    # is lettER, reduced schwa) and the converter maps each faithfully — and
    # (b) buggy on ReadLex uppercase vowel variants (Æ Ɑ Ə I), which are not
    # in IPA_NUCLEI so the scan sails past them (after ˈÆftəR -> false NURSE).
    # It also mishandles secondary-stress compounds (adverb ˈædvɜːRb keeps
    # NURSE). Trusting the converter's ɜːR/əR mapping is both simpler and
    # measured-correct (drops 110 control regressions to ~0).

    ending_stressed = C.has_stress(ipa) and C.final_syllable_stressed(ipa)

    for name, lat_re, pos_f, exp_re, fixes, min_syl in C.SUFFIX_RULES:
        if syl < min_syl or not re.search(lat_re, low):
            continue
        if name == "-able/-ible" and low in C.ABLE_STOPLIST:
            continue
        if pos_f and not pos_f.match(pos):
            continue
        if ending_stressed:
            continue
        if re.search(exp_re, shaw):
            fired.append(f"affix-ok:{name}")
            continue
        # DRIFT-FIX: only when the source IPA is silent/ambiguous about the
        # suffix vowel. On a clean IPA basis the converter already produced
        # the faithful vowel; overriding it corrupts genuine full-vowel
        # suffixes (baroness ˈbærənes -> 𐑧𐑕, badlands ˈbædlændz -> 𐑨𐑯𐑛).
        # We therefore respell only when the shape is unrecognized AND there
        # is no stress information pinning the ending — i.e. the drifted
        # supplement case (which is exactly where the fix earns its keep,
        # e.g. -ity ɑtɪ). With stress marks (ReadLex control), trust the IPA.
        if C.has_stress(ipa):
            notes.append(f"suffix-shape-nonstandard:{name}")
            continue
        for drift_re, repl in fixes:
            new = re.sub(drift_re, repl, shaw)
            if new != shaw:
                shaw = new
                fired.append(f"affix-fix:{name}")
                break
        else:
            notes.append(f"suffix-shape-unrecognized:{name}")

    # happY: -y/-ie/-ey orthography proves the unstressed category — but only
    # respell when the IPA is silent. A stress-marked iː is a genuine final
    # FLEECE (ash-key ˈæʃ-kiː, a transparent compound); trust it.
    if syl >= 2 and not ending_stressed and not C.has_stress(ipa) \
            and C.HAPPY_LATIN.search(low) and shaw.endswith("𐑰"):
        shaw = shaw[:-1] + "𐑦"
        fired.append("affix-fix:happy-final")

    # un- (=not) takes the fuller 𐑳𐑯- (Guide P9).
    if (low.startswith("un") and len(low) > 5
            and not low.startswith(("under", "uni", "unan", "unt", "unl"))
            and shaw.startswith("𐑩𐑯")):
        shaw = "𐑳𐑯" + shaw[2:]
        fired.append("affix-fix:un-prefix")

    shaw = near_comparative_flip(shaw, word, pos, ipa, fired)

    return shaw


# --------------------------------------------------------------- stress gate

def stress_gate(shaw: str, word: str, pos: str, ipa: str,
                fired: list) -> tuple[list, list]:
    """Stress-dependent spelling sites that IPA stress marks did not resolve.
    Returns (hard_flags, soft_notes) — hard flags demote to FLAG/F."""
    low = word.lower()
    stress_known = C.has_stress(ipa) or C.syllables(shaw) <= 1
    if stress_known:
        return [], []

    hard, soft = [], []
    ending_vouched = any(f.startswith(("affix-ok:", "affix-fix:"))
                         and "un-prefix" not in f for f in fired)
    if low.endswith("ee") and shaw[-1:] in ("𐑦", "𐑰"):
        hard.append("final-ee-stress-unknown")
    final = shaw.rstrip("𐑟𐑛")[-1:]
    if final == "𐑻" and C.syllables(shaw) >= 2 and not ending_vouched:
        hard.append("final-nurse-unvouched")
    elif final == "𐑼" and not C.ER_LATIN.search(low) and not ending_vouched:
        hard.append("final-letter-unvouched")
    elif "𐑻" in shaw or "𐑼" in shaw:
        soft.append("nurse-letter-medial-unverified")
    if re.search(r"at(e|es|ed|ing)$", low) and (
            C.NOUNISH.match(pos) or C.ADJISH.match(pos)
            or C.VERBISH.match(pos)):
        exp = "𐑱𐑑" if C.VERBISH.match(pos) else "𐑩𐑑"
        if exp not in shaw[-4:]:
            hard.append("ate-pos-mismatch")
    return hard, soft


# ------------------------------------------------------------ the generator

def generate(word: str, ipa: str | None, pos: str = "",
             shave_opts: tuple = ()) -> Proposal:
    """Produce the canonical RRP Shavian proposal for one word.

    ipa        ReadLex-convention IPA (capital R, Ə, + boundaries), or None
    shave_opts shave -b spellings for the word (witness, or sole basis)
    """
    p = Proposal(shave_opts=tuple(shave_opts))

    if not ipa:
        return _generate_from_shave(word, p)

    # The neutral vowel never takes stress: a primary-stressed plain schwa
    # has no RRP spelling — the evidence itself is un-RRP.
    if C.stressed_schwa_violation(ipa):
        p.flags.append("stressed-schwa")
        p.outcome, p.tier = "FAIL", "F"
        return p

    norm = house_normalize_ipa(ipa, word, p.fired)
    raw = ipa_to_shavian(norm)
    p.raw_shaw = raw

    if contains_non_shavian(raw.replace(" ", "").replace("-", "")):
        p.flags.append("ipa-contamination")
        p.outcome, p.tier = "FAIL", "F"
        return p

    shaw = canonical_respell(raw, word, pos, norm, p.fired, p.notes)
    hard, soft = stress_gate(shaw, word, pos, norm, p.fired)
    p.notes.extend(soft)
    p.shaw = shaw

    if p.shave_opts:
        p.shave_agrees = shaw.lstrip("·") in p.shave_opts
        if p.shave_agrees is False:
            p.notes.append("shave-diverges")

    if hard:
        p.flags.extend(hard)
        p.outcome, p.tier = "FLAG", "F"
        return p

    stress_known = C.has_stress(norm) or C.syllables(shaw) <= 1
    if not stress_known:
        p.tier = "C"
    elif p.shave_agrees:
        p.tier = "A"
    else:
        p.tier = "B"
    if soft and p.tier == "A":
        p.tier = "B"
    return p


def proposed_record(word: str, pos: str, p: Proposal,
                    from_rec: dict | None = None) -> dict:
    """The record a live phase would emit for a GEN/FLAG proposal.

    Schema (owner-directed, report-first):
      source: ["generated"]  — the origin facet value for synthesized RRP
              entries, filterable in the editor alongside wordnet/wiktionary.
      generated_from         — the lineage: which input record (anchor key +
              its var and source list) or bare name the spelling was
              synthesized FROM, via which evidence path, with which
              corroborating witnesses. Makes the kneading visible.
    """
    lineage = {
        "record": (f"{from_rec['Latn']}_{from_rec['pos']}_{from_rec['Shaw']}"
                   if from_rec else None),
        "var": from_rec.get("var") if from_rec else None,
        "source": from_rec.get("source") if from_rec else None,
        "method": "ipa-converter" if p.basis == "ipa" else "shave-g2p",
        "witnesses": (["shave"] if p.shave_agrees else []),
    }
    rec = {
        "Latn": word,
        "Shaw": p.shaw,
        "pos": pos,
        "var": "RRP",
        "source": ["generated"],
        "gen_tier": p.tier,
        "generated_from": lineage,
    }
    if from_rec and from_rec.get("ipa"):
        rec["ipa"] = from_rec["ipa"]
    if p.flags:
        rec["gen_flags"] = list(p.flags)
    return rec


def _generate_from_shave(word: str, p: Proposal) -> Proposal:
    """No IPA: shave -b is the generator. Single opinion only — a bracket
    list of alternatives is a flag, never a guess."""
    p.basis = "shave"
    opts = [o for o in p.shave_opts if o]
    if not opts:
        p.flags.append("no-evidence")
        p.outcome, p.tier = "FAIL", "F"
        return p
    if len(opts) > 1:
        p.flags.append("shave-multi-option")
        p.outcome, p.tier = "FLAG", "F"
        return p
    shaw = opts[0]
    if contains_non_shavian(shaw.replace(" ", "").replace("-", "")):
        p.flags.append("shave-non-shavian")
        p.outcome, p.tier = "FAIL", "F"
        return p
    p.shaw = shaw
    p.tier = "D"
    p.notes.append("shave-sole-basis")
    return p
