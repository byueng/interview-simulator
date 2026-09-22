from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any

from interview_simulator.models import Question


_MODULE_DIRECTORY_RE = re.compile(r"^\d{2}-.+")
_QUESTION_FILENAME_RE = re.compile(r"^(?P<id>\d{3})-.+\.md$")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_FRONT_MATTER_DELIMITER = "+++"
_BANK_MANIFEST_FILENAME = "knowledge-base.toml"
_VALID_KINDS = frozenset({"concept", "system_design", "troubleshooting", "code_review", "comparison", "quantitative", "interview_chain"})
_VALID_STATUSES = frozenset({"draft", "published", "deprecated"})


class QuestionNotFoundError(KeyError):
    """请求的原始题号不在扫描后的题库中。"""


class QuestionBank:
    """题库 Markdown 的只读内存索引。"""

    def __init__(self, root: Path, bank_id: str, questions: list[Question]) -> None:
        self.root = root
        self.bank_id = bank_id
        self._questions = tuple(sorted(questions, key=lambda question: question.id))
        self._by_id = {question.id: question for question in self._questions}
        if len(self._by_id) != len(self._questions):
            raise ValueError("题库中存在重复题号")

    @classmethod
    def scan(cls, root: Path) -> "QuestionBank":
        if not root.is_dir():
            raise ValueError(f"题库目录不存在或不可读取：{root}")
        bank_id, modules = cls._load_manifest(root)
        questions: list[Question] = []
        for module_dir in sorted(root.iterdir()):
            if not module_dir.is_dir() or not _MODULE_DIRECTORY_RE.match(module_dir.name):
                continue
            for markdown_file in sorted(module_dir.glob("*.md")):
                match = _QUESTION_FILENAME_RE.match(markdown_file.name)
                if match is not None:
                    questions.append(
                        cls._parse_question(
                            root, markdown_file, match.group("id"), module_dir.name, bank_id, modules
                        )
                    )
        return cls(root, bank_id, questions)

    @classmethod
    def _parse_question(
        cls,
        root: Path,
        markdown_file: Path,
        question_id: str,
        fallback_module: str,
        bank_id: str,
        modules: dict[str, str],
    ) -> Question:
        content = markdown_file.read_text(encoding="utf-8")
        title_match = _TITLE_RE.search(content)
        if title_match is None:
            raise ValueError(f"题目缺少一级标题：{markdown_file}")
        front_matter = cls._front_matter(content, markdown_file)
        if front_matter is None:
            return Question(
                id=question_id,
                knowledge_id=f"{bank_id}:{question_id}",
                bank_id=bank_id,
                title=title_match.group(1),
                module=cls._metadata(content, "分类") or fallback_module,
                difficulty=cls._metadata(content, "难度") or "未标注",
                kind="concept",
                tags=(),
                prerequisites=(),
                revision=1,
                status="published",
                relative_path=markdown_file.relative_to(root).as_posix(),
                source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                reference_markdown=content,
            )

        metadata = cls._validate_entry_metadata(front_matter, markdown_file, question_id, bank_id, modules)
        return Question(
            id=question_id,
            knowledge_id=metadata["knowledge_id"],
            bank_id=bank_id,
            title=title_match.group(1),
            module=modules[metadata["module_id"]],
            difficulty=metadata["difficulty"],
            kind=metadata["kind"],
            tags=metadata["tags"],
            prerequisites=metadata["prerequisites"],
            revision=metadata["revision"],
            status=metadata["status"],
            relative_path=markdown_file.relative_to(root).as_posix(),
            source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            reference_markdown=content,
        )

    @classmethod
    def _load_manifest(cls, root: Path) -> tuple[str, dict[str, str]]:
        manifest_path = root / _BANK_MANIFEST_FILENAME
        if not manifest_path.is_file():
            return _normalize_bank_id(root.name), {}
        try:
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"知识库清单不是合法 TOML：{manifest_path}") from exc
        if manifest.get("schema_version") != 1:
            raise ValueError(f"知识库清单 schema_version 必须为 1：{manifest_path}")
        bank_id = _required_string(manifest, "bank_id", manifest_path)
        if _normalize_bank_id(bank_id) != bank_id:
            raise ValueError(f"知识库 bank_id 只能使用小写字母、数字和连字符：{manifest_path}")
        raw_modules = manifest.get("modules")
        if not isinstance(raw_modules, list) or not raw_modules:
            raise ValueError(f"知识库清单必须声明非空 modules：{manifest_path}")
        modules: dict[str, str] = {}
        for raw_module in raw_modules:
            if not isinstance(raw_module, dict):
                raise ValueError(f"知识库模块必须是对象：{manifest_path}")
            module_id = _required_string(raw_module, "id", manifest_path)
            module_name = _required_string(raw_module, "name", manifest_path)
            if _normalize_bank_id(module_id) != module_id or module_id in modules:
                raise ValueError(f"知识库模块 id 非法或重复：{manifest_path}")
            modules[module_id] = module_name
        return bank_id, modules

    @classmethod
    def _front_matter(cls, content: str, markdown_file: Path) -> dict[str, Any] | None:
        if not content.startswith(f"{_FRONT_MATTER_DELIMITER}\n"):
            return None
        closing = content.find(f"\n{_FRONT_MATTER_DELIMITER}\n", len(_FRONT_MATTER_DELIMITER) + 1)
        if closing == -1:
            raise ValueError(f"知识条目 TOML 元数据未关闭：{markdown_file}")
        try:
            metadata = tomllib.loads(content[len(_FRONT_MATTER_DELIMITER) + 1 : closing])
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"知识条目元数据不是合法 TOML：{markdown_file}") from exc
        return metadata

    @classmethod
    def _validate_entry_metadata(
        cls,
        metadata: dict[str, Any],
        markdown_file: Path,
        question_id: str,
        bank_id: str,
        modules: dict[str, str],
    ) -> dict[str, Any]:
        if metadata.get("schema_version") != 1:
            raise ValueError(f"知识条目 schema_version 必须为 1：{markdown_file}")
        knowledge_id = _required_string(metadata, "knowledge_id", markdown_file)
        expected_prefix = f"{bank_id}:"
        if not knowledge_id.startswith(expected_prefix):
            raise ValueError(f"knowledge_id 必须以 {expected_prefix} 开头：{markdown_file}")
        if _required_string(metadata, "legacy_question_id", markdown_file) != question_id:
            raise ValueError(f"legacy_question_id 必须与文件题号一致：{markdown_file}")
        module_id = _required_string(metadata, "module_id", markdown_file)
        if module_id not in modules:
            raise ValueError(f"module_id 未在知识库清单声明：{markdown_file}")
        difficulty = _required_string(metadata, "difficulty", markdown_file)
        kind = _required_string(metadata, "kind", markdown_file)
        if kind not in _VALID_KINDS:
            raise ValueError(f"kind 不受支持：{markdown_file}")
        status = _required_string(metadata, "status", markdown_file)
        if status not in _VALID_STATUSES:
            raise ValueError(f"status 不受支持：{markdown_file}")
        revision = metadata.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError(f"revision 必须是大于等于 1 的整数：{markdown_file}")
        tags = _string_list(metadata.get("tags"), "tags", markdown_file)
        prerequisites = _string_list(metadata.get("prerequisites"), "prerequisites", markdown_file)
        return {
            "knowledge_id": knowledge_id,
            "module_id": module_id,
            "difficulty": difficulty,
            "kind": kind,
            "status": status,
            "revision": revision,
            "tags": tags,
            "prerequisites": prerequisites,
        }

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


def _normalize_bank_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "knowledge-base"


def _required_string(mapping: dict[str, Any], name: str, path: Path) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串：{path}")
    return value.strip()


def _string_list(value: object, name: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} 必须是非空字符串数组：{path}")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} 不允许重复：{path}")
    return normalized
