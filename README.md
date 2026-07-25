# dataset-shared

Queria データセットリポジトリの共通スクリプト。

各データセットリポが submodule として参照し、ビルド・デプロイの共通処理を提供する。

## 使い方

各データセットリポで:

```bash
# submodule 追加（初回のみ）
git submodule add https://github.com/queria-io/dataset-shared.git shared

# ビルド
scripts/build.sh local
```

## 提供マクロ

`macros/` に共通の dbt マクロを配置。各データセットの `dbt_project.yml` で参照する:

```yaml
macro-paths: ["macros", "shared/macros"]
```

- `macros/catalog.sql`: dbt-duckdb の `duckdb__get_catalog` オーバーライド。全アタッチ DB を対象にする修正
- `macros/generate_schema_name.sql`: サブディレクトリ名をスキーマ名として使用

## 提供スクリプト

- `scripts/build-dataset.sh`: データセットのビルド + artifacts push + catalog 自動リビルド
- `scripts/upload_artifacts.py`: dbt artifacts の S3/ローカル push

## queria_dataset — データセット宣言の検証とビルド

データセットのメタデータを宣言し、`dataset.json` に compile するツール。dbt を使うかどうかに
関わらず同じ形で書ける。dbt-core / DuckLake / fdl には import 依存しない。

### 書くもの

規約は 2 つだけ。ディレクトリ名は標準化しない。

| 規約 | 内容 |
|---|---|
| `dataset.yml`（ルート・必須） | データセット宣言。ここにしか書けない |
| `**/*.table.yml`（どこでもよい） | テーブル記述。1 テーブルでも複数でもよい |

```yaml
# dataset.yml
spec_version: "1.0"
name: calendar
title: 日本の暦データ
description: 1955年〜2027年の日付スパインに祝日・曜日・和暦・会計年度を付与
language: ja
licenses: [JP-GOV-STD-2.0]     # ID だけ書けば title/url/権利フラグはレジストリから入る
contributors:
  - title: 内閣府
    roles: [rightsHolder]
schemas:
  - name: main
    title: メイン
```

```yaml
# models/main/mart/mart_calendar.table.yml
schema: main
name: mart_calendar
title: 日本の暦データ
description: 祝日・曜日・和暦・会計年度を付与した日付スパイン
published: true
fields:
  - name: date
    title: 日付
    semantic: { role: entity, name: date }
```

同じ列構成の表が並ぶ場合は 1 ファイルに複数書ける。YAML アンカーが効く:

```yaml
_fields: &fields
  - { name: area, title: 地域コード }
  - { name: value, title: 統計値, semantic: { role: measure, agg: sum } }
tables:
  - { schema: ssds, name: a_municipal_population, title: A 人口・世帯, fields: *fields }
  - { schema: ssds, name: b_municipal_land,       title: B 自然環境,   fields: *fields }
```

**列の型は書かない。** compile が実データ（DuckLake / Parquet）から解決する。二重管理させない。

### dbt と併用する場合

`models/` 配下に `*.table.yml` を置くと dbt が properties ファイルとして読もうとして
パースエラーになる。`.dbtignore` に 1 行足すこと（検証が error で知らせる）:

```
*.table.yml
```

### 実行

```bash
# 検証のみ
uv run fdl run local -- python -m queria_dataset validate

# dataset.json を書き出す
uv run fdl run local -- python -m queria_dataset compile -o dist/dataset.json
```

`fdl run` 経由にするのは、カタログの場所（`FDL_CATALOG_PATH` / `FDL_DATA_URL`）を
環境変数で受け取るため。明示したいときは `--ducklake` / `--data-path` で上書きする。
dbt を使う場合は `--manifest target/manifest.json`（既定でこのパスを探す）。

### 供給元の役割

| 情報 | 供給元 |
|---|---|
| title / description / license / published / semantic | 宣言（`dataset.yml` / `*.table.yml`） |
| テーブル一覧・列・型・列順・NULL 許容・table か view か | 実データ |
| lineage・変換 SQL・ソースファイルのパス | dbt の `manifest.json`（**あれば**） |

dbt が無い場合、lineage は `depends_on` の手書き、変換 SQL は同名 `.sql` の自動検知で代替できる。

### 開発

```bash
uv sync
uv run pytest
```
