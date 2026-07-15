"""Model & product monitoring — the data behind the Reports page.

Answers the operator questions:
  - Which model artifacts are deployed, and how stale are they? (model "rot")
  - What did offline training achieve? (metrics pulled from the MLflow SQLite store)
  - What is happening live? (session volume, score/readiness/memorization trends)
  - Is the live population drifting away from what the models were trained on?

Everything reads local state (models_store/, mlflow.db, data/sessions/) with stdlib only —
no mlflow import needed (we query its SQLite schema directly), so the endpoint stays fast.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from reflecta.config import CONFIG
from reflecta.serving import model_registry_info

# staleness thresholds (days) for the "rot" verdict
_FRESH_DAYS = 30
_AGING_DAYS = 90


def _artifact_health() -> list[dict]:
    """Age + rot verdict for every artifact in models_store/."""
    store = CONFIG.paths.models_store
    out = []
    if not store.exists():
        return out
    now = datetime.now(timezone.utc)
    for path in sorted(store.iterdir()):
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_days = (now - mtime).days
        status = ("fresh" if age_days <= _FRESH_DAYS
                  else "aging" if age_days <= _AGING_DAYS else "stale")
        out.append({
            "artifact": path.name,
            "trained_at": mtime.date().isoformat(),
            "age_days": age_days,
            "size_kb": round(path.stat().st_size / 1024, 1),
            "status": status,
        })
    return out


def _mlflow_metrics() -> list[dict]:
    """Latest metric values per run from the local MLflow SQLite store (no mlflow import)."""
    db = CONFIG.paths.root / "mlflow.db"
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        rows = con.execute(
            """
            SELECT r.name, m.key, m.value, MAX(m.step)
            FROM metrics m JOIN runs r ON r.run_uuid = m.run_uuid
            GROUP BY r.run_uuid, m.key
            ORDER BY r.start_time DESC
            """
        ).fetchall()
        con.close()
    except Exception:
        return []
    runs: dict[str, dict] = {}
    for run_name, key, value, _ in rows:
        runs.setdefault(run_name or "run", {})[key] = round(float(value), 4)
    return [{"run": name, "metrics": metrics} for name, metrics in runs.items()]


def _session_stats() -> dict:
    """Live product stats + simple drift check: recent half vs older half of sessions."""
    sess_dir = CONFIG.paths.sessions
    sessions = []
    if sess_dir.exists():
        for path in sorted(sess_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                a = d.get("analysis", {})
                sessions.append({
                    "ts": d.get("timestamp"),
                    "score": d.get("score"),
                    "readiness": a.get("readiness"),
                    "memorization": a.get("memorization_index"),
                    "n_answers": len(d.get("interactions", [])),
                })
            except Exception:
                continue

    def _mean(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        return round(sum(xs) / len(xs), 4) if xs else None

    stats = {
        "total_sessions": len(sessions),
        "total_answers": sum(s["n_answers"] for s in sessions),
        "avg_score": _mean([s["score"] for s in sessions]),
        "avg_readiness": _mean([s["readiness"] for s in sessions]),
        "avg_memorization": _mean([s["memorization"] for s in sessions]),
        "recent_scores": [s["score"] for s in sessions[-10:]],
        "drift": None,
    }

    # drift: compare the recent half against the older half (needs >= 6 sessions)
    if len(sessions) >= 6:
        mid = len(sessions) // 2
        old, new = _mean([s["score"] for s in sessions[:mid]]), _mean([s["score"] for s in sessions[mid:]])
        if old is not None and new is not None:
            delta = round(new - old, 4)
            stats["drift"] = {
                "older_avg_score": old,
                "recent_avg_score": new,
                "delta": delta,
                "verdict": ("stable" if abs(delta) < 0.10
                            else "improving" if delta > 0 else "degrading"),
            }
    return stats


def build_report() -> dict:
    """Everything the Reports page needs, in one payload."""
    artifacts = _artifact_health()
    worst = max((a["age_days"] for a in artifacts), default=None)
    overall = ("no models" if not artifacts
               else "healthy" if worst <= _FRESH_DAYS
               else "watch" if worst <= _AGING_DAYS else "retrain recommended")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "service_version": CONFIG.version,
        "overall_status": overall,
        "registry": model_registry_info(),
        "artifacts": artifacts,
        "training_metrics": _mlflow_metrics(),
        "live": _session_stats(),
        "thresholds": {"fresh_days": _FRESH_DAYS, "aging_days": _AGING_DAYS,
                       "drift_alert_delta": 0.10},
    }
