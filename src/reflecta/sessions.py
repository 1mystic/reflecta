"""Session persistence — a small storage abstraction.

Default is file-backed JSON under data/sessions/ (self-contained, zero infra). The
interface is deliberately DB-shaped (save / get / delete / sweep) so it can be swapped for
Postgres/SQLite in production without touching the API.

Privacy by design: sessions are keyed by an opaque random id, contain no name/email/IP, and
support right-to-erasure (`delete`) and retention sweeps (`sweep_expired`).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reflecta.config import CONFIG
from reflecta.logging_config import get_logger

log = get_logger(__name__)


class FileSessionStore:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or CONFIG.paths.sessions
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        # guard against path traversal in the id
        safe = "".join(c for c in session_id if c.isalnum())
        return self.dir / f"{safe}.json"

    def save(self, session_id: str, payload: dict) -> Path:
        payload = {**payload, "stored_at": datetime.now(timezone.utc).isoformat()}
        path = self._path(session_id)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("session_saved", extra={"session_id": session_id})
        return path

    def get(self, session_id: str) -> dict | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, session_id: str) -> bool:
        """Right-to-erasure: remove a learner's stored session."""
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            log.info("session_deleted", extra={"session_id": session_id})
            return True
        return False

    def sweep_expired(self, retention_days: int | None = None) -> int:
        """Delete sessions older than the retention window. Returns count removed."""
        days = retention_days if retention_days is not None else CONFIG.session_retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed = 0
        for path in self.dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ts = datetime.fromisoformat(data.get("stored_at") or data.get("timestamp"))
                if ts < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                continue
        if removed:
            log.info("retention_sweep", extra={"removed": removed, "retention_days": days})
        return removed

    def count(self) -> int:
        return sum(1 for _ in self.dir.glob("*.json"))

    def for_learner(self, learner_id: str, limit: int = 50) -> list[dict]:
        """Sessions for one opaque learner id, oldest-first — powers the growth trend.

        `learner_id` is a client-generated random id (see frontend/app.js), never linked to
        a real identity; still validated defensively before touching the filesystem.
        """
        safe = "".join(c for c in learner_id if c.isalnum() or c == "-")
        if not safe:
            return []
        out = []
        for path in self.dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("learner_id") == safe:
                out.append(data)
        out.sort(key=lambda d: d.get("stored_at") or d.get("timestamp") or "")
        return out[-limit:]


class PendingSessionStore:
    """Disk-backed state for an in-progress quiz (the server-side answer key, goal, and
    goal requirements between /quiz/start and /quiz/submit).

    This used to be a plain in-memory dict on the FastAPI app. That broke in two
    concrete, observed ways:
      1. `uvicorn --reload` restarts the whole Python process on any file save (including
         edits unrelated to the running quiz), wiping every in-memory dict — a learner
         mid-quiz would submit into an empty dict and get "unknown or expired session_id".
      2. In production, gunicorn runs multiple *worker processes* (see Dockerfile: `-w 2`).
         Each worker has its own memory. A session started on worker A and submitted to
         worker B (a normal round-robin outcome) would never be found — the exact same
         symptom, but permanent, not just a dev-server quirk.
    Writing to a shared file (visible to every worker, and to the next process after a
    restart) fixes both. TTL-expiry treats an abandoned quiz (tab left open past the
    window) the same as a truly unknown id, without needing a background cron job.
    """

    def __init__(self, directory: Path | None = None, ttl_hours: float = 4.0):
        self.dir = directory or CONFIG.paths.pending_sessions
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)

    def _path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum())
        return self.dir / f"{safe}.json"

    def save(self, session_id: str, payload: dict) -> None:
        payload = {**payload, "created_at": datetime.now(timezone.utc).isoformat()}
        self._path(session_id).write_text(json.dumps(payload), encoding="utf-8")

    def pop(self, session_id: str) -> dict | None:
        """Read and delete — a pending session is consumed exactly once, on submit."""
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(data["created_at"])
        except Exception:
            path.unlink(missing_ok=True)
            return None
        path.unlink(missing_ok=True)
        if datetime.now(timezone.utc) - created > self.ttl:
            return None  # expired: treat identically to "never existed"
        return data

    def sweep_expired(self) -> int:
        """Delete abandoned pending sessions (tab left open past the TTL window)."""
        cutoff = datetime.now(timezone.utc) - self.ttl
        removed = 0
        for path in self.dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if datetime.fromisoformat(data["created_at"]) < cutoff:
                    path.unlink()
                    removed += 1
            except Exception:
                continue
        return removed
