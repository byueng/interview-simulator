from __future__ import annotations

from pathlib import Path

from interview_simulator.question_bank import QuestionBank


def test_scan_extracts_filename_id_markdown_metadata_and_reference(tmp_path: Path) -> None:
    module = tmp_path / "01-agent-architecture"
    module.mkdir()
    (module / "006-agent-loop.md").write_text(
        "# 如何控制 Agent Loop？\n\n"
        "> 难度：中级\n"
        "> 分类：Agent 架构\n\n"
        "## 简短回答\n\n使用 max_steps 和状态机。\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("ignore", encoding="utf-8")

    question = QuestionBank.scan(tmp_path).get("006")

    assert question.title == "如何控制 Agent Loop？"
    assert question.module == "Agent 架构"
    assert question.difficulty == "中级"
    assert "max_steps" in question.reference_markdown
    assert question.relative_path == "01-agent-architecture/006-agent-loop.md"


def test_page_uses_original_sparse_question_ids_in_order(tmp_path: Path) -> None:
    module = tmp_path / "03-tool-use"
    module.mkdir()
    for question_id in ("022", "006", "101"):
        (module / f"{question_id}-question.md").write_text(
            f"# Q{question_id}\n\n> 难度：基础\n> 分类：Tool Use\n",
            encoding="utf-8",
        )

    items, total = QuestionBank.scan(tmp_path).page(page=1, page_size=2)

    assert [item.id for item in items] == ["006", "022"]
    assert total == 3


def test_scan_reads_knowledge_manifest_and_entry_metadata(tmp_path: Path) -> None:
    (tmp_path / "knowledge-base.toml").write_text(
        'schema_version = 1\n'
        'bank_id = "agent-interview-100"\n\n'
        '[[modules]]\n'
        'id = "agent-architecture"\n'
        'name = "Agent 架构"\n',
        encoding="utf-8",
    )
    module = tmp_path / "01-agent-architecture"
    module.mkdir()
    (module / "006-agent-loop.md").write_text(
        '+++\n'
        'schema_version = 1\n'
        'knowledge_id = "agent-interview-100:agent-architecture:006-agent-loop"\n'
        'legacy_question_id = "006"\n'
        'module_id = "agent-architecture"\n'
        'difficulty = "中级"\n'
        'kind = "concept"\n'
        'tags = ["agent", "loop"]\n'
        'prerequisites = []\n'
        'revision = 1\n'
        'status = "published"\n'
        '+++\n\n'
        '# 如何控制 Agent Loop？\n\n## 简短回答\n\n使用状态机。\n',
        encoding="utf-8",
    )

    bank = QuestionBank.scan(tmp_path)
    question = bank.get("006")

    assert bank.bank_id == "agent-interview-100"
    assert question.knowledge_id == "agent-interview-100:agent-architecture:006-agent-loop"
    assert question.module == "Agent 架构"
    assert question.tags == ("agent", "loop")
    assert question.prerequisites == ()


def test_manifest_rejects_entry_with_mismatched_legacy_question_id(tmp_path: Path) -> None:
    (tmp_path / "knowledge-base.toml").write_text(
        'schema_version = 1\nbank_id = "test-bank"\n\n[[modules]]\nid = "agent"\nname = "Agent"\n',
        encoding="utf-8",
    )
    module = tmp_path / "01-agent"
    module.mkdir()
    (module / "006-loop.md").write_text(
        '+++\nschema_version = 1\nknowledge_id = "test-bank:agent:006-loop"\n'
        'legacy_question_id = "007"\nmodule_id = "agent"\ndifficulty = "基础"\nkind = "concept"\n'
        'tags = ["agent"]\nprerequisites = []\nrevision = 1\nstatus = "published"\n+++\n\n# Loop\n',
        encoding="utf-8",
    )

    import pytest

    with pytest.raises(ValueError, match="legacy_question_id"):
        QuestionBank.scan(tmp_path)
