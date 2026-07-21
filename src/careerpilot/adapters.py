from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from careerpilot.models import Company, JobPosting, SourceHealth, SourceKind
from careerpilot.taxonomy import extract_skills, normalize_text


def source_kind_for(company: Company, url: str) -> SourceKind:
    source_host = urlparse(url).netloc.lower().removeprefix("www.")
    home_host = urlparse(str(company.homepage_url)).netloc.lower().removeprefix("www.")
    if source_host == home_host:
        return SourceKind.OFFICIAL_DOMAIN
    if source_host.endswith("." + home_host):
        return SourceKind.OFFICIAL_SUBDOMAIN
    if any(
        source_host == urlparse(str(item)).netloc.lower().removeprefix("www.")
        for item in company.career_urls
    ):
        return SourceKind.OFFICIAL_REDIRECT
    return SourceKind.UNVERIFIED


def parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def clean_html(value: object) -> str:
    return normalize_text(BeautifulSoup(str(value or ""), "html.parser").get_text(" "))


class CareerAdapter(Protocol):
    company_name: str
    entry_url: str

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]: ...


class TencentCareerAdapter:
    company_name = "腾讯"
    entry_url = "https://careers.tencent.com/"
    api_url = "https://careers.tencent.com/tencentcareer/api/post/Query"

    def __init__(self, page_size: int = 100):
        self.page_size = page_size

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        response = await client.get(
            self.api_url,
            params={
                "pageIndex": 1,
                "pageSize": self.page_size,
                "language": "zh-cn",
                "area": "cn",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        posts = response.json().get("Data", {}).get("Posts", [])
        jobs: list[JobPosting] = []
        for post in posts:
            published_at = None
            if value := post.get("LastUpdateTime"):
                try:
                    published_at = datetime.strptime(value, "%Y年%m月%d日").replace(tzinfo=UTC)
                except ValueError:
                    pass
            target_url = str(post.get("PostURL") or "").replace("http://", "https://", 1)
            if not target_url:
                target_url = f"https://careers.tencent.com/jobdesc.html?postId={post['PostId']}"
            full_text = " ".join(
                str(post.get(key) or "")
                for key in ("RecruitPostName", "Responsibility", "Requirement")
            )
            job = JobPosting(
                external_id=str(post.get("PostId") or target_url),
                company_name=company.name,
                title=normalize_text(str(post.get("RecruitPostName") or "")),
                location=normalize_text(str(post.get("LocationName") or "")),
                department=normalize_text(
                    " / ".join(
                        value
                        for value in (
                            str(post.get("BGName") or ""),
                            str(post.get("ProductName") or ""),
                            str(post.get("CategoryName") or ""),
                        )
                        if value
                    )
                ),
                experience_required=normalize_text(
                    str(post.get("RequireWorkYearsName") or "")
                ),
                description=normalize_text(str(post.get("Responsibility") or "")),
                requirements=normalize_text(str(post.get("Requirement") or "")),
                skills=extract_skills(full_text),
                source_url=target_url,
                apply_url=target_url,
                source_kind=source_kind_for(company, target_url),
                source_evidence="腾讯招聘官网公开职位接口；保留官网详情链接与更新时间",
                published_at=published_at,
                last_seen_at=datetime.now(UTC),
            ).ensure_content_hash()
            if job.title:
                jobs.append(job)
        return jobs, _health(company, self.api_url, jobs)


class NetEaseCareerAdapter:
    company_name = "网易"
    entry_url = "https://hr.163.com/"
    api_url = "https://hr.163.com/api/hr163/position/queryPage"

    def __init__(self, page_size: int = 100):
        self.page_size = page_size

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        response = await client.post(
            self.api_url,
            json={"pageNum": 1, "pageSize": self.page_size},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 200:
            raise ValueError(f"NetEase API returned code {payload.get('code')}")
        jobs: list[JobPosting] = []
        for item in payload.get("data", {}).get("list", []):
            job_id = str(item.get("id") or "")
            target_url = f"https://hr.163.com/job-detail?id={job_id}"
            location = "、".join(item.get("workPlaceNameList") or [])
            full_text = " ".join(
                str(item.get(key) or "") for key in ("name", "description", "requirement")
            )
            timestamp = item.get("updateTime")
            published_at = (
                datetime.fromtimestamp(timestamp / 1000, tz=UTC)
                if isinstance(timestamp, int | float)
                else None
            )
            jobs.append(
                JobPosting(
                    external_id=job_id,
                    company_name=company.name,
                    title=normalize_text(str(item.get("name") or "")),
                    location=normalize_text(location),
                    department=normalize_text(
                        " / ".join(
                            value
                            for value in (
                                str(item.get("firstDepName") or ""),
                                str(item.get("productName") or ""),
                                str(item.get("firstPostTypeName") or ""),
                            )
                            if value
                        )
                    ),
                    employment_type="实习" if str(item.get("workType")) == "1" else "社会招聘",
                    experience_required=normalize_text(
                        str(item.get("reqWorkYearsName") or "")
                    ),
                    education_required=normalize_text(str(item.get("reqEducationName") or "")),
                    description=normalize_text(str(item.get("description") or "")),
                    requirements=normalize_text(str(item.get("requirement") or "")),
                    skills=extract_skills(full_text),
                    source_url=target_url,
                    apply_url=target_url,
                    source_kind=source_kind_for(company, target_url),
                    source_evidence="网易招聘官网公开职位接口；包含完整职责与任职要求",
                    published_at=published_at,
                    last_seen_at=datetime.now(UTC),
                ).ensure_content_hash()
            )
        return jobs, _health(company, self.api_url, jobs)


class DidiCareerAdapter:
    company_name = "滴滴"
    entry_url = "https://talent.didiglobal.com/"
    api_url = "https://talent.didiglobal.com/recruit-portal-service/api/job/front/list"

    def __init__(self, page_size: int = 100):
        self.page_size = page_size

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        response = await client.get(
            self.api_url,
            params={"pageNo": 1, "pageSize": self.page_size},
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("meta", {}).get("code") != 0:
            raise ValueError(f"DiDi API returned code {payload.get('meta', {}).get('code')}")
        jobs: list[JobPosting] = []
        for item in payload.get("data", {}).get("items", []):
            job_id = str(item.get("jdId") or item.get("jdNo") or "")
            target_url = f"https://talent.didiglobal.com/social/p/{job_id}"
            published_at = None
            if value := item.get("refreshTime"):
                try:
                    published_at = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=UTC
                    )
                except ValueError:
                    pass
            full_text = " ".join(
                str(item.get(key) or "")
                for key in ("jobName", "jobDuty", "jobQualification")
            )
            jobs.append(
                JobPosting(
                    external_id=job_id,
                    company_name=company.name,
                    title=normalize_text(str(item.get("jobName") or "")),
                    location=normalize_text(str(item.get("workArea") or "")),
                    department=normalize_text(str(item.get("deptName") or "")),
                    description=normalize_text(str(item.get("jobDuty") or "")),
                    requirements=normalize_text(str(item.get("jobQualification") or "")),
                    skills=extract_skills(full_text),
                    source_url=target_url,
                    apply_url=target_url,
                    source_kind=source_kind_for(company, target_url),
                    source_evidence="滴滴招聘官网公开职位接口；保留官网职位编号与刷新时间",
                    published_at=published_at,
                    last_seen_at=datetime.now(UTC),
                ).ensure_content_hash()
            )
        return jobs, _health(company, self.api_url, jobs)


class HuaweiCareerAdapter:
    company_name = "华为"
    entry_url = "https://career.huawei.com/cn/social-recruitment-job-list"
    api_url = (
        "https://apigw-dgg-b0.huawei.com/api/apig/channelhw/"
        "recruitmentPosition/pub/getJobPage"
    )
    app_id = "app_000000035886"

    def __init__(self, page_size: int = 100, pages: int = 2):
        self.page_size = page_size
        self.pages = pages

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        jobs: list[JobPosting] = []
        headers = {
            "x-jalor-tenantAlias": "hcm",
            "x-language": "zh_CN",
            "x-Referer": "https://career.huawei.com/cn",
            "X-HW-ID": self.app_id,
            "Referer": self.entry_url,
        }
        for page in range(1, self.pages + 1):
            response = await client.post(
                self.api_url,
                params={"X-HW-ID": self.app_id},
                json={"curPage": page, "pageSize": self.page_size, "jobType": "SR"},
                headers=headers,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "SUCCESS":
                raise ValueError(f"Huawei API returned status {payload.get('status')}")
            data = payload.get("data") or {}
            items = data.get("result") or []
            for item in items:
                job_id = str(item.get("jobId") or item.get("advertisementId") or "")
                target_url = f"https://career.huawei.com/cn/job-details?jobId={job_id}"
                description = normalize_text(str(item.get("mainBusiness") or ""))
                requirements = normalize_text(str(item.get("jobRequire") or ""))
                title = normalize_text(str(item.get("jobName") or ""))
                jobs.append(
                    JobPosting(
                        external_id=job_id,
                        company_name=company.name,
                        title=title,
                        location=normalize_text(
                            str(item.get("workPlace") or item.get("jobAddress") or "")
                        ),
                        department=normalize_text(
                            " / ".join(
                                value
                                for value in (
                                    str(item.get("deptName") or ""),
                                    str(item.get("jobFamilyName") or ""),
                                )
                                if value
                            )
                        ),
                        experience_required=normalize_text(str(item.get("workYear") or "")),
                        description=description,
                        requirements=requirements,
                        skills=extract_skills(f"{title} {description} {requirements}"),
                        source_url=target_url,
                        apply_url=target_url,
                        source_kind=source_kind_for(company, self.entry_url),
                        source_evidence="华为招聘官网公开职位 API；包含职责、要求和最后更新日期",
                        published_at=parse_iso_datetime(item.get("lastUpdateDate")),
                        last_seen_at=datetime.now(UTC),
                    ).ensure_content_hash()
                )
            page_vo = data.get("pageVO") or {}
            if page >= int(page_vo.get("totalPages") or 1) or not items:
                break
        jobs = list({job.fingerprint: job for job in jobs}.values())
        return jobs, _health(company, self.api_url, jobs)


class DjiMokaCareerAdapter:
    company_name = "大疆"
    entry_url = "https://apply.careers.dji.com/social-recruitment/dji/170070"

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        response = await client.get(self.entry_url, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        node = soup.find("input", id="init-data")
        if not node or not node.get("value"):
            raise ValueError("Moka init-data is missing")
        payload = json.loads(str(node.get("value")))
        jobs: list[JobPosting] = []
        for item in payload.get("jobs", []):
            job_id = str(item.get("id") or "")
            target_url = f"{self.entry_url}#/job/{job_id}"
            locations = item.get("locations") or []
            location = "、".join(
                normalize_text(f"{part.get('country', '')} {part.get('address', '')}")
                for part in locations
            )
            department = item.get("department") or {}
            function = item.get("zhineng") or {}
            title = normalize_text(str(item.get("title") or ""))
            jobs.append(
                JobPosting(
                    external_id=job_id,
                    company_name=company.name,
                    title=title,
                    location=location,
                    department=normalize_text(
                        f"{department.get('name', '')} / {function.get('name', '')}"
                    ),
                    skills=extract_skills(title),
                    source_url=target_url,
                    apply_url=target_url,
                    source_kind=source_kind_for(company, self.entry_url),
                    source_evidence="大疆招聘官网 Moka 公开初始化职位数据；保留官网申请链接",
                    published_at=parse_iso_datetime(item.get("publishedAt")),
                    last_seen_at=datetime.now(UTC),
                ).ensure_content_hash()
            )
        return jobs, _health(company, self.entry_url, jobs)


class LenovoCareerAdapter:
    company_name = "联想"
    entry_url = "https://jobs.lenovo.com/en_US/careers/SearchJobs/"

    def __init__(self, page_size: int = 20, pages: int = 5):
        self.page_size = page_size
        self.pages = pages

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        jobs: list[JobPosting] = []
        for page in range(self.pages):
            response = await client.get(
                self.entry_url,
                params={
                    "jobRecordsPerPage": self.page_size,
                    "jobOffset": page * self.page_size,
                },
                follow_redirects=True,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.select("article.article--result")
            if not articles:
                break
            for article in articles:
                title_link = article.select_one(".article__header__text__title a[href]")
                if not title_link:
                    continue
                target_url = str(title_link.get("href"))
                subtitles = [
                    normalize_text(node.get_text(" "))
                    for node in article.select(".article__header__text__subtitle span")
                ]
                location = subtitles[0] if subtitles else ""
                if "china" not in location.lower() and "中国" not in location:
                    continue
                req_id = subtitles[1].removeprefix("Req #:").strip() if len(subtitles) > 1 else ""
                published_at = None
                if len(subtitles) > 2:
                    value = subtitles[2].removeprefix("Posted").strip()
                    try:
                        published_at = datetime.strptime(value, "%d-%b-%Y").replace(tzinfo=UTC)
                    except ValueError:
                        pass
                department_node = article.select_one(".article__header__text > .paragraph")
                title = normalize_text(title_link.get_text(" "))
                description = normalize_text(article.get_text(" "))
                jobs.append(
                    JobPosting(
                        external_id=req_id or target_url,
                        company_name=company.name,
                        title=title,
                        location=location,
                        department=normalize_text(
                            department_node.get_text(" ") if department_node else ""
                        ),
                        description=description,
                        skills=extract_skills(f"{title} {description}"),
                        source_url=target_url,
                        apply_url=target_url,
                        source_kind=source_kind_for(company, target_url),
                        source_evidence="联想招聘官网 Avature 搜索结果；仅保留中国地区职位",
                        published_at=published_at,
                        last_seen_at=datetime.now(UTC),
                    ).ensure_content_hash()
                )
        jobs = list({job.fingerprint: job for job in jobs}.values())
        return jobs, _health(company, self.entry_url, jobs)


class AmazonChinaCareerAdapter:
    company_name = "亚马逊中国"
    entry_url = "https://www.amazon.jobs/en/search?normalized_country_code%5B%5D=CHN"
    api_url = "https://www.amazon.jobs/en/search.json"

    def __init__(self, page_size: int = 100):
        self.page_size = page_size

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        response = await client.get(
            self.api_url,
            params={
                "normalized_country_code[]": "CHN",
                "offset": 0,
                "result_limit": self.page_size,
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        jobs: list[JobPosting] = []
        for item in payload.get("jobs", []):
            if item.get("country_code") != "CHN":
                continue
            job_id = str(item.get("id_icims") or item.get("id") or "")
            target_url = f"https://www.amazon.jobs{item.get('job_path', '')}"
            description = clean_html(item.get("description"))
            requirements = clean_html(
                " ".join(
                    str(item.get(key) or "")
                    for key in ("basic_qualifications", "preferred_qualifications")
                )
            )
            title = normalize_text(str(item.get("title") or ""))
            posted_at = None
            if value := item.get("posted_date"):
                try:
                    posted_at = datetime.strptime(str(value), "%B %d, %Y").replace(tzinfo=UTC)
                except ValueError:
                    pass
            jobs.append(
                JobPosting(
                    external_id=job_id,
                    company_name=company.name,
                    title=title,
                    location=normalize_text(
                        str(item.get("normalized_location") or item.get("location") or "")
                    ),
                    department=normalize_text(
                        " / ".join(
                            str(item.get(key) or "")
                            for key in ("job_category", "job_family")
                            if item.get(key)
                        )
                    ),
                    employment_type=normalize_text(str(item.get("job_schedule_type") or "")),
                    description=description,
                    requirements=requirements,
                    skills=extract_skills(f"{title} {description} {requirements}"),
                    source_url=target_url,
                    apply_url=str(item.get("url_next_step") or target_url),
                    source_kind=source_kind_for(company, target_url),
                    source_evidence="Amazon Jobs 官网中国区公开 JSON 搜索；仅保留 CHN 职位",
                    published_at=posted_at,
                    last_seen_at=datetime.now(UTC),
                ).ensure_content_hash()
            )
        return jobs, _health(company, self.api_url, jobs)


class AppleChinaCareerAdapter:
    company_name = "苹果中国"
    entry_url = "https://jobs.apple.com/en-us/search?location=china-CHNC"

    def __init__(self, pages: int = 5):
        self.pages = pages

    @staticmethod
    def _hydration_data(content: str) -> dict[str, object]:
        match = re.search(
            r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((\".*\")\);",
            content,
            re.DOTALL,
        )
        if not match:
            raise ValueError("Apple hydration data is missing")
        return json.loads(json.loads(match.group(1)))

    async def fetch(
        self, client: httpx.AsyncClient, company: Company
    ) -> tuple[list[JobPosting], SourceHealth]:
        jobs: list[JobPosting] = []
        for page in range(1, self.pages + 1):
            response = await client.get(
                self.entry_url,
                params={"location": "china-CHNC", "page": page},
                follow_redirects=True,
            )
            response.raise_for_status()
            data = self._hydration_data(response.text)
            loader_data = data.get("loaderData") if isinstance(data, dict) else None
            search = loader_data.get("search") if isinstance(loader_data, dict) else None
            items = search.get("searchResults", []) if isinstance(search, dict) else []
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if not isinstance(item, dict):
                    continue
                locations = item.get("locations") or []
                location = "、".join(
                    normalize_text(str(place.get("name") or place.get("countryName") or ""))
                    for place in locations
                    if isinstance(place, dict)
                )
                job_id = str(item.get("positionId") or item.get("id") or "")
                slug = str(item.get("transformedPostingTitle") or "job")
                target_url = f"https://jobs.apple.com/en-us/details/{job_id}/{slug}"
                title = normalize_text(str(item.get("postingTitle") or ""))
                description = clean_html(item.get("jobSummary"))
                team = item.get("team") or {}
                jobs.append(
                    JobPosting(
                        external_id=job_id,
                        company_name=company.name,
                        title=title,
                        location=location,
                        department=normalize_text(
                            str(team.get("teamName") or "") if isinstance(team, dict) else ""
                        ),
                        employment_type=normalize_text(str(item.get("type") or "")),
                        description=description,
                        skills=extract_skills(f"{title} {description}"),
                        source_url=target_url,
                        apply_url=target_url,
                        source_kind=source_kind_for(company, target_url),
                        source_evidence="Apple Careers 官网中国筛选页服务端结构化职位数据",
                        published_at=parse_iso_datetime(item.get("postDateInGMT")),
                        last_seen_at=datetime.now(UTC),
                    ).ensure_content_hash()
                )
            total = int(search.get("totalRecords") or 0) if isinstance(search, dict) else 0
            if page * len(items) >= total:
                break
        jobs = list({job.fingerprint: job for job in jobs}.values())
        return jobs, _health(company, self.entry_url, jobs)


def _health(company: Company, url: str, jobs: list[JobPosting]) -> SourceHealth:
    return SourceHealth(
        company_name=company.name,
        url=url,
        status="healthy" if jobs else "empty",
        jobs_found=len(jobs),
        error="" if jobs else "official source returned no active jobs",
    )


def default_adapters() -> dict[str, CareerAdapter]:
    adapters: list[CareerAdapter] = [
        TencentCareerAdapter(),
        NetEaseCareerAdapter(),
        DidiCareerAdapter(),
        HuaweiCareerAdapter(),
        DjiMokaCareerAdapter(),
        LenovoCareerAdapter(),
        AmazonChinaCareerAdapter(),
        AppleChinaCareerAdapter(),
    ]
    return {adapter.company_name: adapter for adapter in adapters}
