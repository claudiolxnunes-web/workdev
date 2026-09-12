#!/usr/bin/env python3
"""Exporta exemplos validados de AgentRunReview para JSONL de treino.

Critérios:
- payload.training_candidate == true
- gate_passed == true
- verdict == approved

O script é somente leitura no banco.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/opt/workdev")
API = ROOT / "apps" / "api"

sys.path.insert(0, str(API))

from app.database import SessionLocal  # noqa: E402
from app.models.handoff import AgentRun, AgentRunReview  # noqa: E402


OUT_DIR = ROOT / "training" / "feedback"
OUT_FILE = OUT_DIR / "validated-training.jsonl"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()

    try:
        rows = (
            db.query(AgentRunReview, AgentRun)
            .join(AgentRun, AgentRun.id == AgentRunReview.run_id)
            .filter(
                AgentRunReview.verdict == "approved",
                AgentRunReview.gate_passed.is_(True),
            )
            .order_by(AgentRunReview.created_at.asc())
            .all()
        )

        exported = 0

        with OUT_FILE.open("w", encoding="utf-8") as f:
            for review, run in rows:
                payload = review.payload or {}

                if payload.get("training_candidate") is not True:
                    continue

                item = {
                    "schema_version": 1,
                    "run_id": str(run.id),
                    "backlog_id": str(run.backlog_id),
                    "agent": run.agent,
                    "model": run.model,
                    "reviewer_agent": review.reviewer_agent,
                    "attempt": review.attempt,
                    "verdict": review.verdict,
                    "gate_passed": review.gate_passed,
                    "feedback_category": payload.get("feedback_category"),
                    "feedback_confidence": payload.get("feedback_confidence"),
                    "feedback_reason": payload.get("feedback_reason"),
                    "complexity": payload.get("complexity"),
                    "complexity_score": payload.get("complexity_score"),
                    "reasoning_effort": payload.get("reasoning_effort"),
                    "routing_mode": payload.get("routing_mode"),
                    "result": run.result,
                    "review_feedback": review.feedback,
                    "created_at": (
                        review.created_at.isoformat()
                        if review.created_at
                        else None
                    ),
                }

                f.write(
                    json.dumps(
                        item,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                exported += 1

        print(f"OK: {exported} exemplo(s) exportado(s)")
        print(f"Arquivo: {OUT_FILE}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
