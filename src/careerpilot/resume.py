from __future__ import annotations

import io
import re
from pathlib import Path

import pdfplumber

from careerpilot.models import Education, Experience, ResumeProfile
from careerpilot.taxonomy import extract_skills, infer_target_roles, normalize_text

SECTION_HEADERS = (
    "教育经历",
    "实习经历",
    "工作经历",
    "项目经历",
    "技能&爱好",
    "技能",
    "education",
    "experience",
    "projects",
    "skills",
)


def extract_pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _section(text: str, names: tuple[str, ...]) -> str:
    lowered = text.lower()
    starts = [lowered.find(name.lower()) for name in names if lowered.find(name.lower()) >= 0]
    if not starts:
        return ""
    start = min(starts)
    candidates = []
    for header in SECTION_HEADERS:
        idx = lowered.find(header.lower(), start + 2)
        if idx > start:
            candidates.append(idx)
    end = min(candidates) if candidates else len(text)
    return text[start:end]


def _parse_experiences(text: str) -> list[Experience]:
    section = _section(text, ("实习经历", "工作经历", "experience"))
    if not section:
        return []
    experiences: list[Experience] = []
    current: Experience | None = None
    date_pattern = re.compile(
        r"(\d{2}/\d{4}|\d{4}[.-]\d{1,2}).{0,5}(\d{2}/\d{4}|\d{4}[.-]\d{1,2}|至今)"
    )
    for raw_line in section.splitlines()[1:]:
        line = raw_line.strip(" -•\t")
        if not line:
            continue
        date_match = date_pattern.search(line)
        if date_match and not raw_line.lstrip().startswith(("-", "•")):
            prefix = line[: date_match.start()].strip()
            parts = re.split(r"\s{2,}|\t", prefix)
            organization = parts[0] if parts else prefix
            title = parts[-1] if len(parts) > 1 else ""
            current = Experience(
                organization=organization,
                title=title,
                start_date=date_match.group(1),
                end_date=date_match.group(2),
            )
            experiences.append(current)
        elif current:
            current.highlights.append(normalize_text(line))
    return experiences


def _parse_education(text: str) -> list[Education]:
    section = _section(text, ("教育经历", "education"))
    if not section:
        return []
    schools: list[Education] = []
    for line in section.splitlines()[1:]:
        clean = normalize_text(line)
        if not clean:
            continue
        if any(token in clean for token in ("大学", "学院", "University", "College")):
            degree = "硕士" if any(x in clean for x in ("硕士", "Master")) else "学士"
            major_match = re.search(r"(计算机科学|信息系统|数据科学|软件工程)[^，,\d]{0,12}", clean)
            date_match = re.search(r"(\d{2}/\d{4}|\d{4}[.-]\d{1,2})$", clean)
            schools.append(
                Education(
                    institution=clean.split()[0],
                    degree=degree,
                    major=major_match.group(0).strip() if major_match else "",
                    graduation_date=date_match.group(1) if date_match else None,
                )
            )
    return schools


def parse_resume_text(text: str) -> ResumeProfile:
    clean = text.strip()
    first_line = next((line.strip() for line in clean.splitlines() if line.strip()), "")
    name = first_line if len(first_line) <= 20 and "@" not in first_line else ""
    skills = extract_skills(clean)
    experiences = _parse_experiences(clean)
    education = _parse_education(clean)
    role_targets = infer_target_roles(skills)
    summary_parts = []
    if education:
        summary_parts.append(f"{education[-1].degree}学历")
    if experiences:
        summary_parts.append(f"{len(experiences)}段工作或实习经历")
    if skills:
        summary_parts.append(f"核心技能：{'、'.join(skills[:8])}")
    return ResumeProfile(
        name=name,
        summary="；".join(summary_parts),
        skills=skills,
        experiences=experiences,
        education=education,
        target_roles=role_targets,
        raw_text=clean,
    )


def parse_resume_pdf(data: bytes) -> ResumeProfile:
    return parse_resume_text(extract_pdf_text(data))


def parse_resume_file(path: str | Path) -> ResumeProfile:
    return parse_resume_pdf(Path(path).read_bytes())
