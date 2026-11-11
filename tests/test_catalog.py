"""Repository contract for the optional SQL run catalog."""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from experiments.catalog import RunCatalog
from experiments.store import RunRecord


def record(tmp_path) -> RunRecord:
    run_id = str(uuid.uuid4())
    path = tmp_path / run_id
    return RunRecord(
        run_id=run_id,
        created_at="2026-11-10T00:00:00+00:00",
        data_hash="a" * 64,
        config={"strategy": {"name": "allocation"}},
        metrics={"total_return": 0.25},
        review_state="draft",
        path=path,
        artifacts={"result": path / "result.parquet"},
    )


def test_catalog_persists_and_lists_run_metadata(tmp_path):
    url = f"sqlite:///{tmp_path / 'catalog.sqlite'}"
    run = record(tmp_path)

    with RunCatalog(url) as first:
        first.upsert(run)
    with RunCatalog(url) as second:
        saved = second.find_by_id(run.run_id)
        assert saved is not None
        assert saved.config == run.config
        assert saved.metrics == run.metrics
        assert saved.path == run.path
        assert saved.artifacts == run.artifacts
        assert [item.run_id for item in second.find_all()] == [run.run_id]


def test_upsert_is_idempotent_and_can_refresh_metadata(tmp_path):
    run = record(tmp_path)
    with RunCatalog(f"sqlite:///{tmp_path / 'catalog.sqlite'}") as catalog:
        catalog.upsert(run)
        catalog.upsert(replace(run, metrics={"total_return": 0.5}))
        assert len(catalog.find_all()) == 1
        assert catalog.find_by_id(run.run_id).metrics == {"total_return": 0.5}


def test_review_state_update_and_validation(tmp_path):
    run = record(tmp_path)
    with RunCatalog(f"sqlite:///{tmp_path / 'catalog.sqlite'}") as catalog:
        catalog.upsert(run)
        assert catalog.update_state(run.run_id, "reviewed").review_state == "reviewed"
        with pytest.raises(ValueError, match="review state"):
            catalog.update_state(run.run_id, "published")
        with pytest.raises(KeyError):
            catalog.update_state(str(uuid.uuid4()), "reviewed")
        with pytest.raises(ValueError, match="run ID"):
            catalog.find_by_id("../../oops")
