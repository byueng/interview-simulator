from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """用户配置无法安全使用。"""


@dataclass(frozen=True, slots=True)
class UiConfig:
    page_size: int = 15
    theme: str = "dark"
    show_reference_after_scoring: bool = False
    keybindings: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    temperature: float = 0.9
    feedback_style: str = "detailed_interviewer"


@dataclass(frozen=True, slots=True)
class AppConfig:
    question_bank_path: Path
    ui: UiConfig
    scoring: ScoringConfig

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"找不到配置文件：{path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"config.json 不是合法 JSON：{exc.msg}") from exc

        if not isinstance(raw, dict):
            raise ConfigError("config.json 顶层必须是对象")

        question_bank = raw.get("question_bank_path")
        if not isinstance(question_bank, str) or not question_bank.strip():
            raise ConfigError("question_bank_path 必须是非空字符串")

        return cls(
            question_bank_path=Path(question_bank).expanduser(),
            ui=cls._ui_config(raw.get("ui", {})),
            scoring=cls._scoring_config(raw.get("scoring", {})),
        )

    @staticmethod
    def _ui_config(raw: object) -> UiConfig:
        if not isinstance(raw, dict):
            raise ConfigError("ui 必须是对象")
        page_size = raw.get("page_size", 15)
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise ConfigError("ui.page_size 必须是大于等于 1 的整数")
        theme = raw.get("theme", "dark")
        if not isinstance(theme, str):
            raise ConfigError("ui.theme 必须是字符串")
        show_reference = raw.get("show_reference_after_scoring", False)
        if not isinstance(show_reference, bool):
            raise ConfigError("ui.show_reference_after_scoring 必须是布尔值")
        keybindings = raw.get("keybindings")
        if keybindings is not None and not isinstance(keybindings, dict):
            raise ConfigError("ui.keybindings 必须是对象")
        return UiConfig(page_size, theme, show_reference, keybindings)

    @staticmethod
    def _scoring_config(raw: object) -> ScoringConfig:
        if not isinstance(raw, dict):
            raise ConfigError("scoring 必须是对象")
        temperature = raw.get("temperature", 0.9)
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
            raise ConfigError("scoring.temperature 必须是数字")
        if not 0 <= float(temperature) <= 2:
            raise ConfigError("scoring.temperature 必须介于 0 和 2")
        feedback_style = raw.get("feedback_style", "detailed_interviewer")
        if not isinstance(feedback_style, str) or not feedback_style:
            raise ConfigError("scoring.feedback_style 必须是非空字符串")
        return ScoringConfig(float(temperature), feedback_style)
