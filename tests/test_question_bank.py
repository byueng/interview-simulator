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
