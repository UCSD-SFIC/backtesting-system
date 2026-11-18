"""Live smoke check against the real sources.

    python -m terminal COST AAPL

Prints a short summary per ticker so you can confirm SEC and price data load
on your machine. Needs SEC_USER_AGENT (see docs/terminal-data-api.md).
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from terminal.errors import TerminalError
from terminal.service import TerminalService


def _number(value: object) -> str:
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "n/a"


def summarize(service: TerminalService, ticker: str) -> list[str]:
    overview = service.overview(ticker)
    data, meta = overview["data"], overview["meta"]
    company, price, annual = data["company"], data["price"], data["latest_annual"]
    lines = [f"{company['ticker']}  {company['name']}  (CIK {company['cik']})"]
    if price:
        lines.append(f"  last close   {_number(price['last_close'])} on {price['last_close_date']}")
    lines.append(f"  market cap   {_number(data['market_cap']['value'])}")
    if annual:
        for key in ("revenue", "net_income", "operating_cash_flow"):
            cell = annual["metrics"][key]
            source = cell.get("source", {})
            lines.append(
                f"  {key:<20} {_number(cell['value'])}  {annual['period']}  "
                f"{source.get('form', '')} {source.get('accession', '')}".rstrip()
            )
    quarterly = service.financials(ticker, "income", "quarterly", 4)["data"]
    periods = ", ".join(period["key"] for period in quarterly["periods"])
    lines.append(f"  quarters     {periods or 'none'}")
    for source in meta["sources"]:
        state = "STALE" if source["stale"] else "ok"
        lines.append(f"  source       {source['id']}  {source['retrieved_at']}  {state}")
    for warning in meta["warnings"]:
        lines.append(f"  warning      {warning['code']}: {warning['message']}")
    return lines


def main(
    argv: list[str] | None = None,
    service_factory: Callable[[], TerminalService] = TerminalService,
) -> int:
    tickers = sys.argv[1:] if argv is None else argv
    if not tickers:
        print("usage: python -m terminal TICKER [TICKER ...]")
        return 2
    service = service_factory()
    failed = False
    for ticker in tickers:
        try:
            print("\n".join(summarize(service, ticker)))
        except TerminalError as exc:
            failed = True
            print(f"{ticker.upper()}  ERROR {exc.code}: {exc.message}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
