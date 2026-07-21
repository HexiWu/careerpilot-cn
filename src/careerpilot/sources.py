from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag

from careerpilot.models import Company, JobPosting, SourceHealth, SourceKind
from careerpilot.taxonomy import extract_skills, normalize_text

JOB_LINK_TERMS = ("job", "jobs", "position", "career", "招聘", "职位", "岗位")
CAREER_LINK_TERMS = ("career", "careers", "jobs", "join", "recruit", "招聘", "加入我们", "人才")


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int
    content: str
    content_type: str


class PublicPageGuard:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    @staticmethod
    def is_restricted_page(content: str) -> bool:
        signals = ("请输入验证码", "短信验证码", "登录后查看", "扫码登录", "captcha")
        lowered = content.lower()
        return any(signal.lower() in lowered for signal in signals)

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = await client.get(robots_url)
            if response.status_code >= 400:
                return True
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            return parser.can_fetch(self.user_agent, url)
        except httpx.HTTPError:
            return True


class OfficialCareerParser:
    def parse(self, company: Company, page_url: str, content: str) -> list[JobPosting]:
        soup = BeautifulSoup(content, "html.parser")
        jobs = self._parse_json_ld(company, page_url, soup)
        if jobs:
            return self._dedupe(jobs)
        jobs = self._parse_embedded_json(company, page_url, soup)
        if jobs:
            return self._dedupe(jobs)
        return self._dedupe(self._parse_html(company, page_url, soup))

    def _source_kind(self, company: Company, url: str) -> SourceKind:
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

    def _from_mapping(
        self, company: Company, page_url: str, item: dict[str, Any]
    ) -> JobPosting | None:
        title = (
            item.get("title")
            or item.get("name")
            or item.get("jobTitle")
            or item.get("positionName")
        )
        if not isinstance(title, str) or not title.strip():
            return None
        location_value = item.get("jobLocation") or item.get("location") or item.get("city") or ""
        if isinstance(location_value, dict):
            address = location_value.get("address", location_value)
            if isinstance(address, dict):
                location_value = address.get("addressLocality") or address.get("name") or ""
            else:
                location_value = str(address)
        if isinstance(location_value, list):
            location_value = "、".join(str(value) for value in location_value)
        description = item.get("description") or item.get("responsibilities") or ""
        requirements = item.get("qualifications") or item.get("requirements") or ""
        target_url = item.get("url") or item.get("applyUrl") or item.get("absolute_url") or page_url
        target_url = urljoin(page_url, str(target_url))
        external_id = str(
            item.get("identifier") or item.get("id") or item.get("jobId") or target_url
        )
        if isinstance(item.get("identifier"), dict):
            external_id = str(item["identifier"].get("value", target_url))
        published = item.get("datePosted") or item.get("publishTime") or item.get("updated_at")
        published_at = None
        if isinstance(published, str):
            try:
                published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                published_at = None
        full_text = normalize_text(BeautifulSoup(str(description), "html.parser").get_text(" "))
        requirement_text = normalize_text(
            BeautifulSoup(str(requirements), "html.parser").get_text(" ")
        )
        return JobPosting(
            external_id=external_id,
            company_name=company.name,
            title=normalize_text(title),
            location=normalize_text(str(location_value)),
            department=normalize_text(
                str(item.get("department") or item.get("occupationalCategory") or "")
            ),
            employment_type=normalize_text(str(item.get("employmentType") or "")),
            description=full_text,
            requirements=requirement_text,
            skills=extract_skills(f"{title} {full_text} {requirement_text}"),
            source_url=target_url,
            apply_url=target_url,
            source_kind=self._source_kind(company, page_url),
            source_evidence=f"职位由{company.name}预登记的官方招聘入口采集",
            published_at=published_at,
            last_seen_at=datetime.now(UTC),
        ).ensure_content_hash()

    def _parse_json_ld(
        self, company: Company, page_url: str, soup: BeautifulSoup
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.get_text(strip=True))
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            expanded: list[Any] = []
            for candidate in candidates:
                if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                    expanded.extend(candidate["@graph"])
                else:
                    expanded.append(candidate)
            for item in expanded:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    job = self._from_mapping(company, page_url, item)
                    if job:
                        jobs.append(job)
        return jobs

    def _parse_embedded_json(
        self, company: Company, page_url: str, soup: BeautifulSoup
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for node in soup.select("script"):
            text = node.string or ""
            if not text or not any(
                key in text for key in ('"jobTitle"', '"positionName"', '"datePosted"')
            ):
                continue
            matches = re.findall(
                r"\{[^{}]{0,8000}(?:jobTitle|positionName|datePosted)[^{}]{0,8000}\}", text
            )
            for raw in matches:
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                job = self._from_mapping(company, page_url, item)
                if job:
                    jobs.append(job)
        return jobs

    def _parse_html(self, company: Company, page_url: str, soup: BeautifulSoup) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        selectors = (
            "[data-job-id]",
            ".job-item",
            ".job-card",
            ".position-item",
            "li.job",
            "article.job",
        )
        nodes: list[Tag] = []
        for selector in selectors:
            nodes.extend(node for node in soup.select(selector) if isinstance(node, Tag))
        if not nodes:
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href", ""))
                text = normalize_text(anchor.get_text(" "))
                if 2 <= len(text) <= 80 and any(term in href.lower() for term in JOB_LINK_TERMS):
                    nodes.append(anchor)
        for node in nodes[:500]:
            anchor = node if node.name == "a" else node.find("a", href=True)
            title_node = node.select_one(".job-title, .position-name, .title, h2, h3, h4")
            title = normalize_text((title_node or anchor or node).get_text(" "))
            if not title or len(title) > 100:
                continue
            href = str(anchor.get("href", page_url)) if anchor else page_url
            location_node = node.select_one(".location, .city, .job-location")
            location = normalize_text(location_node.get_text(" ")) if location_node else ""
            item = {
                "title": title,
                "location": location,
                "url": href,
                "id": node.get("data-job-id") or href,
                "description": normalize_text(node.get_text(" ")),
            }
            job = self._from_mapping(company, page_url, item)
            if job:
                jobs.append(job)
        return jobs

    @staticmethod
    def _dedupe(jobs: list[JobPosting]) -> list[JobPosting]:
        return list({job.fingerprint: job for job in jobs}.values())


class CareerSiteDiscoverer:
    def discover_from_html(self, homepage_url: str, content: str) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        discovered: list[str] = []
        for anchor in soup.find_all("a", href=True):
            text = normalize_text(anchor.get_text(" ")).lower()
            href = str(anchor.get("href", ""))
            if any(term in f"{text} {href.lower()}" for term in CAREER_LINK_TERMS):
                discovered.append(urljoin(homepage_url, href))
        return list(dict.fromkeys(discovered))


class TencentCareerAdapter:
    """Adapter for the public JSON endpoint used by Tencent's official career site."""

    api_url = "https://careers.tencent.com/tencentcareer/api/post/Query"

    def __init__(self, parser: OfficialCareerParser, page_size: int = 100):
        self.parser = parser
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
        payload = response.json()
        posts = payload.get("Data", {}).get("Posts", [])
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
                skills=extract_skills(
                    " ".join(
                        str(post.get(key) or "")
                        for key in ("RecruitPostName", "Responsibility", "Requirement")
                    )
                ),
                source_url=target_url,
                apply_url=target_url,
                source_kind=self.parser._source_kind(company, target_url),
                source_evidence="腾讯招聘官网公开职位接口；保留官网详情链接与更新时间",
                published_at=published_at,
                last_seen_at=datetime.now(UTC),
            ).ensure_content_hash()
            if job.title:
                jobs.append(job)
        return jobs, SourceHealth(
            company_name=company.name,
            url=self.api_url,
            status="healthy" if jobs else "empty",
            jobs_found=len(jobs),
            error="" if jobs else "official API returned no active jobs",
        )


class OfficialCareerSync:
    def __init__(self, timeout: float = 20, user_agent: str = "CareerPilotCN/0.1"):
        self.timeout = timeout
        self.user_agent = user_agent
        self.parser = OfficialCareerParser()
        self.guard = PublicPageGuard(user_agent)
        self.tencent = TencentCareerAdapter(self.parser)

    async def fetch(self, client: httpx.AsyncClient, url: str) -> FetchResult:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            content=response.text,
            content_type=response.headers.get("content-type", ""),
        )

    async def sync_company(self, company: Company) -> tuple[list[JobPosting], list[SourceHealth]]:
        jobs: list[JobPosting] = []
        health: list[SourceHealth] = []
        headers = {"User-Agent": self.user_agent, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"}
        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            urls = [str(url) for url in company.career_urls]
            if company.name == "腾讯":
                official_url = urls[0] if urls else str(company.homepage_url)
                if not await self.guard.allowed(client, official_url):
                    return [], [
                        SourceHealth(
                            company_name=company.name,
                            url=official_url,
                            status="blocked_by_robots",
                            error="robots.txt disallows automated access",
                        )
                    ]
                try:
                    api_jobs, api_health = await self.tencent.fetch(client, company)
                    if api_jobs:
                        return api_jobs, [api_health]
                    health.append(api_health)
                except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    health.append(
                        SourceHealth(
                            company_name=company.name,
                            url=self.tencent.api_url,
                            status="error",
                            error=f"official API failed; falling back to HTML: {exc}",
                        )
                    )
            if not urls:
                try:
                    homepage = await self.fetch(client, str(company.homepage_url))
                    urls = CareerSiteDiscoverer().discover_from_html(homepage.url, homepage.content)
                except httpx.HTTPError as exc:
                    health.append(
                        SourceHealth(
                            company_name=company.name,
                            url=str(company.homepage_url),
                            status="error",
                            error=str(exc),
                        )
                    )
            for url in urls:
                try:
                    if not await self.guard.allowed(client, url):
                        health.append(
                            SourceHealth(
                                company_name=company.name,
                                url=url,
                                status="blocked_by_robots",
                                error="robots.txt disallows automated access",
                            )
                        )
                        continue
                    page = await self.fetch(client, url)
                    if self.guard.is_restricted_page(page.content):
                        health.append(
                            SourceHealth(
                                company_name=company.name,
                                url=url,
                                status="restricted",
                                error="login or CAPTCHA required",
                            )
                        )
                        continue
                    found = self.parser.parse(company, page.url, page.content)
                    jobs.extend(found)
                    health.append(
                        SourceHealth(
                            company_name=company.name,
                            url=url,
                            status="healthy",
                            jobs_found=len(found),
                        )
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    health.append(
                        SourceHealth(
                            company_name=company.name, url=url, status="error", error=str(exc)
                        )
                    )
        return OfficialCareerParser._dedupe(jobs), health
