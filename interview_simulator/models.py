from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Question:
    """知识库中的单个只读 Markdown 条目。"""

    id: str
    knowledge_id: str
    bank_id: str
    title: str
    module: str
    difficulty: str
    kind: str
    tags: tuple[str, ...]
    prerequisites: tuple[str, ...]
    revision: int
    status: str
    relative_path: str
    source_hash: str
    reference_markdown: str


@dataclass(frozen=True, slots=True)
class Turn:
    round_no: int
    question: str
    answer: str
    feedback: str
    next_question: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    question_id: str
    knowledge_id: str
    mode: str
    source_hash: str
    title: str
    current_question: str | None
    status: str
    started_at: str
    ended_at: str | None
    final_score: float | None
    final_evaluation: dict[str, Any] | None
    turns: tuple[Turn, ...] = ()


@dataclass(frozen=True, slots=True)
class Progress:
    question_id: str
    practiced: bool
    latest_score: float | None
    latest_practiced_at: str | None


@dataclass(frozen=True, slots=True)
class InterviewReply:
    feedback: str
    next_question: str


@dataclass(frozen=True, slots=True)
class FinalEvaluation:
    score: float
    verdict: str
    interviewer_feedback: str
    strengths: list[str]
    issues: list[str]
    answer_upgrade_suggestions: list[str]
    follow_up_questions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "interviewer_feedback": self.interviewer_feedback,
            "strengths": self.strengths,
            "issues": self.issues,
            "answer_upgrade_suggestions": self.answer_upgrade_suggestions,
            "follow_up_questions": self.follow_up_questions,
        }


@dataclass(frozen=True, slots=True)
class StreamedReplyEvent:
    """模型流式输出中的一段文本，或其解析完成后的结构化结果。"""

    text: str | None = None
    reply: InterviewReply | FinalEvaluation | None = None


@dataclass(frozen=True, slots=True)
class SubmitResult:
    session: Session
    ended: bool
    feedback: str | None
    next_question: str | None
    evaluation: FinalEvaluation | None
