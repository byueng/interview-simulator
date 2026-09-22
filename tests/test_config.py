from __future__ import annotations

import json
from pathlib import Path

import pytest

from interview_simulator.config import AppConfig, ConfigError


def write_config(path: Path, *, page_size: int = 15, temperature: float = 0.9) -> None:
    path.write_text(
        json.dumps(
            {
                "question_bank_path": "/tmp/question-bank",
                "ui": {"page_size": page_size},
                "scoring": {"temperature": temperature},
            }
        ),
        encoding="utf-8",
    )


def test_load_config_reads_ui_and_scoring_values(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    write_config(config_file)

    config = AppConfig.load(config_file)

    assert config.ui.page_size == 15
    assert config.scoring.temperature == 0.9
    assert config.question_bank_path == Path("/tmp/question-bank")


def test_load_config_rejects_page_size_below_one(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    write_config(config_file, page_size=0)

    with pytest.raises(ConfigError, match="page_size"):
        AppConfig.load(config_file)


def test_load_config_rejects_unknown_feedback_style(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"question_bank_path": "/tmp/question-bank", "scoring": {"feedback_style": "mean"}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="feedback_style"):
        AppConfig.load(config_file)


def test_public_config_example_is_loadable() -> None:
    project_root = Path(__file__).parent.parent

    config = AppConfig.load(project_root / "config.example.json")

    assert config.question_bank_path == Path("path/to/your-question-bank")
    assert config.ui.page_size == 15
    assert config.scoring.temperature == 0.9
