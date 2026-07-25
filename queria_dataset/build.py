"""宣言・実データ・dbt artifacts を突き合わせて dataset.json を組み立てる。

供給元の役割:
  宣言 (dataset.yml / *.table.yml)  title / description / license / published / semantic
  実データ (DuckLake / Parquet)     テーブル一覧・列・型・列順・NULL 許容・table か view か
  dbt artifacts (manifest.json)     lineage・変換 SQL・ソースファイルのパス（あれば）

出力は入力が同じなら常にバイト等価になる（キーを安定ソートし、時刻を入れない）。
時刻は Platform が後から付ける。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import normalize
from .dbt import DbtArtifacts, load_manifest
from .errors import Report
from .loader import Loaded, basename_of, load
from .physical import PhysicalTable

SPEC_VERSION = "1.0"

DATASET_KEYS = {
    "spec_version",
    "name",
    "title",
    "description",
    "keywords",
    "homepage",
    "language",
    "licenses",
    "sources",
    "contributors",
    "temporal_coverage",
    "spatial_coverage",
    "update_frequency",
    "cover",
    "ai_context",
    "schemas",
}

TABLE_KEYS = {
    "schema",
    "name",
    "title",
    "description",
    "keywords",
    "published",
    "sql",
    "licenses",
    "sources",
    "depends_on",
    "ai_context",
    "fields",
}


@dataclass
class BuildInput:
    root: Path
    catalog_path: str | None = None
    data_path: str | None = None
    manifest_path: Path | None = None
    parquet: list[Path] | None = None


def _dataset_level(loaded: Loaded, report: Report) -> tuple[dict[str, Any], bool]:
    raw = loaded.dataset
    source = loaded.dataset_file

    unknown = sorted(set(raw) - DATASET_KEYS - {"platform"})
    if unknown:
        report.error("dataset-unknown-keys", f"dataset.yml に未知のキー {unknown}", source)
    if "platform" in raw:
        report.error(
            "platform-declared",
            "platform は Platform が付与する領域なので Publisher は書けない",
            source,
        )

    licenses, verified = normalize.normalize_licenses(
        raw.get("licenses"), report, source, where="dataset"
    )

    out: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "name": normalize.normalize_text(raw.get("name")) or "",
        "title": normalize.normalize_text(raw.get("title")) or "",
        "language": normalize.normalize_text(raw.get("language")) or "",
        "licenses": licenses,
    }
    for key in ("description", "homepage", "cover", "update_frequency"):
        value = normalize.normalize_text(raw.get(key))
        if value is not None:
            out[key] = value
    for key in ("keywords", "spatial_coverage"):
        values = normalize.normalize_string_list(raw.get(key), report, source, f"dataset.{key}")
        if values:
            out[key] = values
    for key in ("sources", "contributors"):
        if raw.get(key):
            out[key] = raw[key]
    if raw.get("temporal_coverage"):
        out["temporal_coverage"] = raw["temporal_coverage"]
    if raw.get("ai_context"):
        out["ai_context"] = raw["ai_context"]

    schemas = raw.get("schemas") or []
    if schemas:
        out["schemas"] = [
            {k: v for k, v in schema.items() if v is not None}
            for schema in schemas
            if isinstance(schema, dict)
        ]

    for key in ("name", "title", "language"):
        if not out[key]:
            report.error("dataset-required-missing", f"dataset.yml に {key} が無い", source)
    if not licenses:
        report.error(
            "licenses-missing",
            "licenses が無い。ライセンス不明のデータは受け入れない",
            source,
        )
    return out, verified


def _resolve_sql(
    declaration: dict[str, Any],
    source: Path,
    root: Path,
    table_name: str,
    dbt_compiled: str | None,
    report: Report,
) -> tuple[str | None, str | None]:
    """(sql, source_path) を返す。

    優先順位:
      1. sql: で明示指定されたファイル（Publisher の意思）
      2. dbt manifest の compiled_code（Jinja 展開済みでそのまま実行できる）
      3. 同ディレクトリの同名 .sql の自動検知
    """
    explicit = declaration.get("sql")
    if explicit is False:
        return dbt_compiled, None
    if isinstance(explicit, str):
        candidate = (source.parent / explicit).resolve()
        if not candidate.is_file():
            report.error(
                "sql-file-missing", f"{table_name}: sql: の指す {explicit} が無い", source
            )
            return dbt_compiled, None
        return candidate.read_text(encoding="utf-8").strip(), _relative(candidate, root)

    if dbt_compiled:
        return dbt_compiled, None

    # 自動検知はファイル名とテーブル名が対応しているときだけ。
    # 複数テーブルを 1 ファイルに書いた場合は basename が一意にならないので効かない。
    if source.name.endswith((".table.yml", ".table.yaml")) and basename_of(source) == table_name:
        candidate = source.parent / f"{table_name}.sql"
        if candidate.is_file():
            report.info(
                "sql-auto-detected",
                f"{table_name}: 同名の {candidate.name} を変換 SQL として紐づけた",
                source,
            )
            return candidate.read_text(encoding="utf-8").strip(), _relative(candidate, root)
    return None, None


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def build(spec: BuildInput, report: Report) -> dict[str, Any]:
    loaded = load(spec.root, report)
    dataset, license_verified = _dataset_level(loaded, report)

    physical = _read_physical(spec, report)
    artifacts = (
        load_manifest(spec.manifest_path) if spec.manifest_path else DbtArtifacts()
    )

    declared: dict[tuple[str, str], tuple[dict[str, Any], Path]] = {}
    for table in loaded.tables:
        key = table.key
        if not key[1] or key in declared:
            continue
        declared[key] = (table.data, table.source)

    _check_dbtignore(loaded, report)

    keys = sorted(set(physical) | set(declared))
    tables: list[dict[str, Any]] = []
    for key in keys:
        entry = _build_table(
            key,
            declared.get(key),
            physical.get(key),
            artifacts.nodes.get(key),
            dataset,
            spec.root,
            physical_available=bool(physical),
            report=report,
        )
        if entry is not None:
            tables.append(entry)

    _check_depends_on(tables, report)
    _check_schemas(dataset, tables, report)

    dataset["tables"] = tables
    dataset["platform"] = {"license_verified": license_verified}
    return dataset


def _read_physical(spec: BuildInput, report: Report) -> dict[tuple[str, str], PhysicalTable]:
    from . import physical as physical_module

    if spec.parquet:
        return physical_module.read_parquet(spec.parquet)
    if spec.catalog_path:
        return physical_module.read_ducklake(spec.catalog_path, spec.data_path)
    report.warning(
        "physical-not-read",
        "実データを読んでいないので型・列順・NULL 許容が付かず、実スキーマ照合も行わない",
    )
    return {}


def _build_table(
    key: tuple[str, str],
    declaration: tuple[dict[str, Any], Path] | None,
    physical: PhysicalTable | None,
    dbt_node,
    dataset: dict[str, Any],
    root: Path,
    *,
    physical_available: bool,
    report: Report,
) -> dict[str, Any] | None:
    schema, name = key

    if declaration is None:
        # 実データにあるが記述が無い。中間テーブルでは普通のこと。
        report.info("table-not-declared", f"{schema}.{name}: 記述が無い（物理名のみで載る）")
        data: dict[str, Any] = {}
        source = None
    else:
        data, source = declaration
        if physical_available and physical is None:
            report.error(
                "table-not-in-data",
                f"{schema}.{name}: 記述はあるが実データに存在しない",
                source,
            )
            return None
        unknown = sorted(set(data) - TABLE_KEYS)
        if unknown:
            report.error("table-unknown-keys", f"{schema}.{name}: 未知のキー {unknown}", source)

    out: dict[str, Any] = {
        "schema": schema,
        "name": name,
        "published": bool(data.get("published", False)),
    }
    for field_name in ("title", "description"):
        value = normalize.normalize_text(data.get(field_name))
        if value is not None:
            out[field_name] = value
    keywords = normalize.normalize_string_list(
        data.get("keywords"), report, source, f"{schema}.{name}.keywords"
    )
    if keywords:
        out["keywords"] = keywords

    if physical is not None:
        out["materialized"] = physical.materialized
    elif dbt_node is not None and dbt_node.materialized:
        out["materialized"] = dbt_node.materialized

    # licenses / sources は table > dataset の 2 段。compile で解決して artifact には
    # 継承の痕跡を残さない（読む側が場合分けしなくて済む）。
    if data.get("licenses"):
        licenses, _ = normalize.normalize_licenses(
            data["licenses"], report, source, where=f"{schema}.{name}"
        )
    else:
        licenses = dataset.get("licenses", [])
    if licenses:
        out["licenses"] = licenses
    sources = data.get("sources") or dataset.get("sources")
    if sources:
        out["sources"] = sources
    if data.get("ai_context"):
        out["ai_context"] = data["ai_context"]

    if source is not None:
        sql, source_path = _resolve_sql(
            data,
            source,
            root,
            name,
            dbt_node.compiled_code if dbt_node else None,
            report,
        )
    else:
        sql, source_path = (dbt_node.compiled_code if dbt_node else None), None
    if sql:
        out["sql"] = sql
    if source_path is None and dbt_node is not None and dbt_node.original_file_path:
        source_path = dbt_node.original_file_path
    if source_path:
        out["source_path"] = source_path

    depends_on = _resolve_depends_on(key, data, source, dbt_node, report)
    if depends_on:
        out["depends_on"] = depends_on

    out["fields"] = _build_fields(key, data, physical, source, report)
    if declaration is not None and out["published"] and not out.get("description"):
        report.warning(
            "published-without-description",
            f"{schema}.{name}: 公開テーブルに description が無い",
            source,
        )
    return out


def _resolve_depends_on(key, data, source, dbt_node, report: Report) -> list[str]:
    declared = data.get("depends_on") or []
    if dbt_node is not None and dbt_node.parents:
        if declared:
            report.warning(
                "depends-on-ignored",
                f"{key[0]}.{key[1]}: dbt manifest から lineage が取れるので depends_on は無視される",
                source,
            )
        return sorted(f"{schema}.{name}" for schema, name in dbt_node.parents)

    out = []
    for item in declared:
        text = str(item)
        parts = text.split(".")
        if len(parts) != 2:
            report.error(
                "depends-on-invalid",
                f"{key[0]}.{key[1]}: depends_on は schema.name の 2 段で書く "
                f"(got {text!r})。クロスデータセット参照は v1 では未対応",
                source,
            )
            continue
        if tuple(parts) == key:
            report.error(
                "depends-on-self", f"{key[0]}.{key[1]}: 自分自身に依存している", source
            )
            continue
        out.append(text)
    return sorted(set(out))


def _build_fields(key, data, physical, source, report: Report) -> list[dict[str, Any]]:
    schema, name = key
    declared = normalize.normalize_fields(
        data.get("fields"), report, source, f"{schema}.{name}"
    )

    if physical is None:
        # 実データを読んでいない。宣言順をそのまま使う。
        return [
            {**entry, "index": index}
            for index, entry in enumerate(declared.values())
        ]

    out = []
    for column in physical.fields:
        entry = dict(declared.pop(column.name, {"name": column.name}))
        entry["index"] = column.index
        entry["type"] = column.type
        entry["nullable"] = column.nullable
        out.append(entry)
        if "title" not in entry and "description" not in entry:
            continue

    for leftover in sorted(declared):
        report.error(
            "field-not-in-data",
            f"{schema}.{name}.{leftover}: 記述はあるが実データに列が無い",
            source,
        )
    described = {f["name"] for f in out if f.get("title") or f.get("description")}
    missing = [f["name"] for f in out if f["name"] not in described]
    if missing and source is not None:
        report.warning(
            "field-not-described",
            f"{schema}.{name}: 説明の無い列 {missing}",
            source,
        )
    return out


def _check_depends_on(tables: list[dict[str, Any]], report: Report) -> None:
    known = {f"{t['schema']}.{t['name']}" for t in tables}
    for table in tables:
        for reference in table.get("depends_on", []):
            if reference not in known:
                report.error(
                    "depends-on-unknown",
                    f"{table['schema']}.{table['name']}: depends_on の {reference} が存在しない",
                )


def _check_schemas(dataset: dict[str, Any], tables, report: Report) -> None:
    declared = {s["name"] for s in dataset.get("schemas", [])}
    used = {t["schema"] for t in tables}
    for schema in sorted(used - declared):
        report.info(
            "schema-not-declared",
            f"スキーマ {schema} は schemas[] に無い（title が付かないだけ）",
        )
    for schema in sorted(declared - used):
        report.warning(
            "schema-unused", f"schemas[] の {schema} に対応するテーブルが無い"
        )


def _check_dbtignore(loaded: Loaded, report: Report) -> None:
    """dbt の model-paths 配下に *.table.yml を置くなら .dbtignore が要る。

    dbt は model-paths 配下の .yml を全部 properties ファイルとして読むので、
    除外しないと未知のトップレベルキーでパースエラーになる。
    """
    if not loaded.colocated_in_model_paths:
        return
    dbtignore = loaded.root / ".dbtignore"
    patterns = (
        dbtignore.read_text(encoding="utf-8").splitlines() if dbtignore.is_file() else []
    )
    if any(line.strip() in {"*.table.yml", "*.table.yaml", "**/*.table.yml"} for line in patterns):
        return
    example = loaded.colocated_in_model_paths[0]
    report.error(
        "dbtignore-missing",
        f"{example} など dbt の models 配下に *.table.yml があるのに "
        f".dbtignore に '*.table.yml' が無い。dbt がこれを properties ファイルとして"
        f"読もうとしてパースエラーになる",
        dbtignore if dbtignore.is_file() else loaded.root / ".dbtignore",
    )


def to_json(artifact: dict[str, Any]) -> str:
    """キーを安定ソートして書き出す。同じ入力から常にバイト等価になる。"""
    return json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
