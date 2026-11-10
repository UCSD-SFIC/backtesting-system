import json

import polars as pl

from experiments.store import save_run
from pipeline.cli import main


def test_paper_rebalance_cli_exports_packet(tmp_path, capsys):
    weights = tmp_path / "weights.json"
    prices = tmp_path / "prices.json"
    holdings = tmp_path / "holdings.csv"
    output = tmp_path / "packet.csv"
    weights.write_text(json.dumps({"A": 1.0}))
    prices.write_text(json.dumps({"A": 10.0}))
    holdings.write_text("ticker,shares\nA,2\n")

    assert main(["paper-rebalance", "--weights", str(weights), "--prices", str(prices),
                 "--holdings", str(holdings), "--cash", "30", "--output", str(output)]) == 0
    assert output.exists()
    assert "A" in output.read_text()
    assert "Leftover cash" in capsys.readouterr().out


def test_scenario_analysis_cli_writes_sensitivity(tmp_path):
    portfolios = tmp_path / "portfolios.json"
    shocks = tmp_path / "shocks.json"
    output = tmp_path / "scenario.csv"
    portfolios.write_text(json.dumps({"defensive": {"SPY": 0.5, "SH": 0.5}}))
    shocks.write_text(json.dumps({"selloff": {"SPY": -0.2, "SH": 0.1}}))

    assert main(["scenario-analysis", "--portfolios", str(portfolios), "--shocks",
                 str(shocks), "--output", str(output)]) == 0
    assert "selloff" in output.read_text()


def test_compare_runs_cli_lists_saved_metrics(tmp_path, capsys):
    frame = pl.DataFrame({"timestamp": [1], "close": [10.0]})
    record = save_run(tmp_path, config={"strategy": "example"}, price_history=frame,
                      result=frame, metrics={"total_return": 0.25})
    assert main(["compare-runs", "--run-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert record.run_id in output
    assert "25.00%" in output


def test_paper_cli_rejects_nonnumeric_weight_without_traceback(tmp_path, capsys):
    weights = tmp_path / "weights.json"
    prices = tmp_path / "prices.json"
    holdings = tmp_path / "holdings.csv"
    weights.write_text('{"A": "bad"}')
    prices.write_text('{"A": 10}')
    holdings.write_text("ticker,shares\nA,0\n")
    assert main(["paper-rebalance", "--weights", str(weights), "--prices", str(prices),
                 "--holdings", str(holdings), "--cash", "10", "--output",
                 str(tmp_path / "out.csv")]) == 2
    assert "error:" in capsys.readouterr().err
