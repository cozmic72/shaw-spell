"""RRP canonicalization classifier — the pass-as-RRP judgment engine.

Judges whether a supplement candidate's Shavian spelling passes as RRP under
the Guide's stress-based rules (shavian-spelling skill §1–§7): a candidate
sourced from any accent (RSSB, GenAm) canonicalizes to RRP iff its spelling is
what the RRP rules sanction; otherwise it stays in its source dialect (the
honest residue) or is flagged for editorial review.

Pure logic — no I/O, no mutation, no shave, fully DETERMINISTIC. The respells
(PASS_RESPELL) are the Guide's page-5 affix tables plus IPA-stress-guided
NURSE/lettER fixes — deterministic string transforms, never a shave call, so
running the reclassify stage twice on identical input yields identical output
(no patch-orphaning churn). shave, where consulted, is only a tier witness
(A vs B) and is deliberately NOT used by the live reclassify stage.

The live consumer is src/tools/reclassify_rrp.py, which applies judge_record's
PER-RECORD verdict (relabel var to RRP for PASS/PASS_RESPELL, keep source var
otherwise). judge_group / apply_group_to_records compute the group-level
collapse/variant taxonomy — those are the DOWNSTREAM merger/variant stage's
concern and are NOT applied by the reclassify stage (report/analysis only).

Outcomes:
  PASS          spelling is RRP-sanctioned as-is           -> relabel var=RRP
  PASS_RESPELL  RRP-sanctioned after a deterministic,
                Guide-table-backed respell                 -> respell + relabel
  PASS_MERGER   base RRP + attested merger flag            -> relabel, keep flag
  ABSORB        loser of a normalizable competing pair     -> variant/absorb
  STAY          genuine category difference (yod-drop,
                CURE-lowering, unexplained pair residue)   -> keep source var
  REVIEW        cannot judge (stress-gated site, neutral-
                vowel violation, structural oddity)        -> editorial

Tiers: A pass w/ 2+ witnesses; B pass; C pass-after-respell; D pass+merger;
E stay-source; F review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# ---------------------------------------------------------------- constants

VOWELS = set("𐑦𐑰𐑧𐑱𐑨𐑲𐑩𐑳𐑪𐑴𐑷𐑶𐑫𐑵𐑬𐑭𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿")
SHAVIAN_OK = set(chr(c) for c in range(0x10450, 0x10480)) | set("·'- ")

NOUNISH = re.compile(r"^(NN|NP)")
ADJISH = re.compile(r"^AJ")
VERBISH = re.compile(r"^(VV|VB|VD|VH|VM)")

IPA_NUCLEI = set("iɪeɛæɑɒɔʊuəʌɜaoɐ")

# stress mark, then optional onset consonants, then bare i with no length
STRESSED_SHORT_I = re.compile("ˈ[^iɪeɛæɑɒɔʊuəʌɜaoɐː]*i(?!ː)")

# Pair-diff correspondence classes: (high-precedence seg, low-precedence seg)
# -> class name. Normalizable classes collapse; merger classes keep the flag
# infra; national classes keep a legitimate exception entry; stress classes
# need stress marks; anything else is unexplained residue.
NORMALIZABLE_CLASSES = {"weak-i-schwa", "schwa-epenthesis", "happy-tensing",
                        "weak-o", "yod-weak-u", "goose-foot",
                        "price-artifact", "t-elision", "fleece-kit-drift"}
MERGER_CLASSES = {"trap-bath", "cot-caught"}
NATIONAL_CLASSES = {"yod", "lot-palm", "bath-trap-national", "square-merry",
                    "loan-o", "foreign-a", "near-kit-r", "force-lot-r"}
STRESS_CLASSES = {"nurse-letter", "strut-schwa"}
# Real residue classes: keep both records, but review-worthy (direction or
# convention undecided): schwa-compressed r, R-restoration misses, glide-yod
# hiatus, prevocalic r-compounds.
CATEGORY_CLASSES = {"trap-schwa-onset", "r-compression", "rhoticity-mismatch",
                    "hiatus-glide", "r-compound-prevocalic"}

_PAIR_CLASS_PAIRS = [
    (("𐑦", "𐑩"), "weak-i-schwa"),
    (("𐑦", "𐑰"), "happy-tensing"),
    (("𐑩", "𐑴"), "weak-o"),        # unstressed o: RP schwa vs GenAm GOAT
    (("𐑩", "𐑪"), "weak-o"),        # unstressed o: RP schwa vs GenAm LOT
    (("𐑿", "𐑘𐑫"), "yod-weak-u"),   # weak ju: vs jʊ — ambiguous weak u
    (("𐑵", "𐑫"), "goose-foot"),    # ambiguous weak u (house style: 𐑫)
    (("𐑷", "𐑪"), "cot-caught"),
    (("𐑪", "𐑭"), "lot-palm"),
    (("𐑿", "𐑵"), "yod"),
    (("𐑿", "𐑫"), "yod"),           # salute: RP juː vs GenAm u
    (("𐑺", "𐑧𐑮"), "square-merry"), # Mary/merry kept distinct; GenAm merges
    (("𐑺", "𐑨𐑮"), "square-merry"), # Mary/marry likewise
    (("𐑪", "𐑴"), "loan-o"),        # loanword o: RP LOT vs GenAm GOAT
    (("𐑨", "𐑪"), "foreign-a"),     # foreign a: RP TRAP vs GenAm LOT
    (("𐑽", "𐑦𐑮"), "near-kit-r"),   # mirror/nearer: GenAm KIT+r for NEAR
    (("𐑹", "𐑪𐑮"), "force-lot-r"),  # horse/orange: FORCE vs LOT+r
    (("𐑳𐑦", "𐑲"), "price-artifact"),  # SSB narrow ʌɪ mis-mapped
    (("𐑨", "𐑩"), "trap-schwa-onset"),
    (("𐑳", "𐑩"), "strut-schwa"),   # the neutral-vowel confusable
    (("𐑻", "𐑼"), "nurse-letter"),
    (("𐑩", ""), "schwa-epenthesis"),
    (("𐑮", "𐑼"), "r-compression"), # -bury: compressed r vs schwa+r
    (("𐑩", "𐑼"), "rhoticity-mismatch"),  # R-restoration miss on one side
    (("𐑘", ""), "hiatus-glide"),   # narrow jə glide vs plain hiatus
    (("𐑼", "𐑮"), "r-compound-prevocalic"),
]

PAIR_CLASS_TABLE = {}
for (a, b), cls in _PAIR_CLASS_PAIRS:
    PAIR_CLASS_TABLE[(a, b)] = cls
    PAIR_CLASS_TABLE.setdefault((b, a), cls)
PAIR_CLASS_TABLE[("𐑭", "𐑨")] = "trap-bath"
PAIR_CLASS_TABLE[("𐑨", "𐑭")] = "bath-trap-national"
# t-elision is directional: only a collapse when the CANONICAL side keeps t.
PAIR_CLASS_TABLE[("𐑑", "")] = "t-elision"


def syllables(shaw: str) -> int:
    return sum(1 for ch in shaw if ch in VOWELS)


# ------------------------------------------------------- suffix conformance
# The Guide's page-5 affix tables, keyed on ORTHOGRAPHIC suffixes. The Latin
# suffix carries the conventional stress category, so these checks work even
# where the source IPA has no stress marks (the orthographic rescue).
#
# Each rule: (name, latin_regex, pos_filter, expected_shaw_re, fixes, min_syl)
# fixes: list of (drift_re, replacement) — deterministic respells; a suffix
# matching neither expected nor drift is only noted, never failed (it may be
# a legitimately different pronunciation).

SUFFIX_RULES = [
    ("-ness", r"ness(es)?$", None, r"𐑯𐑩𐑕(𐑦𐑟|𐑩𐑟)?$",
     [(r"𐑯[𐑦𐑧]𐑕", "𐑯𐑩𐑕")], 2),
    ("-less", r"less$", None, r"𐑤𐑩𐑕$", [(r"𐑤[𐑦𐑧]𐑕$", "𐑤𐑩𐑕")], 2),
    ("-ment", r"ments?$", NOUNISH, r"𐑥𐑩𐑯𐑑𐑕?$",
     [(r"𐑥[𐑦𐑧]𐑯𐑑(𐑕?)$", r"𐑥𐑩𐑯𐑑\1")], 2),
    ("-tion", r"([ts]ion|cion|cean|tian)s?$", None,
     r"[𐑖𐑠]𐑩𐑯𐑟?$", [(r"([𐑖𐑠])[𐑪𐑧]𐑯(𐑟?)$", r"\1𐑩𐑯\2")], 2),
    ("-ing", r"ing$", None, r"𐑦𐑙$", [(r"𐑰𐑙$", "𐑦𐑙")], 2),
    ("-ity", r"it(y|ies)$", None, r"𐑦𐑑𐑦𐑟?$",
     [(r"𐑩𐑑𐑦(𐑟?)$", r"𐑦𐑑𐑦\1")], 3),
    ("-ily", r"ily$", None, r"𐑦𐑤𐑦$", [(r"𐑩𐑤𐑦$", "𐑦𐑤𐑦")], 3),
    ("-age", r"ages?$", None, r"𐑦𐑡(𐑦𐑟|𐑩𐑟)?$",
     [(r"𐑩𐑡(𐑦𐑟|𐑩𐑟)?$", "𐑦𐑡")], 2),
    ("-ance/-ence", r"[ae]nces?$", None, r"𐑩𐑯𐑕(𐑦𐑟|𐑩𐑟)?$",
     [(r"[𐑧𐑦]𐑯𐑕$", "𐑩𐑯𐑕")], 3),
    ("-able/-ible", r"[ai]bl[ey]$", None, r"𐑩𐑚(𐑩𐑤|𐑤𐑦)$",
     [(r"[𐑦𐑧]𐑚(𐑩𐑤|𐑤𐑦)$", r"𐑩𐑚\1")], 3),
    ("-ism", r"[ai]sms?$", None, r"𐑟𐑩𐑥𐑟?$", [(r"𐑟(𐑥𐑟?)$", r"𐑟𐑩\1")], 2),
    ("-ward", r"wards?$", None, r"𐑢𐑼𐑛𐑟?$",
     [(r"𐑢[𐑷𐑹][𐑮]?𐑛(𐑟?)$", r"𐑢𐑼𐑛\1")], 2),
    ("-day", r"day$", None, r"𐑛𐑱$", [(r"𐑛[𐑦𐑩]$", "𐑛𐑱")], 2),
    ("-some", r"some$", None, r"𐑕𐑩𐑥$", [(r"𐑕𐑳𐑥$", "𐑕𐑩𐑥")], 2),
    ("-ful(adj)", r"ful(ly)?$", ADJISH, r"𐑓𐑩𐑤(𐑦?)$",
     [(r"𐑓𐑫𐑤(𐑦?)$", r"𐑓𐑩𐑤\1")], 2),
    ("-ly", r"[^l]ly$", None, r"𐑤𐑦$", [(r"𐑤𐑰$", "𐑤𐑦")], 2),
    ("-land", r"lands?$", None, r"𐑤𐑩𐑯𐑛𐑟?$",
     [(r"𐑤𐑨𐑯𐑛(𐑟?)$", r"𐑤𐑩𐑯𐑛\1")], 2),
]

ABLE_STOPLIST = {"unable", "enable", "disable", "parable", "unstable"}

# Final -y/-ie/-ey (not -ee): orthography proves the happY category, so a
# final 𐑰 is the happy-tensing drift and respells to 𐑦 (skill §5).
HAPPY_LATIN = re.compile(r"([^e]y|ie|[^e]ey)$")

# Final -er-family orthography with shaw ending in stressed NURSE: a
# stress-dependent site (defer vs differ). Respelled only when stress marks
# prove the final syllable unstressed; otherwise flagged.
ER_LATIN = re.compile(r"(er|or|our|ar|re|ur)s?$")


@dataclass
class Judgment:
    outcome: str = "PASS"
    tier: str = "B"
    reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    witnesses: list = field(default_factory=list)
    respell: str | None = None
    fired: list = field(default_factory=list)  # rule names, for fire rates


# ------------------------------------------------------------- IPA helpers

def has_stress(ipa: str) -> bool:
    return "ˈ" in ipa or "ˌ" in ipa


def _site_stressed(ipa: str, pos: int) -> bool:
    """Whether the nucleus starting at ipa[pos] is in a stressed syllable:
    scanning back through the onset, a stress mark is met before any other
    nucleus (word start counts as unstressed here — stress marks required)."""
    j = pos - 1
    while j >= 0:
        c = ipa[j]
        if c in "ˈˌ":
            return True
        if c in IPA_NUCLEI or c == "ː":
            return False
        j -= 1
    return False


def stressed_schwa_violation(ipa: str) -> bool:
    """A primary-stressed plain schwa (not əʊ GOAT, not əR lettER, not əː):
    un-RRP-spellable as-is — the neutral vowel never takes stress."""
    for m in re.finditer(r"ə", ipa):
        i = m.start()
        if ipa[i + 1:i + 2] in ("ʊ", "R", "r", "ː"):
            continue
        j = i - 1
        while j >= 0 and ipa[j] not in IPA_NUCLEI and ipa[j] != "ː":
            if ipa[j] == "ˈ":
                return True
            j -= 1
    return False


def nurse_letter_respells(ipa: str, shaw: str):
    """Stress-driven NURSE/lettER fixes, IPA-guided (needs stress marks).
    Returns (new_shaw, fixes) where fixes name each site corrected:
    unstressed ɜː spelt 𐑻 -> 𐑼; primary-stressed əR spelt 𐑼 -> 𐑻."""
    fixes = []
    # Map k-th ɜː in IPA to k-th 𐑻 in shaw (both linear, same order).
    nurse_sites = [m.start() for m in re.finditer(r"ɜː", ipa)]
    letter_sites = [m.start() for m in re.finditer(r"əR", ipa)]
    shaw_list = list(shaw)
    nurse_idx = [i for i, ch in enumerate(shaw_list) if ch == "𐑻"]
    letter_idx = [i for i, ch in enumerate(shaw_list) if ch == "𐑼"]
    if len(nurse_sites) == len(nurse_idx):
        for k, site in enumerate(nurse_sites):
            if not _site_stressed(ipa, site):
                shaw_list[nurse_idx[k]] = "𐑼"
                fixes.append("nurse->letter(unstressed)")
    if len(letter_sites) == len(letter_idx):
        for k, site in enumerate(letter_sites):
            if _primary_stressed(ipa, site):
                shaw_list[letter_idx[k]] = "𐑻"
                fixes.append("letter->nurse(stressed)")
    return "".join(shaw_list), fixes


def _primary_stressed(ipa: str, pos: int) -> bool:
    j = pos - 1
    while j >= 0 and ipa[j] not in IPA_NUCLEI and ipa[j] != "ː":
        if ipa[j] == "ˈ":
            return True
        j -= 1
    return False


def final_syllable_stressed(ipa: str) -> bool:
    """Whether the LAST nucleus in the IPA carries a stress mark (commence,
    trustee): such a word's ending must not be respelled by a suffix table."""
    last = -1
    for m in re.finditer("[" + "".join(IPA_NUCLEI) + "]", ipa):
        last = m.start()
    return last >= 0 and _site_stressed(ipa, last)


# -------------------------------------------------------------- per-record

def judge_record(rec: dict, ctx: dict) -> Judgment:
    """Judge one candidate record: does its spelling pass as RRP?

    ctx keys:
      cross_dialect: set of (latn.lower, pos, shaw) attested by 2+ vars
      shave: dict latn.lower -> set of shave -b spellings (may be empty)
    """
    j = Judgment()
    latn = rec["Latn"]
    low = latn.lower()
    pos = rec.get("pos", "")
    ipa = rec.get("ipa") or ""
    shaw = rec["Shaw"]
    var = rec.get("var", "")
    syl = syllables(shaw)
    stress_known = has_stress(ipa) or syl <= 1

    # --- structural sanity -------------------------------------------------
    bad = set(shaw) - SHAVIAN_OK
    if bad:
        j.reasons.append("non-shavian-chars")
        j.fired.append("struct:contamination")
    if "𐑘𐑵" in shaw:
        j.reasons.append("decomposed-yew")
        j.fired.append("struct:decomposed-yew")
    for m in re.finditer(r"[𐑩𐑭𐑷𐑾]𐑮", shaw):
        nxt = shaw[m.end():m.end() + 1]
        if nxt == "" or nxt not in VOWELS:
            j.notes.append("possible-decomposed-r-compound")
            j.fired.append("struct:decomposed-r")
            break
    if re.search(r"(.)\1", shaw):
        j.notes.append("doubled-letter")
        j.fired.append("struct:doubled-letter")
    if j.reasons:
        j.outcome, j.tier = "REVIEW", "F"
        return j

    # --- neutral-vowel violations (IPA-evidenced) --------------------------
    if stressed_schwa_violation(ipa):
        j.reasons.append("stressed-schwa")
        j.fired.append("neutral:stressed-schwa")
        j.outcome, j.tier = "REVIEW", "F"
        return j

    # GenAm stressed bare i is FLEECE, but the converter's weak-i convention
    # spelt it 𐑦 (3D "ˈθri" -> 𐑔𐑮𐑦). Upstream normalizer fix needed
    # (ˈi -> iː for GenAm sources); flag, don't guess glyph sites here.
    if STRESSED_SHORT_I.search(ipa):
        j.reasons.append("stressed-short-i-artifact")
        j.fired.append("neutral:stressed-short-i")
        j.outcome, j.tier = "REVIEW", "F"
        return j

    respelled = shaw
    # SSB narrow-PRICE artifact: source ʌɪ leaked through as 𐑳𐑦; the PRICE
    # category letter is 𐑲 (known converter-bug class, deterministic fix).
    if "ʌɪ" in ipa and "𐑳𐑦" in respelled:
        respelled = respelled.replace("𐑳𐑦", "𐑲")
        j.fired.append("neutral:price-artifact-fix")
        j.notes.append("respell:price-artifact")

    if has_stress(ipa):
        respelled, fixes = nurse_letter_respells(ipa, respelled)
        for f in fixes:
            j.fired.append(f"neutral:{f}")
        j.notes.extend(fixes)

    # --- affix conformance (orthographic rescue) ---------------------------
    # A stress-marked final syllable (commence, trustee) exempts the ending
    # from every suffix-table respell — the tables encode UNSTRESSED shapes.
    ending_stressed = has_stress(ipa) and final_syllable_stressed(ipa)
    unresolved_sites = []
    for name, lat_re, pos_f, exp_re, fixes, min_syl in SUFFIX_RULES:
        if syl < min_syl or not re.search(lat_re, low):
            continue
        if name == "-able/-ible" and low in ABLE_STOPLIST:
            continue
        if pos_f and not pos_f.match(pos):
            continue
        if ending_stressed:
            j.fired.append(f"affix-skip-stressed:{name}")
            continue
        if re.search(exp_re, respelled):
            j.fired.append(f"affix-ok:{name}")
            continue
        for drift_re, repl in fixes:
            new = re.sub(drift_re, repl, respelled)
            if new != respelled:
                respelled = new
                j.fired.append(f"affix-fix:{name}")
                j.notes.append(f"respell:{name}")
                break
        else:
            j.fired.append(f"affix-odd:{name}")
            j.notes.append(f"suffix-shape-unrecognized:{name}")

    # happY: final -y/-ie/-ey with 𐑰 -> 𐑦 (orthography proves the category)
    if syl >= 2 and not ending_stressed \
            and HAPPY_LATIN.search(low) and respelled.endswith("𐑰"):
        respelled = respelled[:-1] + "𐑦"
        j.fired.append("affix-fix:happy-final")
        j.notes.append("respell:happy-final")

    # un- (=not) prefix: fuller 𐑳𐑯- (P9)
    if (low.startswith("un") and len(low) > 5
            and not low.startswith(("under", "uni", "unan", "unt", "unl"))
            and respelled.startswith("𐑩𐑯")):
        respelled = "𐑳𐑯" + respelled[2:]
        j.fired.append("affix-fix:un-prefix")
        j.notes.append("respell:un-prefix")

    # --- stress-dependent sites not orthographically resolved --------------
    soft_uncertain = []
    if not stress_known:
        if low.endswith("ee") and respelled[-1:] in ("𐑦", "𐑰"):
            unresolved_sites.append("final-ee")
        # The defer/differ site: a FINAL 𐑻/𐑼 (ignoring -s/-d inflection) is
        # where the stress decision bites; no marks -> flag, never guess.
        # An affix-table hit on the ending (-ward, -er...) vouches for it.
        ending_vouched = any(
            f.startswith(("affix-ok:", "affix-fix:")) and "un-prefix" not in f
            for f in j.fired)
        final = respelled.rstrip("𐑟𐑛")[-1:]
        if final == "𐑻" and syllables(respelled) >= 2 and not ending_vouched:
            unresolved_sites.append("final-nurse-unvouched")
        elif final == "𐑼" and not ER_LATIN.search(low) and not ending_vouched:
            unresolved_sites.append("final-letter-unvouched")
        elif "𐑻" in respelled or "𐑼" in respelled:
            # medial sites are far lower-risk: note + one notch down
            soft_uncertain.append("nurse-letter-medial-unverified")
        if re.search(r"at(e|es|ed|ing)$", low) and (
                NOUNISH.match(pos) or ADJISH.match(pos) or VERBISH.match(pos)):
            exp = "𐑱𐑑" if VERBISH.match(pos) else "𐑩𐑑"
            if exp not in respelled[-4:]:
                unresolved_sites.append("ate-pos-mismatch")
    else:
        # stress known: -ate POS convention as a soft note only
        if re.search(r"ate$", low) and NOUNISH.match(pos) \
                and respelled.endswith("𐑱𐑑"):
            j.notes.append("ate-noun-full-vowel")
            j.fired.append("soft:ate-noun-full")

    if unresolved_sites:
        j.reasons.extend(unresolved_sites)
        for s in unresolved_sites:
            j.fired.append(f"stress-gate:{s}")
        j.outcome, j.tier = "REVIEW", "F"
        j.respell = respelled if respelled != shaw else None
        return j

    # --- CURE (fixed rule: always 𐑫𐑼) -------------------------------------
    if "ʊə" in ipa:
        j.fired.append("cure:conformal")
    if re.search(r"(ure[sd]?|uring|oor)s?$", low) and re.search(r"𐑹𐑟?$", respelled):
        j.reasons.append("cure-lowered-to-force")
        j.fired.append("cure:lowered")
        j.outcome, j.tier = "STAY", "E"
        j.notes.append("goal2-variant-candidate")
        return j

    # --- var-seeded risk priors -------------------------------------------
    uncertain = bool(soft_uncertain)
    j.notes.extend(soft_uncertain)
    for s in soft_uncertain:
        j.fired.append(f"soft:{s}")
    if var == "GenAm":
        if re.search(r"[^aeiou][tdns](ue|ew|eu|u[^aeiou])", " " + low) \
                and "𐑵" in respelled and "𐑿" not in respelled:
            j.notes.append("yod-uncertain")
            j.fired.append("prior:genam-yod-uncertain")
            uncertain = True
        if set(respelled) & {"𐑪", "𐑷", "𐑭"}:
            j.notes.append("genam-lot-thought-uncertain")
            j.fired.append("prior:genam-lot-thought")
            uncertain = True

    # --- witnesses (raise confidence, never gate) --------------------------
    if has_stress(ipa):
        j.witnesses.append("stress-marks")
    if (low, pos, shaw) in ctx.get("cross_dialect", ()):
        j.witnesses.append("cross-dialect")
    shave_opts = ctx.get("shave", {}).get(low, ())
    if respelled in shave_opts or shaw in shave_opts:
        j.witnesses.append("shave-agrees")
    if len(rec.get("source") or []) >= 2:
        j.witnesses.append("multi-source")

    # --- verdict -----------------------------------------------------------
    if respelled != shaw:
        j.respell = respelled
        j.outcome, j.tier = "PASS_RESPELL", "C"
    elif rec.get("mergers"):
        j.outcome, j.tier = "PASS_MERGER", "D"
    else:
        j.outcome = "PASS"
        j.tier = "A" if len(j.witnesses) >= 2 and not uncertain else "B"
    if uncertain and j.tier == "A":
        j.tier = "B"
    return j


# ------------------------------------------------------------- group level

VAR_RANK = {"RRP": 0, "RSSB": 1, "GenAm": 2}


def classify_pair(shaw_hi: str, shaw_lo: str) -> list[str]:
    """Correspondence classes of the diff between two competing spellings
    (hi = higher-precedence var's spelling)."""
    classes = []
    sm = SequenceMatcher(None, shaw_hi, shaw_lo, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        a, b = shaw_hi[i1:i2], shaw_lo[j1:j2]
        cls = PAIR_CLASS_TABLE.get((a, b))
        # KIT~FLEECE is only happY-tensing word-finally; medially it is
        # mostly the GenAm stressed-bare-i artifact (or a true variant).
        if cls == "happy-tensing" and i2 != len(shaw_hi):
            cls = "fleece-kit-drift"
        classes.append(cls if cls else f"other:{a or '∅'}~{b or '∅'}")
    return classes


def judge_group(records: list[dict], judgments: list[Judgment]) -> dict:
    """Verdict for one (word.lower, pos) group of competing spellings.

    Returns {verdict, canonical_shaw, pair_classes}. Verdicts:
      solo              one spelling; record judgment stands
      collapse-pair     diffs all normalizable -> one RRP entry, loser ABSORB
      merger-siblings   diffs are attested-merger swaps -> flag infra owns it
      national-pair     genuine national alternative -> both kept (exception)
      stress-pair       nurse/letter diff, needs stress marks -> review
      unexplained-pair  residue -> both stay + review note
    """
    spellings = {}
    for r in records:
        spellings.setdefault(r["Shaw"], []).append(r)
    if len(spellings) == 1:
        return {"verdict": "solo", "canonical_shaw": records[0]["Shaw"],
                "pair_classes": []}
    # Competing spellings all within ONE dialect are not a dialect collapse:
    # they are within-var pronunciation variants — the Goal-2 / variant-flag
    # decision, which is editorial. Per-record judgments stand.
    if len({r.get("var", "") for r in records}) == 1:
        return {"verdict": "within-var-variants",
                "canonical_shaw": records[0]["Shaw"], "pair_classes": []}

    ranked = sorted(spellings, key=lambda s: min(
        VAR_RANK.get(r.get("var", ""), 3) for r in spellings[s]))
    canon = ranked[0]
    all_classes = []
    verdicts = set()
    for other in ranked[1:]:
        classes = classify_pair(canon, other)
        all_classes.extend(classes)
        cset = set(classes)
        if cset <= NORMALIZABLE_CLASSES:
            verdicts.add("collapse-pair")
        elif cset <= NORMALIZABLE_CLASSES | MERGER_CLASSES:
            verdicts.add("merger-siblings")
        elif cset <= (NORMALIZABLE_CLASSES | MERGER_CLASSES
                      | NATIONAL_CLASSES):
            verdicts.add("national-pair")
        elif cset <= (NORMALIZABLE_CLASSES | MERGER_CLASSES
                      | NATIONAL_CLASSES | CATEGORY_CLASSES):
            verdicts.add("category-pair")
        elif cset & STRESS_CLASSES and not any(
                c.startswith("other:") for c in cset):
            verdicts.add("stress-pair")
        else:
            verdicts.add("unexplained-pair")

    for v in ("unexplained-pair", "stress-pair", "category-pair",
              "national-pair", "merger-siblings", "collapse-pair"):
        if v in verdicts:
            return {"verdict": v, "canonical_shaw": canon,
                    "pair_classes": all_classes}
    return {"verdict": "solo", "canonical_shaw": canon, "pair_classes": []}


def apply_group_to_records(group_verdict: dict, records: list[dict],
                           judgments: list[Judgment]) -> None:
    """Fold the group verdict back into member judgments (the variant
    decision): losers of a collapse-pair become ABSORB; members of an
    unexplained pair are demoted to STAY with a review note."""
    v = group_verdict["verdict"]
    canon = group_verdict["canonical_shaw"]
    for rec, j in zip(records, judgments):
        j.notes.append(f"group:{v}")
        loser = rec["Shaw"] != canon
        if v == "collapse-pair" and loser and j.outcome.startswith("PASS"):
            j.outcome, j.tier = "ABSORB", "C"
            j.reasons.append("pair-loser-variant")
        elif v in ("national-pair", "category-pair") and loser \
                and j.outcome.startswith("PASS"):
            # legitimate exception entry in its source dialect — a success
            j.outcome, j.tier = "STAY", "E"
            j.reasons.append("national-exception" if v == "national-pair"
                             else "category-residue")
        elif v == "unexplained-pair" and j.outcome.startswith("PASS"):
            j.outcome, j.tier = "STAY", "E"
            j.reasons.append("unexplained-pair-residue")
        elif v == "stress-pair" and loser and j.outcome.startswith("PASS") \
                and "stress-marks" not in j.witnesses:
            j.outcome, j.tier = "REVIEW", "F"
            j.reasons.append("stress-pair-unresolved")
