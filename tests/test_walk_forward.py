import datetime as dt

import pytest

from research.walk_forward import (
    FoldResult,
    make_walk_forward_windows,
    summarize_out_of_sample,
)

DATES = [dt.date(2024, 1, day) for day in range(1, 11)]


def test_windows_roll_training_and_do_not_overlap_test_periods():
    windows = make_walk_forward_windows(DATES, train_size=4, test_size=2)
    assert [(w.train_start, w.train_stop, w.test_start, w.test_stop) for w in windows] == [
        (0, 4, 4, 6),
        (2, 6, 6, 8),
        (4, 8, 8, 10),
    ]
    assert windows[0].train_end == DATES[3]
    assert windows[0].test_begin == DATES[4]
    assert windows[1].test_begin > windows[0].test_end


def test_windows_require_ordered_unique_dates_and_complete_folds():
    assert make_walk_forward_windows(DATES[:5], train_size=4, test_size=2) == []
    with pytest.raises(ValueError, match="strictly increasing"):
        make_walk_forward_windows([DATES[1], DATES[0]], 1, 1)
    with pytest.raises(ValueError, match="positive"):
        make_walk_forward_windows(DATES, 0, 2)
    with pytest.raises(ValueError, match="test_size"):
        make_walk_forward_windows(DATES, 4, 2, step_size=1)


def test_summary_compounds_only_test_returns_and_reports_worst_drawdown():
    windows = make_walk_forward_windows(DATES, train_size=4, test_size=2)
    folds = [
        FoldResult("momentum", windows[0], (0.1, -0.1)),
        FoldResult("momentum", windows[1], (0.2, 0.0)),
        FoldResult("hedged", windows[0], (0.02, 0.02)),
    ]
    summary = summarize_out_of_sample(folds).sort("strategy").to_dicts()
    hedged, momentum = summary
    assert hedged["folds"] == 1
    assert momentum["observations"] == 4
    assert momentum["compounded_return"] == pytest.approx(1.1 * 0.9 * 1.2 - 1)
    assert momentum["worst_drawdown"] == pytest.approx(-0.1)


def test_summary_rejects_leaked_or_invalid_test_returns():
    window = make_walk_forward_windows(DATES, 4, 2)[0]
    with pytest.raises(ValueError, match="test_size"):
        summarize_out_of_sample([FoldResult("a", window, (0.1,))])
    with pytest.raises(ValueError, match="return"):
        summarize_out_of_sample([FoldResult("a", window, (0.1, -1.1))])


def test_summary_rejects_overlapping_test_periods_for_same_strategy():
    windows = make_walk_forward_windows(DATES, 4, 2, step_size=2)
    with pytest.raises(ValueError, match="overlap"):
        summarize_out_of_sample(
            [
                FoldResult("a", windows[0], (0.0, 0.0)),
                FoldResult("a", windows[0], (0.0, 0.0)),
            ]
        )
