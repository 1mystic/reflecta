# Security Policy

## Reporting a vulnerability
Please open a private report or email the maintainer rather than filing a public issue.
Include steps to reproduce and impact. We aim to acknowledge within a few days.

## Security posture of this project
- **No answer leakage** — quiz correct-answers are held server-side; the client only ever
  receives shuffled options. Grading happens on the server (`api/main.py`, `question_bank.py`).
- **No secrets in the repo** — configuration is via environment variables (`.env`, gitignored).
  `.env.example` documents the keys.
- **Input validation** — all request bodies are validated by Pydantic schemas with bounds
  (`api/schemas.py`); the goal string is length-capped.
- **CORS** — wildcard is used only in `dev`; in `prod` (`REFLECTA_ENV=prod`) origins are
  restricted to `REFLECTA_CORS_ORIGINS`.
- **Rate limiting** — per-IP limit on quiz endpoints (`REFLECTA_RATE_LIMIT_PER_MIN`). For
  multi-worker deployments, back this with Redis.
- **Error handling** — unhandled exceptions return an opaque error id, never a stack trace.
- **Least privilege** — the container runs as a non-root user (`Dockerfile`).
- **Path-traversal guard** — session ids are sanitized before touching the filesystem.

## Dependencies
Pin and scan dependencies before deploying (`pip-audit` / Dependabot recommended). This repo
keeps optional heavy deps (torch, tracking) out of the base install to reduce attack surface.
