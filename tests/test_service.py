from pathlib import Path

from pytest import MonkeyPatch

from careerpilot.config import Settings
from careerpilot.models import ResumeProfile
from careerpilot.service import CareerPilotService


def test_dashboard_recommendations_reads_full_active_corpus(
    tmp_path: Path, monkeypatch: MonkeyPatch
):
    service = CareerPilotService(
        Settings(database_path=tmp_path / "service.db", scheduler_enabled=False)
    )
    requested: dict[str, int] = {}

    def list_jobs(query: str = "", limit: int = 100):
        requested["limit"] = limit
        return []

    monkeypatch.setattr(service.db, "list_jobs", list_jobs)

    assert service.recommendations(ResumeProfile(skills=["Python"])) == []
    assert requested["limit"] == 10_000
