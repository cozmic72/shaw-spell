#!/usr/bin/env python3
"""
Train a classifier to predict where capital R (linking r) should be inserted
into non-rhotic IPA to produce ReadLex-convention IPA.

Handles all vowel+R patterns from ReadLex:
  əR  (lettER, mothER)
  ɜːR (NURSE: bird, her)
  ɑːR (START: car, father)
  ɔːR (NORTH/FORCE: more, war)
  ɪəR (NEAR: here, ear)
  eəR (SQUARE: care, air)
  ʊəR (CURE: poor, tour)

Training data: ReadLex RRP entries. We strip R to create synthetic non-rhotic
IPA, then train the model to predict which positions get R restored.

Usage:
    python3 src/tools/train_rhoticity_model.py
"""

import json
import re
import pickle
import numpy as np
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).parent.parent.parent
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
MODEL_PATH = PROJECT_ROOT / "data" / "rhoticity-model.pkl"

# All vowel sequences that can precede R in ReadLex
# Ordered longest-first for greedy matching
R_VOWELS = ['ɜː', 'ɑː', 'ɔː', 'ɪə', 'eə', 'ʊə', 'ə']


def find_R_sites(ipa: str):
    """Find all positions in IPA where R occurs after a vowel.

    Returns list of (start_pos, vowel_seq, label) tuples.
    start_pos: index of the start of the vowel
    vowel_seq: the vowel sequence before R (e.g. 'ə', 'ɜː', 'ɑː')
    label: 1 if R follows, 0 if not

    For training: scans IPA with R present, records which vowels have R.
    For inference: scans IPA without R, predicts which vowels need R.
    """
    sites = []
    i = 0
    while i < len(ipa):
        # Try to match each R_VOWEL pattern at position i
        matched = False
        for vowel in R_VOWELS:
            vlen = len(vowel)
            if ipa[i:i + vlen] == vowel:
                # Check if R follows
                next_pos = i + vlen
                if next_pos < len(ipa) and ipa[next_pos] == 'R':
                    sites.append((i, vowel, 1))
                    i = next_pos + 1  # skip past vowel+R
                else:
                    # Special case: skip əʊ diphthong (not a schwa site)
                    if vowel == 'ə' and next_pos < len(ipa) and ipa[next_pos] in ('ʊ',):
                        i += 1
                        continue
                    sites.append((i, vowel, 0))
                    i += vlen
                matched = True
                break
        if not matched:
            i += 1
    return sites


def extract_features(ipa: str, word: str, site_pos: int, vowel: str) -> dict:
    """Extract features for a vowel position that may or may not need R."""
    word_lower = word.lower()
    ipa_len = len(ipa)
    word_len = len(word_lower)
    vlen = len(vowel)

    # Position after the vowel (where R would go)
    after_pos = site_pos + vlen

    # IPA context
    ctx_before = ipa[max(0, site_pos - 3):site_pos].rjust(3, '_')
    ctx_after = ipa[after_pos:after_pos + 3].ljust(3, '_')
    next_char = ipa[after_pos] if after_pos < ipa_len else '_'
    prev_char = ipa[site_pos - 1] if site_pos > 0 else '_'

    # Normalized position
    norm_pos = site_pos / max(ipa_len - 1, 1)

    # Is this vowel at the end of the IPA?
    is_final = after_pos >= ipa_len

    # Aligned position in spelling
    aligned_pos = int(norm_pos * (word_len - 1)) if word_len > 1 else 0
    aligned_pos = min(aligned_pos, word_len - 1)

    # Spelling context
    spell_at = word_lower[aligned_pos] if aligned_pos < word_len else '_'
    spell_window = word_lower[max(0, aligned_pos - 2):aligned_pos + 3]

    # R proximity in spelling
    r_positions = [i for i, c in enumerate(word_lower) if c == 'r']
    if r_positions:
        min_r_dist = min(abs(aligned_pos - rp) for rp in r_positions)
        nearest_r_pos = min(r_positions, key=lambda rp: abs(aligned_pos - rp))
        r_before = nearest_r_pos < aligned_pos
        r_after = nearest_r_pos >= aligned_pos
    else:
        min_r_dist = 99
        r_before = False
        r_after = False

    r_at_aligned = spell_at == 'r'
    r_near_aligned = 'r' in word_lower[max(0, aligned_pos - 1):aligned_pos + 2]

    # Word suffix patterns
    ends_er = word_lower[-2:] in ('er', 're')
    ends_or = word_lower[-2:] == 'or'
    ends_ar = word_lower[-2:] == 'ar'
    ends_r = word_lower.endswith('r')
    ends_re = word_lower.endswith('re')

    # Counts
    r_count = word_lower.count('r')
    vowel_count_in_ipa = sum(1 for c in ipa if c in 'iɪeɛæɑɒɔʊuəʌɜaɐoɵʉɨ')

    # Consonant/vowel classification of next char
    consonants = set('pbtdkɡfvθðszʃʒhmnŋlrwjʍ')
    ipa_vowels = set('iɪeɛæɑɒɔʊuəʌɜaɐoɵʉɨ')
    next_is_consonant = next_char in consonants
    next_is_vowel = next_char in ipa_vowels

    # Vowel type (which R_VOWEL pattern)
    vowel_type = R_VOWELS.index(vowel) if vowel in R_VOWELS else -1

    # Syllable index (rough: count vowel-like chars before this position)
    syllable_index = sum(1 for c in ipa[:site_pos] if c in ipa_vowels)

    return {
        'prev_char': prev_char,
        'next_char': next_char,
        'spell_at': spell_at,
        'ctx_before_1': ctx_before[-1],
        'ctx_before_2': ctx_before[-2] if len(ctx_before) >= 2 else '_',
        'ctx_after_1': ctx_after[0],
        'ctx_after_2': ctx_after[1] if len(ctx_after) >= 2 else '_',
        'norm_pos': norm_pos,
        'is_final': is_final,
        'r_at_aligned': r_at_aligned,
        'r_near_aligned': r_near_aligned,
        'min_r_dist': min_r_dist,
        'r_before': r_before,
        'r_after': r_after,
        'ends_er': ends_er,
        'ends_or': ends_or,
        'ends_ar': ends_ar,
        'ends_r': ends_r,
        'ends_re': ends_re,
        'r_count': r_count,
        'word_len': word_len,
        'ipa_len': ipa_len,
        'next_is_consonant': next_is_consonant,
        'next_is_vowel': next_is_vowel,
        'vowel_type': vowel_type,
        'syllable_index': syllable_index,
        'vowel_count': vowel_count_in_ipa,
    }


def features_to_vector(features: dict, char_vocab: dict) -> np.ndarray:
    """Convert feature dict to numpy vector."""
    def ci(c):
        return char_vocab.get(c, 0)

    vec = [
        ci(features['prev_char']),
        ci(features['next_char']),
        ci(features['spell_at']),
        ci(features['ctx_before_1']),
        ci(features['ctx_before_2']),
        ci(features['ctx_after_1']),
        ci(features['ctx_after_2']),
        features['norm_pos'],
        float(features['is_final']),
        float(features['r_at_aligned']),
        float(features['r_near_aligned']),
        min(features['min_r_dist'], 20) / 20.0,
        float(features['r_before']),
        float(features['r_after']),
        float(features['ends_er']),
        float(features['ends_or']),
        float(features['ends_ar']),
        float(features['ends_r']),
        float(features['ends_re']),
        features['r_count'] / 5.0,
        features['word_len'] / 20.0,
        features['ipa_len'] / 20.0,
        float(features['next_is_consonant']),
        float(features['next_is_vowel']),
        features['vowel_type'] / len(R_VOWELS),
        features['syllable_index'] / 5.0,
        features['vowel_count'] / 8.0,
    ]
    return np.array(vec, dtype=np.float32)


def build_training_data():
    """Build training data from ReadLex entries."""
    print(f"Loading ReadLex from {READLEX_PATH}...")
    with open(READLEX_PATH, 'r', encoding='utf-8') as f:
        readlex = json.load(f)

    # Build character vocabulary
    all_chars = Counter()
    entries = []
    for key, entry_list in readlex.items():
        for e in entry_list:
            if e.get('var', '') not in ('', 'RRP'):
                continue
            ipa = e.get('ipa', '')
            word = e.get('Latn', '')
            if not ipa or not word:
                continue
            # Only use entries where word contains 'r' (others are trivial)
            if 'r' not in word.lower():
                continue
            entries.append((word, ipa))
            for c in ipa:
                all_chars[c] += 1

    char_vocab = {'_': 0}
    for i, (c, _) in enumerate(all_chars.most_common(100)):
        char_vocab[c] = i + 1

    print(f"  {len(entries):,} RRP entries with 'r' in spelling")

    # Extract training examples
    X_features = []
    y_labels = []
    vowel_type_counts = Counter()

    for word, ipa in entries:
        # Strip stress marks
        ipa_clean = re.sub('[ˈˌ]', '', ipa)

        # Find R sites in the original IPA (with R's present)
        sites = find_R_sites(ipa_clean)

        for site_pos, vowel, label in sites:
            # Create non-rhotic version: remove all R's from the IPA
            ipa_noR = ipa_clean.replace('R', '')
            # Adjust site_pos for removed R's before this position
            r_before_count = ipa_clean[:site_pos].count('R')
            adjusted_pos = site_pos - r_before_count

            features = extract_features(ipa_noR, word, adjusted_pos, vowel)
            X_features.append(features)
            y_labels.append(label)
            vowel_type_counts[(vowel, label)] += 1

    pos = sum(y_labels)
    neg = len(y_labels) - pos
    print(f"  {len(X_features):,} vowel sites ({pos:,} +R, {neg:,} plain)")
    print(f"\n  By vowel type:")
    for vowel in R_VOWELS:
        n_pos = vowel_type_counts.get((vowel, 1), 0)
        n_neg = vowel_type_counts.get((vowel, 0), 0)
        total = n_pos + n_neg
        if total > 0:
            print(f"    {vowel:4s}  +R={n_pos:6,}  plain={n_neg:6,}  total={total:6,}  R%={100*n_pos/total:.1f}%")

    X = np.array([features_to_vector(f, char_vocab) for f in X_features])
    y = np.array(y_labels)

    return X, y, char_vocab


def train_and_evaluate(X, y, char_vocab):
    """Train a gradient boosted classifier and evaluate."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score, train_test_split
    from sklearn.metrics import classification_report

    print(f"\nTraining on {X.shape[0]:,} examples, {X.shape[1]} features...")

    # Stratified split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y
    )

    model = GradientBoostingClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.1,
        min_samples_leaf=10,
        subsample=0.8,
        random_state=42,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print(f"\n=== Test Set Results ===")
    print(classification_report(y_test, y_pred, target_names=['plain vowel', 'vowel+R']))

    scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    print(f"5-fold CV accuracy: {scores.mean():.4f} ± {scores.std():.4f}")

    # Feature importance
    feature_names = [
        'prev_char', 'next_char', 'spell_at',
        'ctx_before[-1]', 'ctx_before[-2]', 'ctx_after[0]', 'ctx_after[1]',
        'norm_pos', 'is_final', 'r_at_aligned', 'r_near_aligned',
        'min_r_dist', 'r_before', 'r_after',
        'ends_er', 'ends_or', 'ends_ar', 'ends_r', 'ends_re',
        'r_count', 'word_len', 'ipa_len',
        'next_is_consonant', 'next_is_vowel',
        'vowel_type', 'syllable_index', 'vowel_count',
    ]
    importances = sorted(zip(feature_names, model.feature_importances_),
                         key=lambda x: -x[1])
    print(f"\nTop 10 features:")
    for name, imp in importances[:10]:
        print(f"  {name:20s} {imp:.4f}")

    # Retrain on full data
    print(f"\nRetraining on full dataset...")
    model.fit(X, y)

    return model


def main():
    X, y, char_vocab = build_training_data()
    model = train_and_evaluate(X, y, char_vocab)

    print(f"\nSaving model to {MODEL_PATH}...")
    with open(MODEL_PATH, 'wb') as f:
        pickle.dump({
            'model': model,
            'char_vocab': char_vocab,
            'r_vowels': R_VOWELS,
        }, f)

    print("Done.")


if __name__ == '__main__':
    main()
