"""Run the full data + model lifecycle and log to MLflow (or W&B / console).

    python scripts/run_pipeline.py                       # auto source, mlflow tracker
    python scripts/run_pipeline.py --source assistments  # require real data
    python scripts/run_pipeline.py --tracker none        # offline, console metrics

View results:  mlflow ui   (then open http://localhost:5000)
"""
from __future__ import annotations

import argparse

from reflecta.pipeline import run_lifecycle


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="auto", choices=["auto", "assistments", "synthetic"])
    ap.add_argument("--tracker", default="mlflow", choices=["mlflow", "wandb", "none"])
    ap.add_argument("--irt-epochs", type=int, default=300)
    ap.add_argument("--bkt-grid", type=int, default=5)
    args = ap.parse_args()

    summary = run_lifecycle(
        source=args.source, tracker=args.tracker,
        irt_epochs=args.irt_epochs, bkt_grid=args.bkt_grid,
    )
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
