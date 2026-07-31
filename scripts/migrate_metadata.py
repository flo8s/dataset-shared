"""Moves a dataset's metadata out of fdl.toml and dbt, into dataset.yml.

Run once per repository, then delete the old copies once the catalog reads
dataset.json. This only moves text: the columns themselves are enumerated from
the data when `queria compile` runs, so nothing here has to touch the warehouse.

    python shared/scripts/migrate_metadata.py

Anything it cannot decide — a license that is not in the table below — stops the
run rather than being guessed at.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

SPEC_VERSION = "0.1"

#: The free-text licenses in fdl.toml, mapped to the ids the registry uses.
#: Anything absent stops the migration so a person decides.
LICENSE_IDS = {
    "政府標準利用規約 第2.0版": "JP-GOV-STD-2.0",
    "政府標準利用規約（第2.0版）": "JP-GOV-STD-2.0",
    "CC BY 4.0": "CC-BY-4.0",
    "クリエイティブ・コモンズ 表示 4.0 国際 (CC BY 4.0)": "CC-BY-4.0",
    "デジタル庁利用規約": "JP-DIGITAL-ADDRESS-BR",
    "国土数値情報利用規約": "JP-MLIT-NLFTP",
    "国土地理院コンテンツ利用規約（公共データ利用規約 PDL 1.0）": "JP-GSI-PDL-1.0",
    "金融庁 EDINET 利用規約": "JP-FSA-EDINET",
    "自由利用（日本郵便）": "JP-JAPANPOST-ZIPCODE",
    "メディア芸術データベースデータセット利用条件（自由な二次利用可）": "JP-MEDIAARTS-DB",
    # The ministries below all publish under PDL 1.0, worded differently in each
    # fdl.toml. Two of these free texts had gone stale: the gBizINFO terms page
    # they name is gone, and the JMA now follows PDL 1.0 rather than the
    # government standard terms. The ids are what their own pages say today.
    "公共データ利用規約（第1.0版）": "JP-PDL-1.0",
    "公共データ利用規約（第1.0版）準拠（CC BY 4.0 互換、出典明記が必要）": "JP-PDL-1.0",
    "公共データ利用規約（第1.0版）(PDL1.0) / CC BY 4.0": "JP-PDL-1.0",
    "気象庁ホームページ利用規約（政府標準利用規約 第2.0版 準拠）": "JP-PDL-1.0",
    "gBizINFO 利用規約準拠（出典明記のうえ商用利用可）": "JP-GOV-STD-2.0",
}

#: fdl.toml [meta].schedule values that the declaration accepts as-is.
UPDATE_FREQUENCIES = {
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "yearly",
    "irregular",
    "continuous",
}


class MigrationError(Exception):
    """Something a person has to resolve before the migration can run."""


class _Indented(yaml.SafeDumper):
    """Indents list items under their key, so the result reads like hand-written YAML."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _dump(data: dict[str, Any]) -> str:
    return yaml.dump(
        data, Dumper=_Indented, allow_unicode=True, sort_keys=False, width=100
    )


def _clean(value: Any) -> Any:
    """Drops empty values, so the result has no keys that say nothing."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if _clean(v) not in (None, [], {})}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return value.strip() or None
    return value


def license_id(free_text: str) -> str:
    resolved = LICENSE_IDS.get(free_text.strip())
    if resolved is None:
        raise MigrationError(
            f"license {free_text!r} has no id yet. Read the terms, add an entry to "
            f"queria's licenses.yml, then map it in LICENSE_IDS here"
        )
    return resolved


def dataset_declaration(
    meta: dict[str, Any], name: str, licenses: list[str] | None = None
) -> dict[str, Any]:
    """Turns fdl.toml's [meta] into the dataset-level declaration.

    ``licenses`` names the ids to use instead of reading [meta].license. Queria's
    own datasets need it: their content is nobody else's, so they never had a
    license to carry over, and the declaration requires one.
    """
    if licenses:
        ids = list(licenses)
    elif meta.get("license"):
        ids = [license_id(meta["license"])]
    else:
        raise MigrationError(
            "fdl.toml [meta] has no license. Pass --license <id> to say what this "
            "dataset is published under"
        )

    out: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "name": name,
        "title": meta.get("title"),
        "description": meta.get("description"),
        "keywords": meta.get("tags") or [],
        "homepage": meta.get("repository_url"),
        # Every dataset moved here today is described in Japanese. A dataset in
        # another language sets this itself.
        "language": "ja",
        "licenses": ids,
    }

    if meta.get("source_url"):
        out["sources"] = [{"path": meta["source_url"]}]

    schedule = (meta.get("schedule") or "").strip()
    if schedule:
        if schedule not in UPDATE_FREQUENCIES:
            raise MigrationError(
                f"schedule {schedule!r} is not one of {sorted(UPDATE_FREQUENCIES)}"
            )
        out["update_frequency"] = schedule

    if meta.get("cover"):
        out["cover"] = meta["cover"]

    schemas = [
        {"name": schema_name, "title": (body or {}).get("title")}
        for schema_name, body in (meta.get("schemas") or {}).items()
    ]
    if schemas:
        out["schemas"] = schemas

    return _clean(out)


def table_declarations(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Turns each dbt model's metadata into a table declaration.

    Note the asymmetry in how these projects were written: a table's description
    sits at dbt's top level, a column's under meta. Both are read, because
    dropping either would lose text that is already published.
    """
    out: dict[str, dict[str, Any]] = {}
    for node in (manifest.get("nodes") or {}).values():
        if not isinstance(node, dict) or node.get("resource_type") != "model":
            continue
        meta = (node.get("config") or {}).get("meta") or node.get("meta") or {}

        declaration: dict[str, Any] = {
            "schema": node.get("schema"),
            "name": node.get("name"),
            "title": meta.get("title"),
            "description": node.get("description"),
            "keywords": meta.get("tags") or [],
            "published": bool(meta.get("published", False)),
        }
        if meta.get("source_url"):
            declaration["sources"] = [{"path": meta["source_url"]}]
        if meta.get("license"):
            declaration["licenses"] = [license_id(meta["license"])]

        fields = []
        for column, body in (node.get("columns") or {}).items():
            column_meta = body.get("meta") or {}
            entry = _clean(
                {
                    "name": column,
                    "title": column_meta.get("title"),
                    "description": column_meta.get("description")
                    or body.get("description"),
                }
            )
            if len(entry) > 1:  # a bare name carries nothing worth moving
                fields.append(entry)
        if fields:
            declaration["fields"] = fields

        declaration = _clean(declaration)
        declaration.setdefault("published", False)
        if _worth_writing(declaration):
            out[str(node.get("original_file_path") or "")] = declaration
    return out


def _worth_writing(declaration: dict[str, Any]) -> bool:
    """Skips models that had nothing written about them in the first place."""
    return bool(
        declaration.get("title")
        or declaration.get("description")
        or declaration.get("fields")
        or declaration.get("published")
    )


def declaration_path(root: Path, original_file_path: str, name: str) -> Path:
    if original_file_path:
        return root / Path(original_file_path).with_suffix(".table.yml")
    return root / "tables" / f"{name}.table.yml"


def ensure_dbtignore(root: Path) -> bool:
    """dbt reads every .yml under its model paths and would fail on these."""
    path = root / ".dbtignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if any(line.strip() == "*.table.yml" for line in lines):
        return False
    lines.append("*.table.yml")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def migrate(
    root: Path, *, force: bool = False, licenses: list[str] | None = None
) -> list[Path]:
    fdl_toml = root / "fdl.toml"
    if not fdl_toml.is_file():
        raise MigrationError(f"{fdl_toml} not found")
    with fdl_toml.open("rb") as fh:
        config = tomllib.load(fh)
    meta = config.get("meta")
    if not meta:
        raise MigrationError("fdl.toml has no [meta] to migrate")

    manifest_path = root / "target" / "manifest.json"
    if not manifest_path.is_file():
        raise MigrationError(
            f"{manifest_path} not found. Build the dataset first so dbt writes it"
        )
    with manifest_path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)

    written: list[Path] = []

    dataset_file = root / "dataset.yml"
    if dataset_file.exists() and not force:
        raise MigrationError(f"{dataset_file} already exists (pass --force to replace)")
    dataset_file.write_text(
        _dump(dataset_declaration(meta, str(config["name"]), licenses)), encoding="utf-8"
    )
    written.append(dataset_file)

    for original_file_path, declaration in sorted(table_declarations(manifest).items()):
        path = declaration_path(root, original_file_path, declaration["name"])
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dump(declaration), encoding="utf-8")
        written.append(path)

    if any(p.is_relative_to(root / "models") for p in written) and ensure_dbtignore(root):
        written.append(root / ".dbtignore")

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--force", action="store_true", help="replace declarations that already exist"
    )
    parser.add_argument(
        "--license",
        action="append",
        dest="licenses",
        metavar="ID",
        help="license id to use instead of the one in fdl.toml (repeatable)",
    )
    args = parser.parse_args(argv)

    try:
        written = migrate(args.root, force=args.force, licenses=args.licenses)
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(f"wrote {path.relative_to(args.root)}")
    print(REMAINING)
    return 0


REMAINING = """
Only what already existed was moved. These have to be written by hand, because
nothing in fdl.toml or dbt knows them:

  contributors        who to credit. Required by most of these licenses, so
                      `queria validate` will stop until it is filled in
  temporal_coverage   the period the data covers
  spatial_coverage    the countries it covers

Run `queria validate` next; it lists what is still missing.

Leave [meta] in fdl.toml and meta.* in the dbt YAML for now. Removing them
before the catalog reads dataset.json would blank out this dataset in
production."""


if __name__ == "__main__":
    raise SystemExit(main())
