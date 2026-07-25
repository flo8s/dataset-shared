"""ライセンスレジストリ。

Publisher には ID だけ書かせ、title / url / 権利フラグはここから引く。
Publisher に法的判断をさせないための仕組みなので、レジストリに無い ID は
Publisher 自身に commercial_use を明示させ、検証ゲートで人手レビューに回す。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).parent / "licenses.yml"


@lru_cache(maxsize=1)
def registry() -> dict[str, dict[str, Any]]:
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def lookup(license_id: str) -> dict[str, Any] | None:
    entry = registry().get(license_id)
    if entry is None:
        return None
    return {
        "id": license_id,
        "spdx": entry.get("spdx"),
        "url": entry.get("url"),
        "title": entry.get("title"),
        "commercial_use": bool(entry.get("commercial_use", False)),
        "share_alike": bool(entry.get("share_alike", False)),
        "attribution_required": bool(entry.get("attribution_required", False)),
    }


def known_ids() -> list[str]:
    return sorted(registry())
