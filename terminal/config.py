"""Settings for the research-terminal data backend.

Everything has a default except `SEC_USER_AGENT`, which the SEC requires on
every request: a name plus a contact email, e.g.
`SFIC Research Terminal yourname@ucsd.edu`. Put it in `.env` (ignored by Git).
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from terminal.errors import ConfigurationError


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str | None = None
    data_dir: Path = Path("terminal_data")
    database_url: str | None = None
    price_provider: str = "yfinance"
    # The SEC allows 10 requests/second per client; stay well under it.
    sec_requests_per_second: float = 5.0
    # How long a cached copy is served before we ask the source again.
    directory_ttl: dt.timedelta = field(default=dt.timedelta(days=1))
    company_facts_ttl: dt.timedelta = field(default=dt.timedelta(hours=12))
    submissions_ttl: dt.timedelta = field(default=dt.timedelta(hours=1))
    price_ttl: dt.timedelta = field(default=dt.timedelta(minutes=30))
    price_history_years: int = 10

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        data_dir = Path(os.getenv("TERMINAL_DATA_DIR", "terminal_data"))
        return cls(
            sec_user_agent=os.getenv("SEC_USER_AGENT") or None,
            data_dir=data_dir,
            database_url=os.getenv("TERMINAL_DATABASE_URL") or None,
            price_provider=os.getenv("TERMINAL_PRICE_PROVIDER", "yfinance"),
        )

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'terminal.sqlite3'}"

    def require_sec_user_agent(self) -> str:
        agent = (self.sec_user_agent or "").strip()
        if "@" not in agent:
            raise ConfigurationError(
                "SEC_USER_AGENT is not set. The SEC requires a name and contact email on "
                "every request, for example: SEC_USER_AGENT='SFIC Research Terminal "
                "yourname@ucsd.edu'. Add it to .env and restart."
            )
        return agent
