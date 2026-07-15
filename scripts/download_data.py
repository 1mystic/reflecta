"""Download public datasets into data/raw/.

Usage:
    python scripts/download_data.py --dataset assistments
    python scripts/download_data.py --dataset mmlu          # via HuggingFace datasets
    python scripts/download_data.py --list

Some sources (Eedi, EdNet, MedMCQA) require accepting terms or a Kaggle token; those print
manual instructions rather than downloading silently. Everything is free.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

SOURCES = {
    "assistments": {
        "kind": "url",
        # ASSISTments 2009-2010 skill-builder (raw columns: user_id, problem_id,
        # skill_name, correct, ms_first_response). ~83MB / 525k interactions.
        "url": "https://raw.githubusercontent.com/GaoSida/DKT/master/Assistments/skill_builder_data.csv",
        "filename": "assistments_2009.csv",
        "note": "Real KT dataset, 525k interactions — start here.",
    },
    "mmlu": {
        "kind": "hf",
        "hf_name": ("cais/mmlu", "all"),
        "note": "Question content; MMLU-Redux has corrected labels.",
    },
    "eedi": {
        "kind": "manual",
        "note": "Kaggle: 'Eedi - Mining Misconceptions in Mathematics' or the NeurIPS 2020 "
                "Education Challenge. Download with a Kaggle token, place CSVs in data/raw/.",
    },
    "ednet": {
        "kind": "manual",
        "note": "github.com/riiid/ednet — large; grab KT1 sample, place in data/raw/ednet/.",
    },
    "medmcqa": {
        "kind": "hf",
        "hf_name": ("openlifescienceai/medmcqa", None),
        "note": "194k Indian medical entrance MCQs.",
    },
}


def download_url(url: str, filename: str) -> None:
    import requests
    from tqdm import tqdm

    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / filename
    print(f"Downloading {url}\n  -> {dest}")
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    with open(dest, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
            bar.update(len(chunk))
    print("Done.")


def download_hf(name: tuple[str, str | None], key: str) -> None:
    from datasets import load_dataset

    RAW.mkdir(parents=True, exist_ok=True)
    repo, config = name
    print(f"Loading HuggingFace dataset {repo} ({config})…")
    ds = load_dataset(repo, config) if config else load_dataset(repo)
    out = RAW / f"{key}.parquet"
    split = "test" if "test" in ds else list(ds.keys())[0]
    ds[split].to_parquet(out)
    print(f"Saved split '{split}' -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=list(SOURCES), help="which dataset to fetch")
    ap.add_argument("--list", action="store_true", help="list available datasets")
    args = ap.parse_args()

    if args.list or not args.dataset:
        print("Available datasets:\n")
        for k, v in SOURCES.items():
            print(f"  {k:12s} [{v['kind']:6s}]  {v['note']}")
        return 0

    src = SOURCES[args.dataset]
    if src["kind"] == "url":
        download_url(src["url"], src["filename"])
    elif src["kind"] == "hf":
        download_hf(src["hf_name"], args.dataset)
    else:
        print(f"[manual] {args.dataset}: {src['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
