from __future__ import annotations

import pytest
from textual.app import SuspendNotSupported
from textual.widgets import Static

from interview_simulator import tui
from interview_simulator.tui import PracticeApp


class FakePracticeApi:
    async def list_questions(self, *, page: int, page_size: int) -> dict[str, object]:
        return {
            "page": page,
            "page_size": page_size,
            "total": 1,
            "items": [
                {
                    "id": "006",
                    "module": "Agent 架构",
                    "difficulty": "中级",
                    "practiced": False,
                    "latest_score": None,
                    "title": "如何控制 Agent Loop？",
                }
            ],
        }

    async def create_session(self, *, question_id: str, mode: str) -> dict[str, object]:
        assert question_id == "006"
        assert mode == "deep"
        return {"id": "session-1", "title": "如何控制 Agent Loop？", "status": "active"}

    async def submit_turn(self, *, session_id: str, answer: str) -> dict[str, object]:
        raise AssertionError("TUI 应调用流式接口，而不是一次性提交接口")

    async def stream_turn(self, *, session_id: str, answer: str):
        assert session_id == "session-1"
        assert answer == "我会设置最大步数。"
        yield {"event": "delta", "field": "feedback", "text": "max_steps 只能止损，你还缺少"}
        yield {"event": "delta", "field": "feedback", "text": "任务完成判定。"}
        yield {"event": "delta", "field": "next_question", "text": "怎样判断任务已经完成？"}
        yield {
            "event": "completed",
            "payload": {
                "ended": False,
                "feedback": "max_steps 只能止损，你还缺少任务完成判定。",
                "next_question": "怎样判断任务已经完成？",
                "evaluation": None,
            },
        }


@pytest.mark.asyncio
async def test_practice_tui_selects_question_starts_deep_session_and_submits_answer() -> None:
    app = PracticeApp(FakePracticeApi(), page_size=15)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "如何控制 Agent Loop" in str(app.screen.query_one("#question-title", Static).render())

        await pilot.press("enter")
        await pilot.pause()
        answer = app.screen.query_one("#answer-input")
        answer.text = "我会设置最大步数。"
        await pilot.click("#submit-answer")
        await pilot.pause()

        transcript = app.screen.query_one("#transcript", Static)
        assert "任务完成判定" in str(transcript.render())
        assert "怎样判断任务已经完成" in str(transcript.render())


@pytest.mark.asyncio
async def test_practice_tui_f2_fills_answer_from_terminal_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tui, "read_terminal_answer", lambda app: "我会限制最大轮数，并设置完成判定。")
    app = PracticeApp(FakePracticeApi(), page_size=15)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()

        answer = app.screen.query_one("#answer-input")
        assert answer.text == "我会限制最大轮数，并设置完成判定。"


@pytest.mark.asyncio
async def test_practice_tui_visible_terminal_input_button_fills_chinese_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tui, "read_terminal_answer", lambda app: "这是普通终端直接输入的中文回答。")
    app = PracticeApp(FakePracticeApi(), page_size=15)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#terminal-input")
        await pilot.pause()

        answer = app.screen.query_one("#answer-input")
        assert answer.text == "这是普通终端直接输入的中文回答。"


@pytest.mark.asyncio
async def test_practice_tui_f2_preserves_answer_when_terminal_suspend_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported_terminal_input(app: object) -> str:
        raise SuspendNotSupported()

    monkeypatch.setattr(tui, "read_terminal_answer", unsupported_terminal_input)
    app = PracticeApp(FakePracticeApi(), page_size=15)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause()
        answer = app.screen.query_one("#answer-input")
        answer.text = "原有回答"

        await pilot.press("f2")
        await pilot.pause()

        assert answer.text == "原有回答"
        status = app.screen.query_one("#interview-status", Static)
        assert "Cmd+V" in str(status.render())
