from __future__ import annotations

import time
import json
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from interview_simulator.logging_config import get_logger
from interview_simulator.models import Session, SubmitResult
from interview_simulator.question_bank import QuestionBank, QuestionNotFoundError
from interview_simulator.service import InterviewService
from interview_simulator.storage import SQLiteStorage, SessionNotFoundError


class CreateSessionRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=16)
    mode: Literal["single", "deep"]


class SubmitTurnRequest(BaseModel):
    answer: str = Field(min_length=1)


def create_app(service: InterviewService, bank: QuestionBank, storage: SQLiteStorage) -> FastAPI:
    app = FastAPI(title="Interview Simulator Local API", version="1.0.0")
    logger = get_logger()

    @app.middleware("http")
    async def log_request(request: Request, call_next: Any) -> Any:
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1_000
            logger.exception(
                "%s %s status=500 duration_ms=%.1f",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - started_at) * 1_000
        logger.info(
            "%s %s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/questions")
    def list_questions(
        page: int = Query(default=1, ge=1), page_size: int = Query(default=15, ge=1, le=100)
    ) -> dict[str, Any]:
        items, total = bank.page(page, page_size)
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [_question_payload(question, storage) for question in items],
        }

    @app.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
        try:
            session = await service.create_session(request.question_id, request.mode)
        except QuestionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="题号不存在") from exc
        return _session_payload(session, include_turns=False)

    @app.post("/sessions/{session_id}/turns")
    async def submit_turn(session_id: str, request: SubmitTurnRequest) -> dict[str, Any]:
        try:
            result = await service.submit_answer(session_id, request.answer)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="面试会话不存在") from exc
        except (QuestionNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _submit_payload(result)

    @app.post("/sessions/{session_id}/turns/stream")
    async def stream_turn(session_id: str, request: SubmitTurnRequest) -> StreamingResponse:
        async def events() -> Any:
            try:
                async for event in service.stream_answer(session_id, request.answer):
                    if event["event"] == "completed":
                        result = event["result"]
                        assert isinstance(result, SubmitResult)
                        payload: dict[str, object] = {"event": "completed", "payload": _submit_payload(result)}
                    else:
                        payload = event
                    yield _sse(payload)
            except Exception as exc:
                logger.exception("stream_turn failed")
                yield _sse({"event": "error", "message": str(exc)})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/sessions/{session_id}/finish")
    async def finish_session(session_id: str) -> dict[str, Any]:
        try:
            result = await service.finish(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="面试会话不存在") from exc
        except (QuestionNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _submit_payload(result)

    @app.get("/sessions")
    def list_sessions() -> dict[str, Any]:
        return {"items": [_session_payload(item, include_turns=False) for item in storage.list_sessions()]}

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            session = storage.get_session(session_id)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="面试会话不存在") from exc
        return _session_payload(session, include_turns=True)

    @app.get("/questions/{question_id}/reference")
    def get_reference(question_id: str) -> dict[str, str]:
        try:
            question = bank.get(question_id)
        except QuestionNotFoundError as exc:
            raise HTTPException(status_code=404, detail="题号不存在") from exc
        return {"id": question.id, "reference_markdown": question.reference_markdown}

    return app


def _question_payload(question: Any, storage: SQLiteStorage) -> dict[str, Any]:
    progress = storage.latest_progress(question.id)
    return {
        "id": question.id,
        "title": question.title,
        "module": question.module,
        "difficulty": question.difficulty,
        "relative_path": question.relative_path,
        "practiced": progress is not None and progress.practiced,
        "latest_score": progress.latest_score if progress else None,
        "latest_practiced_at": progress.latest_practiced_at if progress else None,
    }


def _submit_payload(result: SubmitResult) -> dict[str, Any]:
    return {
        "session": _session_payload(result.session, include_turns=True),
        "ended": result.ended,
        "feedback": result.feedback,
        "next_question": result.next_question,
        "evaluation": result.evaluation.to_dict() if result.evaluation else None,
    }


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _session_payload(session: Session, *, include_turns: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": session.id,
        "question_id": session.question_id,
        "mode": session.mode,
        "title": session.title,
        "status": session.status,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "final_score": session.final_score,
        "final_evaluation": session.final_evaluation,
    }
    if include_turns:
        payload["turns"] = [
            {
                "round_no": turn.round_no,
                "question": turn.question,
                "answer": turn.answer,
                "feedback": turn.feedback,
                "next_question": turn.next_question,
                "created_at": turn.created_at,
            }
            for turn in session.turns
        ]
    return payload
