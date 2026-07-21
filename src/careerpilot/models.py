from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, computed_field


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceKind(StrEnum):
    OFFICIAL_DOMAIN = "official_domain"
    OFFICIAL_SUBDOMAIN = "official_subdomain"
    AUTHORIZED_ATS = "authorized_ats"
    OFFICIAL_REDIRECT = "official_redirect"
    UNVERIFIED = "unverified"


class JobStatus(StrEnum):
    ACTIVE = "active"
    SUSPECTED_CLOSED = "suspected_closed"
    CLOSED = "closed"


class ApplicationStatus(StrEnum):
    RECOMMENDED = "recommended"
    SAVED = "saved"
    PREPARING = "preparing"
    APPLIED = "applied"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    CLOSED = "closed"


class Experience(BaseModel):
    organization: str = ""
    title: str = ""
    start_date: str | None = None
    end_date: str | None = None
    highlights: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str = ""
    degree: str = ""
    major: str = ""
    graduation_date: str | None = None


class ResumeProfile(BaseModel):
    id: int | None = None
    name: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    preferred_cities: list[str] = Field(default_factory=list)
    raw_text: str = Field(default="", exclude=True)
    created_at: datetime = Field(default_factory=utc_now)


class Company(BaseModel):
    id: int | None = None
    name: str
    aliases: list[str] = Field(default_factory=list)
    homepage_url: HttpUrl
    career_urls: list[HttpUrl] = Field(default_factory=list)
    industry: str = "technology"
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True


class JobPosting(BaseModel):
    id: int | None = None
    external_id: str = ""
    company_name: str
    title: str
    location: str = ""
    department: str = ""
    employment_type: str = ""
    recruitment_type: str = ""
    experience_required: str = ""
    education_required: str = ""
    description: str = ""
    requirements: str = ""
    skills: list[str] = Field(default_factory=list)
    source_url: HttpUrl
    apply_url: HttpUrl | None = None
    source_kind: SourceKind = SourceKind.UNVERIFIED
    source_evidence: str = ""
    published_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    status: JobStatus = JobStatus.ACTIVE
    content_hash: str = ""

    @computed_field
    @property
    def fingerprint(self) -> str:
        raw = "|".join(
            [self.company_name.lower(), self.title.lower(), self.location.lower(), self.external_id]
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    def ensure_content_hash(self) -> JobPosting:
        if not self.content_hash:
            raw = "|".join([self.title, self.description, self.requirements, self.location])
            self.content_hash = sha256(raw.encode("utf-8")).hexdigest()
        return self


class MatchBreakdown(BaseModel):
    skills: float = 0
    experience: float = 0
    projects: float = 0
    direction: float = 0
    eligibility: float = 0
    industry: float = 0
    location: float = 0
    growth: float = 0


class JobRecommendation(BaseModel):
    job: JobPosting
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    breakdown: MatchBreakdown
    matched_evidence: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    rationale: str = ""


class AgentEvent(BaseModel):
    run_id: str
    agent: str
    event_type: str
    status: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SourceHealth(BaseModel):
    company_name: str
    url: str
    status: str
    jobs_found: int = 0
    error: str = ""
    checked_at: datetime = Field(default_factory=utc_now)
