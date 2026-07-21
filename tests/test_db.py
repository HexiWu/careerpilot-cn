from pathlib import Path

from careerpilot.db import Database
from careerpilot.models import JobPosting, SourceKind


def test_upsert_and_query_job(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    job = JobPosting(
        external_id="abc",
        company_name="示例科技",
        title="数据工程师",
        location="上海",
        description="建设数据平台",
        source_url="https://careers.example.com/jobs/abc",
        source_kind=SourceKind.OFFICIAL_SUBDOMAIN,
    )

    job_id, state = db.upsert_job(job)
    second_id, second_state = db.upsert_job(job)

    assert state == "created"
    assert second_state == "unchanged"
    assert job_id == second_id
    assert db.list_jobs("数据")[0].company_name == "示例科技"
