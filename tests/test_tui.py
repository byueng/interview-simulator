from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from interview_simulator.tui import BankInspectorApp


@pytest.mark.asyncio
async def test_bank_inspector_shows_loaded_count_and_question_preview(tmp_path: Path) -> None:
    module = tmp_path / "03-tool-use"
    module.mkdir()
    (module / "022-tool-schema.md").write_text(
        "# 如何定义 Tool Schema？\n\n> 难度：基础\n> 分类：Tool Use\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"question_bank_path": str(tmp_path), "ui": {"page_size": 15}}),
        encoding="utf-8",
    )

    app = BankInspectorApp(config_path)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        status = app.query_one("#bank-status", Static)
        table = app.query_one("#question-table", DataTable)

        assert "已加载 1 道题" in str(status.render())
        assert table.row_count == 1
