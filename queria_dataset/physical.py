"""実データからテーブル・列・型・列順・NULL 許容を読む。

Publisher に型を書かせないための仕組み。dbt があってもなくても同じ経路を通るので、
dbt を使わないデータセットでも型が付く。

読むのは常に **ローカル** のカタログ／ファイル。compile はデータセット自身の
ビルド直後に走るので、HTTP 越しの ATTACH は必要ない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import SpecError

#: ATTACH に使う一時的な別名。ユーザーのスキーマ名と衝突しないもの。
ALIAS = "__queria_dataset_src"

#: DuckLake の内部スキーマ。テーブル一覧から除外する。
INTERNAL_SCHEMAS = frozenset({"information_schema", "pg_catalog", "main_ducklake_metadata"})


@dataclass
class PhysicalField:
    name: str
    type: str
    index: int
    nullable: bool


@dataclass
class PhysicalTable:
    schema: str
    name: str
    materialized: str
    fields: list[PhysicalField] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.schema, self.name)


def _attach_target(catalog_path: str) -> tuple[str, dict[str, str]]:
    """ATTACH 文と追加オプションを組み立てる。"""
    options: dict[str, str] = {}
    if catalog_path.endswith(".sqlite"):
        options["META_TYPE"] = "'sqlite'"
    return f"ducklake:{catalog_path}", options


def read_ducklake(catalog_path: str, data_path: str | None) -> dict[tuple[str, str], PhysicalTable]:
    try:
        import duckdb
    except ModuleNotFoundError as exc:  # pragma: no cover - 環境依存
        raise SpecError(
            "duckdb が入っていない。実データからの型解決には duckdb が要る"
        ) from exc

    target, options = _attach_target(catalog_path)
    if data_path:
        options["DATA_PATH"] = f"'{data_path}'"
        options["OVERRIDE_DATA_PATH"] = "true"
    # READ_ONLY は必須。AUTOMATIC_MIGRATION は絶対に付けない
    # （カタログを書き換えてしまい、他のツールとバージョンが食い違う）。
    rendered = ", ".join(["READ_ONLY"] + [f"{k} {v}" for k, v in options.items()])

    con = duckdb.connect()
    try:
        con.execute("INSTALL ducklake; LOAD ducklake;")
        try:
            con.execute(f"ATTACH '{target}' AS {ALIAS} ({rendered})")
        except Exception as exc:
            if "version mismatch" in str(exc):
                raise SpecError(
                    f"DuckLake カタログのバージョンが duckdb 拡張と食い違っている。"
                    f"データセットをビルドし直してから compile すること。"
                    f"（自動マイグレーションはカタログを書き換えるので行わない）\n  {exc}"
                ) from exc
            raise SpecError(f"カタログを開けない: {catalog_path}\n  {exc}") from exc
        return _introspect(con)
    finally:
        con.close()


def _introspect(con) -> dict[tuple[str, str], PhysicalTable]:
    tables: dict[tuple[str, str], PhysicalTable] = {}

    rows = con.execute(
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_catalog = ?
        ORDER BY table_schema, table_name
        """,
        [ALIAS],
    ).fetchall()
    for schema, name, table_type in rows:
        if schema in INTERNAL_SCHEMAS:
            continue
        materialized = "view" if str(table_type).upper().endswith("VIEW") else "table"
        tables[(schema, name)] = PhysicalTable(
            schema=schema, name=name, materialized=materialized
        )

    columns = con.execute(
        """
        SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_catalog = ?
        ORDER BY table_schema, table_name, ordinal_position
        """,
        [ALIAS],
    ).fetchall()
    for schema, name, column, data_type, is_nullable, position in columns:
        table = tables.get((schema, name))
        if table is None:
            continue
        table.fields.append(
            PhysicalField(
                name=column,
                type=str(data_type),
                # information_schema は 1 始まり。artifact は 0 始まりに揃える。
                index=int(position) - 1,
                nullable=str(is_nullable).upper() != "NO",
            )
        )
    return tables


def read_parquet(paths: list[Path], schema: str = "main") -> dict[tuple[str, str], PhysicalTable]:
    """Parquet を直接読む（dbt も DuckLake も使わない Publisher 向け）。

    テーブル名はファイル名（拡張子を除いたもの）とする。
    """
    try:
        import duckdb
    except ModuleNotFoundError as exc:  # pragma: no cover - 環境依存
        raise SpecError("duckdb が入っていない") from exc

    con = duckdb.connect()
    tables: dict[tuple[str, str], PhysicalTable] = {}
    try:
        for path in sorted(paths):
            name = path.stem
            table = PhysicalTable(schema=schema, name=name, materialized="table")
            rows = con.execute(
                "SELECT name, type FROM parquet_schema(?) WHERE num_children IS NULL",
                [str(path)],
            ).fetchall()
            for index, (column, data_type) in enumerate(rows):
                table.fields.append(
                    PhysicalField(
                        name=column, type=str(data_type), index=index, nullable=True
                    )
                )
            tables[table.key] = table
    finally:
        con.close()
    return tables


def resolve_from_env() -> tuple[str | None, str | None]:
    """`fdl run` が渡す環境変数からカタログとデータの場所を得る。

    fdl には import 依存しない（このツールは dbt / DuckLake / fdl から独立させる）。
    """
    return os.environ.get("FDL_CATALOG_PATH"), os.environ.get("FDL_DATA_URL")
