"""HTTP endpoints for the research terminal. See docs/terminal-data-api.md.

    GET /api/companies?q=cost                      company / ticker search
    GET /api/companies/{ticker}                    overview
    GET /api/companies/{ticker}/prices             daily price history
    GET /api/companies/{ticker}/financials         normalized statements
    GET /api/financial-metrics                     metric definitions

Success responses are `{"data": ..., "meta": ...}`. Errors are
`{"detail": "<message>", "code": "<machine code>"}` with a matching status.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from terminal.errors import TerminalError
from terminal.service import TerminalService

ServiceFactory = Callable[[], TerminalService]
PriceRange = Literal["1m", "3m", "6m", "1y", "3y", "5y", "max"]


def install_terminal_api(app: FastAPI, service_factory: ServiceFactory | None = None) -> None:
    """Add the terminal routes and error format to `app`.

    The service is created on first use, so importing the app never touches
    the network, the database, or the environment.
    """
    factory = service_factory or TerminalService
    lock = threading.Lock()
    holder: list[TerminalService] = []

    def service() -> TerminalService:
        with lock:
            if not holder:
                holder.append(factory())
            return holder[0]

    @app.exception_handler(TerminalError)
    async def terminal_error(_request: Request, exc: TerminalError) -> JSONResponse:
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(max(1, round(exc.retry_after)))
        return JSONResponse(
            {"detail": exc.message, "code": exc.code}, status_code=exc.status_code, headers=headers
        )

    router = APIRouter(prefix="/api", tags=["research terminal"])

    @router.get("/financial-metrics")
    def financial_metrics() -> dict[str, Any]:
        return service().metric_definitions()

    @router.get("/companies")
    def search_companies(
        q: str = Query(min_length=1, max_length=64),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict[str, Any]:
        return service().search(q, limit)

    @router.get("/companies/{ticker}")
    def company_overview(ticker: str) -> dict[str, Any]:
        return service().overview(ticker)

    @router.get("/companies/{ticker}/prices")
    def company_prices(ticker: str, range: PriceRange = "1y") -> dict[str, Any]:  # noqa: A002
        return service().prices(ticker, range)

    @router.get("/companies/{ticker}/financials")
    def company_financials(
        ticker: str,
        statement: Literal["income", "balance", "cash_flow"] = "income",
        period: Literal["annual", "quarterly"] = "annual",
        limit: int | None = Query(default=None, ge=1, le=40),
    ) -> dict[str, Any]:
        return service().financials(ticker, statement, period, limit)

    app.include_router(router)
