"""ファイルの読み込みと正規化。

規約は「dataset.yml が 1 つ」と「*.table.yml はどこでもよい」の 2 つだけ、
という前提が本当に成り立つかを見る。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import codes, run_build, write
from queria_dataset.errors import Level, Report, SpecError
from queria_dataset.loader import load


def test_単一形と複数形が同じ結果になる(repo: Path):
    write(
        repo / "a.table.yml",
        """
        schema: main
        name: t_single
        title: 単一形
        """,
    )
    write(
        repo / "b.table.yml",
        """
        tables:
          - schema: main
            name: t_multi
            title: 複数形
        """,
    )
    artifact, report = run_build(repo)
    assert not report.failed, report.render()
    titles = {t["name"]: t.get("title") for t in artifact["tables"]}
    assert titles == {"t_single": "単一形", "t_multi": "複数形"}


def test_YAMLアンカーで列構成を共有できる(repo: Path):
    """同じ列を持つ表が並ぶケース。1 ファイル 1 テーブルを強制すると破綻する。"""
    write(
        repo / "ssds.table.yml",
        """
        _fields: &fields
          - name: area
            title: 地域コード
          - name: value
            title: 統計値

        _common: &common
          schema: main
          published: true
          fields: *fields

        tables:
          - <<: *common
            name: a_population
            title: A 人口
            description: 人口
          - <<: *common
            name: b_land
            title: B 自然環境
            description: 面積
        """,
    )
    artifact, report = run_build(repo)
    assert not report.failed, report.render()
    tables = {t["name"]: t for t in artifact["tables"]}
    assert [f["name"] for f in tables["a_population"]["fields"]] == ["area", "value"]
    assert [f["name"] for f in tables["b_land"]["fields"]] == ["area", "value"]


def test_アンダースコア始まりのキーは無視される(repo: Path):
    write(
        repo / "x.table.yml",
        """
        _anchor: &a { title: アンカー置き場 }
        schema: main
        name: t
        title: 本体
        """,
    )
    artifact, report = run_build(repo)
    assert not report.failed, report.render()
    assert artifact["tables"][0]["title"] == "本体"


def test_同じテーブルが二重定義されたらerror(repo: Path):
    write(repo / "a.table.yml", "schema: main\nname: dup\n")
    write(repo / "b.table.yml", "schema: main\nname: dup\n")
    _, report = run_build(repo)
    assert "duplicate-table" in codes(report, Level.ERROR)


def test_無視ディレクトリの中は読まない(repo: Path):
    write(repo / ".venv" / "junk.table.yml", "schema: main\nname: junk\n")
    write(repo / "dbt_packages" / "dep.table.yml", "schema: main\nname: dep\n")
    artifact, report = run_build(repo)
    assert not report.failed, report.render()
    assert artifact["tables"] == []


def test_tablesと他キーの混在はerror(repo: Path):
    write(
        repo / "x.table.yml",
        """
        name: まぎらわしい
        tables:
          - schema: main
            name: t
        """,
    )
    _, report = run_build(repo)
    assert "mixed-form" in codes(report, Level.ERROR)


def test_datasetymlが無ければ続行しない(tmp_path: Path):
    with pytest.raises(SpecError, match="dataset.yml"):
        load(tmp_path, Report())


def test_dataset_ymlにインラインで書ける(tmp_path: Path):
    """casual publisher は 1 ファイルで完結できる。"""
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: solo
        title: 単一ファイル
        description: テスト
        language: en
        licenses: [CC0-1.0]
        tables:
          - schema: main
            name: only_table
            title: 唯一の表
        """,
    )
    artifact, report = run_build(tmp_path)
    assert not report.failed, report.render()
    assert artifact["tables"][0]["name"] == "only_table"
