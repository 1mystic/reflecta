"""Experiment tracking wrapper — one interface, three backends.

Chosen via REFLECTA_TRACKER: "wandb" | "mlflow" | "none". Keeps experiment code
backend-agnostic and lets the whole project run offline (`none`) with zero config.

    from reflecta.tracking.experiment import track

    with track("irt-baseline", config={"lr": 0.1}) as run:
        run.log({"val/auc": 0.74, "val/ece": 0.08})
"""
from __future__ import annotations

from contextlib import contextmanager

from reflecta.config import CONFIG


class _Run:
    def __init__(self, backend: str, handle=None):
        self.backend = backend
        self._h = handle

    def log(self, metrics: dict, step: int | None = None) -> None:
        if self.backend == "wandb":
            self._h.log(metrics, step=step)
        elif self.backend == "mlflow":
            import mlflow

            for k, v in metrics.items():
                mlflow.log_metric(k.replace("/", "_"), v, step=step or 0)
        else:  # none
            prefix = f"[step {step}] " if step is not None else ""
            print(prefix + " ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                                    for k, v in metrics.items()))


@contextmanager
def track(name: str, config: dict | None = None, tracker: str | None = None):
    """Context manager that opens a run on the configured backend."""
    backend = tracker or CONFIG.tracker
    config = config or {}

    if backend == "wandb":
        try:
            import wandb

            handle = wandb.init(
                project=CONFIG.wandb_project,
                entity=CONFIG.wandb_entity,
                name=name,
                config=config,
                reinit=True,
            )
            yield _Run("wandb", handle)
            handle.finish()
            return
        except Exception as e:  # missing key / offline -> degrade gracefully
            print(f"[tracking] wandb unavailable ({e}); falling back to console.")
            backend = "none"

    if backend == "mlflow":
        import mlflow

        # keep the tracking store inside this repo (self-contained, no system changes).
        # newer MLflow requires a DB backend -> local SQLite file in the repo root.
        db = (CONFIG.paths.root / "mlflow.db").as_posix()
        mlflow.set_tracking_uri(f"sqlite:///{db}")
        mlflow.set_experiment(CONFIG.wandb_project)
        with mlflow.start_run(run_name=name):
            mlflow.log_params(config)
            yield _Run("mlflow")
        return

    # none
    print(f"[tracking:none] run='{name}' config={config}")
    yield _Run("none")
