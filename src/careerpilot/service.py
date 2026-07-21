from __future__ import annotations

from careerpilot.agents import WorkflowState, build_supervisor
from careerpilot.config import Settings
from careerpilot.db import Database
from careerpilot.matching import rank_jobs
from careerpilot.models import Company, JobRecommendation, ResumeProfile
from careerpilot.resume import parse_resume_pdf
from careerpilot.sources import OfficialCareerSync


class CareerPilotService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.database_path)
        self.db.initialize()
        self.syncer = OfficialCareerSync(
            timeout=settings.request_timeout,
            user_agent=settings.user_agent,
        )

    def ingest_resume(self, filename: str, data: bytes) -> ResumeProfile:
        profile = parse_resume_pdf(data)
        profile.id = self.db.save_resume(filename, profile.model_dump_json(), profile.created_at)
        return profile

    def latest_profile(self) -> ResumeProfile | None:
        data = self.db.latest_resume()
        return ResumeProfile.model_validate(data) if data else None

    async def research(
        self,
        profile: ResumeProfile | None = None,
        companies: list[Company] | None = None,
    ) -> WorkflowState:
        profile = profile or self.latest_profile()
        if not profile:
            raise ValueError("请先上传简历")
        supervisor = build_supervisor(
            self.db,
            self.syncer,
            max_companies=self.settings.max_companies_per_sync,
        )
        return await supervisor.run(WorkflowState(profile=profile, companies=companies or []))

    def recommendations(self, profile: ResumeProfile | None = None) -> list[JobRecommendation]:
        profile = profile or self.latest_profile()
        if not profile:
            return []
        return rank_jobs(profile, self.db.list_jobs(limit=500))
