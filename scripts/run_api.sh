#!/usr/bin/env bash
# Start the Reflecta backend (serves the frontend at http://localhost:8000)
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/Scripts/python.exe -m uvicorn api.main:app --reload --port 8000
