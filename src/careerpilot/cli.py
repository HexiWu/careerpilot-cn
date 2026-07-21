from __future__ import annotations

import argparse
import asyncio
import json

import uvicorn

from careerpilot.config import settings
from careerpilot.resume import parse_resume_file
from careerpilot.service import CareerPilotService


def main() -> None:
    parser = argparse.ArgumentParser(description="CareerPilot CN")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run the web application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    resume = sub.add_parser("parse-resume", help="Parse a local PDF resume")
    resume.add_argument("path")
    sync = sub.add_parser("sync", help="Run the official-career-site agent workflow")
    sync.add_argument("--resume")
    sync.add_argument("--companies", type=int, default=10)
    args = parser.parse_args()

    if args.command == "parse-resume":
        print(parse_resume_file(args.path).model_dump_json(indent=2, exclude={"raw_text"}))
        return
    if args.command == "sync":
        service = CareerPilotService(settings)
        profile = parse_resume_file(args.resume) if args.resume else None
        if profile and args.resume:
            profile.id = service.db.save_resume(
                args.resume, profile.model_dump_json(), profile.created_at
            )
        original = service.settings.max_companies_per_sync
        object.__setattr__(service.settings, "max_companies_per_sync", args.companies)
        state = asyncio.run(service.research(profile=profile))
        object.__setattr__(service.settings, "max_companies_per_sync", original)
        print(
            json.dumps(
                {"run_id": state.run_id, "metrics": state.metrics}, ensure_ascii=False, indent=2
            )
        )
        return
    uvicorn.run(
        "careerpilot.api:app",
        host=getattr(args, "host", "127.0.0.1"),
        port=getattr(args, "port", 8000),
    )


if __name__ == "__main__":
    main()
