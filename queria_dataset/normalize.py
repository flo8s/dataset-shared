"""authoring 形式の短縮形を、artifact の正規形に展開する。

正規化するのは「書き方の揺れ」だけで、意味を足したり推測したりはしない。
実データ由来の情報（型・列順・nullable）と dbt 由来の情報（lineage・SQL）は
compile が別途載せる。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import registry
from .errors import Report

#: dataset レベルから table レベルへ継承するキー。これ以外は継承しない。
INHERITED = ("licenses", "sources")


def normalize_licenses(
    raw: Any, report: Report, source: Path | None, *, where: str
) -> tuple[list[dict[str, Any]], bool]:
    """licenses を正規形へ。戻り値は (licenses, すべてレジストリ由来か)。

    受ける形:
        licenses: [CC-BY-4.0]                      文字列配列の短縮形
        licenses: [{id: ..., url: ..., ...}]       明示形
    """
    if raw is None:
        return [], True
    if not isinstance(raw, list):
        report.error("licenses-not-a-list", f"{where}: licenses がリストではない", source)
        return [], True

    out: list[dict[str, Any]] = []
    verified = True
    for item in raw:
        if isinstance(item, str):
            item = {"id": item}
        if not isinstance(item, dict):
            report.error(
                "license-not-a-mapping",
                f"{where}: licenses の要素は文字列かマッピング",
                source,
            )
            continue

        license_id = item.get("id")
        if not license_id:
            report.error("license-id-missing", f"{where}: licenses[].id が無い", source)
            continue

        known = registry.lookup(str(license_id))
        if known is not None:
            # レジストリが正。Publisher の記述で上書きさせない。
            overridden = sorted(set(item) - {"id"})
            if overridden:
                report.info(
                    "license-fields-ignored",
                    f"{where}: {license_id} はレジストリ登録済みなので "
                    f"{overridden} は無視される",
                    source,
                )
            out.append(known)
            continue

        # レジストリに無い。Publisher の申告として扱い、あとで人手レビューに回す。
        verified = False
        if "commercial_use" not in item:
            report.error(
                "license-unverified-no-commercial-use",
                f"{where}: {license_id} はレジストリに無い。"
                f"commercial_use を明示するか、レジストリに追加すること "
                f"(既知: {', '.join(registry.known_ids())})",
                source,
            )
            continue
        if not item.get("url"):
            report.error(
                "license-unverified-no-url",
                f"{where}: {license_id} はレジストリに無いので url が必須",
                source,
            )
            continue
        out.append(
            {
                "id": str(license_id),
                "spdx": item.get("spdx"),
                "url": item.get("url"),
                "title": item.get("title"),
                "commercial_use": bool(item.get("commercial_use")),
                "share_alike": bool(item.get("share_alike", False)),
                "attribution_required": bool(item.get("attribution_required", False)),
            }
        )
        report.warning(
            "license-unverified",
            f"{where}: {license_id} はレジストリに無い。"
            f"platform.license_verified を false にして人手レビューに回す",
            source,
        )

    return out, verified


def normalize_semantic(raw: Any, report: Report, source: Path | None, where: str):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        report.error("semantic-not-a-mapping", f"{where}: semantic がマッピングではない", source)
        return None
    role = raw.get("role")
    if role not in ("entity", "dimension", "measure"):
        report.error(
            "semantic-role-invalid",
            f"{where}: semantic.role は entity / dimension / measure のいずれか (got {role!r})",
            source,
        )
        return None
    out: dict[str, Any] = {"role": role}
    if raw.get("name") is not None:
        out["name"] = str(raw["name"])
    if raw.get("agg") is not None:
        out["agg"] = str(raw["agg"])
    unknown = sorted(set(raw) - {"role", "name", "agg"})
    if unknown:
        report.error(
            "semantic-unknown-keys", f"{where}: semantic に未知のキー {unknown}", source
        )
    return out


def normalize_fields(raw: Any, report: Report, source: Path | None, where: str):
    """宣言されたフィールドを名前でひける形にする。型・列順は実データから載せる。"""
    if raw is None:
        return {}
    if not isinstance(raw, list):
        report.error("fields-not-a-list", f"{where}: fields がリストではない", source)
        return {}

    declared: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            report.error("field-not-a-mapping", f"{where}: fields[{index}] がマッピングではない", source)
            continue
        name = item.get("name")
        if not name:
            report.error("field-name-missing", f"{where}: fields[{index}].name が無い", source)
            continue
        name = str(name)
        if name in declared:
            report.error("duplicate-field", f"{where}: フィールド {name} が重複している", source)
            continue

        entry: dict[str, Any] = {"name": name}
        for key in ("title", "description"):
            if item.get(key) is not None:
                entry[key] = str(item[key]).strip()
        semantic = normalize_semantic(
            item.get("semantic"), report, source, f"{where}.{name}"
        )
        if semantic is not None:
            entry["semantic"] = semantic

        unknown = sorted(set(item) - {"name", "title", "description", "semantic"})
        if unknown:
            report.error(
                "field-unknown-keys",
                f"{where}.{name}: 未知のキー {unknown}。型は実データから解決するので書かない",
                source,
            )
        declared[name] = entry

    return declared


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_string_list(raw: Any, report: Report, source: Path | None, where: str):
    if raw is None:
        return []
    if not isinstance(raw, list):
        report.error("not-a-list", f"{where} がリストではない", source)
        return []
    return [str(item) for item in raw]
