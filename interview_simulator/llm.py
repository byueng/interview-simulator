from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from interview_simulator.logging_config import get_logger
from interview_simulator.models import FinalEvaluation, InterviewReply, Question, StreamedReplyEvent, Turn


class ModelConfigError(ValueError):
    """模型配置缺失或格式不正确。"""


class ModelResponseError(RuntimeError):
    """模型服务失败，或未返回程序可用的结构化内容。"""


@dataclass(frozen=True, slots=True)
class ModelSettings:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env_file(cls, path: Path) -> "ModelSettings":
        values = _read_dotenv(path)
        base_url = os.environ.get("LLM_BASE_URL") or values.get("LLM_BASE_URL")
        api_key = os.environ.get("LLM_API_KEY") or values.get("LLM_API_KEY")
        model = os.environ.get("LLM_MODEL") or values.get("LLM_MODEL")
        if not base_url:
            raise ModelConfigError("缺少 LLM_BASE_URL")
        if not api_key:
            raise ModelConfigError("缺少 LLM_API_KEY")
        if not model:
            raise ModelConfigError("缺少 LLM_MODEL")
        return cls(base_url.rstrip("/"), api_key, model)


class OpenAICompatibleInterviewer:
    """使用 OpenAI-compatible Chat Completions 的中文 Agent 面试官。"""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        temperature: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.temperature = temperature
        self.transport = transport

    async def follow_up(self, *, question: Question, transcript: list[Turn]) -> InterviewReply:
        payload = await self._chat(
            system=(
                "你是一位高标准的中文 AI Agent 工程师面试官。基于候选人的真实回答和题库参考内容，"
                "直接指出技术错误、缺失的工程边界或空泛之处，再只提出一个能继续下钻的问题。"
                "不得虚构候选人说过的内容，也不得给泛泛鼓励。"
            ),
            user=(
                f"题目：{question.title}\n模块：{question.module}\n难度：{question.difficulty}\n\n"
                f"参考解析（不可泄露为标准答案）：\n{question.reference_markdown}\n\n"
                f"当前面试记录：\n{_format_transcript(transcript)}\n\n"
                "只返回 JSON：{\"feedback\": \"即时批评与解释\", \"next_question\": \"一个追问\"}"
            ),
        )
        return InterviewReply(
            feedback=_required_text(payload, "feedback"),
            next_question=_required_text(payload, "next_question"),
        )

    async def stream_follow_up(
        self, *, question: Question, transcript: list[Turn]
    ) -> AsyncIterator[StreamedReplyEvent]:
        response_text: list[str] = []
        async for text in self._stream_chat(
            system=(
                "你是一位高标准的中文 AI Agent 工程师面试官。基于候选人的真实回答和题库参考内容，"
                "直接指出技术错误、缺失的工程边界或空泛之处，再只提出一个能继续下钻的问题。"
                "不得虚构候选人说过的内容，也不得给泛泛鼓励。"
            ),
            user=(
                f"题目：{question.title}\n模块：{question.module}\n难度：{question.difficulty}\n\n"
                f"参考解析（不可泄露为标准答案）：\n{question.reference_markdown}\n\n"
                f"当前面试记录：\n{_format_transcript(transcript)}\n\n"
                "只返回 JSON：{\"feedback\": \"即时批评与解释\", \"next_question\": \"一个追问\"}"
            ),
        ):
            response_text.append(text)
            yield StreamedReplyEvent(text=text)

        payload = _parse_json_object("".join(response_text))
        yield StreamedReplyEvent(
            reply=InterviewReply(
                feedback=_required_text(payload, "feedback"),
                next_question=_required_text(payload, "next_question"),
            )
        )

    async def evaluate(self, *, question: Question, transcript: list[Turn]) -> FinalEvaluation:
        payload = await self._chat(
            system=(
                "你是一位高标准的中文 AI Agent 工程师面试官。请对整场面试给中肯且详细的最终评价。"
                "优点必须对应候选人的原话；没有提到的工程能力不得补分；错误和模糊表达要明确说明。"
                "分数为 0 到 10，可使用 0.5；4 分表示基本表达，7 分以上要求工程实现，"
                "8 分以上要求工程边界与取舍。"
            ),
            user=(
                f"原题：{question.title}\n\n参考解析：\n{question.reference_markdown}\n\n"
                f"完整面试记录：\n{_format_transcript(transcript)}\n\n"
                "只返回 JSON："
                "{\"score\": 0, \"verdict\": \"一句结论\", \"interviewer_feedback\": \"详细长评\", "
                "\"strengths\": [\"具体优点\"], \"issues\": [\"具体问题\"], "
                "\"answer_upgrade_suggestions\": [\"可补充的工程点\"], "
                "\"follow_up_questions\": [\"后续值得练习的问题\"]}"
            ),
        )
        return _final_evaluation(payload)

    async def stream_evaluate(
        self, *, question: Question, transcript: list[Turn]
    ) -> AsyncIterator[StreamedReplyEvent]:
        response_text: list[str] = []
        async for text in self._stream_chat(
            system=(
                "你是一位高标准的中文 AI Agent 工程师面试官。请对整场面试给中肯且详细的最终评价。"
                "优点必须对应候选人的原话；没有提到的工程能力不得补分；错误和模糊表达要明确说明。"
                "分数为 0 到 10，可使用 0.5；4 分表示基本表达，7 分以上要求工程实现，"
                "8 分以上要求工程边界与取舍。"
            ),
            user=(
                f"原题：{question.title}\n\n参考解析：\n{question.reference_markdown}\n\n"
                f"完整面试记录：\n{_format_transcript(transcript)}\n\n"
                "只返回 JSON："
                "{\"score\": 0, \"verdict\": \"一句结论\", \"interviewer_feedback\": \"详细长评\", "
                "\"strengths\": [\"具体优点\"], \"issues\": [\"具体问题\"], "
                "\"answer_upgrade_suggestions\": [\"可补充的工程点\"], "
                "\"follow_up_questions\": [\"后续值得练习的问题\"]}"
            ),
        ):
            response_text.append(text)
            yield StreamedReplyEvent(text=text)
        yield StreamedReplyEvent(reply=_final_evaluation(_parse_json_object("".join(response_text))))

    async def _chat(self, *, system: str, user: str) -> dict[str, Any]:
        request_body = {
            "model": self.settings.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(
                base_url=f"{self.settings.base_url}/",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                transport=self.transport,
                timeout=90.0,
            ) as client:
                response = await client.post("chat/completions", json=request_body)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            get_logger().warning(
                "model_request failed status=%s model=%s",
                exc.response.status_code,
                self.settings.model,
            )
            raise ModelResponseError(f"模型服务请求失败：HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            get_logger().warning("model_request failed reason=connection model=%s", self.settings.model)
            raise ModelResponseError("无法连接模型服务") from exc

        get_logger().info("model_request succeeded model=%s", self.settings.model)

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelResponseError("模型服务响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ModelResponseError("模型响应 content 必须是字符串")
        return _parse_json_object(content)

    async def _stream_chat(self, *, system: str, user: str) -> AsyncIterator[str]:
        request_body = {
            "model": self.settings.model,
            "temperature": self.temperature,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        emitted_text = False
        try:
            async with httpx.AsyncClient(
                base_url=f"{self.settings.base_url}/",
                headers={"Authorization": f"Bearer {self.settings.api_key}"},
                transport=self.transport,
                timeout=90.0,
            ) as client:
                async with client.stream("POST", "chat/completions", json=request_body) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            payload = json.loads(data)
                            content = payload["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError, ValueError) as exc:
                            raise ModelResponseError("模型流式响应缺少 choices[0].delta.content") from exc
                        if content is None:
                            continue
                        if not isinstance(content, str):
                            raise ModelResponseError("模型流式响应 content 必须是字符串")
                        if content:
                            emitted_text = True
                            yield content
        except httpx.HTTPStatusError as exc:
            get_logger().warning(
                "model_stream failed status=%s model=%s",
                exc.response.status_code,
                self.settings.model,
            )
            raise ModelResponseError(f"模型流式请求失败：HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            get_logger().warning("model_stream failed reason=connection model=%s", self.settings.model)
            raise ModelResponseError("无法连接模型流式服务") from exc

        if not emitted_text:
            raise ModelResponseError("模型流式响应没有生成文本")
        get_logger().info("model_stream succeeded model=%s", self.settings.model)


def _read_dotenv(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ModelConfigError(f"找不到环境文件：{path}") from exc
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").strip()
        key, separator, value = stripped.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _format_transcript(transcript: list[Turn]) -> str:
    if not transcript:
        return "候选人尚未回答。"
    parts: list[str] = []
    for turn in transcript:
        parts.append(f"第 {turn.round_no} 轮\n问题：{turn.question}\n回答：{turn.answer}")
        if turn.feedback:
            parts.append(f"即时反馈：{turn.feedback}")
    return "\n\n".join(parts)


def _parse_json_object(content: str) -> dict[str, Any]:
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```")
        if normalized.endswith("```"):
            normalized = normalized[:-3]
        normalized = normalized.strip()
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ModelResponseError("模型没有返回合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ModelResponseError("模型 JSON 顶层必须是对象")
    return payload


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ModelResponseError(f"模型字段 {field} 必须是非空字符串")
    return value.strip()


def _text_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ModelResponseError(f"模型字段 {field} 必须是非空字符串列表")
    return [item.strip() for item in value]


def _final_evaluation(payload: dict[str, Any]) -> FinalEvaluation:
    score = payload.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 10:
        raise ModelResponseError("模型评分必须是 0 到 10 的数字")
    return FinalEvaluation(
        score=float(score),
        verdict=_required_text(payload, "verdict"),
        interviewer_feedback=_required_text(payload, "interviewer_feedback"),
        strengths=_text_list(payload, "strengths"),
        issues=_text_list(payload, "issues"),
        answer_upgrade_suggestions=_text_list(payload, "answer_upgrade_suggestions"),
        follow_up_questions=_text_list(payload, "follow_up_questions"),
    )
