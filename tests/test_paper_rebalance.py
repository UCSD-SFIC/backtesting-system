import csv

import pytest

from paper.csv import read_holdings_csv, write_rebalance_csv
from paper.rebalance import rebalance


def test_rebalance_sells_before_buying_and_keeps_cash_nonnegative():
    result = rebalance(
        {"AAA": 0.5, "BBB": 0.5},
        {"AAA": 10.0, "BBB": 20.0},
        {"AAA": 10},
        cash=0.0,
    )
    assert [(t.ticker, t.delta_shares) for t in result.trades] == [("AAA", -5), ("BBB", 2)]
    assert result.ending_cash == pytest.approx(10.0)
    assert result.turnover == pytest.approx(0.9)


def test_costs_can_reduce_affordable_buy_shares():
    result = rebalance({"AAA": 1.0}, {"AAA": 10.0}, {}, cash=100.0, cost_bps=100.0)
    assert result.trades[0].target_shares == 9
    assert result.estimated_cost == pytest.approx(0.9)
    assert result.ending_cash == pytest.approx(9.1)


def test_unmentioned_holding_is_sold_and_rounding_leaves_cash():
    result = rebalance({"BBB": 0.5}, {"AAA": 10.0, "BBB": 30.0}, {"AAA": 3}, cash=0.0)
    assert [(t.ticker, t.delta_shares) for t in result.trades] == [("AAA", -3), ("BBB", 0)]
    assert result.ending_cash == pytest.approx(30.0)


@pytest.mark.parametrize(
    "weights,prices,holdings,cash",
    [
        ({"AAA": 1.2}, {"AAA": 10.0}, {}, 100.0),
        ({"AAA": -0.1}, {"AAA": 10.0}, {}, 100.0),
        ({"AAA": 1.0}, {"AAA": 0.0}, {}, 100.0),
        ({"AAA": 1.0}, {}, {}, 100.0),
        ({}, {"AAA": 10.0}, {"AAA": -1}, 100.0),
        ({}, {}, {}, -1.0),
    ],
)
def test_invalid_inputs_raise(weights, prices, holdings, cash):
    with pytest.raises(ValueError):
        rebalance(weights, prices, holdings, cash)


def test_holdings_csv_round_trip_with_rebalance_export(tmp_path):
    holdings_path = tmp_path / "holdings.csv"
    holdings_path.write_text("ticker,shares\nAAA,2\nBBB,0\n")
    holdings = read_holdings_csv(holdings_path)
    assert holdings == {"AAA": 2, "BBB": 0}

    result = rebalance({"BBB": 1.0}, {"AAA": 10.0, "BBB": 5.0}, holdings, 0.0)
    output_path = tmp_path / "paper_packet.csv"
    write_rebalance_csv(output_path, result)
    with output_path.open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["ticker"] == "AAA"
    assert rows[0]["delta_shares"] == "-2"
    assert rows[1]["target_shares"] == "4"


def test_duplicate_holdings_csv_ticker_is_rejected(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("ticker,shares\nAAA,2\nAAA,3\n")
    with pytest.raises(ValueError, match="duplicate"):
        read_holdings_csv(path)


def test_excessive_simulated_cost_is_rejected():
    with pytest.raises(ValueError, match="cost_bps"):
        rebalance({}, {}, {}, cash=1.0, cost_bps=10_001)
