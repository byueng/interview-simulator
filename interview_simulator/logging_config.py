from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path


LOGGER_NAME = "interview_simulator"
LOG_FILE_NAME = "interview-simulator.log"
LOG_RETENTION_DAYS = 30
_DAILY_LOG_PATTERN = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})\.log$")


class _SensitiveValueFilter(logging.Filter):
    _patterns = (
        re.compile(r"(LLM_API_KEY\s*=\s*)[^\s,;]+"),
        re.compile(r"(Authorization\s*:\s*Bearer\s+)[^\s,;]+", re.IGNORECASE),
        re.compile(r"(Bearer\s+)[^\s,;]+", re.IGNORECASE),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in self._patterns:
            message = pattern.sub(r"\1[REDACTED]", message)
        record.msg = message
        record.args = ()
        return True


class _DailyFileHandler(logging.Handler):
    """按日志记录的本机自然日写入独立文件，并清理过期日期日志。"""

    terminator = "\n"

    def __init__(self, log_directory: Path, *, retention_days: int = LOG_RETENTION_DAYS) -> None:
        super().__init__()
        self.log_directory = log_directory
        self.retention_days = retention_days
        self._active_day: date | None = None
        self._stream: object | None = None

        today = _local_today()
        self._migrate_legacy_log(today)
        self._cleanup_expired_logs(today)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._switch_to(_local_day(record.created))
            assert self._stream is not None
            self._stream.write(self.format(record) + self.terminator)  # type: ignore[union-attr]
            self._stream.flush()  # type: ignore[union-attr]
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            if self._stream is not None:
                self._stream.close()  # type: ignore[union-attr]
                self._stream = None
                self._active_day = None
        finally:
            super().close()

    def _switch_to(self, target_day: date) -> None:
        if self._active_day == target_day and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()  # type: ignore[union-attr]
        self._cleanup_expired_logs(_local_today())
        self._stream = self._path_for(target_day).open("a", encoding="utf-8")
        self._active_day = target_day

    def _migrate_legacy_log(self, today: date) -> None:
        legacy_path = self.log_directory / LOG_FILE_NAME
        if not legacy_path.is_file():
            return
        legacy_content = legacy_path.read_bytes()
        if legacy_content:
            destination = self._path_for(today)
            with destination.open("ab") as daily_file:
                if daily_file.tell() and not legacy_content.startswith(b"\n"):
                    daily_file.write(b"\n")
                daily_file.write(legacy_content)
        legacy_path.unlink()

    def _cleanup_expired_logs(self, today: date) -> None:
        earliest_kept_day = today - timedelta(days=self.retention_days - 1)
        for candidate in self.log_directory.iterdir():
            match = _DAILY_LOG_PATTERN.fullmatch(candidate.name)
            if match is None or not candidate.is_file():
                continue
            try:
                candidate_day = date.fromisoformat(match.group("day"))
            except ValueError:
                continue
            if candidate_day < earliest_kept_day:
                candidate.unlink()

    def _path_for(self, target_day: date) -> Path:
        return self.log_directory / f"{target_day.isoformat()}.log"


def _local_today() -> date:
    return datetime.now().astimezone().date()


def _local_day(timestamp: float) -> date:
    return datetime.fromtimestamp(timestamp).astimezone().date()


def configure_logging(log_directory: Path, *, level: int = logging.INFO) -> logging.Logger:
    """配置仅写入本地、按自然日拆分的应用日志。"""
    log_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    handler = _DailyFileHandler(log_directory)
    handler.setLevel(level)
    handler.addFilter(_SensitiveValueFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
