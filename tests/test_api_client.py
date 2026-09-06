from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
import pytest

from interview_simulator.api_client import HttpPracticeApi, LocalApiError


class ApiSseStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield 'data: {"event":"delta","field":"feedback","text":"需要"}\n\n'.encode("utf-8")
        yield 'data: {"event":"completed","payload":{"ended":false,"next_question":"追问"}}\n\n'.encode("utf-8")

    async def aclose(self) -> None:
        return None


def mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/questions":
            assert request.url.params["page"] == "2"
            assert request.url.params["page_size"] == "15"
            return httpx.Response(200, json={"page": 2, "page_size": 15, "total": 20, "items": []})
        if request.method == "POST" and request.url.path == "/sessions":
            assert json.loads(request.content) == {"question_id": "006", "mode": "deep"}
            return httpx.Response(201, json={"id": "session-1", "status": "active"})
        if request.method == "POST" and request.url.path == "/sessions/session-1/turns":
            assert json.loads(request.content) == {"answer": "我的回答"}
            return httpx.Response(200, json={"ended": False, "feedback": "继续", "next_question": "追问"})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


async def test_http_practice_api_maps_tui_calls_to_local_api_requests() -> None:
    api = HttpPracticeApi("http://127.0.0.1:8765/", transport=mock_transport())

    questions = await api.list_questions(page=2, page_size=15)
    session = await api.create_session(question_id="006", mode="deep")
    turn = await api.submit_turn(session_id="session-1", answer="我的回答")

    assert questions["total"] == 20
    assert session["id"] == "session-1"
    assert turn["next_question"] == "追问"


async def test_http_practice_api_hides_response_body_when_local_service_errors() -> None:
    api = HttpPracticeApi(
        "http://127.0.0.1:8765",
        transport=httpx.MockTransport(lambda _: httpx.Response(500, text="internal details")),
    )

    with pytest.raises(LocalApiError, match="HTTP 500") as exc_info:
        await api.list_questions(page=1, page_size=15)

    assert "internal details" not in str(exc_info.value)


async def test_http_practice_api_reads_each_sse_stream_event() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/sessions/session-1/turns/stream"
        assert json.loads(request.content) == {"answer": "我的回答"}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ApiSseStream())

    api = HttpPracticeApi("http://127.0.0.1:8765", transport=httpx.MockTransport(handler))
    events = [event async for event in api.stream_turn(session_id="session-1", answer="我的回答")]

    assert events[0] == {"event": "delta", "field": "feedback", "text": "需要"}
    assert events[-1]["payload"]["next_question"] == "追问"
