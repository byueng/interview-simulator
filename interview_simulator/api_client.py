from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx


class LocalApiError(RuntimeError):
    """本机 FastAPI 服务不可用或返回了无法使用的响应。"""


class HttpPracticeApi:
    """供 Textual 调用的本机 HTTP API 客户端。"""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout

    async def list_questions(self, *, page: int, page_size: int) -> dict[str, object]:
        return await self._request("GET", "/questions", params={"page": page, "page_size": page_size})

    async def create_session(self, *, question_id: str, mode: str) -> dict[str, object]:
        return await self._request("POST", "/sessions", json={"question_id": question_id, "mode": mode})

    async def submit_turn(self, *, session_id: str, answer: str) -> dict[str, object]:
        return await self._request("POST", f"/sessions/{session_id}/turns", json={"answer": answer})

    async def stream_turn(self, *, session_id: str, answer: str) -> AsyncIterator[dict[str, object]]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, transport=self.transport, timeout=None) as client:
                async with client.stream(
                    "POST", f"/sessions/{session_id}/turns/stream", json={"answer": answer}
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if not content_type.startswith("text/event-stream"):
                        raise LocalApiError("本机服务没有返回流式事件")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line.removeprefix("data:").strip())
                        except json.JSONDecodeError as exc:
                            raise LocalApiError("本机服务返回了损坏的流式事件") from exc
                        if not isinstance(event, dict):
                            raise LocalApiError("本机服务返回的流式事件必须是对象")
                        yield event
        except httpx.HTTPStatusError as exc:
            raise LocalApiError(f"本机服务请求失败：HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LocalApiError("无法连接本机面试服务") from exc

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, transport=self.transport, timeout=self.timeout) as client:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LocalApiError(f"本机服务请求失败：HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LocalApiError("无法连接本机面试服务") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise LocalApiError("本机服务返回的不是 JSON") from exc
        if not isinstance(payload, dict):
            raise LocalApiError("本机服务返回的 JSON 顶层必须是对象")
        return payload
