"""dataset.yml と **/*.table.yml を読む。

規約は 2 つだけ:
  - dataset.yml がリポジトリルートに 1 つ（必須）
  - *.table.yml はどこに置いてもよい

エンティティの同一性はファイルの内容（schema + name）で決まる。パスは規約ではない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import Level, Report, SpecError

DATASET_FILENAMES = ("dataset.yml", "dataset.yaml")
TABLE_SUFFIXES = (".table.yml", ".table.yaml")

# 走査から外すディレクトリ。ビルド成果物や依存の中に紛れ込んだ YAML を拾わない。
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "target",
        "dist",
        ".fdl",
        "dbt_packages",
        ".claude",
        "__pycache__",
        "logs",
        ".pytest_cache",
        ".mypy_cache",
    }
)


@dataclass
class LoadedTable:
    """1 テーブルの宣言と、それがどのファイル由来かの記録。"""

    data: dict[str, Any]
    source: Path

    @property
    def key(self) -> tuple[str, str]:
        return (str(self.data.get("schema", "")), str(self.data.get("name", "")))


@dataclass
class Loaded:
    root: Path
    dataset_file: Path
    dataset: dict[str, Any]
    tables: list[LoadedTable] = field(default_factory=list)
    #: co-located な *.table.yml が dbt の model-paths 配下にあるか
    colocated_in_model_paths: list[Path] = field(default_factory=list)


def _read_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise SpecError(f"{path}: YAML として読めない: {exc}") from exc


def find_dataset_file(root: Path) -> Path:
    for name in DATASET_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise SpecError(
        f"{root}: dataset.yml が見つからない。リポジトリルートに 1 つ必要"
    )


def iter_table_files(root: Path):
    """*.table.yml を走査する。IGNORED_DIRS 配下には降りない。"""
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in IGNORED_DIRS:
                    stack.append(entry)
            elif entry.name.endswith(TABLE_SUFFIXES):
                yield entry


def _strip_anchor_keys(data: dict[str, Any]) -> dict[str, Any]:
    """`_` 始まりのトップレベルキーは YAML アンカー置き場なので落とす。"""
    return {k: v for k, v in data.items() if not k.startswith("_")}


def split_table_declarations(
    data: Any, source: Path, report: Report
) -> list[dict[str, Any]]:
    """単一形と複数形（tables: リスト）の両方を受け、テーブル宣言のリストに正規化する。

    1 ファイル 1 テーブルを強制すると、同じ列構成を共有する表の集まり
    （e-Stat の社会・人口統計体系など）で同じフィールド定義を何度も書くことになる。
    同一ファイル内なら YAML アンカーが効くので、複数形を許す。
    """
    if data is None:
        report.warning("empty-file", "中身が空", source)
        return []
    if not isinstance(data, dict):
        report.error("not-a-mapping", "トップレベルがマッピングではない", source)
        return []

    cleaned = _strip_anchor_keys(data)

    if "tables" in cleaned:
        extra = set(cleaned) - {"tables"}
        if extra:
            report.error(
                "mixed-form",
                f"tables: を使う場合、他のトップレベルキーは書けない: {sorted(extra)}",
                source,
            )
        tables = cleaned.get("tables")
        if not isinstance(tables, list):
            report.error("tables-not-a-list", "tables: がリストではない", source)
            return []
        out = []
        for index, item in enumerate(tables):
            if not isinstance(item, dict):
                report.error(
                    "table-not-a-mapping", f"tables[{index}] がマッピングではない", source
                )
                continue
            out.append(item)
        return out

    return [cleaned]


def load(root: Path, report: Report, *, model_paths: tuple[str, ...] = ("models",)) -> Loaded:
    root = root.resolve()
    dataset_file = find_dataset_file(root)
    raw = _read_yaml(dataset_file)
    if not isinstance(raw, dict):
        raise SpecError(f"{dataset_file}: トップレベルがマッピングではない")

    dataset = _strip_anchor_keys(raw)
    inline_tables = dataset.pop("tables", None)

    loaded = Loaded(root=root, dataset_file=dataset_file, dataset=dataset)

    if inline_tables is not None:
        if not isinstance(inline_tables, list):
            report.error(
                "tables-not-a-list", "dataset.yml の tables: がリストではない", dataset_file
            )
        else:
            for index, item in enumerate(inline_tables):
                if not isinstance(item, dict):
                    report.error(
                        "table-not-a-mapping",
                        f"tables[{index}] がマッピングではない",
                        dataset_file,
                    )
                    continue
                loaded.tables.append(LoadedTable(data=item, source=dataset_file))

    seen: dict[tuple[str, str], Path] = {}
    for path in sorted(iter_table_files(root)):
        declarations = split_table_declarations(_read_yaml(path), path, report)
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in model_paths:
            loaded.colocated_in_model_paths.append(rel)
        for data in declarations:
            loaded.tables.append(LoadedTable(data=data, source=path))

    for table in loaded.tables:
        key = table.key
        if not key[1]:
            report.error("table-name-missing", "name が無い", table.source)
            continue
        previous = seen.get(key)
        if previous is not None:
            report.error(
                "duplicate-table",
                f"{key[0]}.{key[1]} が重複している（{previous} にも定義がある）",
                table.source,
            )
            continue
        seen[key] = table.source

    return loaded


def basename_of(path: Path) -> str:
    """`mart_calendar.table.yml` -> `mart_calendar`"""
    name = path.name
    for suffix in TABLE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem
