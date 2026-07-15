"""Central configuration: paths and runtime settings.

Everything is anchored to the repo root so the project is fully self-contained —
no absolute paths, no external state directories.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# repo root = two levels up from this file (src/reflecta/config.py -> repo/)
ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.getenv(name, default).split(",") if x.strip())


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    data: Path = ROOT / "data"
    raw: Path = ROOT / "data" / "raw"
    processed: Path = ROOT / "data" / "processed"
    legacy_kaggle: Path = ROOT / "data" / "legacy_kaggle"
    sessions: Path = ROOT / "data" / "sessions"
    experiments: Path = ROOT / "experiments"
    models_store: Path = ROOT / "models_store"


@dataclass(frozen=True)
class Config:
    paths: Paths = field(default_factory=Paths)

    # --- runtime environment ---
    env: str = os.getenv("REFLECTA_ENV", "dev")  # "dev" | "prod"
    version: str = "0.3.0"

    # --- experiment tracking: "mlflow" (local, self-contained) | "wandb" | "none" ---
    tracker: str = os.getenv("REFLECTA_TRACKER", "mlflow")
    wandb_project: str = os.getenv("WANDB_PROJECT", "reflecta")
    wandb_entity: str | None = os.getenv("WANDB_ENTITY") or None

    # --- reflection LLM backend: "none" | "ollama" | "transformers" ---
    llm_backend: str = os.getenv("REFLECTA_LLM_BACKEND", "none")
    llm_model: str = os.getenv("REFLECTA_LLM_MODEL", "llama3.2:3b")
    llm_base_url: str = os.getenv("REFLECTA_LLM_BASE_URL", "http://localhost:11434/v1")

    # --- API / product ---
    # In prod, set REFLECTA_CORS_ORIGINS to your exact frontend origin(s).
    cors_origins: tuple[str, ...] = _env_list(
        "REFLECTA_CORS_ORIGINS", "http://localhost:8000,http://localhost:5173"
    )
    require_consent: bool = _env_bool("REFLECTA_REQUIRE_CONSENT", True)
    session_retention_days: int = int(os.getenv("REFLECTA_SESSION_RETENTION_DAYS", "365"))
    rate_limit_per_min: int = int(os.getenv("REFLECTA_RATE_LIMIT_PER_MIN", "60"))
    log_level: str = os.getenv("REFLECTA_LOG_LEVEL", "INFO")
    log_json: bool = _env_bool("REFLECTA_LOG_JSON", False)

    seed: int = 42

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in {"prod", "production"}


CONFIG = Config()
