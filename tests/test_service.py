from __future__ import annotations

from pathlib import Path

import pytest

from interview_simulator.models import FinalEvaluation, InterviewReply
from interview_simulator.logging_config import configure_logging
from interview_simulator.llm import StreamedReplyEvent
from interview_simulator.question_bank import QuestionBank
from interview_simulator.service import InterviewService
from interview_simulator.storage import SQLiteStorage


class FakeInterviewer:
    def __init__(self) -> None:
        self.follow_up_calls = 0
        self.evaluate_calls = 0

    async def follow_up(self, **_: object) -> InterviewReply:
        self.follow_up_calls += 1
        return InterviewReply(
            feedback="这里仍缺少失败恢复策略。",
            next_question="如果工具超时，状态应该如何保存？",
        )

    async def evaluate(self, **_: object) -> FinalEvaluation:
        self.evaluate_calls += 1
        return FinalEvaluation(
            score=6.5,
            verdict="概念正确，但工程边界不完整。",
            interviewer_feedback="需要补充超时和幂等设计。",
            strengths=["说出了基本流程"],
            issues=["没有失败恢复"],
            answer_upgrade_suggestions=["说明状态机和重试上限"],
            follow_up_questions=["如何保证幂等？"],
        )


class StreamingFakeInterviewer(FakeInterviewer):
    async def stream_follow_up(self, **_: object):
        yield StreamedReplyEvent(text='{"feedback":"max_')
        yield StreamedReplyEvent(text='steps 只能止损。","next_question":"怎样判断')
        yield StreamedReplyEvent(text='任务已经完成？"}')
        yield StreamedReplyEvent(reply=InterviewReply("max_steps 只能止损。", "怎样判断任务已经完成？"))

    async def stream_evaluate(self, **_: object):
        evaluation = await self.evaluate()
        yield StreamedReplyEvent(text='{"score":6.5,"interviewer_feedback":"需要补充')
        yield StreamedReplyEvent(text='失败恢复。"}')
        yield StreamedReplyEvent(reply=evaluation)


@pytest.fixture
def service(tmp_path: Path) -> tuple[InterviewService, FakeInterviewer]:
    module = tmp_path / "01-agent-architecture"
    module.mkdir()
    (module / "006-agent-loop.md").write_text(
        "# 如何控制 Agent Loop？\n\n> 难度：中级\n> 分类：Agent 架构\n\n## 简短回答\n\n使用状态机。\n",
        encoding="utf-8",
    )
    interviewer = FakeInterviewer()
    return InterviewService(QuestionBank.scan(tmp_path), SQLiteStorage(tmp_path / "practice.db"), interviewer), interviewer


async def test_deep_session_finishes_after_tenth_answer(service: tuple[InterviewService, FakeInterviewer]) -> None:
    interview, interviewer = service
    session = await interview.create_session("006", "deep")

    for _ in range(9):
        result = await interview.submit_answer(session.id, "我会保存状态并限制重试次数。")
        assert result.ended is False

    result = await interview.submit_answer(session.id, "我会对副作用操作做幂等控制。")

    assert result.ended is True
    assert result.evaluation is not None
    assert interviewer.follow_up_calls == 9
    assert interviewer.evaluate_calls == 1


async def test_exact_i_dont_know_ends_but_substantive_uncertainty_continues(
    service: tuple[InterviewService, FakeInterviewer],
) -> None:
    interview, interviewer = service
    ended_session = await interview.create_session("006", "deep")
    continued_session = await interview.create_session("006", "deep")

    ended = await interview.submit_answer(ended_session.id, "我不知道")
    continued = await interview.submit_answer(continued_session.id, "我不确定，但会先限制重试次数。")

    assert ended.ended is True
    assert continued.ended is False
    assert interviewer.evaluate_calls == 1


async def test_single_session_ends_after_its_first_answer(
    service: tuple[InterviewService, FakeInterviewer], tmp_path: Path
) -> None:
    configure_logging(tmp_path / "logs")
    interview, interviewer = service
    session = await interview.create_session("006", "single")

    result = await interview.submit_answer(session.id, "答案")

    assert result.ended is True
    assert interviewer.follow_up_calls == 0
    assert interviewer.evaluate_calls == 1
    log_text = (tmp_path / "logs" / "interview-simulator.log").read_text(encoding="utf-8")
    assert "session_created question_id=006 mode=single" in log_text
    assert "session_finished question_id=006 score=6.5" in log_text


async def test_stream_answer_emits_visible_deltas_and_saves_only_after_completion(
    service: tuple[InterviewService, FakeInterviewer],
) -> None:
    interview, _ = service
    interview.interviewer = StreamingFakeInterviewer()
    session = await interview.create_session("006", "deep")

    stream = interview.stream_answer(session.id, "设置 max_steps")
    first_event = await anext(stream)

    assert first_event == {"event": "delta", "field": "feedback", "text": "max_"}
    assert interview.storage.get_session(session.id).turns == ()

    remaining_events = [event async for event in stream]

    assert {"event": "delta", "field": "next_question", "text": "怎样判断"} in remaining_events
    assert remaining_events[-1]["event"] == "completed"
    assert interview.storage.get_session(session.id).turns[0].next_question == "怎样判断任务已经完成？"


async def test_stream_single_answer_shows_final_review_before_persisting_score(
    service: tuple[InterviewService, FakeInterviewer],
) -> None:
    interview, _ = service
    interview.interviewer = StreamingFakeInterviewer()
    session = await interview.create_session("006", "single")

    events = [event async for event in interview.stream_answer(session.id, "设置 max_steps")]

    assert {"event": "delta", "field": "interviewer_feedback", "text": "需要补充"} in events
    assert events[-1]["event"] == "completed"
    assert events[-1]["result"].ended is True
    assert interview.storage.get_session(session.id).final_score == 6.5
