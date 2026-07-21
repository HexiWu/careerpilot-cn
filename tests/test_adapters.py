import html
import json

import httpx
import pytest

from careerpilot.adapters import (
    AmazonChinaCareerAdapter,
    AppleChinaCareerAdapter,
    DidiCareerAdapter,
    DjiMokaCareerAdapter,
    HuaweiCareerAdapter,
    LenovoCareerAdapter,
    NetEaseCareerAdapter,
)
from careerpilot.models import Company, SourceKind


def make_company(name: str, homepage: str, career: str) -> Company:
    return Company(name=name, homepage_url=homepage, career_urls=[career])


@pytest.mark.asyncio
async def test_netease_adapter_maps_complete_job_description():
    payload = {
        "code": 200,
        "data": {
            "list": [
                {
                    "id": 76015,
                    "name": "大数据平台研发工程师（实习生）",
                    "workType": "1",
                    "firstPostTypeName": "技术",
                    "description": "围绕 Agent 编程建设数据平台",
                    "requirement": "熟悉 Python、Spark、Flink、Hive",
                    "reqEducationName": "本科",
                    "reqWorkYearsName": "不限",
                    "firstDepName": "技术中心",
                    "productName": "网易游戏",
                    "workPlaceNameList": ["广州市"],
                    "updateTime": 1784627453000,
                }
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json=payload)

    company = make_company("网易", "https://www.163.com", "https://hr.163.com")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs, health = await NetEaseCareerAdapter().fetch(client, company)

    assert health.status == "healthy"
    assert jobs[0].employment_type == "实习"
    assert {"Python", "Spark", "Flink", "Hive"}.issubset(jobs[0].skills)
    assert jobs[0].source_kind == SourceKind.OFFICIAL_SUBDOMAIN


@pytest.mark.asyncio
async def test_didi_adapter_maps_refresh_time_and_official_link():
    payload = {
        "meta": {"code": 0},
        "data": {
            "items": [
                {
                    "jdId": 63572,
                    "jdNo": "JR2026043000F",
                    "jobName": "AI策略专家/资深分析师",
                    "workArea": "上海市",
                    "deptName": "金融事业部",
                    "refreshTime": "2026-07-20 17:50:24",
                    "jobDuty": "建设数据策略",
                    "jobQualification": "熟悉 Python 和 SQL",
                }
            ]
        },
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        jobs, health = await DidiCareerAdapter().fetch(
            client,
            make_company("滴滴", "https://www.didiglobal.com", "https://talent.didiglobal.com"),
        )

    assert health.jobs_found == 1
    assert jobs[0].published_at.year == 2026
    assert str(jobs[0].source_url) == "https://talent.didiglobal.com/social/p/63572"


@pytest.mark.asyncio
async def test_amazon_china_adapter_filters_country_and_maps_full_requirements():
    payload = {
        "hits": 2,
        "jobs": [
            {
                "id_icims": "10479781",
                "country_code": "CHN",
                "title": "Senior AI Agent & Data Engineer",
                "normalized_location": "Shanghai, CHN",
                "job_category": "Data Science",
                "job_family": "Data Engineering",
                "job_schedule_type": "full-time",
                "description": "Build <b>AI agent</b> and ETL pipelines",
                "basic_qualifications": "Experience with SQL and Python",
                "preferred_qualifications": "Experience with Spark and Hive",
                "job_path": "/en/jobs/10479781/senior-data-engineer",
                "url_next_step": "https://account.amazon.jobs/jobs/10479781/apply",
                "posted_date": "July 21, 2026",
            },
            {"id": "not-china", "country_code": "USA", "title": "US role"},
        ],
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        jobs, health = await AmazonChinaCareerAdapter().fetch(
            client,
            make_company(
                "亚马逊中国", "https://www.amazon.cn", "https://www.amazon.jobs"
            ),
        )

    assert health.jobs_found == 1
    assert jobs[0].requirements == "Experience with SQL and Python Experience with Spark and Hive"
    assert {"Python", "SQL", "Spark", "Hive", "ETL", "LLM"}.issubset(jobs[0].skills)
    assert jobs[0].source_kind == SourceKind.OFFICIAL_REDIRECT


@pytest.mark.asyncio
async def test_apple_china_adapter_reads_server_hydration_jobs():
    hydration = {
        "loaderData": {
            "search": {
                "totalRecords": 1,
                "searchResults": [
                    {
                        "id": "PIPE-200",
                        "positionId": "200",
                        "postingTitle": "Machine Learning Engineer",
                        "jobSummary": "Build machine learning systems with Python",
                        "locations": [{"name": "Shanghai, China"}],
                        "postDateInGMT": "2026-07-21T10:42:40.933744366Z",
                        "transformedPostingTitle": "machine-learning-engineer",
                        "team": {"teamName": "Machine Learning and AI"},
                        "type": "STD",
                    }
                ],
            }
        }
    }
    encoded = json.dumps(json.dumps(hydration))
    page = f"<script>window.__staticRouterHydrationData = JSON.parse({encoded});</script>"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    ) as client:
        jobs, health = await AppleChinaCareerAdapter(pages=2).fetch(
            client,
            make_company("苹果中国", "https://www.apple.com.cn", "https://jobs.apple.com"),
        )

    assert health.jobs_found == 1
    assert jobs[0].department == "Machine Learning and AI"
    assert {"Machine Learning", "Python"}.issubset(jobs[0].skills)
    assert jobs[0].published_at.tzinfo is not None
    assert str(jobs[0].source_url).endswith("/200/machine-learning-engineer")


@pytest.mark.asyncio
async def test_dji_adapter_reads_public_moka_initial_jobs():
    init_data = {
        "jobs": [
            {
                "id": "job-1",
                "title": "中高级决策规划算法工程师（NN方向）",
                "publishedAt": "2026-07-17T02:34:05.000Z",
                "locations": [{"country": "中国", "address": "深圳市"}],
                "department": {"name": "研发部"},
                "zhineng": {"name": "算法"},
            }
        ]
    }
    page = f'<input id="init-data" value="{html.escape(json.dumps(init_data))}">'
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    ) as client:
        jobs, health = await DjiMokaCareerAdapter().fetch(
            client,
            make_company("大疆", "https://www.dji.com", "https://careers.dji.com"),
        )

    assert health.status == "healthy"
    assert jobs[0].location == "中国 深圳市"
    assert jobs[0].department == "研发部 / 算法"
    assert "#/job/job-1" in str(jobs[0].source_url)


@pytest.mark.asyncio
async def test_huawei_adapter_maps_job_page_and_requirements():
    payload = {
        "status": "SUCCESS",
        "data": {
            "pageVO": {"totalPages": 1},
            "result": [
                {
                    "jobId": 112583,
                    "jobName": "AI安全验证技术专家",
                    "workPlace": "东莞",
                    "deptName": "质量与流程IT部",
                    "jobFamilyName": "研发族",
                    "workYear": "3",
                    "mainBusiness": "负责 AI 智能体安全验证",
                    "jobRequire": "本科及以上，熟悉 Python 和大模型",
                    "lastUpdateDate": "2026-07-17",
                }
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["X-HW-ID"] == HuaweiCareerAdapter.app_id
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs, health = await HuaweiCareerAdapter(pages=1).fetch(
            client,
            make_company("华为", "https://www.huawei.com", "https://career.huawei.com"),
        )

    assert health.jobs_found == 1
    assert jobs[0].department == "质量与流程IT部 / 研发族"
    assert {"Python", "LLM"}.issubset(jobs[0].skills)
    assert str(jobs[0].source_url).endswith("jobId=112583")


@pytest.mark.asyncio
async def test_lenovo_adapter_keeps_only_china_jobs_and_safe_links():
    first_page = """
    <article class="article article--result">
      <div class="article__header__text">
        <h3 class="article__header__text__title"><a href="https://jobs.lenovo.com/en_US/careers/JobDetail/Data/1">数据工程师</a></h3>
        <span class="paragraph">Data Engineering</span>
        <div class="article__header__text__subtitle">
          <span>China, Shanghai, 上海</span><span>Req #: WD001</span><span>Posted 21-Jul-2026</span>
        </div>
      </div>
    </article>
    <article class="article article--result">
      <div class="article__header__text">
        <h3 class="article__header__text__title"><a href="https://jobs.lenovo.com/en_US/careers/JobDetail/US/2">US Engineer</a></h3>
        <div class="article__header__text__subtitle"><span>United States</span></div>
      </div>
    </article>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=first_page if request.url.params["jobOffset"] == "0" else "")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs, health = await LenovoCareerAdapter(pages=2).fetch(
            client,
            make_company("联想", "https://www.lenovo.com", "https://jobs.lenovo.com"),
        )

    assert health.jobs_found == 1
    assert jobs[0].title == "数据工程师"
    assert jobs[0].external_id == "WD001"
    assert jobs[0].published_at.year == 2026
