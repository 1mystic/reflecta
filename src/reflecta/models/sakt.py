"""SAKT — Self-Attentive Knowledge Tracing (Pandey & Karypis, 2019).

The neural step beyond BKT. BKT models each skill with an independent 2-state HMM; SAKT
uses a single self-attention block so that predicting the response to the *next* exercise
can attend over the learner's *entire* relevant history — capturing cross-skill transfer
and long-range dependencies BKT cannot.

Formulation (per learner sequence of length L):
    exercises   e_1..e_L         (skill id answered at each step)
    responses   r_1..r_L         (0/1)
    interaction x_i = e_i + n_skills * r_i          (skill ⊕ correctness)

At step t we predict r_t from exercise e_t (the QUERY) attending over the *past*
interactions x_1..x_{t-1} (the KEYS/VALUES, shifted right by one and causally masked).

This module imports torch lazily-at-module-load; the rest of the package does not import it,
so `import reflecta` still works without torch installed. Install with:  pip install -e .[neural]
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

PAD = 0  # reserved index 0 for padding in both exercise and interaction spaces


# ---------------- data ----------------
def build_sequences(df: pd.DataFrame, max_len: int = 100, min_len: int = 3):
    """Per-learner sequences of (exercise_id, response), preserving row order (≈ time).

    Skills are mapped to ids in [1, n_skills]; 0 is padding. Long histories are split into
    non-overlapping windows of `max_len`.
    """
    skills = {s: i + 1 for i, s in enumerate(sorted(df["skill"].astype(str).unique()))}
    seqs = []
    for _, grp in df.groupby("learner_id", sort=False):
        e = grp["skill"].astype(str).map(skills).to_numpy()
        r = grp["correct"].to_numpy(dtype=int)
        for start in range(0, len(e), max_len):
            ce, cr = e[start:start + max_len], r[start:start + max_len]
            if len(ce) >= min_len:
                seqs.append((ce, cr))
    return seqs, len(skills)


class KTDataset(Dataset):
    def __init__(self, seqs, n_skills: int, max_len: int = 100):
        self.seqs, self.n_skills, self.max_len = seqs, n_skills, max_len

    def __len__(self):
        return len(self.seqs)

    def __getitem__(self, i):
        e, r = self.seqs[i]
        L = len(e)
        ex = np.zeros(self.max_len, dtype=np.int64)      # query exercises e_t
        inter = np.zeros(self.max_len, dtype=np.int64)   # past interactions x_{t-1}
        target = np.zeros(self.max_len, dtype=np.float32)
        mask = np.zeros(self.max_len, dtype=np.float32)

        ex[:L] = e
        target[:L] = r
        mask[:L] = 1.0
        # interaction ids shifted right by one (position t sees x_{t-1}); index 0 stays PAD
        x = e + self.n_skills * r  # in [1 .. 2*n_skills]
        inter[1:L] = x[:L - 1]
        return (torch.from_numpy(ex), torch.from_numpy(inter),
                torch.from_numpy(target), torch.from_numpy(mask))


# ---------------- model ----------------
class SAKT(nn.Module):
    def __init__(self, n_skills: int, d_model: int = 64, n_heads: int = 4,
                 max_len: int = 100, dropout: float = 0.2):
        super().__init__()
        self.exercise_emb = nn.Embedding(n_skills + 1, d_model, padding_idx=PAD)
        self.interaction_emb = nn.Embedding(2 * n_skills + 1, d_model, padding_idx=PAD)
        self.pos_emb = nn.Embedding(max_len, d_model)
        self.attn = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.ln1 = nn.LayerNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_model), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(d_model, d_model),
        )
        self.ln2 = nn.LayerNorm(d_model)
        self.out = nn.Linear(d_model, 1)
        self.max_len = max_len

    def forward(self, exercises, interactions):
        L = exercises.size(1)
        pos = torch.arange(L, device=exercises.device).unsqueeze(0)
        q = self.exercise_emb(exercises) + self.pos_emb(pos)      # queries
        kv = self.interaction_emb(interactions) + self.pos_emb(pos)  # keys/values
        # causal mask: position t may attend to <= t (interactions already shifted to past)
        causal = torch.triu(torch.ones(L, L, device=exercises.device), diagonal=1).bool()
        attn_out, _ = self.attn(q, kv, kv, attn_mask=causal)
        h = self.ln1(q + attn_out)
        h = self.ln2(h + self.ffn(h))
        return self.out(h).squeeze(-1)  # logits (B, L)


# ---------------- train / eval ----------------
def _auc(logits, targets, mask):
    from reflecta.eval.metrics import next_question_auc
    p = torch.sigmoid(logits).detach().cpu().numpy()[mask.cpu().numpy() == 1]
    y = targets.cpu().numpy()[mask.cpu().numpy() == 1]
    return next_question_auc(p, y)


def train_sakt(df: pd.DataFrame, max_len: int = 100, d_model: int = 64, n_heads: int = 4,
               epochs: int = 5, batch_size: int = 64, lr: float = 1e-3,
               val_frac: float = 0.2, device: str | None = None, seed: int = 42,
               log_fn=None) -> dict:
    """Train SAKT with a group-aware (by-learner) split. Returns metrics + the model."""
    from reflecta.data.split import group_train_val_split

    torch.manual_seed(seed)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    train_df, val_df = group_train_val_split(df, group_col="learner_id", val_frac=val_frac, seed=seed)

    train_seqs, n_skills = build_sequences(train_df, max_len=max_len)
    val_seqs, _ = build_sequences(val_df, max_len=max_len)
    tr = DataLoader(KTDataset(train_seqs, n_skills, max_len), batch_size=batch_size, shuffle=True)
    va = DataLoader(KTDataset(val_seqs, n_skills, max_len), batch_size=batch_size)

    model = SAKT(n_skills, d_model, n_heads, max_len).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.BCEWithLogitsLoss(reduction="none")

    best_auc = float("nan")
    for epoch in range(epochs):
        model.train()
        for ex, inter, target, mask in tr:
            ex, inter, target, mask = (t.to(device) for t in (ex, inter, target, mask))
            opt.zero_grad()
            logits = model(ex, inter)
            loss = (loss_fn(logits, target) * mask).sum() / mask.sum()
            loss.backward()
            opt.step()

        # validation AUC
        model.eval()
        all_p, all_y = [], []
        with torch.no_grad():
            for ex, inter, target, mask in va:
                ex, inter, target, mask = (t.to(device) for t in (ex, inter, target, mask))
                logits = model(ex, inter)
                m = mask.cpu().numpy() == 1
                all_p.append(torch.sigmoid(logits).cpu().numpy()[m])
                all_y.append(target.cpu().numpy()[m])
        from reflecta.eval.metrics import next_question_auc
        val_auc = next_question_auc(np.concatenate(all_p), np.concatenate(all_y))
        best_auc = val_auc if np.isnan(best_auc) else max(best_auc, val_auc)
        print(f"[sakt] epoch {epoch+1}/{epochs}  train_loss={loss.item():.4f}  val_auc={val_auc:.4f}")
        if log_fn:
            log_fn({"sakt/train_loss": float(loss.item()), "sakt/val_auc": float(val_auc)}, step=epoch)

    return {"model": model, "n_skills": n_skills, "val_auc": float(best_auc),
            "n_train_seq": len(train_seqs), "n_val_seq": len(val_seqs)}
