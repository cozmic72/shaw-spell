#!/usr/bin/env python3
"""
ML-based IPA normalizer that converts Britfone (SSB) IPA to ReadLex (Rhotic RP) IPA.

Uses a context-sensitive character substitution model trained on ~14K overlapping
words between Britfone and ReadLex dictionaries.

Usage:
    from ml_ipa_normalizer import ml_normalize_ipa, load_model

    model = load_model()
    readlex_ipa = ml_normalize_ipa("kæt", "cat", model)
"""

import json
import re
from pathlib import Path

BOS = "^"
EOS = "$"

MODEL_PATH = Path(__file__).parent.parent.parent / "data" / "ipa-normalizer-model.json"

_cached_model = None


def load_model(path: str | Path | None = None) -> dict:
    """Load the trained normalizer model from JSON."""
    global _cached_model
    if _cached_model is not None and path is None:
        return _cached_model

    model_path = Path(path) if path else MODEL_PATH
    if not model_path.exists():
        raise FileNotFoundError(
            f"IPA normalizer model not found: {model_path}\n"
            f"Run: python3 src/tools/train_ipa_normalizer.py"
        )

    with open(model_path, 'r', encoding='utf-8') as f:
        model = json.load(f)

    if path is None:
        _cached_model = model
    return model


def _lookup_best(model_level: dict, key: str, min_count: int, min_prob: float) -> str | None:
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


def ml_normalize_ipa(ipa: str, word: str = "", model: dict | None = None) -> str:
    """Apply ML model to normalize Britfone IPA toward ReadLex conventions.

    This should be called AFTER the rule-based normalize_ipa() from ipa_to_shavian.py.
    Stress marks should already be stripped.

    Args:
        ipa: Stress-stripped, rule-normalized IPA string from Britfone
        word: Latin spelling of the word (currently unused, reserved for future)
        model: Trained model dict. If None, loads from default path.

    Returns:
        IPA string with ML-based corrections applied.
    """
    if model is None:
        model = load_model()

    src = ipa
    n = len(src)
    result = []

    for i in range(n):
        char = src[i]
        l1 = src[i-1] if i >= 1 else BOS
        l2 = src[i-2] if i >= 2 else BOS
        r1 = src[i+1] if i < n-1 else EOS
        r2 = src[i+2] if i < n-2 else EOS

        tgt = None

        # 5-gram (most specific)
        key5 = f"{l2}|{l1}|{char}|{r1}|{r2}"
        tgt = _lookup_best(model.get('5gram', {}), key5, min_count=3, min_prob=0.6)

        # Trigram
        if tgt is None:
            key3 = f"{l1}|{char}|{r1}"
            tgt = _lookup_best(model.get('trigram', {}), key3, min_count=5, min_prob=0.65)

        # Bigram right
        if tgt is None:
            key_br = f"{char}|{r1}"
            tgt = _lookup_best(model.get('bigram_r', {}), key_br, min_count=8, min_prob=0.75)

        # Bigram left
        if tgt is None:
            key_bl = f"{l1}|{char}"
            tgt = _lookup_best(model.get('bigram_l', {}), key_bl, min_count=8, min_prob=0.75)

        # Unigram (most general)
        if tgt is None:
            key1 = char
            tgt = _lookup_best(model.get('unigram', {}), key1, min_count=10, min_prob=0.85)

        if tgt is None:
            tgt = char

        # Don't apply deletions from substitution model
        if tgt == "":
            tgt = char

        result.append(tgt)

    return ''.join(result)


def strip_stress(ipa: str) -> str:
    """Remove stress marks from IPA string."""
    return re.sub('[ˈˌ]', '', ipa)
