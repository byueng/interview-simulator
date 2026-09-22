from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path


def _today_log_path(directory: Path) -> Path:
    return directory / f"{datetime.now().astimezone().date().isoformat()}.log"


def _close_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()
        logger.removeHandler(handler)
        handler.close()
    logging.shutdown()


def test_configure_logging_writes_file_and_redacts_model_api_key(tmp_path: Path) -> None:
    from interview_simulator.logging_config import configure_logging

    logger = configure_logging(tmp_path)
    logger.info("模型调用失败：LLM_API_KEY=super-secret-key")

    log_text = _today_log_path(tmp_path).read_text(encoding="utf-8")
    assert "模型调用失败" in log_text
    assert "super-secret-key" not in log_text
    assert "[REDACTED]" in log_text
    assert not (tmp_path / "interview-simulator.log").exists()

    _close_logger(logger)


def test_daily_handler_switches_files_using_record_local_day(tmp_path: Path) -> None:
    from interview_simulator.logging_config import configure_logging

    logger = configure_logging(tmp_path)
    today = datetime.now().astimezone()
    tomorrow = today + timedelta(days=1)
    for when, message in ((today, "今天的日志"), (tomorrow, "明天的日志")):
        record = logger.makeRecord(logger.name, logging.INFO, __file__, 0, message, (), None)
        record.created = when.timestamp()
        logger.handle(record)

    today_path = tmp_path / f"{today.date().isoformat()}.log"
    tomorrow_path = tmp_path / f"{tomorrow.date().isoformat()}.log"
    assert "今天的日志" in today_path.read_text(encoding="utf-8")
    assert "明天的日志" in tomorrow_path.read_text(encoding="utf-8")
    assert "明天的日志" not in today_path.read_text(encoding="utf-8")

    _close_logger(logger)


def test_configure_logging_keeps_thirty_days_and_migrates_legacy_log(tmp_path: Path) -> None:
    from interview_simulator.logging_config import configure_logging

    today = datetime.now().astimezone().date()
    expired = tmp_path / f"{(today - timedelta(days=30)).isoformat()}.log"
    retained = tmp_path / f"{(today - timedelta(days=29)).isoformat()}.log"
    expired.write_text("过期日志\n", encoding="utf-8")
    retained.write_text("保留日志\n", encoding="utf-8")
    legacy = tmp_path / "interview-simulator.log"
    legacy.write_text("旧固定日志\n", encoding="utf-8")

    logger = configure_logging(tmp_path)

    assert not expired.exists()
    assert retained.exists()
    assert not legacy.exists()
    assert "旧固定日志" in _today_log_path(tmp_path).read_text(encoding="utf-8")

    _close_logger(logger)
