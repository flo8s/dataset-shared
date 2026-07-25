"""検証結果の表現。

error は「Queria に載せられない」を意味する。warning と info は載せられるが
気づいてほしいこと。Publisher 向けの契約なので、メッセージには必ず
どのファイルの何が問題かを含める。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Level(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    level: Level
    code: str
    message: str
    source: Path | None = None

    def render(self) -> str:
        where = f"{self.source}: " if self.source else ""
        return f"{self.level.value}: {where}{self.message} [{self.code}]"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(
        self, level: Level, code: str, message: str, source: Path | None = None
    ) -> None:
        self.findings.append(Finding(level, code, message, source))

    def error(self, code: str, message: str, source: Path | None = None) -> None:
        self.add(Level.ERROR, code, message, source)

    def warning(self, code: str, message: str, source: Path | None = None) -> None:
        self.add(Level.WARNING, code, message, source)

    def info(self, code: str, message: str, source: Path | None = None) -> None:
        self.add(Level.INFO, code, message, source)

    def of(self, level: Level) -> list[Finding]:
        return [f for f in self.findings if f.level is level]

    @property
    def failed(self) -> bool:
        return any(f.level is Level.ERROR for f in self.findings)

    def render(self, *, show_info: bool = True) -> str:
        order = {Level.ERROR: 0, Level.WARNING: 1, Level.INFO: 2}
        shown = [
            f for f in self.findings if show_info or f.level is not Level.INFO
        ]
        shown.sort(key=lambda f: (order[f.level], str(f.source or ""), f.code))
        return "\n".join(f.render() for f in shown)


class SpecError(Exception):
    """読み込み自体が続行不能なときだけ使う（YAML が壊れている等）。"""
