# 作品集与简历写法

## 推荐项目名称

**CareerPilot CN｜中国企业官网求职决策多 Agent 系统**

## 简历项目描述（中文）

> 独立设计并实现面向中国招聘场景的多 Agent 求职决策系统，使用 Supervisor 编排简历解析、企业发现、官网浏览、岗位归一化、证据匹配、来源验证与决策排序 7 个专职 Agent；注册 34 家企业官方招聘入口，为腾讯、网易、华为、滴滴等 8 家企业实现可分页的专用官网适配器，真实简历端到端验收单次获取并匹配 636 个岗位；基于 robots/CAPTCHA 守卫、失败隔离和来源健康快照实现合规且可观察的数据更新；构建 FastAPI、SQLite 和响应式 Web 控制台，以 8 维评分输出匹配证据、能力缺口、风险与置信度，并通过 Docker、GitHub Actions、pytest 与 70% 覆盖率门禁完成工程化交付。

如果简历空间有限，可拆成三条：

- 设计 Supervisor + 7 个专职 Agent 的强类型工作流，实现重试、状态传递、运行轨迹和单来源失败隔离。
- 注册 34 家企业官网招聘入口并实现 8 个专用适配器，设计分页、JSON-LD/嵌入 JSON/HTML 降级解析、内容哈希去重及来源健康快照。
- 基于简历和 JD 构建 8 维可解释匹配，交付 FastAPI + SQLite + Web UI，并用 Docker、GitHub Actions、pytest 和覆盖率门禁保障质量。

## Resume version (English)

> Independently built CareerPilot CN, an observable multi-agent job research system for official corporate career sites in China. Orchestrated seven typed agents for resume profiling, source discovery, browsing, normalization, evidence-based matching, verification, and decision ranking; registered 34 official portals and built eight paginated source adapters, processing 636 live jobs in an end-to-end resume run with robots/CAPTCHA guardrails, source isolation, and health snapshots; shipped a FastAPI/SQLite dashboard with Docker, GitHub Actions, pytest, and a 70% coverage gate.

## 面试演示顺序

1. 上传 PDF 简历，展示结构化技能、经历和目标岗位。
2. 选择 8 个专用源运行一次研究，展示当天岗位、官方链接和来源健康度。
3. 打开推荐页，解释 8 维分数、证据、缺口与风险。
4. 打开 Agent 轨迹，说明 Supervisor、重试和状态流。
5. 打开来源监控，解释为什么受限站点应该显式失败而不是绕过验证。
6. 展示测试、CI 与 Docker，证明项目不是只有界面原型。

## 诚实边界

简历中应写“接入/同步企业官网公开岗位”，不要写“覆盖所有中国公司”或“全网实时”。官网会改版，系统的工程价值在于适配器架构、降级路径和可观察失败，而不是宣称永远抓取成功。
