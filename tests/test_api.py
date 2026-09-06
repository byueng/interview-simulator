from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from interview_simulator.api import create_app
from interview_simulator.logging_config import configure_logging
from interview_simulator.llm import StreamedReplyEvent
from interview_simulator.models import FinalEvaluation, InterviewReply
from interview_simulator.question_bank import QuestionBank
from interview_simulator.service import InterviewService
from interview_simulator.storage import SQLiteStorage


class FakeInterviewer:
    async def follow_up(self, **_: object) -> InterviewReply:
        return InterviewReply("你还需要说明幂等处理。", "副作用操作如何保证幂等？")

    async def evaluate(self, **_: object) -> FinalEvaluation:
        return FinalEvaluation(7.0, "回答有基础", "补充失败恢复即可。", ["知道主流程"], ["缺幂等"], ["说明幂等键"], [])

    async def stream_follow_up(self, **_: object):
        yield StreamedReplyEvent(text='{"feedback":"需要')
        yield StreamedReplyEvent(text='补充幂等。","next_question":"副作用如何控制？"}')
        yield StreamedReplyEvent(reply=InterviewReply("需要补充幂等。", "副作用如何控制？"))


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    module = tmp_path / "03-tool-use"
    module.mkdir()
    (module / "022-tool-schema.md").write_text(
        "# 如何定义 Tool Schema？\n\n> 难度：基础\n> 分类：Tool Use\n\n## 简短回答\n\n参数需要校验。\n",
        encoding="utf-8",
    )
    bank = QuestionBank.scan(tmp_path)
    storage = SQLiteStorage(tmp_path / "practice.db")
    service = InterviewService(bank, storage, FakeInterviewer())
    return TestClient(create_app(service, bank, storage))


def test_questions_endpoint_returns_page_metadata_and_progress(client: TestClient) -> None:
    response = client.get("/questions?page=1&page_size=15")

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 15
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "022"
    assert payload["items"][0]["practiced"] is False


def test_single_session_ends_after_one_answer_and_updates_progress(client: TestClient) -> None:
    created = client.post("/sessions", json={"question_id": "022", "mode": "single"})
    session_id = created.json()["id"]

    result = client.post(f"/sessions/{session_id}/turns", json={"answer": "我会定义参数类型和必填字段。"})
    questions = client.get("/questions?page=1&page_size=15")

    assert created.status_code == 201
    assert result.status_code == 200
    assert result.json()["ended"] is True
    assert result.json()["evaluation"]["score"] == 7.0
    assert questions.json()["items"][0]["latest_score"] == 7.0


def test_unknown_question_returns_404(client: TestClient) -> None:
    response = client.post("/sessions", json={"question_id": "999", "mode": "deep"})

    assert response.status_code == 404


def test_stream_turn_endpoint_emits_sse_deltas_then_completed_payload(client: TestClient) -> None:
    session_id = client.post("/sessions", json={"question_id": "022", "mode": "deep"}).json()["id"]

    response = client.post(f"/sessions/{session_id}/turns/stream", json={"answer": "定义参数类型"})
    events = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")]

    assert response.headers["content-type"].startswith("text/event-stream")
    assert {"event": "delta", "field": "feedback", "text": "需要"} in events
    assert events[-1]["event"] == "completed"
    assert events[-1]["payload"]["next_question"] == "副作用如何控制？"


def test_api_request_writes_method_path_status_and_duration_to_backend_log(tmp_path: Path) -> None:
    configure_logging(tmp_path / "logs")
    module = tmp_path / "03-tool-use"
    module.mkdir()
    (module / "022-tool-schema.md").write_text(
        "# 如何定义 Tool Schema？\n\n> 难度：基础\n> 分类：Tool Use\n",
        encoding="utf-8",
    )
    bank = QuestionBank.scan(tmp_path)
    storage = SQLiteStorage(tmp_path / "practice.db")
    app = create_app(InterviewService(bank, storage, FakeInterviewer()), bank, storage)

    response = TestClient(app).get("/health")

    log_text = (tmp_path / "logs" / "interview-simulator.log").read_text(encoding="utf-8")
    assert response.status_code == 200
    assert "GET /health status=200" in log_text
    assert "duration_ms=" in log_text
