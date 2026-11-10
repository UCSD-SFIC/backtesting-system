import datetime as dt

import pytest

from strategy.universe import Membership, PointInTimeUniverse


def test_eligibility_uses_historical_membership_windows():
    universe = PointInTimeUniverse.from_records(
        [
            Membership("AAA", dt.date(2020, 1, 1), dt.date(2021, 12, 31)),
            Membership("BBB", dt.date(2022, 1, 1)),
        ]
    )
    assert universe.eligible_tickers(dt.date(2021, 12, 31)) == ["AAA"]
    assert universe.eligible_tickers(dt.date(2022, 1, 1)) == ["BBB"]


def test_reentry_after_exit_is_allowed():
    universe = PointInTimeUniverse.from_records(
        [
            Membership("AAA", dt.date(2020, 1, 1), dt.date(2020, 6, 30)),
            Membership("AAA", dt.date(2021, 1, 1)),
        ]
    )
    assert universe.eligible_tickers(dt.date(2020, 8, 1)) == []
    assert universe.eligible_tickers(dt.date(2021, 2, 1)) == ["AAA"]


def test_overlap_for_same_ticker_is_rejected():
    with pytest.raises(ValueError, match="overlap"):
        PointInTimeUniverse.from_records(
            [
                Membership("AAA", dt.date(2020, 1, 1), dt.date(2020, 6, 30)),
                Membership("AAA", dt.date(2020, 6, 30)),
            ]
        )


def test_invalid_window_and_blank_ticker_are_rejected():
    with pytest.raises(ValueError, match="end_date"):
        PointInTimeUniverse.from_records(
            [Membership("AAA", dt.date(2021, 1, 2), dt.date(2021, 1, 1))]
        )
    with pytest.raises(ValueError, match="ticker"):
        PointInTimeUniverse.from_records([Membership(" ", dt.date(2021, 1, 1))])


def test_csv_loads_membership_dates_and_rejects_bad_columns(tmp_path):
    path = tmp_path / "membership.csv"
    path.write_text("ticker,start_date,end_date\nAAA,2020-01-01,2020-12-31\nBBB,2021-01-01,\n")
    universe = PointInTimeUniverse.from_csv(path)
    assert universe.eligible_tickers(dt.date(2021, 2, 1)) == ["BBB"]
    path.write_text("ticker,start_date\nAAA,2020-01-01\n")
    with pytest.raises(ValueError, match="columns"):
        PointInTimeUniverse.from_csv(path)
