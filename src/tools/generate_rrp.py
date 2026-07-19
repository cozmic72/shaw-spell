#!/usr/bin/env python3
"""
RRP generator: mint a canonical RRP Shavian spelling FROM SCRATCH for supplement
candidates that still have no RRP entry, and gate merger/variant flags on the
confidence of their canonical counterpart.

This is the generative counterpart to the RRP reclassifier (reclassify_rrp.py).
The reclassifier JUDGES an existing candidate spelling ("does this pass as RRP?")
and relabels the passable ones to RRP. This stage runs where that leaves a gap:
a (word, pos) group that ended up with NO RRP entry at all, but DOES carry an IPA
pronunciation. For each such record the generator PRODUCES the RRP spelling the
Guide's stress-based rules would sanction, and attaches it ALONGSIDE the record's
existing spelling as a proposal the owner picks in review — never overwriting the
record's own Shaw (owner decision D2).

  data/supplement-combined-reclassified.json  (this stage's input)
  data/supplement-combined-generated.json      (this stage's output)

The stage does two things, in one pass over the reclassified pool:

  1. GENERATE (owner decision D1 — scope). For every record in a (word, pos)
     group that has NO var==RRP record AND that record HAS ipa, run
     rrp_generator.generate over the IPA (the pure, shave-free IPA-basis path
     only — the shave/names path is out of scope here). A GEN/FLAG proposal is
     attached as additive fields:

       generated_shaw    the minted RRP spelling (proposal, NOT the record's Shaw)
       generated_tier    A..F confidence (honest — flaky output reads as low tier)
       generated_method  "ipa-converter"
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

DETERMINISM: the IPA-basis generate() path is a pure function of the record
(Guide-table transforms + the repo converter, NO shave), so this stage is
byte-deterministic run-to-run on identical input. The shave-only path is not
used (out of scope: IPA-basis only).

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
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, load_upstream
import rrp_generator as G

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-reclassified.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-generated.json"

CANONICAL_VAR = "RRP"

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


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under. This
    stage never changes Shaw (propose-alongside), so the key is stable."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def group_key(entry):
    """The (word_lower, pos) group a candidate belongs to — the unit D1 scopes
    over (a group has an RRP entry or it does not) and D3 pairs within."""
    return (entry["Latn"].lower(), entry.get("pos", ""))


def upstream_rrp_words():
    """(word_lower, pos) keys with a NON-merged RRP/RSSB spelling in upstream
    ReadLex — the sanctioned dictionary attestations a merger flag can legitimately
    rest on. A reinterpreted TrapBath entry is itself a merged 𐑨 form (it carries
    a mergers flag) and is excluded, so it can never masquerade as the non-merged
    canonical it is measured against."""
    established = set()
    for entries in load_upstream().values():
        for entry in entries:
            if entry.get("mergers"):
                continue
            established.add((entry.get("Latn", "").lower(), entry.get("pos", "")))
    return established


# ------------------------------------------------------------ D1: generation

def generate_group(entries, tallies, samples):
    """Attach a generated RRP proposal to each ipa-bearing record of a no-RRP
    group, in place on copies. Returns the list of record copies (count-preserving,
    Shaw untouched). A group WITH an RRP entry, or a record WITHOUT ipa, is passed
    through verbatim (out of D1 scope)."""
    has_rrp = any(e.get("var") == CANONICAL_VAR for e in entries)
    out = []
    for entry in entries:
        record = dict(entry)
        if has_rrp or not entry.get("ipa"):
            out.append(record)
            continue

        p = G.generate(entry["Latn"], entry["ipa"], entry.get("pos", ""))
        if p.basis != "ipa":  # scope guard: IPA-basis path only, no shave
            raise SystemExit(
                f"generate_rrp: non-IPA basis {p.basis!r} for "
                f"{entry['Latn']!r} — D1 is IPA-basis only; shave path is "
                f"out of scope for this stage")

        tallies[f"outcome-{p.outcome}"] += 1
        tallies[f"tier-{p.tier}"] += 1

        # Propose ALONGSIDE (D2): the minted spelling is a separate field; the
        # record's own Shaw is never overwritten. A FAIL yields no spelling (no
        # RRP derivable) — recorded only via its flags, so review sees why.
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

def process(supplement, gen_tallies, gen_samples, gate_tallies, gate_samples):
    """The full stage: generate proposals for no-RRP ipa groups (D1/D2), then gate
    merger/variant flags on canonical confidence (D3). Re-groups by (word, pos) so
    both passes see a whole group at once. Count-preserving: every input record
    appears once in the output (only fields are added/stripped)."""
    established_rrp = upstream_rrp_words()

    groups = defaultdict(list)
    for entries in supplement.values():
        for entry in entries:
            groups[group_key(entry)].append(entry)

    out = defaultdict(list)
    for entries in groups.values():
        generated = generate_group(entries, gen_tallies, gen_samples)
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
