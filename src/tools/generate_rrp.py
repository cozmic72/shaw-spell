#!/usr/bin/env python3
"""
RRP generator: mint a canonical RRP Shavian spelling FROM SCRATCH for supplement
candidates that still have no RRP entry, and gate merger/variant flags on the
confidence of their canonical counterpart.

This is the generative counterpart to the RRP reclassifier (reclassify_rrp.py).
The reclassifier JUDGES an existing candidate spelling ("does this pass as RRP?")
and relabels the passable ones to RRP. This stage runs where that leaves a gap:
a (word, pos) group that ended up with NO RRP entry at all. For each such record
the generator PRODUCES an RRP spelling proposal and attaches it ALONGSIDE the
record's existing spelling — a proposal the owner picks in review, never
overwriting the record's own Shaw (owner decision D2). Two evidence paths:

  - a record that carries an IPA pronunciation -> the pure, deterministic
    IPA-basis path: the Guide's stress-based rules over the converter output.
  - a record with NO IPA (a proper name) -> the shave/names path: shave -b
    --confidence 0 is the sole generator (Roman->Shavian G2P). A single argmax
    option is tier D (LOW confidence); no rendering is a FAIL. shave is
    non-deterministic on low-confidence words, which is acceptable HERE precisely
    because nothing touches the patch store and its flaky output is honestly
    routed to tier D (never presented as canonical) — "stakes not mistakes".

  data/supplement-combined-reclassified.json  (this stage's input)
  data/supplement-combined-generated.json      (this stage's output)

The stage does two things, in one pass over the reclassified pool:

  1. GENERATE (owner decision D1 — scope). For every record in a (word, pos)
     group that has NO var==RRP record, run rrp_generator.generate — over the IPA
     if the record has one (deterministic IPA-basis path), else over shave's
     Roman->Shavian G2P (the names path). A GEN/FLAG proposal is attached as
     additive fields:

       generated_shaw    the minted RRP spelling (proposal, NOT the record's Shaw)
       generated_tier    A..F confidence (honest — flaky output reads as low tier)
       generated_method  "ipa-converter" (IPA basis) | "shave-g2p" (names basis)
       generated_from    lineage: the evidence path + any witnesses
       generated_flags   present only for a FLAG/FAIL proposal (a gated site)

     The record's own Shaw / var are UNTOUCHED (propose-alongside). The record
     count is unchanged — this stage only ADDS fields — and that is asserted.

  2. FLAG-GATE (owner decision D3 — the merger/variant invariant). A record may
     carry a merger/variant flag ONLY IF its canonical RRP counterpart is
     HIGH-confidence (tier A/B, IPA-basis, stress-known). A merged form (GenAm 𐑪
     for cot-caught, 𐑨 for trap-bath) is an alternate OF a canonical non-merged
     RRP form; if that canonical is itself a shaky low-confidence guess, the
     "alternate-of" relationship is built on sand (stakes-not-mistakes corollary).
     So: for every merger-flagged record, find its canonical counterpart's
     confidence; if it is NOT high, STRIP the merger flag (recording why in
     merger_gate) and leave both records as plain low-confidence review
     candidates. High-confidence counterparts leave the flag intact.

     The canonical counterpart's confidence is (in resolution order):
       - an established upstream ReadLex RRP entry for the (word, pos)  -> HIGH
         (a sanctioned dictionary spelling; the flag rests on solid ground)
       - an in-group var==RRP sibling relabelled by the reclassifier       -> its
         rrp_tier (A/B = HIGH; C or absent = not high)
       - an in-group sibling this stage generated a tier-A/B proposal for  -> HIGH
       - otherwise (only shaky non-RRP siblings)                           -> NOT HIGH

This gate is enforced HERE, after the reclassifier and the generator, because
that is the first point at which the canonical counterpart's confidence is known:
the merger classifier attaches flags BEFORE any RRP tier exists, and the tier a
flag must consult (rrp_tier for a reclassified sibling, generated_tier for a
generated one) is only written by those two stages. Running the gate here reads
the RIGHT confidence for the canonical.

DETERMINISM (honest): the IPA-basis path is a pure function of the record
(Guide-table transforms + the repo converter, NO shave), so the ipa portion of
the output is byte-deterministic run-to-run on identical input — unchanged. The
shave/names path is only "as deterministic as shave allows": `--confidence 0`
pins shave to its argmax (no interactive ambiguity, no bracket-list), so it is
stable-as-shave-allows, but shave can drift run-to-run on low-confidence words.
That drift is confined to tier-D `generated_shaw` proposals — never the record's
own Shaw, never a patch, never a high tier — so flaky ⟺ low-confidence holds and
the drift costs nothing ("stakes not mistakes").

NEVER-AUTO-ACCEPT: every generated proposal and every gate action produces REVIEW
CANDIDATES. Nothing is sanctioned, nothing is written to the patch store, no
record's accepted spelling is overwritten, nothing is dropped.

PIPELINE PLACEMENT (unchanged upstream/downstream):
  combine -> defs -> dedup -> classify_mergers -> reclassify -> HERE (generated)
  -> collapse -> decontaminate -> filter -> basis

Inputs:  data/supplement-combined-reclassified.json
Outputs: data/supplement-combined-generated.json

Usage:
    python3 src/tools/generate_rrp.py
"""

import json
import subprocess
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, load_upstream
from ipa_to_shavian import contains_shavian
import rrp_generator as G

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-reclassified.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-generated.json"

CANONICAL_VAR = "RRP"

# The shave/names path (no-IPA proper-name records -> shave Roman->Shavian G2P) is
# an OWNER-UNDECIDED feature and DEFAULTS OFF. With it off, this stage is IPA-basis
# ONLY: a no-ipa record in a no-RRP group is passed through verbatim (no shave
# call, no generated_* fields) — identical to the pre-shave-path behaviour. The
# path's CODE remains in place (batch_shave_names, no_ipa_words_needing_shave, the
# shave branch of generate_group) but is DORMANT until explicitly enabled, ready to
# be switched on later (likely repurposed for the no-IPA speculative-words lane).
# Enable per-call via process(..., enable_shave=True); the orchestrator also honours
# SHAW_SPELL_ENABLE_SHAVE_NAMES=1. Off by default, shave is never even invoked.
ENABLE_SHAVE_NAMES = False

# shave invocation for the no-IPA (names) path. `-b` = British/RRP; `--confidence
# 0` = always pick the argmax silently (never emit shave's bracket ambiguity
# list). Argmax is "as deterministic as shave allows" — the reliable-generation
# precedent — and it pins every name proposal to a SINGLE option, which
# rrp_generator._generate_from_shave routes to tier D (low confidence). A
# bracket-list would route to FLAG/F; --confidence 0 means we never rely on that
# path, so a name proposal is tier D or (non-Shavian / no evidence) FAIL, never
# high tier — flaky ⟺ low-tier holds by construction ("stakes not mistakes").
SHAVE_CMD = ["shave", "-b", "--confidence", "0"]
SHAVE_CHUNK = 5000
SHAVE_TIMEOUT = 300

# The reclassifier/generator tiers that count as a HIGH-confidence canonical
# counterpart for the D3 flag-gate: IPA-basis, stress-known, rules-clean. The
# reclassifier only reaches PASS (tier A/B) when every stress-gate is resolved,
# and the generator only reaches tier A/B on a stress-known IPA basis — so A/B is
# exactly "high-confidence, IPA-basis, stress-known". C and below are not.
HIGH_TIERS = frozenset({"A", "B"})

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def batch_shave_names(words):
    """Roman->Shavian G2P for a batch of no-IPA words via `shave -b --confidence
    0`, in ONE subprocess per chunk (shave has a fixed per-invocation startup
    cost). Returns {word: shave_shaw} for words shave rendered as Shavian; a word
    shave could not spell (echoed verbatim, no Shavian letters) is ABSENT — the
    caller then sees no evidence and FAILs it, never a guess.

    Inputs are BLANK-line separated (word\\n\\nword\\n\\n...): the blank line is a
    correctness requirement, not style — it is the sentence/context boundary that
    makes shave judge each word IN ISOLATION. Plain newlines make shave read the
    batch as a pseudo-sentence whose POS/phrase heuristics contaminate
    context-sensitive disambiguation across word boundaries.

    The leading namer dot (·) shave prefixes to proper nouns is stripped: the
    pool stores name spellings WITHOUT it (matching the names supplement and
    ReadLex storage), and upgrade_confidence_shave strips it likewise.

    FAIL-FAST: a per-chunk output/input line-count mismatch is a hard error
    (never silently mis-zip words to the wrong spellings). shave being absent or
    timing out is fatal too — this stage cannot honestly proceed without it.
    """
    out = {}
    for i in range(0, len(words), SHAVE_CHUNK):
        chunk = words[i:i + SHAVE_CHUNK]
        proc = subprocess.run(
            SHAVE_CMD, input="\n\n".join(chunk),
            capture_output=True, text=True, timeout=SHAVE_TIMEOUT, check=True)
        lines = [l for l in proc.stdout.strip().split("\n") if l.strip()]
        if len(lines) != len(chunk):
            raise SystemExit(
                f"generate_rrp: shave returned {len(lines)} lines for "
                f"{len(chunk)} input words — refusing to mis-align proposals")
        for word, line in zip(chunk, lines):
            shaw = line.strip().lstrip("·")
            # A line with no Shavian letters is shave's unknown-word echo, not an
            # opinion — leave the word out so the generator FAILs it (no evidence).
            if shaw and contains_shavian(shaw):
                out[word] = shaw
    return out


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under. This
    stage never changes Shaw (propose-alongside), so the key is stable."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def group_key(entry):
    """The (word_lower, pos) group a candidate belongs to — the unit D1 scopes
    over (a group has an RRP entry or it does not) and D3 pairs within."""
    return (entry["Latn"].lower(), entry.get("pos", ""))


def upstream_rrp_words(upstream=None):
    """(word_lower, pos) keys with a NON-merged RRP/RSSB spelling in upstream
    ReadLex — the sanctioned dictionary attestations a merger flag can legitimately
    rest on. A reinterpreted TrapBath entry is itself a merged 𐑨 form (it carries
    a mergers flag) and is excluded, so it can never masquerade as the non-merged
    canonical it is measured against. `upstream` is threaded in by the orchestrator;
    None loads it."""
    established = set()
    if upstream is None:
        upstream = load_upstream()
    for entries in upstream.values():
        for entry in entries:
            if entry.get("mergers"):
                continue
            established.add((entry.get("Latn", "").lower(), entry.get("pos", "")))
    return established


# ------------------------------------------------------------ D1: generation

def _attach_proposal(record, entry, p, tallies, samples):
    """Attach a generated proposal ALONGSIDE the record (D2): a set of additive
    `generated_*` fields. The record's own Shaw/var are NEVER overwritten. A FAIL
    yields no spelling (no RRP derivable) — recorded only via its flags."""
    tallies[f"outcome-{p.outcome}"] += 1
    tallies[f"tier-{p.tier}"] += 1

    if p.shaw is not None:
        record["generated_shaw"] = p.shaw
    record["generated_tier"] = p.tier
    record["generated_method"] = ("ipa-converter" if p.basis == "ipa"
                                  else "shave-g2p")
    record["generated_from"] = {
        "basis": p.basis,
        "outcome": p.outcome,
        "witnesses": (["shave"] if p.shave_agrees else []),
        "notes": list(p.notes),
    }
    if p.flags:
        record["generated_flags"] = list(p.flags)

    if p.outcome == "GEN" and len(samples["GEN"]) < SAMPLE_LIMIT:
        samples["GEN"].append((entry, p))
    elif p.outcome != "GEN" and len(samples[p.outcome]) < SAMPLE_LIMIT:
        samples[p.outcome].append((entry, p))


def generate_group(entries, shave_map, tallies, samples, enable_shave=ENABLE_SHAVE_NAMES):
    """Attach a generated RRP proposal to each record of a no-RRP group, in place
    on copies. Two evidence paths, dispatched per record:

      - HAS ipa  -> the pure, deterministic IPA-basis converter path (unchanged).
      - NO ipa   -> the shave/names path: shave -b --confidence 0 is the sole
                    generator (basis "shave"), single-option => tier D. shave was
                    run once up front (batch); `shave_map` holds its output.
                    OWNER-UNDECIDED, gated behind `enable_shave` (default OFF): when
                    off, a no-ipa record is passed through VERBATIM (no proposal),
                    identical to the pre-shave-path IPA-basis-only behaviour.

    Returns the list of record copies (count-preserving, Shaw untouched). A group
    WITH an RRP entry is passed through verbatim (out of D1 scope — its canonical
    already exists)."""
    has_rrp = any(e.get("var") == CANONICAL_VAR for e in entries)
    out = []
    for entry in entries:
        record = dict(entry)
        if has_rrp or (not entry.get("ipa") and not enable_shave):
            # no-RRP group with an RRP sibling, OR a no-ipa record while the
            # shave/names path is disabled -> pass through untouched (IPA-only).
            out.append(record)
            continue

        if entry.get("ipa"):
            p = G.generate(entry["Latn"], entry["ipa"], entry.get("pos", ""))
            if p.basis != "ipa":  # an ipa-bearing record must take the ipa path
                raise SystemExit(
                    f"generate_rrp: ipa-bearing {entry['Latn']!r} produced "
                    f"non-IPA basis {p.basis!r} — a bug in path dispatch")
        else:
            # No IPA: shave is the generator. Its argmax spelling (if any) is the
            # sole basis; absence of a rendering => no evidence => FAIL. A single
            # option can only reach tier D (low confidence) by construction.
            key = entry["Latn"].lower()
            opts = (shave_map[key],) if key in shave_map else ()
            p = G.generate(entry["Latn"], None, entry.get("pos", ""),
                           shave_opts=opts)
            if p.basis != "shave":  # a no-ipa record must take the shave path
                raise SystemExit(
                    f"generate_rrp: no-ipa {entry['Latn']!r} produced non-shave "
                    f"basis {p.basis!r} — a bug in path dispatch")
            if p.tier in HIGH_TIERS:  # shave path can NEVER be high tier
                raise SystemExit(
                    f"generate_rrp: shave path yielded high tier {p.tier} for "
                    f"{entry['Latn']!r} — flaky-shave must be low-confidence "
                    f"(D/F) by construction; a high tier here is a bug")

        _attach_proposal(record, entry, p, tallies, samples)
        out.append(record)
    return out


# ---------------------------------------------------------- D3: the flag-gate

def canonical_is_high_confidence(record, group_records, established_rrp):
    """Whether the merger/variant-flagged `record`'s canonical RRP counterpart is
    HIGH-confidence (tier A/B, IPA-basis, stress-known) — the D3 predicate.

    The canonical counterpart is the non-merged RRP form the flag is an alternate
    of. Its confidence, in resolution order:

      1. An established upstream ReadLex RRP/RSSB entry for the (word, pos): the
         sanctioned dictionary spelling. HIGH — a flag on a real dictionary word
         rests on solid ground.
      2. An in-group var==RRP sibling (relabelled by the reclassifier): HIGH iff
         its rrp_tier is A/B (PASS with resolved stress-gates); a tier-C respell
         or a tier-less pass-through is not high.
      3. An in-group sibling this stage generated a tier-A/B proposal for: HIGH.
      4. Otherwise only shaky (non-RRP, or low-tier) siblings exist: NOT high.
    """
    key = (record["Latn"].lower(), record.get("pos", ""))
    if key in established_rrp:
        return True, "readlex-rrp"

    for sib in group_records:
        if sib is record:
            continue
        if sib.get("mergers"):
            continue  # a merged sibling is not the non-merged canonical
        if sib.get("var") == CANONICAL_VAR and sib.get("rrp_tier") in HIGH_TIERS:
            return True, f"reclassified-rrp-{sib['rrp_tier']}"
        if sib.get("generated_tier") in HIGH_TIERS:
            return True, f"generated-rrp-{sib['generated_tier']}"

    return False, "low-confidence-canonical"


def gate_group(entries, established_rrp, tallies, samples):
    """Strip a merger/variant flag from any record whose canonical RRP counterpart
    is not high-confidence (D3). Records without a flag pass through untouched. The
    stripped flag's pre-image is preserved (merger_gate) so review sees the gate
    acted and why — nothing is silently mutated."""
    for record in entries:
        flag_kind = None
        if record.get("mergers"):
            flag_kind = "mergers"
        elif record.get("variant"):
            flag_kind = "variant"
        if flag_kind is None:
            continue

        high, why = canonical_is_high_confidence(record, entries, established_rrp)
        if high:
            tallies["flag-kept"] += 1
            tallies[f"flag-kept-{why}"] += 1
            continue

        # Not high-confidence: strip the flag, leaving both records as plain
        # low-confidence review candidates. Record what was removed and why.
        removed = record.pop("mergers", None) if flag_kind == "mergers" \
            else record.pop("variant", None)
        record["merger_gate"] = {
            "stripped": flag_kind,
            "was": removed,
            "reason": why,
        }
        tallies["flag-stripped"] += 1
        tallies[f"flag-stripped-{flag_kind}"] += 1
        if len(samples["stripped"]) < SAMPLE_LIMIT:
            samples["stripped"].append(record)
    return entries


# ------------------------------------------------------------------- driver

def no_ipa_words_needing_shave(groups):
    """The distinct lowercased words of every no-ipa record in a no-RRP group —
    exactly the shave/names path's inputs. Batched up front so shave runs ONCE
    (fixed startup cost) instead of per record."""
    words = set()
    for entries in groups.values():
        if any(e.get("var") == CANONICAL_VAR for e in entries):
            continue  # group already has a canonical — out of D1 scope
        for entry in entries:
            if not entry.get("ipa"):
                words.add(entry["Latn"].lower())
    return sorted(words)


def process(supplement, gen_tallies, gen_samples, gate_tallies, gate_samples,
            upstream=None, shave_fn=None, enable_shave=ENABLE_SHAVE_NAMES):
    """The full stage: generate proposals for no-RRP groups (D1/D2) — the pure
    IPA-basis path for ipa-bearing records and (when enabled) the shave/names path
    for no-ipa records — then gate merger/variant flags on canonical confidence
    (D3). Re-groups by (word, pos) so both passes see a whole group at once.
    Count-preserving: every input record appears once in the output (only fields
    are added/stripped).

    `upstream` (reinterpreted ReadLex) and `shave_fn` (words -> {word: shaw}) are
    threaded in by the orchestrator; None uses the disk/subprocess defaults. Note
    the shave/names path is non-deterministic on low-confidence words; injecting a
    fixed shave_fn is how a parity harness pins it.

    `enable_shave` gates the OWNER-UNDECIDED shave/names path and DEFAULTS OFF: when
    off, shave is NEVER invoked and no-ipa records pass through verbatim (IPA-basis
    only), identical to the pre-shave-path behaviour."""
    established_rrp = upstream_rrp_words(upstream)
    if shave_fn is None:
        shave_fn = batch_shave_names

    groups = defaultdict(list)
    for entries in supplement.values():
        for entry in entries:
            groups[group_key(entry)].append(entry)

    # Shave the no-ipa names once, up front (blank-line batched, one subprocess).
    # Only when the shave/names path is enabled — off by default, shave is never
    # even invoked and every no-ipa record is passed through verbatim.
    if enable_shave:
        shave_words = no_ipa_words_needing_shave(groups)
        gen_tallies["shave-words-in"] = len(shave_words)
        shave_map = shave_fn(shave_words) if shave_words else {}
        gen_tallies["shave-words-rendered"] = len(shave_map)
    else:
        shave_map = {}

    out = defaultdict(list)
    for entries in groups.values():
        generated = generate_group(entries, shave_map, gen_tallies, gen_samples,
                                   enable_shave=enable_shave)
        gated = gate_group(generated, established_rrp, gate_tallies, gate_samples)
        for record in gated:
            out[output_bucket_key(record)].append(record)

    return {key: out[key] for key in sorted(out)}


def report(gen_tallies, gen_samples, gate_tallies, gate_samples):
    print("\n=== RRP generation report (D1/D2) ===")
    total = sum(v for k, v in gen_tallies.items() if k.startswith("outcome-"))
    print(f"Records given a generated proposal: {total:,}")
    for outcome in ("GEN", "FLAG", "FAIL"):
        print(f"  {outcome:5}: {gen_tallies.get(f'outcome-{outcome}', 0):,}")
    print("Tier distribution:")
    for tier in ("A", "B", "C", "D", "F"):
        print(f"  tier {tier}: {gen_tallies.get(f'tier-{tier}', 0):,}")

    print("Shave/names path (no-ipa records):")
    print(f"  no-ipa words shaved:   {gen_tallies.get('shave-words-in', 0):,}")
    print(f"  rendered by shave:     {gen_tallies.get('shave-words-rendered', 0):,}")

    if gen_samples["GEN"]:
        print("\nSample generated proposals (word [pos] var: tier, "
              "shaw-length only — Shavian sampled, not dumped):")
        for entry, p in gen_samples["GEN"]:
            print(f"  {entry['Latn']} [{entry.get('pos', '')}] "
                  f"{entry.get('var', '')}: tier {p.tier}, "
                  f"len(gen)={len(p.shaw or '')} vs len(own)="
                  f"{len(entry.get('Shaw', ''))}")

    print("\n=== merger/variant flag-gate report (D3) ===")
    print(f"Flags kept (high-conf canonical):   {gate_tallies['flag-kept']:,}")
    for why in sorted(k for k in gate_tallies if k.startswith("flag-kept-")):
        print(f"    {why[len('flag-kept-'):]:22}: {gate_tallies[why]:,}")
    print(f"Flags stripped (low-conf canonical): {gate_tallies['flag-stripped']:,}")
    for kind in ("mergers", "variant"):
        n = gate_tallies.get(f"flag-stripped-{kind}", 0)
        print(f"    {kind:22}: {n:,}")

    if gate_samples["stripped"]:
        print("\nSample stripped flags (word [pos] var: was -> now plain "
              "low-conf candidate):")
        for r in gate_samples["stripped"]:
            g = r["merger_gate"]
            print(f"  {r['Latn']} [{r.get('pos', '')}] {r.get('var', '')}: "
                  f"{g['stripped']}={g['was']} stripped ({g['reason']})")


def main():
    gen_tallies = Counter()
    gen_samples = defaultdict(list)
    gate_tallies = Counter()
    gate_samples = defaultdict(list)

    supplement = load_json(INPUT_PATH)
    n_in = sum(len(v) for v in supplement.values())

    generated = process(supplement, gen_tallies, gen_samples,
                        gate_tallies, gate_samples)
    n_out = sum(len(v) for v in generated.values())
    if n_out != n_in:
        raise SystemExit(
            f"generate_rrp: record count changed ({n_in} -> {n_out}); this stage "
            f"only ADDS proposal fields and STRIPS gated flags — it never drops or "
            f"splits a record, so a count change is a bug")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(generated, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: {n_out:,} records")

    report(gen_tallies, gen_samples, gate_tallies, gate_samples)


if __name__ == "__main__":
    main()
