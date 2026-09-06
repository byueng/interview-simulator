from __future__ import annotations

import hashlib
import re
from pathlib import Path

from interview_simulator.models import Question


_MODULE_DIRECTORY_RE = re.compile(r"^\d{2}-.+")
_QUESTION_FILENAME_RE = re.compile(r"^(?P<id>\d{3})-.+\.md$")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class QuestionNotFoundError(KeyError):
    """请求的原始题号不在扫描后的题库中。"""


class QuestionBank:
    """题库 Markdown 的只读内存索引。"""

    def __init__(self, root: Path, questions: list[Question]) -> None:
        self.root = root
        self._questions = tuple(sorted(questions, key=lambda question: question.id))
        self._by_id = {question.id: question for question in self._questions}
        if len(self._by_id) != len(self._questions):
            raise ValueError("题库中存在重复题号")

    @classmethod
    def scan(cls, root: Path) -> "QuestionBank":
        if not root.is_dir():
            raise ValueError(f"题库目录不存在或不可读取：{root}")
        questions: list[Question] = []
        for module_dir in sorted(root.iterdir()):
            if not module_dir.is_dir() or not _MODULE_DIRECTORY_RE.match(module_dir.name):
                continue
            for markdown_file in sorted(module_dir.glob("*.md")):
                match = _QUESTION_FILENAME_RE.match(markdown_file.name)
                if match is not None:
                    questions.append(cls._parse_question(root, markdown_file, match.group("id"), module_dir.name))
        return cls(root, questions)

    @classmethod
    def _parse_question(cls, root: Path, markdown_file: Path, question_id: str, fallback_module: str) -> Question:
        content = markdown_file.read_text(encoding="utf-8")
        title_match = _TITLE_RE.search(content)
        if title_match is None:
            raise ValueError(f"题目缺少一级标题：{markdown_file}")
        return Question(
            id=question_id,
            title=title_match.group(1),
            module=cls._metadata(content, "分类") or fallback_module,
            difficulty=cls._metadata(content, "难度") or "未标注",
            relative_path=markdown_file.relative_to(root).as_posix(),
            source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            reference_markdown=content,
        )

    @staticmethod
    def _metadata(content: str, name: str) -> str | None:
        match = re.search(rf"^>\s*{re.escape(name)}：\s*(.+?)\s*$", content, re.MULTILINE)
        return match.group(1) if match else None

    def get(self, question_id: str) -> Question:
        normalized = str(question_id).zfill(3)
        try:
            return self._by_id[normalized]
        except KeyError as exc:
            raise QuestionNotFoundError(normalized) from exc

    def page(self, page: int, page_size: int) -> tuple[list[Question], int]:
        if page < 1 or page_size < 1:
            raise ValueError("page 和 page_size 必须大于等于 1")
        start = (page - 1) * page_size
        return list(self._questions[start : start + page_size]), len(self._questions)

    @property
    def questions(self) -> tuple[Question, ...]:
        return self._questions
