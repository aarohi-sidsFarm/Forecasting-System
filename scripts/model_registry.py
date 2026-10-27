"""Record, verify and promote the live forecasting models.

backend/ml_models/model_registry.json lists every live model file with its
checksum, the last training date it saw, when it was promoted and why. The
tests check that the registry matches the files, so a model that is
replaced without being recorded fails CI.

Training scripts write to backend/ml_models/candidates/. To promote:

    # 1. backtest the candidates as issued
    FORECAST_MODEL_ARTIFACT_DIR=backend/ml_models/candidates \\
        python scripts/backtest_as_issued.py --start ... --end ...
    # 2. if they beat the live models (see docs/production_forecast_operations.md)
    python scripts/model_registry.py promote --note "HYD 3.9% vs 4.1%, BLR ..."

Usage:
    python scripts/model_registry.py show
    python scripts/model_registry.py verify
    python scripts/model_registry.py promote --note TEXT [--only FILE ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "backend" / "ml_models"
CANDIDATE_DIR = MODEL_DIR / "candidates"
REGISTRY_PATH = MODEL_DIR / "model_registry.json"

LIVE_MODELS = {
    "lgbm_model.pkl": "General recursive model (all cities)",
    "lgbm_model_hyd.pkl": "HYD recursive model",
    "hyd_d2_direct.pkl": "HYD D-2 direct model",
    "blr_d3_direct.pkl": "BLR D-3 direct model",
    "hyd_d2_direct_focus_direct.pkl": "HYD D-2 direct model, A2 Buffalo / Cow / Toned",
}
# Companion files the training scripts write next to a model.
COMPANIONS = ("_metrics.json", "_backtest.csv")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def trained_through(path: Path) -> str | None:
    with path.open("rb") as handle:
        artifact = pickle.load(handle)
    return artifact.get("trained_through") if isinstance(artifact, dict) else None


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {"models": {}, "history": []}


def save_registry(registry: dict) -> None:
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def problems(registry: dict | None = None) -> list[str]:
    """Differences between the registry and the live model files."""
    registry = registry or load_registry()
    found = []
    for name in LIVE_MODELS:
        entry = registry["models"].get(name)
        path = MODEL_DIR / name
        if not path.exists():
            found.append(f"{name}: file missing")
        elif entry is None:
            found.append(f"{name}: not in model_registry.json")
        elif entry["sha256"] != sha256(path):
            found.append(f"{name}: file changed without being recorded (use scripts/model_registry.py promote)")
    return found


def promote(note: str, only: list[str] | None) -> None:
    names = only or [name for name in LIVE_MODELS if (CANDIDATE_DIR / name).exists()]
    unknown = [name for name in names if name not in LIVE_MODELS]
    if unknown:
        sys.exit(f"Not a live model: {', '.join(unknown)}")
    missing = [name for name in names if not (CANDIDATE_DIR / name).exists()]
    if not names or missing:
        sys.exit(f"No candidate to promote in {CANDIDATE_DIR}: {', '.join(missing) or 'empty'}")

    registry = load_registry()
    now = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
    for name in names:
        source = CANDIDATE_DIR / name
        stem = name.removesuffix(".pkl")
        shutil.copy2(source, MODEL_DIR / name)
        for suffix in COMPANIONS:
            companion = CANDIDATE_DIR / f"{stem}{suffix}"
            if companion.exists():
                shutil.copy2(companion, MODEL_DIR / companion.name)
        previous = registry["models"].get(name)
        if previous:
            registry["history"].append({"file": name, "replaced_at": now, **previous})
        registry["models"][name] = {
            "description": LIVE_MODELS[name],
            "sha256": sha256(MODEL_DIR / name),
            "trained_through": trained_through(MODEL_DIR / name),
            "promoted_at": now,
            "note": note,
        }
        print(f"Promoted {name} (trained through {registry['models'][name]['trained_through']})")
    save_registry(registry)
    print("Commit backend/ml_models together with model_registry.json.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    sub.add_parser("verify")
    promote_parser = sub.add_parser("promote")
    promote_parser.add_argument("--note", required=True, help="why: the backtest result that justified it")
    promote_parser.add_argument("--only", nargs="+", help="model file names; default: every candidate present")
    args = parser.parse_args()

    if args.command == "promote":
        promote(args.note, args.only)
    elif args.command == "verify":
        found = problems()
        print("\n".join(found) or "Registry matches the live models.")
        sys.exit(1 if found else 0)
    else:
        for name, entry in load_registry()["models"].items():
            print(f"{name:34} trained through {entry['trained_through']}  promoted {entry['promoted_at']}  {entry['note']}")


if __name__ == "__main__":
    main()
