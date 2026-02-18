"""Feedback ingestion and immediate memory patching."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from vanna.core.tool import ToolContext


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    question: Optional[str] = None
    original_sql: Optional[str] = None
    corrected_sql: Optional[str] = None
    reason_codes: List[str] = Field(default_factory=list)
    user_edits: Optional[str] = None
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None
    enqueue_for_review: bool = False


class FeedbackResult(BaseModel):
    feedback_id: str
    patched_memories: int
    review_queued: bool
    status: str = "accepted"


class FeedbackService:
    """Processes user feedback and patches memory immediately."""

    def __init__(
        self,
        *,
        feedback_log_path: str = ".vanna/feedback_log.jsonl",
        review_queue_path: str = ".vanna/review_queue.jsonl",
    ):
        self.feedback_log_path = Path(feedback_log_path)
        self.review_queue_path = Path(review_queue_path)

    async def process_feedback(
        self, request: FeedbackRequest, context: ToolContext
    ) -> FeedbackResult:
        feedback_id = f"fb_{uuid.uuid4().hex[:10]}"
        now = datetime.utcnow().isoformat()
        patched = 0

        provenance = {
            "feedback_id": feedback_id,
            "rating": request.rating,
            "reason_codes": request.reason_codes,
            "timestamp": now,
            "conversation_id": request.conversation_id,
            "request_id": request.request_id,
        }

        # Negative patch for incorrect SQL patterns.
        if request.rating == "down" and request.original_sql and request.question:
            await context.agent_memory.save_tool_usage(
                question=request.question,
                tool_name="run_sql",
                args={"sql": request.original_sql},
                context=context,
                success=False,
                metadata={"patch_type": "negative", "weight": 2.0, **provenance},
            )
            patched += 1

        # Corrective positive patch with high weight for immediate behavior changes.
        if request.corrected_sql and request.question:
            await context.agent_memory.save_tool_usage(
                question=request.question,
                tool_name="run_sql",
                args={"sql": request.corrected_sql},
                context=context,
                success=True,
                metadata={"patch_type": "corrective", "weight": 5.0, **provenance},
            )
            patched += 1

        payload: Dict[str, Any] = {
            "feedback_id": feedback_id,
            "timestamp": now,
            **request.model_dump(),
            "patched_memories": patched,
        }
        self._append_jsonl(self.feedback_log_path, payload)

        review_queued = request.enqueue_for_review
        if review_queued:
            self._append_jsonl(
                self.review_queue_path,
                {
                    **payload,
                    "review_status": "pending",
                },
            )

        return FeedbackResult(
            feedback_id=feedback_id,
            patched_memories=patched,
            review_queued=review_queued,
        )

    def _append_jsonl(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
