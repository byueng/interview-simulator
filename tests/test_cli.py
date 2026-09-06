from __future__ import annotations

from pathlib import Path

from interview_simulator.cli import parse_args


def test_cli_uses_current_directory_config_by_default() -> None:
    args = parse_args([])

    assert args.config == Path("config.json")


def test_cli_accepts_an_explicit_config_path() -> None:
    args = parse_args(["--config", "/tmp/custom.json"])

    assert args.config == Path("/tmp/custom.json")
