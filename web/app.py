"""Local research dashboard. Run with ``uvicorn web.app:app``."""

# ruff: noqa: E501

from __future__ import annotations

import csv
import datetime as dt
import inspect
import math
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import polars as pl
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from experiments import list_runs, load_frame, load_run, save_run, set_review_state
from experiments.catalog import RunCatalog
from experiments.store import RunRecord
from paper.rebalance import rebalance
from research import compare_portfolios, historical_returns, scenario_sensitivity

Runner = Callable[[Path], str]


class RunRequest(BaseModel):
    config_name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+\.toml$")
    overrides: RunOverrides | None = None


class RunOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: dt.date | None = None
    end: dt.date | None = None
    tickers: list[str] | None = Field(default=None, min_length=1, max_length=100)
    provider: Literal["yfinance", "polygon"] | None = None
    cost_bps: float | None = Field(default=None, ge=0, le=500)
    target_weights: dict[str, float] | None = Field(default=None, min_length=1, max_length=100)
    rebalance: Literal["monthly", "quarterly"] | None = None
    strategy_params: dict[str, StrictInt] | None = Field(default=None, min_length=1, max_length=2)

    @model_validator(mode="after")
    def check_target_weights(self) -> RunOverrides:
        if self.target_weights is not None:
            _check_tickers(self.target_weights)
            if any(not math.isfinite(weight) or weight < 0 for weight in self.target_weights.values()):
                raise ValueError("target weights must be finite and nonnegative")
            if not math.isclose(sum(self.target_weights.values()), 1.0, abs_tol=1e-9):
                raise ValueError("target weights must total 100%")
        if self.strategy_params is not None and any(
            value <= 0 or value > 10_000 for value in self.strategy_params.values()
        ):
            raise ValueError("strategy parameters must be positive whole numbers up to 10000")
        return self


class ReviewRequest(BaseModel):
    state: Literal["draft", "reviewed", "superseded"]


class PaperRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    target_weights: dict[str, float] = Field(min_length=1, max_length=100)
    prices: dict[str, float] = Field(min_length=1, max_length=100)
    holdings: dict[str, int] = Field(default_factory=dict, max_length=100)
    cash: float = Field(ge=0)
    cost_bps: float = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def check_tickers(self) -> PaperRequest:
        _check_tickers(set(self.target_weights) | set(self.prices) | set(self.holdings))
        return self


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    portfolios: dict[str, dict[str, float]] = Field(min_length=1, max_length=20)
    shocks: dict[str, dict[str, float]] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_tickers(self) -> ScenarioRequest:
        for name, weights in self.portfolios.items():
            if not name or len(name) > 80 or len(weights) > 100:
                raise ValueError("invalid portfolio name or size")
            _check_tickers(weights)
        for name, shocks in self.shocks.items():
            if not name or len(name) > 80 or len(shocks) > 100:
                raise ValueError("invalid scenario name or size")
            _check_tickers(shocks)
        return self


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    benchmark: str = Field(min_length=1, max_length=16)
    portfolios: dict[str, dict[str, float]] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def check_tickers(self) -> CompareRequest:
        _check_tickers([self.benchmark])
        for name, weights in self.portfolios.items():
            if not name or len(name) > 80 or len(weights) > 100:
                raise ValueError("invalid portfolio name or size")
            _check_tickers(weights)
        return self


def _check_tickers(tickers: Iterable[str]) -> None:
    if any(not re.fullmatch(r"[A-Z0-9.^-]{1,16}", ticker) for ticker in tickers):
        raise ValueError("tickers must be uppercase symbols of at most 16 characters")


def _paper_result(request: PaperRequest):
    try:
        return rebalance(
            request.target_weights,
            request.prices,
            request.holdings,
            request.cash,
            request.cost_bps,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _load_run_config(path: Path, settings: RunOverrides | None = None):
    from pipeline.config import load_config

    if settings is None:
        return load_config(path)
    base = load_config(path)
    params = dict(base.strategy.params)
    if settings.strategy_params is not None:
        allowed = {
            "sma_crossover": {"short_window", "long_window"},
            "ema_dip": {"ema_window", "regime_window"},
        }.get(base.strategy.name, set())
        if not set(settings.strategy_params) <= allowed:
            raise ValueError("unsupported strategy parameters for this template")
        params.update(settings.strategy_params)
        window_pairs = {
            "sma_crossover": ("short_window", "long_window"),
            "ema_dip": ("ema_window", "regime_window"),
        }
        shorter, longer = window_pairs[base.strategy.name]
        from strategy.registry import STRATEGIES

        defaults = inspect.signature(STRATEGIES[base.strategy.name]).parameters
        first = params.get(shorter, defaults[shorter].default)
        second = params.get(longer, defaults[longer].default)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (first, second)
        ):
            raise ValueError("indicator windows must be positive whole numbers")
        if first >= second:
            raise ValueError(f"{shorter} must be less than {longer}")
    if settings.target_weights is not None or settings.rebalance is not None:
        if base.strategy.name != "fixed_weight":
            raise ValueError("portfolio weights and schedule require a fixed-weight config")
        if settings.target_weights is not None:
            params["weights"] = settings.target_weights
        if settings.rebalance is not None:
            params["rebalance"] = settings.rebalance
    overrides = {
        "start": settings.start, "end": settings.end, "tickers": settings.tickers,
        "data.provider": settings.provider, "execution.cost_bps": settings.cost_bps,
        "strategy.params": params,
    }
    return load_config(path, overrides)


def _default_runner(
    path: Path, runs_dir: Path, settings: RunOverrides | None = None,
    catalog_url: str | None = None,
) -> str:
    from data.factory import create_data_provider
    from engine.backtest_engine import BacktestEngine
    from engine.history import combine_ticker_histories
    from engine.weights import build_weight_frame
    from pipeline.backtest import summarize_backtest
    from strategy.registry import build_strategy

    config = _load_run_config(path, settings)
    provider = create_data_provider(
        config.data.provider,
        cache_dir=config.data.cache_dir,
        refresh_cache=config.data.refresh_cache,
        validate=config.data.validate_data,
    )
    alpha = build_strategy(
        config.strategy.name,
        config.tickers,
        config.timespan,
        config.start.isoformat(),
        config.end.isoformat(),
        config.strategy.params,
    )
    fetch_start = (config.start - alpha.warmup_period()).isoformat()
    engine = BacktestEngine(provider, cost_bps=config.execution.cost_bps)
    raw = engine.fetch_history(alpha.get_tickers(), config.timespan, fetch_start, config.end.isoformat())
    history = combine_ticker_histories(raw)
    enriched = engine.add_indicators(history, alpha)
    weights = build_weight_frame(alpha, enriched)
    result = engine.run_portfolio_backtest(enriched, weights, alpha.get_tickers())
    metrics = summarize_backtest(
        result,
        risk_free_rate=config.risk_free_rate,
        benchmark_ticker=config.benchmark or config.tickers[0],
    )
    holdings = getattr(alpha, "holdings", [])
    holdings_frame = pl.DataFrame(
        [
            {"timestamp": timestamp, "ticker": ticker, "target_weight": weight}
            for timestamp, weights in holdings
            for ticker, weight in weights.items()
        ],
        schema={"timestamp": pl.Datetime, "ticker": pl.String, "target_weight": pl.Float64},
    )
    record = save_run(
        runs_dir,
        config=config.model_dump(mode="json"),
        price_history=history,
        result=result,
        metrics=metrics,
        holdings=holdings_frame,
    )
    if catalog_url:
        with RunCatalog(catalog_url) as catalog:
            catalog.upsert(record)
    return record.run_id


def create_app(
    config_dir: str | Path = "configs",
    runs_dir: str | Path = "runs",
    *,
    runner: Runner | None = None,
    catalog_url: str | None = None,
    frontend_dir: str | Path | None = None,
) -> FastAPI:
    """Create a local dashboard with fixed config names and run IDs."""
    configs = Path(config_dir)
    runs = Path(runs_dir)
    catalog_url = catalog_url or os.getenv("BACKTEST_DATABASE_URL")
    dashboard = Path(frontend_dir) if frontend_dir is not None else (
        Path(__file__).resolve().parents[1] / "frontend" / "dist"
    )
    launch = runner or (lambda path: _default_runner(path, runs))
    app = FastAPI(title="Backtesting research", version="0.1.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    if (dashboard / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dashboard / "assets"), name="assets")

    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get("host"):
                    return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def home() -> Response:
        if (dashboard / "index.html").is_file():
            return FileResponse(dashboard / "index.html")
        return HTMLResponse(_HTML)

    @app.get("/api/configs")
    def available_configs() -> dict[str, list[str]]:
        return {"configs": sorted(path.name for path in configs.glob("*.toml") if path.is_file())}

    @app.get("/api/configs/{config_name}")
    def config_detail(config_name: str) -> dict[str, object]:
        if config_name not in available_configs()["configs"]:
            raise HTTPException(404, "Unknown configuration")
        try:
            config = _load_run_config(configs / config_name)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(400, "Configuration is invalid") from exc
        return {"config": config.model_dump(mode="json")}

    @app.post("/api/runs")
    def run_backtest(request: RunRequest) -> dict[str, str]:
        if request.config_name not in available_configs()["configs"]:
            raise HTTPException(404, "Unknown configuration")
        try:
            run_id = (
                launch(configs / request.config_name)
                if runner is not None
                else _default_runner(
                    configs / request.config_name, runs, request.overrides, catalog_url
                )
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(400, "Configuration or market data is invalid") from exc
        return {"run_id": run_id}

    @app.get("/api/runs")
    def saved_runs() -> dict[str, list[dict[str, object]]]:
        return {"runs": [_record_view(record) for record in list_runs(runs)]}

    @app.get("/api/runs/{run_id}")
    def saved_run(run_id: str) -> dict[str, object]:
        try:
            return _record_view(load_run(runs, run_id))
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Run not found") from exc

    @app.get("/api/runs/{run_id}/equity")
    def equity(run_id: str) -> dict[str, list[object]]:
        try:
            frame = load_frame(load_run(runs, run_id), "result")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Run not found") from exc
        return {
            "timestamps": [str(value) for value in frame["timestamp"].to_list()],
            "growth": frame["overall_growth"].to_list(),
        }

    @app.get("/api/runs/{run_id}/paper-input")
    def paper_input(run_id: str) -> dict[str, object]:
        try:
            record = load_run(runs, run_id)
            holdings = load_frame(record, "holdings")
            history = load_frame(record, "price_history")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Run or holdings not found") from exc
        if holdings.is_empty():
            raise HTTPException(400, "Run has no target holdings")
        last_date = holdings["timestamp"].max()
        latest = holdings.filter(pl.col("timestamp") == last_date)
        weights = dict(zip(latest["ticker"].to_list(), latest["target_weight"].to_list(), strict=True))
        final_prices = history.sort("timestamp").tail(1).to_dicts()[0]
        prices = {
            column.removesuffix("_close"): value
            for column, value in final_prices.items()
            if column.endswith("_close") and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0
        }
        if any(ticker not in prices for ticker in weights):
            raise HTTPException(400, "Latest price missing for a target holding")
        return {"target_weights": weights, "prices": prices,
                "as_of": str(final_prices["timestamp"])}

    @app.patch("/api/runs/{run_id}/review")
    def review(run_id: str, request: ReviewRequest) -> dict[str, object]:
        try:
            record = set_review_state(runs, run_id, request.state)
            if catalog_url:
                with RunCatalog(catalog_url) as catalog:
                    catalog.upsert(record)
            return _record_view(record)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Run not found") from exc

    @app.post("/api/paper-rebalance")
    def paper_rebalance(request: PaperRequest) -> dict[str, object]:
        return asdict(_paper_result(request))

    @app.post("/api/paper-rebalance.csv")
    def paper_csv(request: PaperRequest) -> Response:
        result = _paper_result(request)
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            ("ticker", "current_shares", "target_shares", "delta_shares", "price", "estimated_cost")
        )
        for trade in result.trades:
            writer.writerow(
                (trade.ticker, trade.current_shares, trade.target_shares,
                 trade.delta_shares, trade.price, trade.estimated_cost)
            )
        return Response(
            stream.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="paper-rebalance.csv"'},
        )

    @app.post("/api/scenarios")
    def scenarios(request: ScenarioRequest) -> dict[str, list[dict[str, object]]]:
        try:
            rows = scenario_sensitivity(request.portfolios, request.shocks).to_dicts()
        except ValueError as exc:
            raise HTTPException(400, "Invalid scenario assumptions") from exc
        return {"results": rows}

    @app.post("/api/runs/{run_id}/compare")
    def compare(run_id: str, request: CompareRequest) -> dict[str, list[dict[str, object]]]:
        try:
            history = load_frame(load_run(runs, run_id), "price_history")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Run not found") from exc
        close_columns = [column for column in history.columns if column.endswith("_close")]
        if not close_columns:
            raise HTTPException(400, "Saved run has no price history")
        prices = history.select("timestamp", *close_columns).unpivot(
            on=close_columns, index="timestamp", variable_name="ticker", value_name="close"
        ).with_columns(pl.col("ticker").str.strip_suffix("_close"))
        try:
            rows = compare_portfolios(
                historical_returns(prices), request.portfolios, request.benchmark
            ).to_dicts()
        except ValueError as exc:
            raise HTTPException(400, "Invalid portfolio comparison") from exc
        return {"results": rows}

    return app


def _record_view(record: RunRecord) -> dict[str, object]:
    return {
        "run_id": record.run_id,
        "created_at": record.created_at,
        "review_state": record.review_state,
        "config": record.config,
        "metrics": record.metrics,
    }


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtesting research</title><style>
body{font:16px system-ui;background:#f4f5f2;color:#173026;margin:0;padding:2rem;max-width:960px;margin:auto}
header{margin-bottom:2rem}h1{font-size:2rem}main{display:grid;gap:1.5rem}
section{background:white;padding:1.5rem;border-radius:12px;box-shadow:0 1px 5px #0001}
button,select{font:inherit;padding:.65rem;border-radius:6px}button{background:#145841;color:white;border:0;cursor:pointer}
button:disabled{opacity:.5}#status{min-height:1.5rem}canvas{width:100%;height:250px}
li{margin:.5rem 0}a{color:#145841}
</style></head><body><header><h1>Portfolio research</h1><p>Run historical strategies and review saved results.</p></header>
<main><section><h2>New backtest</h2><label for="config">Configuration</label>
<select id="config"></select> <button id="run">Run backtest</button><p id="status" role="status"></p></section>
<section><h2>Saved runs</h2><ul id="runs"></ul></section>
<section><h2>Results</h2><div id="metrics"></div><canvas id="equity" width="900" height="250" aria-label="Equity curve"></canvas><p><label for="review">Review state</label> <select id="review"><option>draft</option><option>reviewed</option><option>superseded</option></select> <button id="save-review">Save review</button></p></section>
<section><h2>Paper rebalance</h2><p>Enter target weights, latest prices, and current paper holdings as JSON objects.</p>
<label>Target weights<br><textarea id="weights" rows="3">{"SPY":0.6,"SH":0.4}</textarea></label>
<label>Latest prices<br><textarea id="prices" rows="3">{"SPY":100,"SH":50}</textarea></label>
<label>Current shares<br><textarea id="holdings" rows="3">{"SPY":0,"SH":0}</textarea></label>
<label>Available cash <input id="cash" type="number" min="0" step="0.01" value="10000"></label>
<label>Cost (basis points) <input id="cost" type="number" min="0" max="10000" step="0.1" value="0"></label>
<button id="rebalance">Calculate</button> <button id="download">Download CSV</button><pre id="paper-result"></pre></section>
<section><h2>Scenario comparison</h2><p>Assumed one-period returns, such as -0.2 for a 20% decline.</p>
<label>Portfolio weights<br><textarea id="portfolios" rows="3">{"balanced":{"SPY":0.6,"SH":0.4}}</textarea></label>
<label>Scenario shocks<br><textarea id="shocks" rows="3">{"selloff":{"SPY":-0.2,"SH":0.05}}</textarea></label>
<button id="scenario">Compare scenarios</button><pre id="scenario-result"></pre>
<p><label>Benchmark ticker <input id="benchmark" value="SPY"></label> <button id="compare">Compare with saved history</button></p><pre id="compare-result"></pre></section></main>
<script>
const config=document.querySelector('#config'), status=document.querySelector('#status'), run=document.querySelector('#run');
let selectedRun=null;
async function json(url,options){const response=await fetch(url,options);if(!response.ok)throw Error((await response.json()).detail||'Request failed');return response.json()}
function renderCurve(values){const c=document.querySelector('#equity'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
if(values.length<2)return;const lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
ctx.strokeStyle='#145841';ctx.lineWidth=2;ctx.beginPath();values.forEach((v,i)=>{const x=i/(values.length-1)*(c.width-20)+10,y=c.height-10-(v-lo)/span*(c.height-20);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y)});ctx.stroke()}
async function showRun(id){const [record,curve]=await Promise.all([json('/api/runs/'+encodeURIComponent(id)),json('/api/runs/'+encodeURIComponent(id)+'/equity')]);selectedRun=id;document.querySelector('#review').value=record.review_state;
const area=document.querySelector('#metrics');area.replaceChildren();for(const [key,value] of Object.entries(record.metrics)){const p=document.createElement('p');p.textContent=key.replaceAll('_',' ')+': '+(typeof value==='number'?value.toFixed(3):value);area.append(p)}renderCurve(curve.growth)}
async function refresh(){const data=await json('/api/runs');const list=document.querySelector('#runs');list.replaceChildren();for(const record of data.runs){const li=document.createElement('li'),a=document.createElement('a');a.href='#';a.textContent=record.run_id+' · '+record.review_state;a.onclick=e=>{e.preventDefault();showRun(record.run_id).catch(err=>status.textContent=err.message)};li.append(a);list.append(li)}}
run.onclick=async()=>{run.disabled=true;status.textContent='Running…';try{const result=await json('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config_name:config.value})});status.textContent='Saved '+result.run_id;await refresh();await showRun(result.run_id)}catch(err){status.textContent=err.message}finally{run.disabled=false}};
document.querySelector('#save-review').onclick=async()=>{if(!selectedRun)return;try{await json('/api/runs/'+encodeURIComponent(selectedRun)+'/review',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({state:document.querySelector('#review').value})});status.textContent='Review state saved';await refresh()}catch(err){status.textContent=err.message}};
function paperPayload(){return {target_weights:JSON.parse(document.querySelector('#weights').value),prices:JSON.parse(document.querySelector('#prices').value),holdings:JSON.parse(document.querySelector('#holdings').value),cash:Number(document.querySelector('#cash').value),cost_bps:Number(document.querySelector('#cost').value)}}
document.querySelector('#rebalance').onclick=async()=>{const out=document.querySelector('#paper-result');try{out.textContent=JSON.stringify(await json('/api/paper-rebalance',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(paperPayload())}),null,2)}catch(err){out.textContent=err.message}};
document.querySelector('#download').onclick=async()=>{const out=document.querySelector('#paper-result');try{const response=await fetch('/api/paper-rebalance.csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(paperPayload())});if(!response.ok)throw Error('Could not create CSV');const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='paper-rebalance.csv';a.click();URL.revokeObjectURL(url)}catch(err){out.textContent=err.message}};
document.querySelector('#scenario').onclick=async()=>{const out=document.querySelector('#scenario-result');try{const payload={portfolios:JSON.parse(document.querySelector('#portfolios').value),shocks:JSON.parse(document.querySelector('#shocks').value)};out.textContent=JSON.stringify(await json('/api/scenarios',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),null,2)}catch(err){out.textContent=err.message}};
document.querySelector('#compare').onclick=async()=>{const out=document.querySelector('#compare-result');if(!selectedRun){out.textContent='Select a saved run first';return}try{const payload={portfolios:JSON.parse(document.querySelector('#portfolios').value),benchmark:document.querySelector('#benchmark').value};out.textContent=JSON.stringify(await json('/api/runs/'+encodeURIComponent(selectedRun)+'/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),null,2)}catch(err){out.textContent=err.message}};
json('/api/configs').then(data=>{for(const name of data.configs){const option=document.createElement('option');option.textContent=name;option.value=name;config.append(option)}}).catch(err=>status.textContent=err.message);
refresh().catch(err=>status.textContent=err.message);
</script></body></html>"""


app = create_app()
