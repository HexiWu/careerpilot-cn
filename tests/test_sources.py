from pathlib import Path

from careerpilot.models import Company, SourceKind
from careerpilot.sources import CareerSiteDiscoverer, OfficialCareerParser, PublicPageGuard

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
