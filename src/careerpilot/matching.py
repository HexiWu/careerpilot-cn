from __future__ import annotations

import math
import re

from careerpilot.models import JobPosting, JobRecommendation, MatchBreakdown, ResumeProfile
from careerpilot.taxonomy import extract_skills

ROLE_SYNONYMS = {
    "数据工程师": ("数据开发", "大数据开发", "数仓", "etl", "数据平台"),
    "后端开发工程师": ("后端", "服务端", "python开发", "java开发"),
    "推荐算法工程师": ("推荐", "搜索算法", "广告算法"),
    "机器学习平台工程师": ("机器学习平台", "mlops", "ai平台"),
    "数据分析师": ("数据分析", "商业分析", "bi"),
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _title_alignment(profile: ResumeProfile, title: str) -> float:
    lowered = title.lower()
    for role in profile.target_roles:
        candidates = (role, *ROLE_SYNONYMS.get(role, ()))
        if any(
            candidate.lower() in lowered or lowered in candidate.lower() for candidate in candidates
        ):
            return 100.0
    return 25.0 if any(token in lowered for token in ("数据", "开发", "算法", "分析")) else 0.0


def _eligibility(profile: ResumeProfile, job: JobPosting) -> tuple[float, list[str]]:
    risks: list[str] = []
    text = f"{job.education_required} {job.experience_required} {job.requirements}".lower()
    score = 100.0
    has_master = any(edu.degree == "硕士" for edu in profile.education)
    if "硕士" in text and not has_master:
        score -= 50
        risks.append("岗位要求硕士学历，简历未识别到硕士学历")
    years = [int(x) for x in re.findall(r"(\d+)\s*年", text)]
    if years and max(years) >= 3 and len(profile.experiences) < 3:
        score -= 35
        risks.append(f"岗位可能要求{max(years)}年以上经验，当前经历以实习为主")
    if any(token in text for token in ("博士", "phd")):
        score -= 60
        risks.append("岗位可能要求博士学历")
    return _clamp(score), risks


def match_job(profile: ResumeProfile, job: JobPosting) -> JobRecommendation:
    job_text = " ".join([job.title, job.description, job.requirements, " ".join(job.skills)])
    required_skills = set(job.skills or extract_skills(job_text))
    profile_skills = set(profile.skills)
    matched = sorted(required_skills & profile_skills)
    missing = sorted(required_skills - profile_skills)
    skill_score = 60.0 if not required_skills else 100 * len(matched) / len(required_skills)

    resume_evidence = " ".join(
        highlight for exp in profile.experiences for highlight in exp.highlights
    ).lower()
    keyword_hits = sum(1 for skill in matched if skill.lower() in resume_evidence)
    experience_score = _clamp(45 + 15 * min(keyword_hits, 3) + 5 * len(profile.experiences))
    project_score = _clamp(40 + 8 * len(matched))
    direction_score = _title_alignment(profile, job.title)
    eligibility_score, risks = _eligibility(profile, job)
    location_score = (
        100.0
        if not profile.preferred_cities or any(c in job.location for c in profile.preferred_cities)
        else 45.0
    )
    industry_score = 75.0
    growth_score = (
        80.0 if any(x in job_text.lower() for x in ("平台", "架构", "agent", "ai")) else 65.0
    )

    breakdown = MatchBreakdown(
        skills=skill_score,
        experience=experience_score,
        projects=project_score,
        direction=direction_score,
        eligibility=eligibility_score,
        industry=industry_score,
        location=location_score,
        growth=growth_score,
    )
    weighted = (
        skill_score * 0.25
        + experience_score * 0.20
        + project_score * 0.15
        + direction_score * 0.15
        + eligibility_score * 0.10
        + industry_score * 0.05
        + location_score * 0.05
        + growth_score * 0.05
    )
    evidence = [f"简历与岗位共同包含技能：{skill}" for skill in matched]
    evidence.extend(
        f"经历证据：{highlight}"
        for exp in profile.experiences
        for highlight in exp.highlights
        if any(skill.lower() in highlight.lower() for skill in matched)
    )
    confidence = 1 - math.exp(-max(len(required_skills), 1) / 4)
    rationale = (
        f"岗位方向匹配度{direction_score:.0f}，技能覆盖{skill_score:.0f}，"
        f"共识别{len(matched)}项匹配技能和{len(risks)}项资格风险。"
    )
    return JobRecommendation(
        job=job,
        score=round(_clamp(weighted), 1),
        confidence=round(min(confidence, 0.98), 2),
        breakdown=breakdown,
        matched_evidence=evidence[:8],
        missing_skills=missing[:8],
        risks=risks,
        rationale=rationale,
    )


def rank_jobs(profile: ResumeProfile, jobs: list[JobPosting]) -> list[JobRecommendation]:
    return sorted(
        (match_job(profile, job) for job in jobs), key=lambda item: item.score, reverse=True
    )
