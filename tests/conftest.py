from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from queria_dataset.build import BuildInput, build
from queria_dataset.errors import Level, Report
from queria_dataset.validate import run as validate_run

DATASET_YML = """\
spec_version: "1.0"
name: calendar
title: 日本の暦データ
description: テスト用
language: ja
licenses: [JP-GOV-STD-2.0]
contributors:
  - title: 内閣府
schemas:
  - name: main
    title: メイン
"""


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """最小構成のデータセットリポジトリ。"""
    write(tmp_path / "dataset.yml", DATASET_YML)
    return tmp_path


@pytest.fixture
def ducklake(tmp_path: Path):
    """テーブル 2 つの DuckLake を作り、(catalog, data) を返す。"""
    import duckdb

    catalog = tmp_path / "meta.sqlite"
    data = tmp_path / "data"
    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake;")
    con.execute(
        f"ATTACH 'ducklake:{catalog}' AS q (DATA_PATH '{data}/', META_TYPE 'sqlite')"
    )
    con.execute(
        "CREATE TABLE q.main.mart_calendar "
        "(date DATE NOT NULL, year INTEGER, is_holiday BOOLEAN)"
    )
    con.execute("CREATE TABLE q.main.raw_holidays (date DATE, holiday_name VARCHAR)")
    con.close()
    return str(catalog), f"{data}/"


def run_build(root: Path, **kwargs) -> tuple[dict, Report]:
    report = Report()
    artifact = build(BuildInput(root=root, **kwargs), report)
    validate_run(artifact, report)
    return artifact, report


def codes(report: Report, level: Level) -> set[str]:
    return {finding.code for finding in report.of(level)}
