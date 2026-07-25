"""載せる条件の検証。

error は「Queria に載せられない」を意味する。とくに権利まわりは、これまで
候補台帳に手書きで管理されていた「商用再配布不可なら取り込まない」という
運用ルールを機械可読にするためのもの。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import Report

SCHEMA_PATH = Path(__file__).parent / "schema" / "dataset-1.0.schema.json"


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def check_schema(artifact: dict[str, Any], report: Report) -> None:
    try:
        import jsonschema
    except ModuleNotFoundError:  # pragma: no cover - 環境依存
        report.warning("jsonschema-missing", "jsonschema が無いのでスキーマ検証を飛ばした")
        return

    validator = jsonschema.Draft202012Validator(schema())
    for error in sorted(validator.iter_errors(artifact), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        report.error("schema-violation", f"{location}: {error.message}")


def check_rights(artifact: dict[str, Any], report: Report) -> None:
    licenses = artifact.get("licenses") or []
    for license_ in licenses:
        if not license_.get("commercial_use"):
            report.error(
                "commercial-use-denied",
                f"ライセンス {license_.get('id')} は商用再配布を許していない。"
                f"Queria はこのデータを受け入れない",
            )
        if license_.get("attribution_required") and not _has_attribution(artifact):
            report.error(
                "attribution-missing",
                f"ライセンス {license_.get('id')} は帰属表示を要求しているが、"
                f"帰属先が分からない。contributors か sources に "
                f"title を書くこと",
            )


def _has_attribution(artifact: dict[str, Any]) -> bool:
    for key in ("contributors", "sources"):
        for entry in artifact.get(key) or []:
            if isinstance(entry, dict) and entry.get("title"):
                return True
    return False


def check_quality(artifact: dict[str, Any], report: Report) -> None:
    if not artifact.get("description"):
        report.warning("dataset-description-missing", "dataset に description が無い")
    if not artifact.get("tables"):
        report.warning("no-tables", "テーブルが 1 つも無い")


def run(artifact: dict[str, Any], report: Report) -> Report:
    check_schema(artifact, report)
    check_rights(artifact, report)
    check_quality(artifact, report)
    return report
