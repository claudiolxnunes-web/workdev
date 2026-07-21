#!/usr/bin/env python3
"""CLI local para Agents consumirem e atualizarem handoffs sem expor secrets."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


API_BASE = os.getenv("WORKDEV_LOCAL_API", "http://127.0.0.1:8000/api")
ENV_FILE = Path("/opt/workdev/apps/api/.env")


def api_key() -> str:
    configured = os.getenv("WORKDEV_API_KEY")
    if configured:
        return configured
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text().splitlines():
            key, separator, value = raw.partition("=")
            if separator and key.strip() == "WORKDEV_API_KEY":
                return value.strip().strip("\"'")
    raise RuntimeError("WORKDEV_API_KEY não configurada")


def request(method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}", data=body, method=method,
        headers={
            "X-API-Key": api_key(),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"WorkDev HTTP {error.code}: {detail[:500]}") from error


def main() -> int:
    parser = argparse.ArgumentParser(prog="workdev_agent")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("context", "start"):
        item = sub.add_parser(command)
        item.add_argument("run_id")
    for command in ("block", "review", "complete", "fail", "progress"):
        item = sub.add_parser(command)
        item.add_argument("run_id")
        item.add_argument("message")
    item = sub.add_parser("subtask")
    item.add_argument("run_id")
    item.add_argument("subtask_id")
    item.add_argument("status", choices=("todo", "doing", "done"))
    item.add_argument("result", nargs="?")
    args = parser.parse_args()

    if args.command == "context":
        data = request("GET", f"/handoffs/runs/{args.run_id}/context")
        print(data["prompt"])
        return 0
    if args.command == "subtask":
        data = request(
            "PATCH",
            f"/handoffs/runs/{args.run_id}/subtasks/{args.subtask_id}",
            {"status": args.status, "result": args.result},
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    payloads = {
        "start": {"status": "running", "message": "Agent iniciou o Build"},
        "block": {"status": "blocked", "error": getattr(args, "message", None),
                  "message": getattr(args, "message", None)},
        "review": {"status": "review", "summary": getattr(args, "message", None),
                   "message": getattr(args, "message", None)},
        "complete": {"status": "completed", "result": getattr(args, "message", None),
                     "summary": getattr(args, "message", None),
                     "message": "Build concluído pelo Agent"},
        "fail": {"status": "failed", "error": getattr(args, "message", None),
                 "message": getattr(args, "message", None)},
        "progress": {"message": getattr(args, "message", None)},
    }
    data = request("PATCH", f"/handoffs/runs/{args.run_id}", payloads[args.command])
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, urllib.error.URLError) as error:
        print(f"erro: {error}", file=sys.stderr)
        raise SystemExit(1)
