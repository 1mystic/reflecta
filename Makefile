# Reflecta — common tasks. On Windows use Git Bash, or run the underlying commands directly.
PY := .venv/Scripts/python.exe

.PHONY: install data pipeline sakt api test docker sweep clean

install:            ## create venv + install everything
	uv venv --python 3.12
	uv pip install -e ".[api,tracking,data,neural,dev]"

data:               ## download real ASSISTments KT data
	$(PY) scripts/download_data.py --dataset assistments

pipeline:           ## train IRT + BKT, log to MLflow, persist artifacts
	$(PY) scripts/run_pipeline.py --source assistments

sakt:               ## train SAKT neural KT
	$(PY) scripts/train_sakt.py --epochs 6

api:                ## run the API + frontend (dev)
	$(PY) -m uvicorn api.main:app --reload --port 8000

test:               ## run the test suite
	$(PY) -m pytest -q

sweep:              ## delete sessions past the retention window
	$(PY) -c "from reflecta.sessions import FileSessionStore as S; print('removed', S().sweep_expired())"

docker:             ## build + run the production image
	docker compose up --build

clean:              ## remove caches (keeps data + models)
	rm -rf .pytest_cache **/__pycache__ *.egg-info
