# Reflecta API — multi-stage, slim, non-root. Serves API + static frontend on :8000.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# --- dependencies (cached layer) ---
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[api,data]"

# --- app code ---
COPY api ./api
COPY frontend ./frontend
COPY data/question_bank.json ./data/question_bank.json
# ship trained artifacts if present (optional; app degrades gracefully without them)
COPY models_store ./models_store

# --- runtime hardening ---
RUN adduser --disabled-password --gecos "" appuser \
    && mkdir -p /app/data/sessions && chown -R appuser:appuser /app
USER appuser

ENV REFLECTA_ENV=prod \
    REFLECTA_LOG_JSON=true \
    REFLECTA_REQUIRE_CONSENT=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"

# gunicorn with uvicorn workers = production ASGI serving
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", \
     "-b", "0.0.0.0:8000", "--access-logfile", "-", "api.main:app"]
