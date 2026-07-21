"""Latin(+Shavian)->RP-IPA seq2seq: tokenizer, vocab, model, greedy decode,
candidate scoring.

Inference library for the FROZEN neural G2P artifact in data/g2p-model/
(model.pt + meta.json, BiGRU+attention, ~1.6M params, trained on ReadLex
var==RRP triples — Phase-1 R&D, 91.9% held-out word accuracy). Greedy decode
on CPU is deterministic (byte-identical across runs). The training toolchain
stays outside the repo; this module carries only what pipeline stages need to
load and run the frozen model."""

import json
from pathlib import Path

import torch
import torch.nn as nn

PAD, BOS, EOS, UNK = 0, 1, 2, 3
SPECIALS = ["<pad>", "<bos>", "<eos>", "<unk>"]
SEP = "<sep>"  # between latin and shavian in the two-input variant

# ReadLex-IPA phoneme tokens, longest-match-first
MULTI = [
    "ɑːR", "ɔːR", "eəR", "ɪəR", "ɜːR", "ʊəR", "əR", "Ɑː",
    "iː", "uː", "ɑː", "ɔː", "ɜː",
    "eɪ", "aɪ", "ɔɪ", "aʊ", "əʊ", "ɪə", "eə", "ʊə",
    "tʃ", "dʒ",
]


def tokenize_ipa(ipa: str):
    toks = []
    i = 0
    while i < len(ipa):
        for m in MULTI:
            if ipa.startswith(m, i):
                toks.append(m)
                i += len(m)
                break
        else:
            toks.append(ipa[i])
            i += 1
    return toks


def tokenize_src(latn: str, shaw: str | None):
    toks = list(latn)
    if shaw is not None:
        toks.append(SEP)
        toks.extend(shaw)
    return toks


class Vocab:
    def __init__(self, tokens=None, itos=None):
        if itos is not None:
            self.itos = itos
        else:
            self.itos = SPECIALS + sorted(set(tokens))
        self.stoi = {t: i for i, t in enumerate(self.itos)}

    def encode(self, toks):
        return [self.stoi.get(t, UNK) for t in toks]

    def decode(self, ids):
        return [self.itos[i] for i in ids]

    def __len__(self):
        return len(self.itos)


class Seq2Seq(nn.Module):
    """BiGRU encoder + GRU decoder with Luong (general) attention. Greedy decode."""

    def __init__(self, n_src, n_tgt, emb=128, hid=256):
        super().__init__()
        self.hid = hid
        self.src_emb = nn.Embedding(n_src, emb, padding_idx=PAD)
        self.tgt_emb = nn.Embedding(n_tgt, emb, padding_idx=PAD)
        self.encoder = nn.GRU(emb, hid, batch_first=True, bidirectional=True)
        self.bridge = nn.Linear(2 * hid, hid)
        self.decoder = nn.GRU(emb + 2 * hid, hid, batch_first=True)
        self.attn = nn.Linear(hid, 2 * hid, bias=False)
        self.out = nn.Linear(hid + 2 * hid, n_tgt)

    def encode(self, src, src_mask):
        enc, h = self.encoder(self.src_emb(src))
        h = torch.tanh(self.bridge(torch.cat([h[0], h[1]], dim=-1))).unsqueeze(0)
        return enc, h

    def attend(self, dec_h, enc, src_mask):
        # dec_h: B,H ; enc: B,S,2H ; mask: B,S (True where real token)
        scores = torch.bmm(enc, self.attn(dec_h).unsqueeze(-1)).squeeze(-1)
        scores = scores.masked_fill(~src_mask, float("-inf"))
        ctx = torch.bmm(torch.softmax(scores, dim=-1).unsqueeze(1), enc).squeeze(1)
        return ctx

    def forward(self, src, src_mask, tgt_in):
        """Teacher-forced logits for tgt_in (B,T). Returns B,T,V."""
        enc, h = self.encode(src, src_mask)
        emb = self.tgt_emb(tgt_in)
        logits = []
        ctx = torch.zeros(src.size(0), 2 * self.hid, device=src.device)
        for t in range(tgt_in.size(1)):
            step = torch.cat([emb[:, t], ctx], dim=-1).unsqueeze(1)
            dec, h = self.decoder(step, h)
            ctx = self.attend(dec[:, 0], enc, src_mask)
            logits.append(self.out(torch.cat([dec[:, 0], ctx], dim=-1)))
        return torch.stack(logits, dim=1)

    @torch.no_grad()
    def greedy(self, src, src_mask, max_len=45):
        enc, h = self.encode(src, src_mask)
        B = src.size(0)
        tok = torch.full((B,), BOS, dtype=torch.long, device=src.device)
        ctx = torch.zeros(B, 2 * self.hid, device=src.device)
        done = torch.zeros(B, dtype=torch.bool, device=src.device)
        outs = []
        for _ in range(max_len):
            step = torch.cat([self.tgt_emb(tok), ctx], dim=-1).unsqueeze(1)
            dec, h = self.decoder(step, h)
            ctx = self.attend(dec[:, 0], enc, src_mask)
            tok = self.out(torch.cat([dec[:, 0], ctx], dim=-1)).argmax(-1)
            tok = tok.masked_fill(done, PAD)
            done = done | (tok == EOS)
            outs.append(tok)
            if done.all():
                break
        return torch.stack(outs, dim=1)


def collate(batch, src_vocab, tgt_vocab, with_shaw, device):
    srcs = [src_vocab.encode(tokenize_src(b["latn"], b["shaw"] if with_shaw else None)) for b in batch]
    tgts = [tgt_vocab.encode(tokenize_ipa(b["ipa"])) for b in batch]
    S = max(len(s) for s in srcs)
    T = max(len(t) for t in tgts) + 1
    src = torch.full((len(batch), S), PAD, dtype=torch.long)
    tgt_in = torch.full((len(batch), T), PAD, dtype=torch.long)
    tgt_out = torch.full((len(batch), T), PAD, dtype=torch.long)
    for i, (s, t) in enumerate(zip(srcs, tgts)):
        src[i, : len(s)] = torch.tensor(s)
        tgt_in[i, : len(t) + 1] = torch.tensor([BOS] + t)
        tgt_out[i, : len(t) + 1] = torch.tensor(t + [EOS])
    mask = src != PAD
    return src.to(device), mask.to(device), tgt_in.to(device), tgt_out.to(device)


def load_model(model_dir: Path, device="cpu"):
    meta = json.loads((model_dir / "meta.json").read_text())
    src_vocab = Vocab(itos=meta["src_itos"])
    tgt_vocab = Vocab(itos=meta["tgt_itos"])
    model = Seq2Seq(len(src_vocab), len(tgt_vocab), emb=meta["emb"], hid=meta["hid"])
    model.load_state_dict(torch.load(model_dir / "model.pt", map_location=device, weights_only=True))
    model.to(device).eval()
    return model, src_vocab, tgt_vocab, meta


@torch.no_grad()
def predict_batch(model, src_vocab, tgt_vocab, items, with_shaw, device="cpu", bs=256):
    """Greedy-decode a list of {latn, shaw} dicts -> list of IPA strings."""
    out = []
    model.eval()
    for i in range(0, len(items), bs):
        chunk = items[i : i + bs]
        srcs = [src_vocab.encode(tokenize_src(b["latn"], b["shaw"] if with_shaw else None)) for b in chunk]
        S = max(len(s) for s in srcs)
        src = torch.full((len(chunk), S), PAD, dtype=torch.long)
        for j, s in enumerate(srcs):
            src[j, : len(s)] = torch.tensor(s)
        src = src.to(device)
        ids = model.greedy(src, src != PAD)
        for row in ids.tolist():
            toks = []
            for t in row:
                if t in (EOS, PAD):
                    break
                toks.append(tgt_vocab.itos[t])
            out.append("".join(toks))
    return out


@torch.no_grad()
def score_candidates(model, src_vocab, tgt_vocab, items, with_shaw, device="cpu", bs=256):
    """Mean per-token log-prob of each item's candidate 'ipa' under the model."""
    scores = []
    ce = nn.CrossEntropyLoss(ignore_index=PAD, reduction="none")
    for i in range(0, len(items), bs):
        chunk = items[i : i + bs]
        src, mask, tgt_in, tgt_out = collate(chunk, src_vocab, tgt_vocab, with_shaw, device)
        logits = model(src, mask, tgt_in)
        loss = ce(logits.transpose(1, 2), tgt_out)  # B,T
        ntok = (tgt_out != PAD).sum(dim=1).clamp(min=1)
        scores.extend((-(loss.sum(dim=1) / ntok)).tolist())
    return scores
