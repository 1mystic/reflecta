"""Train SAKT (neural knowledge tracing) on ASSISTments and log to MLflow.

    python scripts/train_sakt.py                      # full data, 5 epochs
    python scripts/train_sakt.py --sample 40000 --epochs 3   # fast smoke run
    python scripts/train_sakt.py --tracker none       # offline

Requires torch:  uv pip install -e ".[neural]"
Saves the checkpoint to models_store/sakt.pt.
"""
from __future__ import annotations

import argparse

from reflecta.config import CONFIG
from reflecta.pipeline import clean, ingest
from reflecta.tracking.experiment import track


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="auto", choices=["auto", "assistments", "synthetic"])
    ap.add_argument("--sample", type=int, default=0, help="subsample N rows (0 = all)")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--d-model", type=int, default=64)
    ap.add_argument("--max-len", type=int, default=100)
    ap.add_argument("--tracker", default="mlflow", choices=["mlflow", "wandb", "none"])
    args = ap.parse_args()

    import torch  # imported here so the CLI errors clearly if torch is missing
    from reflecta.models.sakt import train_sakt

    raw, src = ingest(args.source)
    df = clean(raw, src)
    if args.sample and args.sample < len(df):
        # keep whole learners when subsampling so sequences stay intact
        keep = df["learner_id"].drop_duplicates()
        df = df[df["learner_id"].isin(keep)].head(args.sample).reset_index(drop=True)
        print(f"[sample] using {len(df):,} rows")

    with track("sakt", config={"source": src, "epochs": args.epochs,
                               "d_model": args.d_model, "max_len": args.max_len,
                               "rows": len(df)}, tracker=args.tracker) as run:
        result = train_sakt(df, max_len=args.max_len, d_model=args.d_model,
                            epochs=args.epochs, log_fn=run.log)
        run.log({"sakt/best_val_auc": result["val_auc"],
                 "sakt/n_train_seq": float(result["n_train_seq"]),
                 "sakt/n_val_seq": float(result["n_val_seq"])})

    CONFIG.paths.models_store.mkdir(parents=True, exist_ok=True)
    ckpt = CONFIG.paths.models_store / "sakt.pt"
    torch.save({"state_dict": result["model"].state_dict(),
                "n_skills": result["n_skills"], "d_model": args.d_model,
                "max_len": args.max_len}, ckpt)
    print(f"[done] best val AUC={result['val_auc']:.4f}  ->  {ckpt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
