# Architecture

```mermaid
flowchart LR
    CV[Resume] --> S[Supervisor]
    S --> P[Resume Profiler]
    P --> D[Company Discovery]
    D --> B[Career Browser]
    B --> J[Job Parser]
    J --> M[Matching Agent]
    M --> V[Verification Agent]
    V --> R[Decision Agent]
    R --> UI[Recommendation UI]
    B --> DB[(SQLite)]
    M --> DB
    S --> T[(Agent Traces)]
```

The supervisor executes a durable, inspectable workflow. Each specialist receives structured
state and emits structured output. Tools are domain-restricted and guardrails prevent access to
login-only or CAPTCHA-protected pages.

