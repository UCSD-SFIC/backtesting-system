"""Atomic, inspectable storage for historical research runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

ARTIFACTS = ("price_history", "result", "holdings", "trades")
REVIEW_STATES = frozenset({"draft", "reviewed", "superseded"})


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    created_at: str
    data_hash: str
    config: dict[str, Any]
    metrics: dict[str, float]
    review_state: str
    path: Path
    artifacts: dict[str, Path]


def _is_run_id(run_id: str) -> bool:
    try:
        return str(uuid.UUID(run_id)) == run_id
    except ValueError:
        return False


def _run_path(root: str | Path, run_id: str) -> Path:
    if not _is_run_id(run_id):
        raise ValueError("invalid run ID")
    return Path(root) / run_id


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("config and metrics must be JSON serializable") from exc


def _metadata(record: RunRecord) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": record.run_id,
        "created_at": record.created_at,
        "data_hash": record.data_hash,
        "config": record.config,
        "metrics": record.metrics,
        "review_state": record.review_state,
        "artifacts": sorted(record.artifacts),
    }


def save_run(
    root: str | Path,
    *,
    config: dict[str, Any],
    price_history: pl.DataFrame,
    result: pl.DataFrame,
    metrics: dict[str, float],
    holdings: pl.DataFrame | None = None,
    trades: pl.DataFrame | None = None,
) -> RunRecord:
    """Save one immutable run; the directory appears only after every file is ready."""
    clean_config = _json_value(config)
    if not isinstance(clean_config, dict) or not isinstance(metrics, dict):
        raise ValueError("config and metrics must be JSON objects")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
        for value in metrics.values()
    ):
        raise ValueError("metrics must contain finite numbers")
    clean_metrics = _json_value(metrics)
    if price_history.is_empty() or result.is_empty():
        raise ValueError("price_history and result cannot be empty")

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    final_path = _run_path(root_path, run_id)
    frames = {"price_history": price_history, "result": result}
    if holdings is not None:
        frames["holdings"] = holdings
    if trades is not None:
        frames["trades"] = trades

    with tempfile.TemporaryDirectory(prefix=".pending-", dir=root_path) as temporary:
        pending = Path(temporary)
        for name, frame in frames.items():
            frame.write_parquet(pending / f"{name}.parquet")
        record = RunRecord(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            data_hash=_checksum(pending / "price_history.parquet"),
            config=clean_config,
            metrics=clean_metrics,
            review_state="draft",
            path=final_path,
            artifacts={name: final_path / f"{name}.parquet" for name in frames},
        )
        (pending / "metadata.json").write_text(json.dumps(_metadata(record), indent=2) + "\n")
        os.replace(pending, final_path)
    return record


def load_run(root: str | Path, run_id: str) -> RunRecord:
    path = _run_path(root, run_id)
    metadata = json.loads((path / "metadata.json").read_text())
    if metadata.get("schema_version") != 1 or metadata.get("run_id") != run_id:
        raise ValueError("invalid saved run metadata")
    names = metadata.get("artifacts")
    if not isinstance(names, list) or not {"price_history", "result"} <= set(names):
        raise ValueError("invalid saved run artifacts")
    if any(name not in ARTIFACTS for name in names):
        raise ValueError("invalid saved run artifacts")
    artifacts = {name: path / f"{name}.parquet" for name in names}
    if _checksum(artifacts["price_history"]) != metadata.get("data_hash"):
        raise ValueError("price history checksum mismatch")
    state = metadata.get("review_state")
    if state not in REVIEW_STATES:
        raise ValueError("invalid review state")
    return RunRecord(
        run_id=run_id,
        created_at=metadata["created_at"],
        data_hash=metadata["data_hash"],
        config=metadata["config"],
        metrics=metadata["metrics"],
        review_state=state,
        path=path,
        artifacts=artifacts,
    )


def list_runs(root: str | Path) -> list[RunRecord]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    paths = (
        path for path in root_path.iterdir() if path.is_dir() and _is_run_id(path.name)
    )
    return sorted(
        (load_run(root_path, path.name) for path in paths),
        key=lambda record: record.created_at,
        reverse=True,
    )


def load_frame(record: RunRecord, name: str) -> pl.DataFrame:
    if name not in ARTIFACTS or name not in record.artifacts:
        raise ValueError(f"unknown artifact: {name}")
    return pl.read_parquet(record.artifacts[name])


def set_review_state(root: str | Path, run_id: str, state: str) -> RunRecord:
    if state not in REVIEW_STATES:
        raise ValueError("invalid review state")
    record = load_run(root, run_id)
    updated = RunRecord(**{**record.__dict__, "review_state": state})
    with tempfile.NamedTemporaryFile(
        mode="w", prefix=".metadata-", suffix=".json", dir=record.path, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(_metadata(updated), stream, indent=2)
        stream.write("\n")
    try:
        os.replace(temporary, record.path / "metadata.json")
    finally:
        temporary.unlink(missing_ok=True)
    return updated
