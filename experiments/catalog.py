"""Optional SQL index for saved Parquet research runs.

The file store remains responsible for the immutable result data. The catalog
indexes its metadata in SQLite or PostgreSQL using the same repository API.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from experiments.store import REVIEW_STATES, RunRecord


class _Base(DeclarativeBase):
    pass


class _RunRow(_Base):
    __tablename__ = "research_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String, nullable=False)
    artifact_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)


def _validate_run_id(run_id: str) -> None:
    try:
        valid = str(uuid.UUID(run_id)) == run_id
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("invalid run ID")


def _record(row: _RunRow) -> RunRecord:
    path = Path(row.artifact_path)
    return RunRecord(
        run_id=row.run_id,
        created_at=row.created_at,
        data_hash=row.data_hash,
        config=row.config,
        metrics=row.metrics,
        review_state=row.review_state,
        path=path,
        artifacts={name: path / f"{name}.parquet" for name in row.artifact_names},
    )


class RunCatalog:
    """Searchable metadata for runs stored in the existing Parquet file store."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("database URL is required")
        self._engine = create_engine(database_url)
        _Base.metadata.create_all(self._engine)

    def close(self) -> None:
        """Release pooled database connections when the catalog is no longer used."""
        self._engine.dispose()

    def __enter__(self) -> RunCatalog:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def upsert(self, record: RunRecord) -> RunRecord:
        _validate_run_id(record.run_id)
        if record.review_state not in REVIEW_STATES:
            raise ValueError("invalid review state")
        with Session(self._engine) as session, session.begin():
            row = session.get(_RunRow, record.run_id)
            if row is None:
                row = _RunRow(run_id=record.run_id)
                session.add(row)
            row.created_at = record.created_at
            row.data_hash = record.data_hash
            row.config = record.config
            row.metrics = record.metrics
            row.review_state = record.review_state
            row.artifact_path = str(record.path)
            row.artifact_names = sorted(record.artifacts)
        return record

    def find_by_id(self, run_id: str) -> RunRecord | None:
        _validate_run_id(run_id)
        with Session(self._engine) as session:
            row = session.get(_RunRow, run_id)
            return _record(row) if row is not None else None

    def find_all(self) -> list[RunRecord]:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(_RunRow).order_by(_RunRow.created_at.desc(), _RunRow.run_id.desc())
            ).all()
            return [_record(row) for row in rows]

    def update_state(self, run_id: str, state: str) -> RunRecord:
        _validate_run_id(run_id)
        if state not in REVIEW_STATES:
            raise ValueError("invalid review state")
        with Session(self._engine) as session, session.begin():
            row = session.get(_RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            row.review_state = state
            updated = _record(row)
        return updated
