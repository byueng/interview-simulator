from __future__ import annotations

from pathlib import Path

from interview_simulator.storage import SQLiteStorage


def test_storage_keeps_turns_and_latest_progress(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "practice.db")
    session = storage.create_session("006", "deep", "source-hash", "原题")
    storage.append_turn(session.id, 1, "原题", "我的回答", "继续说明异常分支。", "追问")
    storage.finish_session(session.id, 7.0, {"score": 7.0, "verdict": "有工程意识"})

    progress = storage.latest_progress("006")
    saved = storage.get_session(session.id)

    assert progress is not None
    assert progress.latest_score == 7.0
    assert progress.practiced is True
    assert saved.turns[0].answer == "我的回答"
    assert saved.turns[0].feedback == "继续说明异常分支。"
    assert saved.final_evaluation == {"score": 7.0, "verdict": "有工程意识"}


def test_storage_lists_newest_sessions_first(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "practice.db")
    first = storage.create_session("006", "single", "a", "第一题")
    second = storage.create_session("022", "deep", "b", "第二题")

    sessions = storage.list_sessions()

    assert [session.id for session in sessions] == [second.id, first.id]
