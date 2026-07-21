from pathlib import Path

from fastapi.testclient import TestClient

from careerpilot.api import create_app
from careerpilot.config import Settings
from careerpilot.models import JobPosting, SourceKind


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(Settings(database_path=tmp_path / "api.db", scheduler_enabled=False))
    return TestClient(app)


def test_health_and_spa(tmp_path: Path):
    with make_client(tmp_path) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        response = client.get("/")
        assert response.status_code == 200
        assert "CareerPilot CN" in response.text


def test_spa_starts_behind_resume_upload_gate(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.get("/")

        assert 'id="resume-gate"' in response.text
        assert 'id="dashboard-content" class="hidden"' in response.text
        assert 'id="sync-button" class="primary" disabled' in response.text
        assert 'id="job-search" placeholder="上传简历后可搜索" disabled' in response.text

        script = client.get("/assets/app.js").text
        assert "resumeUploaded:false" in script
        assert "if(!state.resumeUploaded)return" in script
        assert not script.rstrip().endswith("refresh();")


def test_jobs_and_application_board(tmp_path: Path):
    with make_client(tmp_path) as client:
        db = client.app.state.service.db
        job_id, _ = db.upsert_job(
            JobPosting(
                external_id="api-job",
                company_name="示例科技",
                title="数据工程师",
                source_url="https://careers.example.com/api-job",
                source_kind=SourceKind.OFFICIAL_SUBDOMAIN,
            )
        )
        jobs = client.get("/api/jobs").json()
        assert jobs[0]["title"] == "数据工程师"
        response = client.post(
            "/api/applications",
            json={"job_id": job_id, "status": "saved", "note": "优先申请"},
        )
        assert response.status_code == 200
        assert client.get("/api/applications").json()[0]["status"] == "saved"


def test_rejects_non_pdf_resume(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/resumes/upload",
            files={"file": ("resume.txt", b"not pdf", "text/plain")},
        )
        assert response.status_code == 400


def test_rejects_unknown_company_in_research(tmp_path: Path):
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/research",
            json={"company_names": ["不存在的公司"], "max_companies": 1},
        )
        assert response.status_code == 400
        assert "未知公司" in response.json()["detail"]
