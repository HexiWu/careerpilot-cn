# CareerPilot CN

CareerPilot CN is an agentic job research and decision platform focused on public, official
Chinese corporate career sites. It parses a resume, discovers official career portals,
normalizes live job postings, and produces evidence-grounded recommendations.

The project is under active implementation. See `docs/architecture.md` for the target design.

## Principles

- Official company career sites are the primary source.
- No login, CAPTCHA bypass, private cookies, or automated applications.
- The core workflow runs without a paid LLM API.
- Every recommendation is traceable to resume and job-posting evidence.
- Site failures are isolated and observable.

