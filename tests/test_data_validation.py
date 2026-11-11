from __future__ import annotations

import polars as pl
import pytest

from data.schema import normalize_ohlcv
from data.validation import DataValidationError, raise_for_errors, validate_history

# Tests for the data-quality checks run on every provider fetch.

DAY_MS = 24 * 60 * 60 * 1000
START_MS = 1704171600000


def make_history(closes: list[float | None], timestamps: list[int] | None = None) -> pl.DataFrame:
    timestamps = timestamps or [START_MS + i * DAY_MS for i in range(len(closes))]
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [c * 1.01 if c is not None else None for c in closes],
            "low": [c * 0.99 if c is not None else None for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        schema={column: pl.Float64 for column in ["open", "high", "low", "close", "volume"]}
        | {"timestamp": pl.Int64},
    )


def checks(issues) -> set[str]:
    return {issue.check for issue in issues}


def test_clean_history_has_no_issues():
    assert validate_history("A", make_history([10.0, 10.5, 10.2, 10.8])) == []


def test_missing_columns_is_an_error():
    issues = validate_history("A", pl.DataFrame({"timestamp": [1], "close": [1.0]}))

    assert checks(issues) == {"missing_columns"}
    assert issues[0].severity == "error"


def test_empty_history_is_an_error():
    issues = validate_history("A", make_history([]))

    assert checks(issues) == {"empty"}


def test_duplicate_and_null_close_are_errors():
    history = make_history([10.0, None, 11.0], [START_MS, START_MS, START_MS + DAY_MS])

    issues = validate_history("A", history)

    errors = {issue.check for issue in issues if issue.severity == "error"}
    assert {"duplicate_timestamps", "null_values"} <= errors


def test_non_positive_price_is_an_error():
    issues = validate_history("A", make_history([10.0, 0.0, 10.0]))

    assert "non_positive_price" in checks(issues)
    with pytest.raises(DataValidationError, match="non_positive_price"):
        raise_for_errors(issues)


def test_unadjusted_split_is_flagged_as_extreme_return():
    issues = validate_history("A", make_history([100.0, 101.0, 25.5, 25.7]))

    extreme = [issue for issue in issues if issue.check == "extreme_return"]
    assert len(extreme) == 1
    assert extreme[0].severity == "warning"


def test_long_gap_in_daily_bars_is_a_warning():
    timestamps = [START_MS, START_MS + DAY_MS, START_MS + 10 * DAY_MS]

    issues = validate_history("A", make_history([10.0, 10.1, 10.2], timestamps), "day")

    assert checks(issues) == {"missing_bars"}
    raise_for_errors(issues)


def test_intraday_bars_skip_gap_check():
    timestamps = [START_MS, START_MS + 10 * DAY_MS]

    assert validate_history("A", make_history([10.0, 10.1], timestamps), "hour") == []


def test_normalize_ohlcv_casts_and_sorts_and_drops_extra_columns():
    raw = pl.DataFrame(
        {
            "timestamp": [2, 1],
            "open": [1, 1],
            "high": [2, 2],
            "low": [1, 1],
            "close": [2, 1],
            "volume": [5, 5],
            "vwap": [1.5, 1.5],
        }
    )

    result = normalize_ohlcv(raw)

    assert result.columns == ["timestamp", "open", "high", "low", "close", "volume"]
    assert result["timestamp"].to_list() == [1, 2]
    assert result.schema["close"] == pl.Float64


def test_normalize_ohlcv_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        normalize_ohlcv(pl.DataFrame({"timestamp": [1], "close": [1.0]}))
