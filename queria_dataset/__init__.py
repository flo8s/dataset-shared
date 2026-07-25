"""Queria データセット宣言のツール。

dataset.yml と **/*.table.yml を読み、実データと dbt artifacts を突き合わせて
dataset.json を書き出す。dbt-core / DuckLake / fdl には import 依存しない。
"""

from .build import SPEC_VERSION

__all__ = ["SPEC_VERSION"]
