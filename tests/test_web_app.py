from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from data.providers import DataProvider
from experiments import save_run
from web.app import create_app


def test_browser_lists_allowlisted_configs_and_launches_one(tmp_path: Path):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "sample.toml").write_text("", encoding="utf-8")
    (configs / "ignore.txt").write_text("", encoding="utf-8")
    launched = []
    app = create_app(
        configs, tmp_path / "runs", runner=lambda path: launched.append(path) or "run-1"
    )
    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/api/configs").json() == {"configs": ["sample.toml"]}
    assert client.post("/api/runs", json={"config_name": "sample.toml"}).json() == {
        "run_id": "run-1"
    }
    assert launched == [configs / "sample.toml"]


def test_browser_rejects_unknown_and_traversal_configs(tmp_path: Path):
    configs = tmp_path / "configs"
    configs.mkdir()
    app = create_app(configs, tmp_path / "runs", runner=lambda path: "unexpected")
    client = TestClient(app)

    assert client.post("/api/runs", json={"config_name": "../secrets.toml"}).status_code == 422
    assert client.post("/api/runs", json={"config_name": "absent.toml"}).status_code == 404
    assert client.post("/api/runs", json={"config_name": ""}).status_code == 422


def test_saved_run_metrics_and_equity_are_visible(tmp_path: Path):
    runs = tmp_path / "runs"
    record = save_run(
        runs,
        config={"strategy": "sample"},
        price_history=pl.DataFrame({"timestamp": [1, 2], "SPY_close": [10.0, 11.0]}),
        result=pl.DataFrame(
            {"timestamp": [1, 2], "overall_growth": [1.0, 1.1]}
        ),
        metrics={"total_return": 0.1},
    )
    client = TestClient(create_app(tmp_path / "configs", runs))

    assert client.get("/api/runs").json()["runs"][0]["run_id"] == record.run_id
    assert client.get(f"/api/runs/{record.run_id}").json()["metrics"] == {
        "total_return": 0.1
    }
    assert client.get(f"/api/runs/{record.run_id}/equity").json()["growth"] == [1.0, 1.1]
    assert client.get("/api/runs/../equity").status_code == 404
    changed = client.patch(
        f"/api/runs/{record.run_id}/review", json={"state": "reviewed"}
    )
    assert changed.status_code == 200
    assert client.get(f"/api/runs/{record.run_id}").json()["review_state"] == "reviewed"
    assert client.patch(
        f"/api/runs/{record.run_id}/review", json={"state": "invalid"}
    ).status_code == 422


def test_browser_runs_configured_backtest_with_offline_provider(tmp_path: Path, monkeypatch):
    class Provider(DataProvider):
        name = "test"

        def get_history(self, tickers, timespan, from_time, to_time):
            days = [1704171600000 + i * 86_400_000 for i in range(50)]
            return {
                ticker: pl.DataFrame(
                    {"timestamp": days, "close": [float(100 + i) for i in range(50)]}
                )
                for ticker in tickers
            }

    monkeypatch.setattr("data.factory.create_data_provider", lambda *a, **kw: Provider())
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "sample.toml").write_text(
        'tickers=["SPY","SH"]\nstart=2024-01-02\nend=2024-03-01\n'
        '[strategy]\nname="sma_crossover"\n[strategy.params]\n'
        'short_window=5\nlong_window=20\n',
        encoding="utf-8",
    )
    client = TestClient(create_app(configs, tmp_path / "runs"))

    response = client.post("/api/runs", json={"config_name": "sample.toml"})
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert len(client.get(f"/api/runs/{run_id}/equity").json()["growth"]) == 49


def test_paper_rebalance_and_csv_download(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "configs", tmp_path / "runs"))
    payload = {
        "target_weights": {"A": 0.5, "B": 0.5},
        "prices": {"A": 10.0, "B": 20.0},
        "holdings": {"A": 1},
        "cash": 90.0,
        "cost_bps": 0.0,
    }
    result = client.post("/api/paper-rebalance", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["ending_cash"] == pytest.approx(10.0)
    assert {row["ticker"] for row in result.json()["trades"]} == {"A", "B"}
    download = client.post("/api/paper-rebalance.csv", json=payload)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert "ticker,current_shares,target_shares" in download.text
    assert client.post("/api/paper-rebalance", json={**payload, "cash": -1}).status_code == 422


def test_scenario_comparison_rejects_invalid_weights(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "configs", tmp_path / "runs"))
    payload = {
        "portfolios": {"balanced": {"A": 0.6, "B": 0.4}},
        "shocks": {"selloff": {"A": -0.2, "B": 0.05}},
    }
    response = client.post("/api/scenarios", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["portfolio_shock"] == pytest.approx(-0.1)
    assert client.post(
        "/api/scenarios", json={**payload, "portfolios": {"bad": {"A": 2.0}}}
    ).status_code == 400


def test_compare_saved_run_portfolios(tmp_path: Path):
    runs = tmp_path / "runs"
    record = save_run(
        runs,
        config={"strategy": "sample"},
        price_history=pl.DataFrame(
            {
                "timestamp": [1, 2, 3],
                "A_close": [100.0, 110.0, 100.0],
                "B_close": [100.0, 101.0, 103.0],
            }
        ),
        result=pl.DataFrame(
            {"timestamp": [1, 2, 3], "overall_growth": [1.0, 1.1, 1.0]}
        ),
        metrics={"total_return": 0.0},
    )
    client = TestClient(create_app(tmp_path / "configs", runs))
    response = client.post(
        f"/api/runs/{record.run_id}/compare",
        json={"benchmark": "A", "portfolios": {"defensive": {"B": 1.0}}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["portfolio"] == "defensive"
    assert response.json()["results"][0]["observations"] == 2


def test_local_app_rejects_hostile_host_and_cross_origin_mutation(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "configs", tmp_path / "runs"))
    assert client.get("/api/configs", headers={"Host": "attacker.example"}).status_code == 400
    assert client.post(
        "/api/paper-rebalance", headers={"Origin": "https://attacker.example"}, json={}
    ).status_code == 403
