#!/usr/bin/env python3
"""
Train a statistical IPA normalizer that learns to convert Britfone (SSB) IPA
to ReadLex (Rhotic RP) IPA, using the ~15K overlapping words as training data.

Approach: Needleman-Wunsch alignment to learn context-sensitive character
substitution rules with backoff from 5-gram to trigram to unigram.

Usage:
    python3 src/tools/train_ipa_normalizer.py
"""

import json
import re
import sys
import random
from pathlib import Path
from collections import Counter, defaultdict

TOOLS_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOLS_DIR))

from ipa_to_shavian import normalize_ipa, ipa_to_shavian

PROJECT_ROOT = Path(__file__).parent.parent.parent
BRITFONE_CSV = PROJECT_ROOT / "external" / "britfone" / "britfone.main.3.0.1.csv"
READLEX_JSON = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
MODEL_OUTPUT = PROJECT_ROOT / "data" / "ipa-normalizer-model.json"

BOS = "^"
EOS = "$"


def strip_stress(ipa: str) -> str:
    return re.sub('[ˈˌ]', '', ipa)


def parse_britfone() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    with open(BRITFONE_CSV, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',', 1)
            if len(parts) != 2:
                continue
            raw_word = parts[0].strip()
            phonemes_str = parts[1].strip()
            match = re.match(r'^(.+?)\((\d+)\)$', raw_word)
            word = (match.group(1) if match else raw_word).lower().replace('_', ' ')
            ipa = phonemes_str.replace(' ', '')
            if word not in result:
                result[word] = []
            if ipa not in result[word]:
                result[word].append(ipa)
    return result


def parse_readlex() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    with open(READLEX_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for entries in data.values():
        for entry in entries:
            word = entry['Latn'].lower()
            ipa = entry['ipa']
            if word not in result:
                result[word] = []
            if ipa not in result[word]:
                result[word].append(ipa)
    return result


def needleman_wunsch(seq1: str, seq2: str) -> list[tuple[str, str]]:
    """Align two IPA strings. Returns list of (char1, char2) pairs.
    Gaps represented as empty string."""
    GAP = -1
    MATCH = 2
    MISMATCH = -1

    SIMILAR = {
        ('ɪ', 'ə'), ('ə', 'ɪ'), ('ɪ', 'i'), ('i', 'ɪ'),
        ('ə', 'ʌ'), ('ʌ', 'ə'), ('ɒ', 'ɔ'), ('ɔ', 'ɒ'),
        ('e', 'ɛ'), ('ɛ', 'e'), ('ɪ', 'Ə'), ('Ə', 'ɪ'),
        ('ə', 'Ə'), ('Ə', 'ə'), ('ɑ', 'Ɑ'), ('Ɑ', 'ɑ'),
        ('ɪ', 'I'), ('I', 'ɪ'), ('ə', 'I'), ('I', 'ə'),
    }

    def score(a, b):
        if a == b:
            return MATCH
        if (a, b) in SIMILAR:
            return 0
        return MISMATCH

    n, m = len(seq1), len(seq2)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i-1][0] + GAP
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j-1] + GAP

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(
                dp[i-1][j-1] + score(seq1[i-1], seq2[j-1]),
                dp[i-1][j] + GAP,
                dp[i][j-1] + GAP,
            )

    alignment = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i-1][j-1] + score(seq1[i-1], seq2[j-1]):
            alignment.append((seq1[i-1], seq2[j-1]))
            i -= 1
            j -= 1
        elif i > 0 and dp[i][j] == dp[i-1][j] + GAP:
            alignment.append((seq1[i-1], ""))
            i -= 1
        else:
            alignment.append(("", seq2[j-1]))
            j -= 1
    alignment.reverse()
    return alignment


def build_training_pairs(britfone: dict, readlex: dict) -> list[tuple[str, str, str]]:
    pairs = []
    overlap_words = set(britfone.keys()) & set(readlex.keys())
    print(f"Overlapping words: {len(overlap_words)}")

    for word in sorted(overlap_words):
        bf_ipa = britfone[word][0]
        rl_ipa = readlex[word][0]
        bf_normalized = normalize_ipa(bf_ipa, word=word, source="britfone")
        bf_clean = strip_stress(bf_normalized)
        rl_clean = strip_stress(rl_ipa)
        pairs.append((word, bf_clean, rl_clean))

    return pairs


def get_src_context(src_chars: list[str], i: int, width: int) -> list[str]:
    """Get context characters from src side, skipping gaps."""
    ctx = []
    # Left context
    left = []
    for j in range(i - 1, -1, -1):
        if src_chars[j] != "":
            left.append(src_chars[j])
            if len(left) == width:
                break
    left.reverse()
    while len(left) < width:
        left.insert(0, BOS)
    ctx.extend(left)
    # Current
    ctx.append(src_chars[i])
    # Right context
    right = []
    for j in range(i + 1, len(src_chars)):
        if src_chars[j] != "":
            right.append(src_chars[j])
            if len(right) == width:
                break
    while len(right) < width:
        right.append(EOS)
    ctx.extend(right)
    return ctx


def extract_features(pairs: list[tuple[str, str, str]]) -> list[dict]:
    """Extract alignment features with 5-gram context (2 left, current, 2 right)."""
    records = []
    for word, bf_ipa, rl_ipa in pairs:
        alignment = needleman_wunsch(bf_ipa, rl_ipa)
        src_chars = [s for s, t in alignment]
        tgt_chars = [t for s, t in alignment]

        for i in range(len(src_chars)):
            ctx = get_src_context(src_chars, i, 2)
            # ctx is [l2, l1, cur, r1, r2]
            records.append({
                'src': src_chars[i],
                'tgt': tgt_chars[i],
                'l2': ctx[0], 'l1': ctx[1],
                'r1': ctx[3], 'r2': ctx[4],
                'word': word,
            })
    return records


def train_model(records: list[dict]) -> dict:
    """Train context-sensitive substitution model with multiple n-gram levels.

    Stores counts for:
    - 5gram: (l2, l1, src, r1, r2)
    - trigram: (l1, src, r1)
    - bigram_r: (src, r1)
    - bigram_l: (l1, src)
    - unigram: (src,)

    Each maps to a Counter of target characters.
    """
    levels = {
        '5gram': defaultdict(Counter),
        'trigram': defaultdict(Counter),
        'bigram_r': defaultdict(Counter),
        'bigram_l': defaultdict(Counter),
        'unigram': defaultdict(Counter),
    }

    for rec in records:
        src = rec['src']
        tgt = rec['tgt']
        l1, l2 = rec['l1'], rec['l2']
        r1, r2 = rec['r1'], rec['r2']

        levels['5gram'][(l2, l1, src, r1, r2)][tgt] += 1
        levels['trigram'][(l1, src, r1)][tgt] += 1
        levels['bigram_r'][(src, r1)][tgt] += 1
        levels['bigram_l'][(l1, src)][tgt] += 1
        levels['unigram'][(src,)][tgt] += 1

    # Convert to serializable format with distributions
    model = {}
    for level_name, counts_dict in levels.items():
        level_data = {}
        for key, counter in counts_dict.items():
            total = sum(counter.values())
            str_key = "|".join(key)
            # Store top-5 targets with counts
            dist = {tgt: cnt for tgt, cnt in counter.most_common(5)}
            level_data[str_key] = {'d': dist, 'n': total}
        model[level_name] = level_data

    return model


def lookup_best(model_level: dict, key: str, min_count: int, min_prob: float) -> str | None:
    """Look up the best target for a given key in a model level."""
    if key not in model_level:
        return None
    entry = model_level[key]
    if entry['n'] < min_count:
        return None
    dist = entry['d']
    total = entry['n']
    best = max(dist, key=dist.get)
    prob = dist[best] / total
    if prob < min_prob:
        return None
    return best


def apply_model(bf_ipa: str, model: dict) -> str:
    """Apply trained model to convert Britfone IPA toward ReadLex IPA.

    Uses 5-gram context with backoff to trigram, bigram, unigram.
    """
    src = bf_ipa
    n = len(src)
    result = []

    # Phase 1: character substitutions
    for i in range(n):
        char = src[i]
        l1 = src[i-1] if i >= 1 else BOS
        l2 = src[i-2] if i >= 2 else BOS
        r1 = src[i+1] if i < n-1 else EOS
        r2 = src[i+2] if i < n-2 else EOS

        tgt = None

        # 5-gram (most specific)
        key5 = f"{l2}|{l1}|{char}|{r1}|{r2}"
        tgt = lookup_best(model['5gram'], key5, min_count=3, min_prob=0.6)

        # Trigram
        if tgt is None:
            key3 = f"{l1}|{char}|{r1}"
            tgt = lookup_best(model['trigram'], key3, min_count=5, min_prob=0.65)

        # Bigram right
        if tgt is None:
            key_br = f"{char}|{r1}"
            tgt = lookup_best(model['bigram_r'], key_br, min_count=8, min_prob=0.75)

        # Bigram left
        if tgt is None:
            key_bl = f"{l1}|{char}"
            tgt = lookup_best(model['bigram_l'], key_bl, min_count=8, min_prob=0.75)

        # Unigram (most general)
        if tgt is None:
            key1 = char
            tgt = lookup_best(model['unigram'], key1, min_count=10, min_prob=0.85)

        if tgt is None:
            tgt = char

        # Don't apply deletions or insertions from subst model
        if tgt == "":
            tgt = char

        result.append(tgt)

    ipa = ''.join(result)


    return ipa


def evaluate(pairs: list[tuple[str, str, str]], model: dict, label: str = ""):
    """Evaluate model on (word, bf_ipa, rl_ipa) pairs."""
    word_correct = 0
    word_total = len(pairs)
    shaw_correct = 0
    baseline_word_correct = 0
    baseline_shaw_correct = 0
    mismatches = []

    for word, bf_ipa, rl_ipa in pairs:
        predicted = apply_model(bf_ipa, model)

        if predicted == rl_ipa:
            word_correct += 1
        else:
            mismatches.append((word, bf_ipa, rl_ipa, predicted))

        if bf_ipa == rl_ipa:
            baseline_word_correct += 1

        predicted_shaw = ipa_to_shavian(predicted)
        target_shaw = ipa_to_shavian(rl_ipa)
        if predicted_shaw == target_shaw:
            shaw_correct += 1

        baseline_shaw = ipa_to_shavian(bf_ipa)
        if baseline_shaw == target_shaw:
            baseline_shaw_correct += 1

    print(f"\n{'='*60}")
    print(f"Evaluation: {label}")
    print(f"{'='*60}")
    print(f"Word count:        {word_total}")
    print(f"")
    print(f"Baseline (rule-based only):")
    print(f"  Word-level IPA:  {baseline_word_correct}/{word_total} ({100*baseline_word_correct/word_total:.1f}%)")
    print(f"  Shavian:         {baseline_shaw_correct}/{word_total} ({100*baseline_shaw_correct/word_total:.1f}%)")
    print(f"")
    print(f"ML model:")
    print(f"  Word-level IPA:  {word_correct}/{word_total} ({100*word_correct/word_total:.1f}%)")
    print(f"  Shavian:         {shaw_correct}/{word_total} ({100*shaw_correct/word_total:.1f}%)")

    # Show sample mismatches
    print(f"\nSample mismatches (first 30):")
    for word, bf, rl, pred in mismatches[:30]:
        shaw_pred = ipa_to_shavian(pred)
        shaw_tgt = ipa_to_shavian(rl)
        marker = "  " if shaw_pred == shaw_tgt else "!!"
        print(f"  {marker} {word:20s}  bf={bf:20s}  rl={rl:20s}  pred={pred:20s}")

    return {
        'word_accuracy': word_correct / word_total,
        'shaw_accuracy': shaw_correct / word_total,
        'baseline_word': baseline_word_correct / word_total,
        'baseline_shaw': baseline_shaw_correct / word_total,
    }


def analyze_diffs(records: list[dict]):
    """Show most common character differences."""
    diff_counts = Counter()
    for rec in records:
        if rec['src'] != rec['tgt']:
            diff_counts[(rec['src'], rec['tgt'])] += 1

    print(f"\nTop character-level differences (src -> tgt):")
    for (src, tgt), count in diff_counts.most_common(25):
        src_l = repr(src) if src else "'(ins)'"
        tgt_l = repr(tgt) if tgt else "'(del)'"
        print(f"  {src_l:8s} -> {tgt_l:8s}  count={count}")


def main():
    print("Loading data...")
    britfone = parse_britfone()
    readlex = parse_readlex()
    print(f"Britfone: {len(britfone)} words, ReadLex: {len(readlex)} words")

    print("\nBuilding training pairs...")
    pairs = build_training_pairs(britfone, readlex)
    identical = sum(1 for _, bf, rl in pairs if bf == rl)
    print(f"Total: {len(pairs)}, Already identical: {identical} ({100*identical/len(pairs):.1f}%)")

    # 80/20 split
    random.seed(42)
    shuffled = list(pairs)
    random.shuffle(shuffled)
    split = int(len(shuffled) * 0.8)
    train_pairs = shuffled[:split]
    test_pairs = shuffled[split:]
    print(f"Train: {len(train_pairs)}, Test: {len(test_pairs)}")

    print("\nExtracting features...")
    train_records = extract_features(train_pairs)
    print(f"Alignment records: {len(train_records)}")
    analyze_diffs(train_records)

    print("\nTraining model...")
    model = train_model(train_records)
    for level in model:
        print(f"  {level}: {len(model[level])} entries")

    evaluate(train_pairs, model, "TRAIN SET")
    test_results = evaluate(test_pairs, model, "TEST SET")

    # Train final model on all data
    print("\n\nTraining final model on ALL data...")
    all_records = extract_features(pairs)
    final_model = train_model(all_records)

    # Prune model: remove entries that map identity with high probability
    # (they're not needed since the default behavior is identity)
    pruned = {}
    for level_name, level_data in final_model.items():
        pruned_level = {}
        for key, entry in level_data.items():
            dist = entry['d']
            total = entry['n']
            best = max(dist, key=dist.get)
            # Extract the source character from the key
            parts = key.split('|')
            if level_name == '5gram':
                src_char = parts[2]
            elif level_name == 'trigram':
                src_char = parts[1]
            elif level_name == 'bigram_r':
                src_char = parts[0]
            elif level_name == 'bigram_l':
                src_char = parts[1]
            elif level_name == 'unigram':
                src_char = parts[0]
            else:
                src_char = ''
            # Keep entry only if best mapping differs from identity
            # or if identity probability is < 0.95 (ambiguous context)
            identity_count = dist.get(src_char, 0)
            if identity_count / total < 0.95 or best != src_char:
                pruned_level[key] = entry
        pruned[level_name] = pruned_level

    for level in pruned:
        print(f"  {level}: {len(pruned[level])} entries (was {len(final_model[level])})")

    # Save
    with open(MODEL_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(pruned, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\nModel saved: {MODEL_OUTPUT} ({MODEL_OUTPUT.stat().st_size // 1024} KB)")

    # Final benchmark: check accuracy on overlapping words using the full pipeline
    print("\n\n" + "="*60)
    print("FINAL BENCHMARK: Full pipeline on all overlapping words")
    print("="*60)
    benchmark_full_pipeline(britfone, readlex, pruned)

    return test_results


def benchmark_full_pipeline(britfone: dict, readlex: dict, model: dict):
    """Benchmark the full pipeline: Britfone -> normalize_ipa -> ML model -> Shavian.

    Compares against ReadLex Shavian for overlapping words.
    """
    from ml_ipa_normalizer import ml_normalize_ipa, strip_stress

    overlap = set(britfone.keys()) & set(readlex.keys())

    # Load ReadLex Shavian for comparison
    readlex_data = {}
    with open(READLEX_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for entries in data.values():
        for entry in entries:
            word = entry['Latn'].lower()
            if word not in readlex_data:
                readlex_data[word] = entry

    baseline_correct = 0
    ml_correct = 0
    total = 0
    ml_mismatches = []

    for word in sorted(overlap):
        bf_ipa = britfone[word][0]
        entry = readlex_data.get(word)
        if not entry:
            continue
        target_shaw = entry['Shaw']
        target_ipa = entry['ipa']

        total += 1

        # Baseline: rule-based only
        bf_normalized = normalize_ipa(bf_ipa, word=word, source="britfone")
        baseline_shaw = ipa_to_shavian(bf_normalized)
        if baseline_shaw == target_shaw:
            baseline_correct += 1

        # ML: rule-based + ML normalizer
        bf_clean = strip_stress(bf_normalized)
        ml_ipa = ml_normalize_ipa(bf_clean, word, model)
        ml_shaw = ipa_to_shavian(ml_ipa)
        if ml_shaw == target_shaw:
            ml_correct += 1
        else:
            ml_mismatches.append((word, bf_clean, strip_stress(target_ipa), ml_ipa, ml_shaw, target_shaw))

    print(f"Total overlapping words: {total}")
    print(f"Baseline (rule-based):   {baseline_correct}/{total} ({100*baseline_correct/total:.1f}%)")
    print(f"ML model:                {ml_correct}/{total} ({100*ml_correct/total:.1f}%)")
    print(f"Improvement:             +{ml_correct - baseline_correct} words (+{100*(ml_correct - baseline_correct)/total:.1f}%)")

    print(f"\nSample Shavian mismatches (first 20):")
    for word, bf, rl, ml, shaw_ml, shaw_tgt in ml_mismatches[:20]:
        print(f"  {word:20s}  ml_ipa={ml:20s}  rl_ipa={rl:20s}  shaw:{shaw_ml} vs {shaw_tgt}")


if __name__ == '__main__':
    main()
