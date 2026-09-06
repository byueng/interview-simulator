from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest

from interview_simulator.logging_config import configure_logging
from interview_simulator.llm import ModelResponseError, ModelSettings, OpenAICompatibleInterviewer
from interview_simulator.models import FinalEvaluation, InterviewReply, Question, Turn


class SseStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def question() -> Question:
    return Question(
        id="006",
        title="如何控制 Agent Loop？",
        module="Agent 架构",
        difficulty="中级",
        relative_path="01-agent-architecture/006-agent-loop.md",
        source_hash="hash",
        reference_markdown="# 如何控制 Agent Loop？\n\n使用 max_steps 与状态机。",
    )


def transport_with(content: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["temperature"] == 0.9
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    return httpx.MockTransport(handler)


async def test_follow_up_parses_critic_and_next_question_from_openai_response() -> None:
    interviewer = OpenAICompatibleInterviewer(
        ModelSettings("https://example.test/v1", "test-key", "test-model"),
        temperature=0.9,
        transport=transport_with({"feedback": "max_steps 只能止损。", "next_question": "如何识别无效循环？"}),
    )

    reply = await interviewer.follow_up(
        question=question(),
        transcript=[Turn(1, "如何控制 Agent Loop？", "设置 max_steps", "", None, "")],
    )

    assert reply.feedback == "max_steps 只能止损。"
    assert reply.next_question == "如何识别无效循环？"


async def test_evaluate_parses_detailed_chinese_scorecard() -> None:
    interviewer = OpenAICompatibleInterviewer(
        ModelSettings("https://example.test/v1", "test-key", "test-model"),
        temperature=0.9,
        transport=transport_with(
            {
                "score": 6.5,
                "verdict": "基本正确，但工程细节不足。",
                "interviewer_feedback": "你说清了主流程，但没有讨论异常恢复。",
                "strengths": ["知道 max_steps"],
                "issues": ["没有失败状态"],
                "answer_upgrade_suggestions": ["补充重试和熔断"],
                "follow_up_questions": ["怎样恢复中断任务？"],
            }
        ),
    )

    evaluation = await interviewer.evaluate(question=question(), transcript=[])

    assert evaluation.score == 6.5
    assert evaluation.issues == ["没有失败状态"]


def test_model_settings_reads_only_expected_env_names(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_BASE_URL=https://example.test/v1\nLLM_API_KEY=test-key\nLLM_MODEL=test-model\n", encoding="utf-8")

    settings = ModelSettings.from_env_file(env_file)

    assert settings.base_url == "https://example.test/v1"
    assert settings.model == "test-model"


async def test_model_http_failure_is_logged_without_api_key(tmp_path: Path) -> None:
    configure_logging(tmp_path / "logs")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    interviewer = OpenAICompatibleInterviewer(
        ModelSettings("https://example.test/v1", "super-secret-key", "test-model"),
        temperature=0.9,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelResponseError, match="HTTP 401"):
        await interviewer.follow_up(question=question(), transcript=[])

    log_text = (tmp_path / "logs" / "interview-simulator.log").read_text(encoding="utf-8")
    assert "model_request failed status=401" in log_text
    assert "super-secret-key" not in log_text


async def test_follow_up_streams_sse_deltas_then_a_validated_reply() -> None:
    text_chunks = [
        '{"feedback":"max_',
        'steps 只能止损。","next_question":"怎样判断',
        '任务已经完成？"}',
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        sse_chunks = [
            f"data: {json.dumps({'choices': [{'delta': {'content': text}}]}, ensure_ascii=False)}\n\n".encode("utf-8")
            for text in text_chunks
        ]
        sse_chunks.append(b"data: [DONE]\n\n")
        return httpx.Response(200, stream=SseStream(sse_chunks))

    interviewer = OpenAICompatibleInterviewer(
        ModelSettings("https://example.test/v1", "test-key", "test-model"),
        temperature=0.9,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in interviewer.stream_follow_up(question=question(), transcript=[])]

    assert [event.text for event in events[:-1]] == text_chunks
    assert events[-1].reply == InterviewReply("max_steps 只能止损。", "怎样判断任务已经完成？")


async def test_evaluate_streams_sse_deltas_then_a_validated_scorecard() -> None:
    response_text = json.dumps(
        {
            "score": 6.5,
            "verdict": "基础正确。",
            "interviewer_feedback": "需要补充失败恢复。",
            "strengths": ["提到了 max_steps"],
            "issues": ["没有完成判定"],
            "answer_upgrade_suggestions": ["说明状态机"],
            "follow_up_questions": ["如何恢复？"],
        },
        ensure_ascii=False,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=SseStream(
                [
                    f"data: {json.dumps({'choices': [{'delta': {'content': response_text[:40]}}]}, ensure_ascii=False)}\n\n".encode(),
                    f"data: {json.dumps({'choices': [{'delta': {'content': response_text[40:]}}]}, ensure_ascii=False)}\n\n".encode(),
                    b"data: [DONE]\n\n",
                ]
            ),
        )

    interviewer = OpenAICompatibleInterviewer(
        ModelSettings("https://example.test/v1", "test-key", "test-model"),
        temperature=0.9,
        transport=httpx.MockTransport(handler),
    )

    events = [event async for event in interviewer.stream_evaluate(question=question(), transcript=[])]

    assert isinstance(events[-1].reply, FinalEvaluation)
    assert events[-1].reply.score == 6.5
