"""dbt artifacts から、実データにも宣言にも無いものだけを取る。

取るのは lineage（parent_map）と変換 SQL（compiled_code）、そしてソースファイルの
パスだけ。人間向けメタデータ（title / description / tags / published）は読まない
— それらは新形式が正本であり、dbt に戻す道を残さない。

manifest.json が無くても動く。その場合 lineage と SQL が欠けるだけ。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DbtNode:
    schema: str
    name: str
    materialized: str | None
    compiled_code: str | None
    original_file_path: str | None
    parents: list[tuple[str, str]] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.schema, self.name)


@dataclass
class DbtArtifacts:
    nodes: dict[tuple[str, str], DbtNode] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.nodes)


def _unique_id_to_key(unique_id: str, nodes: dict[str, Any]) -> tuple[str, str] | None:
    node = nodes.get(unique_id)
    if not isinstance(node, dict):
        return None
    if node.get("resource_type") != "model":
        return None
    return (str(node.get("schema", "")), str(node.get("name", "")))


def load_manifest(path: Path) -> DbtArtifacts:
    if not path.is_file():
        return DbtArtifacts()

    with path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)

    raw_nodes = manifest.get("nodes") or {}
    artifacts = DbtArtifacts()

    for unique_id, node in raw_nodes.items():
        if not isinstance(node, dict) or node.get("resource_type") != "model":
            continue
        compiled = node.get("compiled_code")
        if isinstance(compiled, str):
            compiled = compiled.strip() or None
        else:
            compiled = None
        entry = DbtNode(
            schema=str(node.get("schema", "")),
            name=str(node.get("name", "")),
            materialized=((node.get("config") or {}).get("materialized")),
            compiled_code=compiled,
            original_file_path=node.get("original_file_path"),
        )
        artifacts.nodes[entry.key] = entry

    for child_id, parent_ids in (manifest.get("parent_map") or {}).items():
        child = _unique_id_to_key(child_id, raw_nodes)
        if child is None or child not in artifacts.nodes:
            continue
        parents = []
        for parent_id in parent_ids or []:
            parent = _unique_id_to_key(parent_id, raw_nodes)
            if parent is not None:
                parents.append(parent)
        artifacts.nodes[child].parents = sorted(set(parents))

    return artifacts
