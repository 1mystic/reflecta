"""Group-aware splitting — the legacy project's hard-won lesson, enforced.

Random row splits leak when the same learner (or near-duplicate items) appear on both
sides. Every reported metric must come from a split where whole GROUPS (learners, or
concepts) are held out. These helpers wrap sklearn's group splitters with our schema.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def group_train_val_split(
    df: pd.DataFrame, group_col: str = "learner_id", val_frac: float = 0.2, seed: int = 42
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out whole groups (default: whole learners) for validation."""
    if group_col not in df.columns:
        raise KeyError(f"group column '{group_col}' not in dataframe")
    rng = np.random.default_rng(seed)
    groups = df[group_col].unique()
    rng.shuffle(groups)
    n_val = max(1, int(len(groups) * val_frac))
    val_groups = set(groups[:n_val])
    val_mask = df[group_col].isin(val_groups)
    return df[~val_mask].reset_index(drop=True), df[val_mask].reset_index(drop=True)


def group_kfold_indices(
    df: pd.DataFrame, group_col: str = "learner_id", n_splits: int = 5, seed: int = 42
):
    """Yield (train_idx, val_idx) with groups never split across folds."""
    try:
        from sklearn.model_selection import GroupKFold

        gkf = GroupKFold(n_splits=n_splits)
        yield from gkf.split(df, groups=df[group_col])
    except Exception:
        # manual fallback
        rng = np.random.default_rng(seed)
        groups = df[group_col].unique()
        rng.shuffle(groups)
        folds = np.array_split(groups, n_splits)
        idx = np.arange(len(df))
        for f in folds:
            val_mask = df[group_col].isin(set(f)).to_numpy()
            yield idx[~val_mask], idx[val_mask]
