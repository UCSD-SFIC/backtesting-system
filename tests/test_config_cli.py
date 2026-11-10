from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

import pipeline.cli as cli
from data.providers import DataProvider
from pipeline.config import load_config
from strategy.registry import build_strategy
from strategy.sample_alpha import SampleAlpha

# Tests for TOML run configs, strategy lookup, and the CLI commands.

REPO_ROOT = Path(__file__).resolve().parent.parent

BASE_CONFIG = """
tickers = ["spy", "SH"]
start = 2024-01-01
end = 2024-03-01

[strategy]
name = "sma_crossover"

[strategy.params]
short_window = 2
long_window = 3
"""


def write_config(tmp_path: Path, text: str = BASE_CONFIG) -> Path:
    path = tmp_path / "run.toml"
    path.write_text(text)
    return path


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.delenv("BACKTEST_CACHE_DIR", raising=False)


def test_load_config_applies_defaults_and_normalizes(tmp_path):
    config = load_config(write_config(tmp_path))

    assert config.tickers == ["SPY", "SH"]
    assert config.benchmark == "SPY"
    assert config.timespan == "day"
    assert config.start == dt.date(2024, 1, 1)
    assert config.data.provider == "yfinance"
    assert config.data.cache_dir == "history_cache"


@pytest.mark.parametrize("path", sorted((REPO_ROOT / "configs").glob("*.toml")))
def test_example_configs_are_valid(path):
    config = load_config(path)

    build_strategy(
        config.strategy.name,
        config.tickers,
        config.timespan,
        config.start.isoformat(),
        config.end.isoformat(),
        config.strategy.params,
    )


def test_env_overrides_file_and_cli_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "polygon")
    path = write_config(tmp_path)

    assert load_config(path).data.provider == "polygon"
    assert load_config(path, {"data.provider": "yfinance"}).data.provider == "yfinance"
    assert load_config(path, {"data.provider": None}).data.provider == "polygon"


@pytest.mark.parametrize(
    ("replace", "message"),
    [
        (("end = 2024-03-01", "end = 2023-03-01"), "end must be after start"),
        (('tickers = ["spy", "SH"]', 'tickers = ["SPY", "spy"]'), "tickers must be unique"),
        (('name = "sma_crossover"', 'name = "nope"'), "unknown strategy"),
        (("start = 2024-01-01", "start = 2024-01-01\nbenchmark = 'QQQ'"), "benchmark must be"),
        (("start = 2024-01-01", "start = 2024-01-01\ntimespn = 'day'"), "Extra inputs"),
    ],
)
def test_invalid_configs_fail_with_clear_errors(tmp_path, replace, message):
    old, new = replace
    path = write_config(tmp_path, BASE_CONFIG.replace(old, new))

    with pytest.raises(ValidationError, match=message):
        load_config(path)


def test_build_strategy_passes_params_and_rejects_unknown_ones():
    alpha = build_strategy("sma_crossover", ["SPY", "SH"], "day", "2024-01-01", "2024-02-01",
                           {"short_window": 2, "long_window": 4})

    assert isinstance(alpha, SampleAlpha)
    assert alpha.long_window == 4
    with pytest.raises(ValueError, match="Invalid params"):
        build_strategy("sma_crossover", ["SPY", "SH"], "day", "2024-01-01", "2024-02-01",
                       {"window": 3})


class TrendProvider(DataProvider):
    name = "trend"

    def __init__(self, bad: bool = False):
        self.bad = bad

    def get_history(self, tickers, timespan, from_time, to_time):
        closes = {
            "SPY": [float(10 + i) for i in range(10)],
            "SH": [float(20 - i) for i in range(10)],
        }
        if self.bad:
            closes["SH"][3] = -1.0
        return {
            ticker: pl.DataFrame(
                {
                    "timestamp": [1704171600000 + i * 86_400_000 for i in range(10)],
                    "open": closes[ticker],
                    "high": closes[ticker],
                    "low": closes[ticker],
                    "close": closes[ticker],
                    "volume": [1.0] * 10,
                }
            )
            for ticker in tickers
        }


def test_cli_run_prints_metrics_and_saves_plot(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "create_data_provider", lambda *args, **kwargs: TrendProvider())
    plot_path = tmp_path / "plot.png"

    code = cli.main(
        ["run", "--config", str(write_config(tmp_path)), "--no-plot", "--save-plot", str(plot_path)]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "sma_crossover on SPY, SH" in output
    assert "Total return" in output
    assert "Beta vs SPY" in output
    assert plot_path.stat().st_size > 0


def test_cli_run_can_save_reproducible_result(tmp_path, monkeypatch):
    from experiments.store import list_runs, load_frame

    monkeypatch.setattr(cli, "create_data_provider", lambda *args, **kwargs: TrendProvider())
    run_dir = tmp_path / "runs"
    code = cli.main(["run", "--config", str(write_config(tmp_path)), "--no-plot",
                     "--save-run", str(run_dir)])
    assert code == 0
    records = list_runs(run_dir)
    assert len(records) == 1
    assert "total_return" in records[0].metrics
    assert not load_frame(records[0], "result").is_empty()


def test_cli_validate_data_reports_errors_with_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "create_raw_provider", lambda name: TrendProvider(bad=True))
    config = write_config(tmp_path, BASE_CONFIG + '\n[data]\ncache_dir = "' + str(tmp_path) + '"\n')

    code = cli.main(["validate-data", "--config", str(config)])

    output = capsys.readouterr().out
    assert code == 1
    assert "SH non_positive_price" in output
    assert "1 errors" in output
    assert not (tmp_path / "trend").exists()


def test_cli_reports_config_errors_without_traceback(tmp_path, capsys):
    path = write_config(tmp_path, BASE_CONFIG.replace("end = 2024-03-01", "end = 2023-03-01"))

    code = cli.main(["run", "--config", str(path), "--no-plot"])

    assert code == 2
    assert "end must be after start" in capsys.readouterr().err


ALLOCATION_CONFIG = """
universe_file = "{universe}"
start = 2024-01-01
end = 2024-12-31
benchmark = "SPY"

[strategy]
name = "allocation"

[execution]
cost_bps = 15
"""


def test_dated_universe_file_is_passed_to_allocation_strategy(tmp_path):
    from pipeline.config import load_config

    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,start_date,end_date\nA,2020-01-01,2022-01-01\nB,2020-01-01,\nA,2023-01-01,\n")
    path = tmp_path / "dated.toml"
    path.write_text(
        f'universe_file = "{universe}"\nstart = 2024-01-01\nend = 2024-12-31\n'
        '[strategy]\nname = "allocation"\n'
    )
    config = load_config(path)
    assert config.tickers == ["A", "B"]
    assert config.strategy.params["membership_file"] == str(universe)


def test_universe_file_and_outside_benchmark(tmp_path):
    universe = tmp_path / "universe.csv"
    universe.write_text("# comment\nticker\nAAPL\nmsft\n")

    config = load_config(write_config(tmp_path, ALLOCATION_CONFIG.format(universe=universe)))

    assert config.tickers == ["AAPL", "MSFT"]
    assert config.benchmark == "SPY"
    assert config.strategy.params["benchmark"] == "SPY"
    assert config.execution.cost_bps == 15


def test_universe_file_and_tickers_are_exclusive(tmp_path):
    universe = tmp_path / "universe.csv"
    universe.write_text("ticker\nAAPL\n")
    text = 'tickers = ["AAPL"]\n' + ALLOCATION_CONFIG.format(universe=universe)

    with pytest.raises(ValueError, match="either tickers or universe_file"):
        load_config(write_config(tmp_path, text))


def test_outside_benchmark_needs_a_strategy_that_supports_it(tmp_path):
    text = BASE_CONFIG.replace("start = 2024-01-01", "start = 2024-01-01\nbenchmark = 'QQQ'")

    with pytest.raises(ValidationError, match="benchmark must be one of the tickers"):
        load_config(write_config(tmp_path, text))
