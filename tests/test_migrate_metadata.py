"""Moving a dataset's metadata into dataset.yml.

This runs once per repository against text that is already published, so the
tests are mostly about not losing any of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_metadata import (  # noqa: E402
    MigrationError,
    dataset_declaration,
    migrate,
    table_declarations,
)

FDL_TOML = """\
name = "calendar"
command = "python main.py"

[targets.local]
url = "~/.local/share/fdl"

[meta]
license = "政府標準利用規約 第2.0版"
license_url = "https://www.cao.go.jp/notice/rule.html"
title = "日本の暦データ"
description = "1955年〜2027年の日付スパイン"
cover = "📅"
tags = ['カレンダー', '祝日']
repository_url = "https://github.com/queria-io/dataset-calendar"
schedule = "yearly"

[meta.schemas]
main.title = "メイン"
"""

MANIFEST = {
    "nodes": {
        "model.calendar.mart_calendar": {
            "resource_type": "model",
            "schema": "main",
            "name": "mart_calendar",
            "description": "1955年から2027年までの暦。",
            "original_file_path": "models/main/mart/mart_calendar.sql",
            "config": {
                "meta": {
                    "title": "日本の暦データ",
                    "published": True,
                    "tags": ["カレンダー"],
                    "source_url": "https://www8.cao.go.jp/",
                }
            },
            "columns": {
                "date": {"meta": {"title": "日付", "description": "主キー"}},
                "year": {"meta": {"title": "年"}},
            },
        },
        "model.calendar.raw_holidays": {
            "resource_type": "model",
            "schema": "main",
            "name": "raw_holidays",
            "description": "内閣府の生データ",
            "original_file_path": "models/main/raw/raw_holidays.sql",
            "columns": {"date": {"description": "日付"}},
        },
    }
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "fdl.toml").write_text(FDL_TOML, encoding="utf-8")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(
        json.dumps(MANIFEST), encoding="utf-8"
    )
    return tmp_path


def test_the_dataset_level_metadata_moves_across(repo: Path):
    migrate(repo)
    data = yaml.safe_load((repo / "dataset.yml").read_text())
    assert data["name"] == "calendar"
    assert data["title"] == "日本の暦データ"
    assert data["keywords"] == ["カレンダー", "祝日"]
    assert data["homepage"] == "https://github.com/queria-io/dataset-calendar"
    assert data["update_frequency"] == "yearly"
    assert data["cover"] == "📅"
    assert data["schemas"] == [{"name": "main", "title": "メイン"}]


def test_the_free_text_license_becomes_an_id(repo: Path):
    migrate(repo)
    data = yaml.safe_load((repo / "dataset.yml").read_text())
    assert data["licenses"] == ["JP-GOV-STD-2.0"]


def test_an_unmapped_license_stops_the_migration(repo: Path):
    text = (repo / "fdl.toml").read_text().replace(
        "政府標準利用規約 第2.0版", "どこかの独自規約"
    )
    (repo / "fdl.toml").write_text(text, encoding="utf-8")
    with pytest.raises(MigrationError, match="どこかの独自規約"):
        migrate(repo)


def test_an_unknown_schedule_stops_the_migration(repo: Path):
    text = (repo / "fdl.toml").read_text().replace('schedule = "yearly"', 'schedule = "毎年"')
    (repo / "fdl.toml").write_text(text, encoding="utf-8")
    with pytest.raises(MigrationError, match="毎年"):
        migrate(repo)


def test_declarations_land_next_to_their_model(repo: Path):
    migrate(repo)
    assert (repo / "models/main/mart/mart_calendar.table.yml").is_file()
    assert (repo / "models/main/raw/raw_holidays.table.yml").is_file()
    # dbt would otherwise read these as its own properties files.
    assert "*.table.yml" in (repo / ".dbtignore").read_text()


def test_table_text_moves_across(repo: Path):
    migrate(repo)
    data = yaml.safe_load((repo / "models/main/mart/mart_calendar.table.yml").read_text())
    assert data["schema"] == "main"
    assert data["title"] == "日本の暦データ"
    assert data["description"] == "1955年から2027年までの暦。"
    assert data["published"] is True
    assert data["keywords"] == ["カレンダー"]
    assert data["sources"] == [{"path": "https://www8.cao.go.jp/"}]


def test_column_text_moves_across_from_either_place(repo: Path):
    """A table's description sits at dbt's top level, a column's under meta."""
    migrate(repo)
    mart = yaml.safe_load((repo / "models/main/mart/mart_calendar.table.yml").read_text())
    fields = {f["name"]: f for f in mart["fields"]}
    assert fields["date"] == {"name": "date", "title": "日付", "description": "主キー"}
    assert fields["year"] == {"name": "year", "title": "年"}

    raw = yaml.safe_load((repo / "models/main/raw/raw_holidays.table.yml").read_text())
    # This one only ever had dbt's own description, with no meta at all.
    assert raw["fields"] == [{"name": "date", "description": "日付"}]
    assert raw["published"] is False


def test_columns_nobody_wrote_about_are_left_out(repo: Path):
    """compile enumerates the real columns, so an empty entry would only be noise."""
    manifest = json.loads(json.dumps(MANIFEST))
    manifest["nodes"]["model.calendar.mart_calendar"]["columns"]["month"] = {}
    (repo / "target" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    migrate(repo)
    data = yaml.safe_load((repo / "models/main/mart/mart_calendar.table.yml").read_text())
    assert [f["name"] for f in data["fields"]] == ["date", "year"]


def test_models_nobody_wrote_about_get_no_file(repo: Path):
    manifest = {
        "nodes": {
            "model.calendar.stg_nothing": {
                "resource_type": "model",
                "schema": "main",
                "name": "stg_nothing",
                "original_file_path": "models/main/stg/stg_nothing.sql",
            }
        }
    }
    assert table_declarations(manifest) == {}


def test_existing_declarations_are_kept(repo: Path):
    migrate(repo)
    target = repo / "models/main/mart/mart_calendar.table.yml"
    target.write_text("mine: do not touch\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="already exists"):
        migrate(repo)
    assert target.read_text() == "mine: do not touch\n"

    migrate(repo, force=True)
    assert "mart_calendar" in target.read_text()


def test_a_dataset_without_a_license_stops_the_migration():
    with pytest.raises(MigrationError, match="license"):
        dataset_declaration({"title": "x"}, "x")


def test_a_missing_manifest_says_to_build_first(tmp_path: Path):
    (tmp_path / "fdl.toml").write_text(FDL_TOML, encoding="utf-8")
    with pytest.raises(MigrationError, match="Build the dataset first"):
        migrate(tmp_path)
