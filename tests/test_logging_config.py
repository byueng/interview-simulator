from __future__ import annotations

import logging
from pathlib import Path


def test_configure_logging_writes_file_and_redacts_model_api_key(tmp_path: Path) -> None:
    from interview_simulator.logging_config import configure_logging

    logger = configure_logging(tmp_path)
    logger.info("模型调用失败：LLM_API_KEY=super-secret-key")

    log_text = (tmp_path / "interview-simulator.log").read_text(encoding="utf-8")
    assert "模型调用失败" in log_text
    assert "super-secret-key" not in log_text
    assert "[REDACTED]" in log_text

    for handler in logger.handlers:
        handler.flush()
        logger.removeHandler(handler)
        handler.close()
    logging.shutdown()
