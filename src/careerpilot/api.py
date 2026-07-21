from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from careerpilot.companies import DEFAULT_COMPANIES
from careerpilot.config import Settings, settings
from careerpilot.models import ApplicationStatus, Company
from careerpilot.service import CareerPilotService

STATIC_DIR = Path(__file__).parent / "static"


class ApplicationUpdate(BaseModel):
    job_id: int
    status: ApplicationStatus
    note: str = Field(default="", max_length=2000)


class ResearchRequest(BaseModel):
    company_names: list[str] = Field(default_factory=list)
    max_companies: int = Field(default=10, ge=1, le=50)


async def _scheduler_loop(service: CareerPilotService) -> None:
    while True:
        await asyncio.sleep(service.settings.sync_interval_hours * 3600)
        if not service.latest_profile():
            continue
        try:
            await service.research()
        except Exception:
            # The supervisor persists the detailed failure trace. A source failure must never
            # terminate the API process or prevent the next scheduled run.
            continue


def create_app(app_settings: Settings | None = None) -> FastAPI:
    resolved = app_settings or settings
    service = CareerPilotService(resolved)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = None
        if resolved.scheduler_enabled:
            task = asyncio.create_task(_scheduler_loop(service))
        yield
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(
        title="CareerPilot CN",
        description="Agentic job research over official Chinese corporate career sites",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.service = service

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "database": str(resolved.database_path),
            "scheduler": resolved.scheduler_enabled,
            "sync_interval_hours": resolved.sync_interval_hours,
        }

    @app.get("/api/profile")
    def profile() -> dict:
        result = service.latest_profile()
        if not result:
            raise HTTPException(404, "尚未上传简历")
        return result.model_dump(mode="json", exclude={"raw_text"})

    @app.post("/api/resumes/upload")
    async def upload_resume(file: UploadFile = File(...)) -> dict:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "只支持PDF简历")
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "简历文件不能超过10MB")
        try:
            result = service.ingest_resume(file.filename, data)
        except Exception as exc:
            raise HTTPException(422, f"简历解析失败：{exc}") from exc
        return result.model_dump(mode="json", exclude={"raw_text"})

    @app.get("/api/companies")
    def companies() -> list[dict]:
        return [company.model_dump(mode="json") for company in DEFAULT_COMPANIES]

    @app.post("/api/research")
    async def research(request: ResearchRequest) -> dict:
        selected: list[Company] = []
        names = set(request.company_names)
        for company in DEFAULT_COMPANIES:
            if names and company.name not in names:
                continue
            selected.append(company)
            if len(selected) >= request.max_companies:
                break
        try:
            state = await service.research(companies=selected)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "run_id": state.run_id,
            "jobs_discovered": len(state.discovered_jobs),
            "recommendations": len(state.recommendations),
            "warnings": state.warnings,
            "metrics": state.metrics,
            "top_jobs": [item.model_dump(mode="json") for item in state.recommendations[:10]],
        }

    @app.get("/api/jobs")
    def jobs(q: str = "", limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
        return [job.model_dump(mode="json") for job in service.db.list_jobs(q, limit)]

    @app.get("/api/recommendations")
    def recommendations(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        return [item.model_dump(mode="json") for item in service.recommendations()[:limit]]

    @app.get("/api/traces")
    def traces(
        run_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)
    ) -> list[dict]:
        return service.db.list_events(run_id, limit)

    @app.get("/api/sources")
    def sources() -> list[dict]:
        return service.db.source_health()

    @app.get("/api/applications")
    def applications() -> list[dict]:
        return service.db.list_applications()

    @app.post("/api/applications")
    def update_application(update: ApplicationUpdate) -> dict:
        service.db.update_application(update.job_id, update.status, update.note)
        return {"status": "updated"}

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
