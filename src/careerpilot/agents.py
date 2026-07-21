from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from careerpilot.companies import DEFAULT_COMPANIES
from careerpilot.db import Database
from careerpilot.matching import rank_jobs
from careerpilot.models import (
    AgentEvent,
    Company,
    JobPosting,
    JobRecommendation,
    ResumeProfile,
    SourceHealth,
    SourceKind,
)
from careerpilot.sources import OfficialCareerSync


@dataclass(slots=True)
class WorkflowState:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    profile: ResumeProfile | None = None
    companies: list[Company] = field(default_factory=list)
    discovered_jobs: list[JobPosting] = field(default_factory=list)
    persisted_jobs: list[JobPosting] = field(default_factory=list)
    recommendations: list[JobRecommendation] = field(default_factory=list)
    source_health: list[SourceHealth] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


class Agent(Protocol):
    name: str

    async def run(self, state: WorkflowState) -> WorkflowState: ...


class Tracer:
    def __init__(self, db: Database):
        self.db = db

    def emit(
        self,
        state: WorkflowState,
        agent: str,
        event_type: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.db.save_event(
            AgentEvent(
                run_id=state.run_id,
                agent=agent,
                event_type=event_type,
                status=status,
                message=message,
                payload=payload or {},
            )
        )


class ResumeProfilerAgent:
    name = "resume_profiler"

    def __init__(self, tracer: Tracer):
        self.tracer = tracer

    async def run(self, state: WorkflowState) -> WorkflowState:
        if not state.profile:
            raise ValueError("A parsed resume profile is required")
        self.tracer.emit(
            state,
            self.name,
            "profile_ready",
            "success",
            f"生成{len(state.profile.target_roles)}个目标岗位方向",
            {"roles": state.profile.target_roles, "skills": state.profile.skills},
        )
        state.metrics["profile_skill_count"] = float(len(state.profile.skills))
        return state


class CompanyDiscoveryAgent:
    name = "company_discovery"

    def __init__(self, tracer: Tracer, max_companies: int = 50):
        self.tracer = tracer
        self.max_companies = max_companies

    async def run(self, state: WorkflowState) -> WorkflowState:
        if not state.companies:
            state.companies = sorted(
                (company for company in DEFAULT_COMPANIES if company.enabled),
                key=lambda company: company.priority,
                reverse=True,
            )[: self.max_companies]
        self.tracer.emit(
            state,
            self.name,
            "companies_selected",
            "success",
            f"选择{len(state.companies)}家中国企业官方招聘站",
            {"companies": [company.name for company in state.companies]},
        )
        state.metrics["company_count"] = float(len(state.companies))
        return state


SyncFunction = Callable[[Company], Awaitable[tuple[list[JobPosting], list[SourceHealth]]]]


class CareerBrowserAgent:
    name = "career_browser"

    def __init__(
        self,
        tracer: Tracer,
        sync_company: SyncFunction,
        concurrency: int = 5,
    ):
        self.tracer = tracer
        self.sync_company = sync_company
        self.concurrency = concurrency

    async def run(self, state: WorkflowState) -> WorkflowState:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def one(company: Company):
            async with semaphore:
                return await self.sync_company(company)

        results = await asyncio.gather(
            *(one(company) for company in state.companies), return_exceptions=True
        )
        for company, result in zip(state.companies, results, strict=True):
            if isinstance(result, BaseException):
                state.warnings.append(f"{company.name}采集失败：{result}")
                state.source_health.append(
                    SourceHealth(
                        company_name=company.name,
                        url=str(
                            company.career_urls[0] if company.career_urls else company.homepage_url
                        ),
                        status="error",
                        error=str(result),
                    )
                )
                continue
            jobs, health = result
            state.discovered_jobs.extend(jobs)
            state.source_health.extend(health)
        self.tracer.emit(
            state,
            self.name,
            "browser_complete",
            "success" if state.discovered_jobs else "warning",
            f"从企业官网发现{len(state.discovered_jobs)}个岗位",
            {
                "jobs": len(state.discovered_jobs),
                "healthy_sources": sum(h.status == "healthy" for h in state.source_health),
                "failed_sources": sum(h.status != "healthy" for h in state.source_health),
            },
        )
        state.metrics["jobs_discovered"] = float(len(state.discovered_jobs))
        return state


class JobParserAgent:
    name = "job_parser"

    def __init__(self, tracer: Tracer, db: Database):
        self.tracer = tracer
        self.db = db

    async def run(self, state: WorkflowState) -> WorkflowState:
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        seen: set[str] = set()
        for job in state.discovered_jobs:
            if job.fingerprint in seen:
                continue
            seen.add(job.fingerprint)
            job_id, status = self.db.upsert_job(job)
            job.id = job_id
            counts[status] += 1
            state.persisted_jobs.append(job)
        for health in state.source_health:
            self.db.save_source_health(health)
        self.tracer.emit(
            state,
            self.name,
            "jobs_persisted",
            "success",
            f"标准化并保存{len(state.persisted_jobs)}个岗位",
            counts,
        )
        state.metrics.update({f"jobs_{key}": float(value) for key, value in counts.items()})
        return state


class MatchingAgent:
    name = "matching"

    def __init__(self, tracer: Tracer):
        self.tracer = tracer

    async def run(self, state: WorkflowState) -> WorkflowState:
        if not state.profile:
            raise ValueError("Resume profile is missing")
        jobs = state.persisted_jobs or state.discovered_jobs
        state.recommendations = rank_jobs(state.profile, jobs)
        self.tracer.emit(
            state,
            self.name,
            "matching_complete",
            "success",
            f"完成{len(jobs)}个岗位的可解释匹配",
            {
                "top_score": state.recommendations[0].score if state.recommendations else 0,
                "recommendations": len(state.recommendations),
            },
        )
        return state


class VerificationAgent:
    name = "verification"

    def __init__(self, tracer: Tracer):
        self.tracer = tracer

    async def run(self, state: WorkflowState) -> WorkflowState:
        verified: list[JobRecommendation] = []
        rejected = 0
        for recommendation in state.recommendations:
            job = recommendation.job
            if not str(job.source_url).startswith("https://"):
                rejected += 1
                continue
            if job.source_kind == SourceKind.UNVERIFIED:
                recommendation.score = max(0, recommendation.score - 15)
                recommendation.risks.append("来源尚未通过企业官网域名验证")
            if not recommendation.matched_evidence:
                recommendation.confidence = min(recommendation.confidence, 0.35)
                recommendation.risks.append("缺少可定位的简历匹配证据")
            verified.append(recommendation)
        state.recommendations = sorted(verified, key=lambda item: item.score, reverse=True)
        self.tracer.emit(
            state,
            self.name,
            "verification_complete",
            "success",
            f"验证{len(verified)}个推荐，拒绝{rejected}个不安全来源",
            {"verified": len(verified), "rejected": rejected},
        )
        return state


class DecisionAgent:
    name = "decision"

    def __init__(self, tracer: Tracer, top_k: int = 30):
        self.tracer = tracer
        self.top_k = top_k

    async def run(self, state: WorkflowState) -> WorkflowState:
        state.recommendations = state.recommendations[: self.top_k]
        self.tracer.emit(
            state,
            self.name,
            "decision_ready",
            "success",
            f"生成每日最佳{len(state.recommendations)}个岗位决策列表",
            {
                "top_jobs": [
                    {"company": item.job.company_name, "title": item.job.title, "score": item.score}
                    for item in state.recommendations[:5]
                ]
            },
        )
        return state


class Supervisor:
    name = "supervisor"

    def __init__(self, tracer: Tracer, agents: list[Agent], retries: int = 1):
        self.tracer = tracer
        self.agents = agents
        self.retries = retries

    async def run(self, state: WorkflowState) -> WorkflowState:
        self.tracer.emit(state, self.name, "run_started", "running", "Agent工作流开始")
        for agent in self.agents:
            for attempt in range(self.retries + 1):
                try:
                    output = agent.run(state)
                    state = await output if inspect.isawaitable(output) else output
                    break
                except Exception as exc:
                    self.tracer.emit(
                        state,
                        agent.name,
                        "agent_error",
                        "retrying" if attempt < self.retries else "failed",
                        str(exc),
                        {"attempt": attempt + 1},
                    )
                    if attempt >= self.retries:
                        self.tracer.emit(
                            state,
                            self.name,
                            "run_failed",
                            "failed",
                            f"{agent.name}失败，工作流停止",
                        )
                        raise
        self.tracer.emit(
            state,
            self.name,
            "run_completed",
            "success",
            "Agent工作流完成",
            {"metrics": state.metrics, "warnings": state.warnings},
        )
        return state


def build_supervisor(
    db: Database,
    syncer: OfficialCareerSync | None = None,
    sync_company: SyncFunction | None = None,
    max_companies: int = 50,
) -> Supervisor:
    tracer = Tracer(db)
    source = syncer or OfficialCareerSync()
    sync_function = sync_company or source.sync_company
    return Supervisor(
        tracer,
        [
            ResumeProfilerAgent(tracer),
            CompanyDiscoveryAgent(tracer, max_companies=max_companies),
            CareerBrowserAgent(tracer, sync_function),
            JobParserAgent(tracer, db),
            MatchingAgent(tracer),
            VerificationAgent(tracer),
            DecisionAgent(tracer),
        ],
    )
