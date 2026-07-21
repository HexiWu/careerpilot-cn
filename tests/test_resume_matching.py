from careerpilot.matching import match_job, rank_jobs
from careerpilot.models import JobPosting, SourceKind
from careerpilot.resume import parse_resume_text

RESUME = """吴和熹
教育经历
卡耐基梅隆大学 信息系统管理硕士 01/2026
实习经历
Shopee  数据开发实习生 05/2025-08/2025
- 使用 Airflow 完成270个任务迁移，使用 SQL 验证数据一致性
- 使用 Spark 和 Python 处理数据管道
技能
Python, Java, SQL, Airflow, Spark, AWS, Docker, Redis
"""


def make_job(title: str, skills: list[str]) -> JobPosting:
    return JobPosting(
        external_id=title,
        company_name="示例公司",
        title=title,
        location="上海",
        requirements="硕士或本科，熟悉" + "、".join(skills),
        skills=skills,
        source_url=f"https://careers.example.com/{title}",
        source_kind=SourceKind.OFFICIAL_SUBDOMAIN,
    )


def test_resume_profile_infers_skills_and_roles():
    profile = parse_resume_text(RESUME)
    assert {"Python", "SQL", "Airflow", "Spark"}.issubset(profile.skills)
    assert "数据工程师" in profile.target_roles
    assert profile.education[0].degree == "硕士"


def test_explainable_matching_prefers_data_job():
    profile = parse_resume_text(RESUME)
    data_job = make_job("数据工程师", ["Python", "SQL", "Airflow", "Spark"])
    design_job = make_job("视觉设计师", [])

    ranked = rank_jobs(profile, [design_job, data_job])

    assert ranked[0].job.title == "数据工程师"
    assert ranked[0].score > ranked[1].score
    assert any("Airflow" in evidence for evidence in ranked[0].matched_evidence)
    assert match_job(profile, data_job).confidence > 0.5
