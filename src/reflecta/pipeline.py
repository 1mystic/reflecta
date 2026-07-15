"""Data & model lifecycle — ingest → clean → feature → split → train → track → persist.

One function, `run_lifecycle()`, executes every stage and returns a summary. It is the
deploy-ready path: models land in models_store/ and every metric is logged to the
configured tracker (MLflow by default). Runnable today on synthetic data; point it at a
real KT CSV in data/raw/ by passing source="assistments".

    from reflecta.pipeline import run_lifecycle
    run_lifecycle(source="auto", tracker="mlflow")
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from reflecta.config import CONFIG
from reflecta.data.split import group_train_val_split
from reflecta.data.synthetic import generate_cohort
from reflecta.eval.metrics import next_question_auc
from reflecta.models.knowledge_tracing import BKT
from reflecta.models.irt import IRT1PL
from reflecta.models.persistence import save_bkt, save_irt
from reflecta.tracking.experiment import track


# ---------- stage 1: ingest ----------
def ingest(source: str = "auto") -> tuple[pd.DataFrame, str]:
    """Load interactions. 'auto' tries real ASSISTments then falls back to synthetic."""
    if source in ("assistments", "auto"):
        try:
            from reflecta.data.loaders import load_assistments

            df = load_assistments()
            print(f"[ingest] loaded real ASSISTments: {len(df):,} rows")
            return df, "assistments"
        except FileNotFoundError:
            if source == "assistments":
                raise
            print("[ingest] ASSISTments not present; using synthetic cohort")
    df = generate_cohort(n_learners=120, seed=CONFIG.seed)
    return df, "synthetic"


# ---------- stage 2: clean / validate ----------
def clean(df: pd.DataFrame, source: str) -> pd.DataFrame:
    df = df.dropna(subset=["learner_id", "correct"]).copy()
    df["correct"] = df["correct"].astype(int).clip(0, 1)
    if "skill" not in df.columns or df["skill"].isna().all():
        df["skill"] = "general"
    df["skill"] = df["skill"].fillna("general").astype(str)
    df["learner_id"] = df["learner_id"].astype("category").cat.codes
    out = CONFIG.paths.processed / f"{source}_clean.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(out)
        print(f"[clean] wrote {out} ({len(df):,} rows, {df['skill'].nunique()} skills)")
    except Exception as e:  # parquet engine optional
        print(f"[clean] parquet skipped ({e}); continuing in-memory")
    return df


# ---------- stage 3: features (index encodings + per-skill sequences) ----------
def featurize(df: pd.DataFrame):
    item_key = df["skill"].astype(str) + "::" + df.get(
        "item_id", pd.Series(range(len(df)))
    ).astype(str)
    df = df.assign(_item_idx=item_key.astype("category").cat.codes)
    return df


def _per_skill_sequences(df: pd.DataFrame, top_skills: int = 12) -> dict[str, list[list[int]]]:
    top = df["skill"].value_counts().head(top_skills).index
    seqs: dict[str, list[list[int]]] = {}
    for skill in top:
        sub = df[df["skill"] == skill]
        by_learner = sub.groupby("learner_id")["correct"].apply(list)
        seqs[str(skill)] = [s for s in by_learner if len(s) >= 2]
    return seqs


# ---------- stages 4-7: split, train, track, persist ----------
def run_lifecycle(source: str = "auto", tracker: str | None = None,
                  irt_epochs: int = 300, bkt_grid: int = 5) -> dict:
    raw, src = ingest(source)
    df = featurize(clean(raw, src))
    train_df, val_df = group_train_val_split(df, group_col="learner_id", val_frac=0.2)
    print(f"[split] train={len(train_df):,}  val={len(val_df):,}  (group=learner)")

    summary: dict = {"source": src, "n_rows": len(df),
                     "n_train": len(train_df), "n_val": len(val_df)}

    with track("lifecycle", config={"source": src, "irt_epochs": irt_epochs,
                                    "bkt_grid": bkt_grid}, tracker=tracker) as run:
        # --- IRT ---
        n_learners = int(df["learner_id"].max()) + 1
        n_items = int(df["_item_idx"].max()) + 1
        irt = IRT1PL(n_learners=n_learners, n_items=n_items)
        irt.fit(train_df["learner_id"].to_numpy(), train_df["_item_idx"].to_numpy(),
                train_df["correct"].to_numpy(), epochs=irt_epochs)
        # eval on val items seen in train (unseen items have prior-0 difficulty)
        val_p = irt.predict_proba(val_df["learner_id"].to_numpy(),
                                  val_df["_item_idx"].to_numpy())
        irt_auc = next_question_auc(val_p, val_df["correct"].to_numpy())
        summary["irt_val_auc"] = float(irt_auc)
        save_irt(irt)

        # --- BKT per skill ---
        train_seqs = _per_skill_sequences(train_df)
        val_seqs = _per_skill_sequences(val_df)
        bkt_models: dict[str, BKT] = {}
        all_preds, all_true = [], []
        for skill, seqs in train_seqs.items():
            if not seqs:
                continue
            bkt = BKT().fit_grid(seqs, grid=bkt_grid)
            bkt_models[skill] = bkt
            for s in val_seqs.get(skill, []):
                preds = bkt.predict_sequence(s)
                all_preds.extend(preds)
                all_true.extend(s)
        bkt_auc = (next_question_auc(np.array(all_preds), np.array(all_true))
                   if all_true else float("nan"))
        summary["bkt_val_auc"] = float(bkt_auc)
        summary["n_skills_modeled"] = len(bkt_models)
        if bkt_models:
            save_bkt(bkt_models)

        run.log({"irt/val_auc": summary["irt_val_auc"],
                 "bkt/val_auc": summary["bkt_val_auc"],
                 "data/n_rows": float(summary["n_rows"]),
                 "data/n_skills": float(summary["n_skills_modeled"])})

    print(f"[done] IRT val AUC={summary['irt_val_auc']:.3f}  "
          f"BKT val AUC={summary['bkt_val_auc']:.3f}  "
          f"artifacts -> {CONFIG.paths.models_store}")
    return summary


if __name__ == "__main__":
    run_lifecycle()
