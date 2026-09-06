from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JsonFieldDelta:
    field: str
    text: str


class JsonFieldStreamParser:
    """从尚未闭合的 JSON 对象中，安全地提取指定字符串字段的新增文本。"""

    def __init__(self, fields: tuple[str, ...]) -> None:
        self._fields = fields
        self._raw = ""
        self._emitted = {field: "" for field in fields}

    def feed(self, text: str) -> list[JsonFieldDelta]:
        self._raw += text
        deltas: list[JsonFieldDelta] = []
        for field in self._fields:
            value = _partial_string_field(self._raw, field)
            if value is None:
                continue
            emitted = self._emitted[field]
            if not value.startswith(emitted):
                raise ValueError(f"模型流式字段 {field} 在生成过程中发生了回退")
            suffix = value[len(emitted) :]
            if suffix:
                self._emitted[field] = value
                deltas.append(JsonFieldDelta(field, suffix))
        return deltas


def _partial_string_field(raw: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"', raw)
    if match is None:
        return None
    index = match.end()
    parts: list[str] = []
    while index < len(raw):
        char = raw[index]
        if char == '"':
            return "".join(parts)
        if char != "\\":
            parts.append(char)
            index += 1
            continue

        if index + 1 >= len(raw):
            break
        escaped = raw[index + 1]
        escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        if escaped == "u":
            if index + 6 > len(raw):
                break
            try:
                parts.append(chr(int(raw[index + 2 : index + 6], 16)))
            except ValueError:
                break
            index += 6
            continue
        if escaped not in escapes:
            break
        parts.append(escapes[escaped])
        index += 2
    return "".join(parts)
