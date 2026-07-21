from pathlib import Path

import pytest

from careerpilot.agents import WorkflowState, build_supervisor
from careerpilot.db import Database
from careerpilot.models import Company, JobPosting, SourceHealth, SourceKind
from careerpilot.resume import parse_resume_text


@pytest.mark.asyncio
async def test_multi_agent_workflow_persists_and_ranks_jobs(tmp_path: Path):
    db = Database(tmp_path / "agents.db")
    db.initialize()
    profile = parse_resume_text(
        """候选人\n教育经历\n示例大学 信息系统硕士 01/2026\n"
        "实习经历\n示例公司  数据开发实习生 01/2025-06/2025\n"
        "- 使用 Python、SQL、Spark、Airflow 建设数据平台\n技能\nPython SQL Spark Airflow Docker"""
    )
    company = Company(
        name="示例科技",
        homepage_url="https://example.com",
        career_urls=["https://careers.example.com"],
    )

    async def fake_sync(selected: Company):
        return (
            [
                JobPosting(
                    external_id="1",
                    company_name=selected.name,
                    title="数据工程师",
                    location="上海",
                    requirements="熟悉 Python SQL Spark Airflow",
                    skills=["Python", "SQL", "Spark", "Airflow"],
                    source_url="https://careers.example.com/jobs/1",
                    source_kind=SourceKind.OFFICIAL_SUBDOMAIN,
                    source_evidence="官网招聘入口",
                )
            ],
            [
                SourceHealth(
                    company_name=selected.name,
                    url="https://careers.example.com",
                    status="healthy",
                    jobs_found=1,
                )
            ],
        )

    supervisor = build_supervisor(db, sync_company=fake_sync)
    state = await supervisor.run(WorkflowState(profile=profile, companies=[company]))

    assert state.recommendations[0].job.title == "数据工程师"
    assert state.recommendations[0].matched_evidence
    assert db.list_jobs()[0].company_name == "示例科技"
    events = db.list_events(state.run_id)
    assert {event["agent"] for event in events} >= {
        "supervisor",
        "resume_profiler",
        "career_browser",
        "matching",
        "verification",
        "decision",
    }
    assert events[-1]["event_type"] == "run_completed"
