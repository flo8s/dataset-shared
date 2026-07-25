"""宣言・実データ・dbt artifacts の突き合わせ。"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import codes, run_build, write
from queria_dataset.build import to_json
from queria_dataset.errors import Level


def _fields(artifact, name):
    (table,) = [t for t in artifact["tables"] if t["name"] == name]
    return {f["name"]: f for f in table["fields"]}


def test_型と列順とNULL許容は実データから入る(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        """
        schema: main
        name: mart_calendar
        title: 暦
        description: テスト
        published: true
        fields:
          - name: date
            title: 日付
        """,
    )
    artifact, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert not report.failed, report.render()
    fields = _fields(artifact, "mart_calendar")
    assert fields["date"]["type"] == "DATE"
    assert fields["date"]["nullable"] is False  # NOT NULL が反映される
    assert fields["date"]["index"] == 0
    assert fields["year"]["nullable"] is True
    # 宣言していない列も実データから載る
    assert set(fields) == {"date", "year", "is_holiday"}


def test_記述にあるが実データに無いテーブルはerror(repo: Path, ducklake):
    catalog, data = ducklake
    write(repo / "ghost.table.yml", "schema: main\nname: ghost\n")
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "table-not-in-data" in codes(report, Level.ERROR)


def test_記述にあるが実データに無い列はerror(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        """
        schema: main
        name: mart_calendar
        fields:
          - name: nonexistent
            title: 無い列
        """,
    )
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "field-not-in-data" in codes(report, Level.ERROR)


def test_記述の無いテーブルも物理名で載る(repo: Path, ducklake):
    """リネージュのノードとして必要なので落とさない。"""
    catalog, data = ducklake
    artifact, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert not report.failed, report.render()
    names = {t["name"] for t in artifact["tables"]}
    assert names == {"mart_calendar", "raw_holidays"}
    assert "table-not-declared" in codes(report, Level.INFO)
    assert all(t["published"] is False for t in artifact["tables"])


def test_同名のSQLを自動検知する(repo: Path, ducklake):
    catalog, data = ducklake
    write(repo / "mart_calendar.table.yml", "schema: main\nname: mart_calendar\n")
    (repo / "mart_calendar.sql").write_text("SELECT 1", encoding="utf-8")
    artifact, report = run_build(repo, catalog_path=catalog, data_path=data)
    (table,) = [t for t in artifact["tables"] if t["name"] == "mart_calendar"]
    assert table["sql"] == "SELECT 1"
    assert table["source_path"] == "mart_calendar.sql"
    assert "sql-auto-detected" in codes(report, Level.INFO)


def test_sql_falseで自動検知を止められる(repo: Path, ducklake):
    catalog, data = ducklake
    write(repo / "mart_calendar.table.yml", "schema: main\nname: mart_calendar\nsql: false\n")
    (repo / "mart_calendar.sql").write_text("SELECT 1", encoding="utf-8")
    artifact, _ = run_build(repo, catalog_path=catalog, data_path=data)
    (table,) = [t for t in artifact["tables"] if t["name"] == "mart_calendar"]
    assert "sql" not in table


def test_sqlの指すファイルが無ければerror(repo: Path, ducklake):
    catalog, data = ducklake
    write(repo / "mart_calendar.table.yml", "schema: main\nname: mart_calendar\nsql: missing.sql\n")
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "sql-file-missing" in codes(report, Level.ERROR)


def test_dbtがあればcompiled_codeが勝つ(repo: Path, ducklake):
    """ソース SQL は ref() が未解決で実行できないため、展開済みを優先する。"""
    catalog, data = ducklake
    write(repo / "mart_calendar.table.yml", "schema: main\nname: mart_calendar\n")
    (repo / "mart_calendar.sql").write_text("SELECT * FROM {{ ref('raw_holidays') }}", encoding="utf-8")
    manifest = repo / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "nodes": {
                    "model.calendar.mart_calendar": {
                        "resource_type": "model",
                        "schema": "main",
                        "name": "mart_calendar",
                        "config": {"materialized": "view"},
                        "compiled_code": "SELECT * FROM main.raw_holidays",
                        "original_file_path": "models/main/mart/mart_calendar.sql",
                    },
                    "model.calendar.raw_holidays": {
                        "resource_type": "model",
                        "schema": "main",
                        "name": "raw_holidays",
                    },
                },
                "parent_map": {
                    "model.calendar.mart_calendar": ["model.calendar.raw_holidays"]
                },
            }
        ),
        encoding="utf-8",
    )
    artifact, report = run_build(
        repo, catalog_path=catalog, data_path=data, manifest_path=manifest
    )
    (table,) = [t for t in artifact["tables"] if t["name"] == "mart_calendar"]
    assert table["sql"] == "SELECT * FROM main.raw_holidays"
    assert table["depends_on"] == ["main.raw_holidays"]
    assert table["source_path"] == "models/main/mart/mart_calendar.sql"


def test_dbtが無ければdepends_onが使われる(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        """
        schema: main
        name: mart_calendar
        depends_on: [main.raw_holidays]
        """,
    )
    artifact, report = run_build(repo, catalog_path=catalog, data_path=data)
    (table,) = [t for t in artifact["tables"] if t["name"] == "mart_calendar"]
    assert table["depends_on"] == ["main.raw_holidays"]


def test_存在しない依存先はerror(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        "schema: main\nname: mart_calendar\ndepends_on: [main.nowhere]\n",
    )
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "depends-on-unknown" in codes(report, Level.ERROR)


def test_クロスデータセット参照はerror(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        "schema: main\nname: mart_calendar\ndepends_on: [other.main.t]\n",
    )
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "depends-on-invalid" in codes(report, Level.ERROR)


def test_models配下に置くならdbtignoreが要る(repo: Path):
    write(repo / "models" / "main" / "t.table.yml", "schema: main\nname: t\n")
    _, report = run_build(repo)
    assert "dbtignore-missing" in codes(report, Level.ERROR)

    (repo / ".dbtignore").write_text("*.table.yml\n", encoding="utf-8")
    _, report = run_build(repo)
    assert "dbtignore-missing" not in codes(report, Level.ERROR)


def test_semanticが列に直接付く(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        """
        schema: main
        name: mart_calendar
        fields:
          - name: date
            semantic: { role: entity, name: date }
          - name: year
            semantic: { role: measure, agg: sum }
        """,
    )
    artifact, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert not report.failed, report.render()
    fields = _fields(artifact, "mart_calendar")
    assert fields["date"]["semantic"] == {"role": "entity", "name": "date"}
    assert fields["year"]["semantic"] == {"role": "measure", "agg": "sum"}


def test_semanticのroleが不正ならerror(repo: Path, ducklake):
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        "schema: main\nname: mart_calendar\nfields:\n  - name: date\n    semantic: { role: bogus }\n",
    )
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "semantic-role-invalid" in codes(report, Level.ERROR)


def test_型を書いたらerror(repo: Path, ducklake):
    """二重管理させないため。型は実データから取る。"""
    catalog, data = ducklake
    write(
        repo / "mart_calendar.table.yml",
        "schema: main\nname: mart_calendar\nfields:\n  - name: date\n    type: DATE\n",
    )
    _, report = run_build(repo, catalog_path=catalog, data_path=data)
    assert "field-unknown-keys" in codes(report, Level.ERROR)


def test_platformを書いたらerror(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: x
        title: X
        language: ja
        licenses: [CC0-1.0]
        platform:
          validation_status: active
        """,
    )
    _, report = run_build(tmp_path)
    assert "platform-declared" in codes(report, Level.ERROR)


def test_出力が冪等(repo: Path, ducklake):
    catalog, data = ducklake
    write(repo / "mart_calendar.table.yml", "schema: main\nname: mart_calendar\ntitle: 暦\n")
    first, _ = run_build(repo, catalog_path=catalog, data_path=data)
    second, _ = run_build(repo, catalog_path=catalog, data_path=data)
    assert to_json(first) == to_json(second)
    # 時刻を混ぜていないこと（Platform が後から付ける）
    assert "modified" not in first["platform"]
