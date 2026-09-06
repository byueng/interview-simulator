from __future__ import annotations

from typing import AsyncIterator, Protocol

from interview_simulator.logging_config import get_logger
from interview_simulator.models import FinalEvaluation, InterviewReply, Session, StreamedReplyEvent, SubmitResult, Turn
from interview_simulator.question_bank import QuestionBank
from interview_simulator.storage import SQLiteStorage
from interview_simulator.streaming import JsonFieldStreamParser


MAX_DEEP_ROUNDS = 10
_INABILITY_ANSWERS = {"我不知道", "不知道", "不会", "没有思路", "跳过"}


class Interviewer(Protocol):
    async def follow_up(self, *, question: object, transcript: list[Turn]) -> InterviewReply: ...

    async def evaluate(self, *, question: object, transcript: list[Turn]) -> FinalEvaluation: ...


class InterviewService:
    def __init__(self, bank: QuestionBank, storage: SQLiteStorage, interviewer: Interviewer) -> None:
        self.bank = bank
        self.storage = storage
        self.interviewer = interviewer

    async def create_session(self, question_id: str, mode: str) -> Session:
        question = self.bank.get(question_id)
        session = self.storage.create_session(question.id, mode, question.source_hash, question.title)
        get_logger().info("session_created question_id=%s mode=%s", session.question_id, session.mode)
        return session

    async def submit_answer(self, session_id: str, answer: str) -> SubmitResult:
        session = self.storage.get_session(session_id)
        if session.status != "active":
            raise ValueError("该面试会话已经结束")
        if not answer.strip():
            raise ValueError("回答不能为空")
        if session.current_question is None:
            raise ValueError("该会话没有等待回答的问题")

        question = self.bank.get(session.question_id)
        round_no = len(session.turns) + 1
        pending_turn = Turn(round_no, session.current_question, answer, "", None, "")
        transcript = [*session.turns, pending_turn]
        get_logger().info("answer_submitted question_id=%s round=%s", session.question_id, round_no)
        ends_now = (
            session.mode == "single"
            or round_no >= MAX_DEEP_ROUNDS
            or _is_explicit_inability(answer)
        )

        if ends_now:
            self.storage.append_turn(session.id, round_no, session.current_question, answer, "", None)
            return await self._finish(session.id, question, self.storage.get_session(session.id))

        reply = await self.interviewer.follow_up(question=question, transcript=transcript)
        self.storage.append_turn(
            session.id,
            round_no,
            session.current_question,
            answer,
            reply.feedback,
            reply.next_question,
        )
        saved = self.storage.get_session(session.id)
        return SubmitResult(saved, False, reply.feedback, reply.next_question, None)

    async def stream_answer(self, session_id: str, answer: str) -> AsyncIterator[dict[str, object]]:
        session = self.storage.get_session(session_id)
        if session.status != "active":
            raise ValueError("该面试会话已经结束")
        if not answer.strip():
            raise ValueError("回答不能为空")
        if session.current_question is None:
            raise ValueError("该会话没有等待回答的问题")

        question = self.bank.get(session.question_id)
        round_no = len(session.turns) + 1
        pending_turn = Turn(round_no, session.current_question, answer, "", None, "")
        transcript = [*session.turns, pending_turn]
        ends_now = (
            session.mode == "single"
            or round_no >= MAX_DEEP_ROUNDS
            or _is_explicit_inability(answer)
        )
        if ends_now:
            stream_evaluate = getattr(self.interviewer, "stream_evaluate", None)
            if not callable(stream_evaluate):
                raise ValueError("当前模型不支持流式评分")
            parser = JsonFieldStreamParser(("interviewer_feedback",))
            final_evaluation: FinalEvaluation | None = None
            get_logger().info("stream_evaluation_started question_id=%s round=%s", session.question_id, round_no)
            async for event in stream_evaluate(question=question, transcript=transcript):
                if not isinstance(event, StreamedReplyEvent):
                    raise ValueError("模型流式事件格式不正确")
                if event.text:
                    for delta in parser.feed(event.text):
                        yield {"event": "delta", "field": delta.field, "text": delta.text}
                if isinstance(event.reply, FinalEvaluation):
                    final_evaluation = event.reply
            if final_evaluation is None:
                raise ValueError("模型流式响应未返回最终评分")
            self.storage.append_turn(session.id, round_no, session.current_question, answer, "", None)
            result = self._save_completed(session.id, final_evaluation)
            yield {"event": "completed", "result": result}
            return

        stream_follow_up = getattr(self.interviewer, "stream_follow_up", None)
        if not callable(stream_follow_up):
            raise ValueError("当前模型不支持流式追问")

        parser = JsonFieldStreamParser(("feedback", "next_question"))
        final_reply: InterviewReply | None = None
        get_logger().info("stream_answer_started question_id=%s round=%s", session.question_id, round_no)
        async for event in stream_follow_up(question=question, transcript=transcript):
            if not isinstance(event, StreamedReplyEvent):
                raise ValueError("模型流式事件格式不正确")
            if event.text:
                for delta in parser.feed(event.text):
                    yield {"event": "delta", "field": delta.field, "text": delta.text}
            if isinstance(event.reply, InterviewReply):
                final_reply = event.reply

        if final_reply is None:
            raise ValueError("模型流式响应未返回最终追问")
        self.storage.append_turn(
            session.id,
            round_no,
            session.current_question,
            answer,
            final_reply.feedback,
            final_reply.next_question,
        )
        saved = self.storage.get_session(session.id)
        result = SubmitResult(saved, False, final_reply.feedback, final_reply.next_question, None)
        get_logger().info("stream_answer_completed question_id=%s round=%s", session.question_id, round_no)
        yield {"event": "completed", "result": result}

    async def finish(self, session_id: str) -> SubmitResult:
        session = self.storage.get_session(session_id)
        if session.status != "active":
            raise ValueError("该面试会话已经结束")
        question = self.bank.get(session.question_id)
        return await self._finish(session.id, question, session)

    async def _finish(self, session_id: str, question: object, session: Session) -> SubmitResult:
        evaluation = await self.interviewer.evaluate(question=question, transcript=list(session.turns))
        return self._save_completed(session_id, evaluation)

    def _save_completed(self, session_id: str, evaluation: FinalEvaluation) -> SubmitResult:
        self.storage.finish_session(session_id, evaluation.score, evaluation.to_dict())
        completed = self.storage.get_session(session_id)
        get_logger().info(
            "session_finished question_id=%s score=%s rounds=%s",
            completed.question_id,
            evaluation.score,
            len(completed.turns),
        )
        return SubmitResult(completed, True, None, None, evaluation)


def _is_explicit_inability(answer: str) -> bool:
    normalized = "".join(answer.strip().split()).strip("。！!？?")
    return normalized in _INABILITY_ANSWERS
