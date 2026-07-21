# CareerPilot CN · 中国官网求职决策 Agent

[![CI](https://github.com/HexiWu/careerpilot-cn/actions/workflows/ci.yml/badge.svg)](https://github.com/HexiWu/careerpilot-cn/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

CareerPilot CN 是一个面向中国招聘场景的多 Agent 求职研究与岗位决策系统。用户上传 PDF 简历后，系统从企业官方招聘站获取公开岗位，执行结构化解析、证据匹配、来源验证和决策排序，并展示完整 Agent 运行轨迹。

项目默认不依赖付费 LLM API；简历解析、职位归一化和可解释排序都能在本地完成。它适合作为可独立运行、可测试、可演示的 Agent Engineering 作品集项目。

## 核心能力

- **多 Agent 编排**：Supervisor 协调 7 个专职 Agent，支持失败隔离、重试和结构化状态传递。
- **公司官网优先**：内置 32 家中国科技企业的官网招聘入口；腾讯使用官网公开 JSON 接口，其余站点使用 JSON-LD、嵌入 JSON 和 HTML 多级降级解析。
- **实时与可核验**：保存岗位首次/最后发现时间、内容哈希、官网链接和来源类型；网页变化或受限状态会进入来源监控，而不是静默伪造数据。
- **简历证据匹配**：从中英文 PDF 提取技能、教育和经历，输出 8 维评分、匹配证据、能力缺口、风险和置信度。
- **可观测性**：每个 Agent 的开始、完成、重试、错误和关键指标都持久化到 SQLite，并可在 Web 控制台追踪。
- **完整交付形态**：FastAPI、响应式 Web UI、CLI、定时同步、Docker、GitHub Actions 和自动化测试。

## Agent 工作流

```mermaid
flowchart LR
    CV["PDF 简历"] --> S["Supervisor"]
    S --> P["Resume Profiler"]
    P --> D["Company Discovery"]
    D --> B["Career Browser"]
    B --> J["Job Parser"]
    J --> M["Matching Agent"]
    M --> V["Verification Agent"]
    V --> R["Decision Agent"]
    R --> UI["决策看板"]
    B --> H[("来源健康度")]
    S --> T[("Agent Traces")]
```

更完整的状态、失败策略和数据边界见 [架构文档](docs/architecture.md)。

## 本地运行

要求 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
careerpilot serve --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`，上传 PDF 简历并点击“开始官网研究”。Swagger 文档位于 `http://127.0.0.1:8000/docs`。

也可以只使用 CLI：

```bash
careerpilot parse-resume /path/to/resume.pdf
careerpilot sync --resume /path/to/resume.pdf --companies 10
```

## Docker

```bash
docker compose up --build
```

服务默认暴露在 `http://127.0.0.1:8000`，SQLite 数据保存在 `careerpilot-data` volume 中。

## 测试与质量门禁

```bash
ruff check .
pytest --cov=careerpilot --cov-report=term-missing --cov-fail-under=70
```

CI 会在 Python 3.11 和 3.13 上执行静态检查、单元测试、API 集成测试以及覆盖率门禁。外部招聘站不会进入 CI：网络行为通过 `httpx.MockTransport` 固定，以避免不稳定测试和对官网产生额外流量。

## 数据源与合规边界

- 仅访问企业官网公开页面或官网前端使用的公开接口。
- 遵守 `robots.txt`；遇到登录、验证码或访问限制时立即停止，并记录为 `restricted` 或 `blocked_by_robots`。
- 不绕过身份验证，不使用私人 Cookie，不自动投递，不采集个人招聘账号数据。
- 不承诺所有官网永远可解析。官网结构变化会通过来源健康度暴露，适配器可以独立更新。
- 推荐结果用于辅助决策，不代表企业录用结论。

## 技术栈

Python 3.11+ · FastAPI · Pydantic v2 · httpx · BeautifulSoup · pdfplumber · SQLite · Vanilla JS · pytest · Ruff · Docker · GitHub Actions

## API 摘要

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/resumes/upload` | 上传并解析 PDF 简历 |
| `POST` | `/api/research` | 运行多 Agent 官网研究流程 |
| `GET` | `/api/recommendations` | 获取可解释岗位推荐 |
| `GET` | `/api/jobs` | 搜索已同步岗位 |
| `GET` | `/api/traces` | 查看 Agent 运行轨迹 |
| `GET` | `/api/sources` | 查看官网来源健康度 |
| `POST` | `/api/applications` | 更新个人申请看板状态 |

## 作品集说明

项目亮点、面试讲法与可直接改写的简历条目见 [作品集指南](docs/portfolio.md)。

## License

[MIT](LICENSE)
