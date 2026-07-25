"""権利まわり。

これまで候補台帳に手書きで管理されていた「商用再配布不可なら取り込まない」を
機械可読にする部分なので、error になることを確かめる。
"""

from __future__ import annotations

from pathlib import Path

from conftest import codes, run_build, write
from queria_dataset.errors import Level


def test_ID一つ書けばレジストリから展開される(repo: Path):
    artifact, report = run_build(repo)
    assert not report.failed, report.render()
    (license_,) = artifact["licenses"]
    assert license_["id"] == "JP-GOV-STD-2.0"
    assert license_["title"] == "政府標準利用規約（第2.0版）"
    assert license_["commercial_use"] is True
    assert license_["attribution_required"] is True
    assert artifact["platform"]["license_verified"] is True


def test_licensesが無ければerror(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: nolicense
        title: ライセンス無し
        language: ja
        """,
    )
    _, report = run_build(tmp_path)
    assert "licenses-missing" in codes(report, Level.ERROR)


def test_レジストリに無くcommercial_use未指定ならerror(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: unknown
        title: 独自規約
        language: ja
        licenses:
          - id: city-example-terms
            url: https://city.example.jp/terms
        """,
    )
    _, report = run_build(tmp_path)
    assert "license-unverified-no-commercial-use" in codes(report, Level.ERROR)


def test_レジストリに無くても申告すれば通り未検証として記録される(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: unknown
        title: 独自規約
        description: テスト
        language: ja
        contributors:
          - title: 〇〇市
        licenses:
          - id: city-example-terms
            url: https://city.example.jp/terms
            title: 〇〇市オープンデータ利用規約
            commercial_use: true
            attribution_required: true
        """,
    )
    artifact, report = run_build(tmp_path)
    assert not report.failed, report.render()
    assert "license-unverified" in codes(report, Level.WARNING)
    assert artifact["platform"]["license_verified"] is False


def test_商用利用不可はerror(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: noncommercial
        title: 非商用
        description: テスト
        language: ja
        licenses:
          - id: some-nc-terms
            url: https://example.com/nc
            commercial_use: false
        """,
    )
    _, report = run_build(tmp_path)
    assert "commercial-use-denied" in codes(report, Level.ERROR)


def test_帰属必須なのに帰属先が無ければerror(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: noattr
        title: 帰属先不明
        description: テスト
        language: ja
        licenses: [CC-BY-4.0]
        """,
    )
    _, report = run_build(tmp_path)
    assert "attribution-missing" in codes(report, Level.ERROR)


def test_帰属不要のライセンスなら帰属先が無くても通る(tmp_path: Path):
    write(
        tmp_path / "dataset.yml",
        """
        spec_version: "1.0"
        name: cc0
        title: パブリックドメイン
        description: テスト
        language: en
        licenses: [CC0-1.0]
        """,
    )
    _, report = run_build(tmp_path)
    assert not report.failed, report.render()
