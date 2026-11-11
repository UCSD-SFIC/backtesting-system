from __future__ import annotations

import json

import polars as pl
import pytest

from experiments.store import list_runs, load_frame, load_run, save_run, set_review_state


def _prices() -> pl.DataFrame:
    return pl.DataFrame({"timestamp": [1, 2], "SPY_close": [100.0, 101.0]})


def test_saved_run_round_trip_and_artifact_hash(tmp_path):
    prices = _prices()
    result = pl.DataFrame({"timestamp": [1, 2], "overall_growth": [1.0, 1.01]})
    holdings = pl.DataFrame({"ticker": ["SPY"], "target_weight": [1.0]})
    record = save_run(
        tmp_path,
        config={"provider": "fixture", "start": "2024-01-01"},
        price_history=prices,
        result=result,
        metrics={"total_return": 0.01},
        holdings=holdings,
    )

    assert len(record.data_hash) == 64
    assert record.review_state == "draft"
    assert load_run(tmp_path, record.run_id) == record
    assert load_frame(record, "price_history").equals(prices)
    assert load_frame(record, "result").equals(result)
    assert load_frame(record, "holdings").equals(holdings)
    assert [item.run_id for item in list_runs(tmp_path)] == [record.run_id]


def test_review_state_is_validated_and_persisted_atomically(tmp_path):
    record = save_run(
        tmp_path, config={}, price_history=_prices(), result=_prices(), metrics={}
    )
    reviewed = set_review_state(tmp_path, record.run_id, "reviewed")
    assert reviewed.review_state == "reviewed"
    assert load_run(tmp_path, record.run_id).review_state == "reviewed"
    with pytest.raises(ValueError, match="review state"):
        set_review_state(tmp_path, record.run_id, "executed")
    assert load_run(tmp_path, record.run_id).review_state == "reviewed"


def test_rejects_invalid_metadata_and_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="JSON"):
        save_run(
            tmp_path, config={"bad": object()}, price_history=_prices(),
            result=_prices(), metrics={}
        )
    with pytest.raises(ValueError, match="run ID"):
        load_run(tmp_path, "../elsewhere")
    assert list_runs(tmp_path) == []


def test_detects_tampered_price_snapshot(tmp_path):
    record = save_run(
        tmp_path, config={}, price_history=_prices(), result=_prices(), metrics={}
    )
    record.artifacts["price_history"].write_bytes(b"not parquet")
    with pytest.raises(ValueError, match="checksum"):
        load_run(tmp_path, record.run_id)


def test_rejects_unknown_artifact_and_invalid_metrics(tmp_path):
    with pytest.raises(ValueError, match="finite"):
        save_run(
            tmp_path, config={}, price_history=_prices(), result=_prices(),
            metrics={"sharpe": float("nan")}
        )
    record = save_run(
        tmp_path, config={}, price_history=_prices(), result=_prices(), metrics={}
    )
    with pytest.raises(ValueError, match="artifact"):
        load_frame(record, "../../other")
    metadata = record.path / "metadata.json"
    assert json.loads(metadata.read_text())["schema_version"] == 1


def test_list_runs_ignores_unrelated_folders_but_rejects_corrupt_runs(tmp_path):
    (tmp_path / "notes").mkdir()
    record = save_run(
        tmp_path, config={}, price_history=_prices(), result=_prices(), metrics={}
    )
    assert [item.run_id for item in list_runs(tmp_path)] == [record.run_id]

    (record.path / "metadata.json").write_text("not JSON")
    with pytest.raises(json.JSONDecodeError):
        list_runs(tmp_path)
