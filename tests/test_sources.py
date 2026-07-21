from pathlib import Path

import httpx
import pytest

from careerpilot.adapters import TencentCareerAdapter
from careerpilot.models import Company, SourceKind
from careerpilot.sources import (
    CareerSiteDiscoverer,
    OfficialCareerParser,
    PublicPageGuard,
)

FIXTURES = Path(__file__).parent / "fixtures"


def company() -> Company:
    return Company(
        name="示例科技",
        homepage_url="https://www.example.com/",
        career_urls=["https://careers.example.com/jobs"],
    )


def test_discovers_official_career_link():
    content = (FIXTURES / "company_home.html").read_text()
    urls = CareerSiteDiscoverer().discover_from_html("https://www.example.com/", content)
    assert urls == ["https://careers.example.com/jobs"]


def test_parses_json_ld_job_with_evidence():
    content = (FIXTURES / "official_jobs.html").read_text()
    jobs = OfficialCareerParser().parse(company(), "https://careers.example.com/jobs", content)
    assert len(jobs) == 1
    assert jobs[0].title == "数据工程师"
    assert jobs[0].location == "上海"
    assert {"Python", "Spark", "SQL", "Airflow", "Docker"}.issubset(jobs[0].skills)
    assert jobs[0].source_kind == SourceKind.OFFICIAL_SUBDOMAIN
    assert str(jobs[0].source_url) == "https://careers.example.com/jobs/DE-001"


def test_guard_detects_login_or_captcha():
    assert PublicPageGuard.is_restricted_page("请登录后查看，请输入验证码")
    assert not PublicPageGuard.is_restricted_page("公开招聘职位列表")


def test_parser_skips_non_http_share_links():
    content = '<a href="mailto:?body=https://example.com/jobs/1">Share job by email</a>'
    assert OfficialCareerParser().parse(company(), "https://careers.example.com", content) == []


@pytest.mark.asyncio
async def test_tencent_adapter_maps_public_official_api():
    payload = {
        "Code": 200,
        "Data": {
            "Posts": [
                {
                    "PostId": "2046210923894571008",
                    "RecruitPostName": "大模型 Agent 研发工程师",
                    "LocationName": "深圳",
                    "BGName": "WXG",
                    "ProductName": "微信",
                    "CategoryName": "技术",
                    "Responsibility": "使用 Python、Docker 构建智能体评测基座",
                    "Requirement": "熟悉 SQL 与机器学习",
                    "RequireWorkYearsName": "两年以上工作经验",
                    "LastUpdateTime": "2026年07月21日",
                    "PostURL": "http://careers.tencent.com/jobdesc.html?postId=2046210923894571008",
                }
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["language"] == "zh-cn"
        return httpx.Response(200, json=payload)

    company = Company(
        name="腾讯",
        homepage_url="https://www.tencent.com/",
        career_urls=["https://careers.tencent.com/"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs, health = await TencentCareerAdapter().fetch(client, company)

    assert health.status == "healthy"
    assert health.jobs_found == 1
    assert jobs[0].external_id == "2046210923894571008"
    assert jobs[0].source_kind == SourceKind.OFFICIAL_SUBDOMAIN
    assert str(jobs[0].source_url).startswith("https://careers.tencent.com/")
    assert {"Python", "Docker", "SQL"}.issubset(jobs[0].skills)
