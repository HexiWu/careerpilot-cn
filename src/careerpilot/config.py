from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    sync_interval_hours: int = 4
    request_timeout: float = 20.0
    user_agent: str = "CareerPilotCN/0.1 (+local portfolio project)"
    max_companies_per_sync: int = 50
    scheduler_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_path=Path(os.getenv("CAREERPILOT_DATABASE", "data/careerpilot.db")),
            sync_interval_hours=int(os.getenv("CAREERPILOT_SYNC_INTERVAL_HOURS", "4")),
            request_timeout=float(os.getenv("CAREERPILOT_REQUEST_TIMEOUT", "20")),
            user_agent=os.getenv(
                "CAREERPILOT_USER_AGENT", "CareerPilotCN/0.1 (+local portfolio project)"
            ),
            max_companies_per_sync=int(os.getenv("CAREERPILOT_MAX_COMPANIES_PER_SYNC", "50")),
            scheduler_enabled=os.getenv("CAREERPILOT_SCHEDULER_ENABLED", "true").lower()
            in {"1", "true", "yes"},
        )


settings = Settings.from_env()
