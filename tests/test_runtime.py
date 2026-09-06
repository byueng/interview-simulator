from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import FastAPI

from interview_simulator.runtime import build_runtime, start_local_server


def test_local_server_binds_loopback_on_ephemeral_port() -> None:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    server = start_local_server(app)
    try:
        response = httpx.get(f"{server.base_url}/health", timeout=2.0)
        assert server.base_url.startswith("http://127.0.0.1:")
        assert response.json() == {"status": "ok"}
    finally:
        server.stop()


def test_build_runtime_composes_bank_storage_interviewer_and_fastapi(tmp_path: Path) -> None:
    module = tmp_path / "01-agent-architecture"
    module.mkdir()
    (module / "006-loop.md").write_text(
        "# 如何控制 Agent Loop？\n\n> 难度：中级\n> 分类：Agent 架构\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"question_bank_path": str(tmp_path), "ui": {"page_size": 15}, "scoring": {"temperature": 0.9}}),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LLM_BASE_URL=https://example.test/v1\nLLM_API_KEY=test-key\nLLM_MODEL=test-model\n",
        encoding="utf-8",
    )

    log_directory = tmp_path / "logs"
    runtime = build_runtime(
        config_path=config_path,
        env_path=env_path,
        database_path=tmp_path / "data" / "practice.db",
        log_directory=log_directory,
    )

    assert runtime.config.ui.page_size == 15
    assert runtime.bank.get("006").title == "如何控制 Agent Loop？"
    assert runtime.storage.database_path.exists()
    assert runtime.app.title == "Interview Simulator Local API"
    assert "runtime_initialized questions=1" in (log_directory / "interview-simulator.log").read_text(encoding="utf-8")
