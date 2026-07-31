# dataset-shared

Queria データセットリポジトリの共通スクリプト。

各データセットリポが submodule として参照し、ビルド・デプロイの共通処理を提供する。

## 使い方

各データセットリポで:

```bash
# submodule 追加（初回のみ）
git submodule add https://github.com/queria-io/dataset-shared.git shared

# ビルドして Queria に公開する
scripts/build.sh
```

公開先は選ばない。データセットは `dataset.yml`、アカウントは `QUERIA_TOKEN` が決める。
公開せずに 1 回転させたいときは queria-cli の `tools/rotate.py` をスタンドインに向けて回す
（fdl の `local` ターゲットに相当するものは無い。書き込みは Queria が発行する
一時認証情報を必ず経由する）。

## 提供マクロ

`macros/` に共通の dbt マクロを配置。各データセットの `dbt_project.yml` で参照する:

```yaml
macro-paths: ["macros", "shared/macros"]
```

- `macros/catalog.sql`: dbt-duckdb の `duckdb__get_catalog` オーバーライド。全アタッチ DB を対象にする修正
- `macros/generate_schema_name.sql`: サブディレクトリ名をスキーマ名として使用

## 提供スクリプト

- `scripts/build-dataset.sh`: `queria sync`（pull → ビルド → push）を回す
- `scripts/migrate_metadata.py`: メタデータを `dataset.yml` へ移す（リポジトリごとに 1 回）

## 規約

- [CONVENTIONS.md](CONVENTIONS.md): データセットについて分かったことを、カラム説明・テーブル説明・`ai_context`・クックブックのどこに書くか

## メタデータの移行

データセットのメタデータは `fdl.toml` の `[meta]` と dbt の `meta:` に分かれているが、
これを `dataset.yml` と `*.table.yml` に移す。移行後は Queria のカタログが
`queria compile` の出力する `dataset.json` を読む。

```bash
bash scripts/build.sh           # dbt が manifest.json を書く
python shared/scripts/migrate_metadata.py
```

**テキストを移すだけで、実データには触らない。** 列の型・列順・NULL 許容は
`queria compile` が実データから解決するので、移行時に列を列挙する必要がない。

判断できないものは止まる。`fdl.toml` の自由文ライセンスは ID へ機械的に変換するが、
`LICENSE_IDS` に無いものはエラーにして人に決めさせる（勝手に推測しない）。

移行が持ってこられないものは、そのあと手で書く。

| 項目 | 理由 |
|---|---|
| `contributors` | 誰を帰属先にするかは既存メタデータに無い。多くのライセンスが必須なので `queria validate` が止まる |
| `temporal_coverage` / `spatial_coverage` | 収録範囲は人が知っている |
| `ai_context` | エージェント向けの注意点。何をどこに書くかは [CONVENTIONS.md](CONVENTIONS.md) |

**`[meta]` と `meta.*` はすぐには消さない。** カタログが `dataset.json` を読むように
なる前に消すと、本番でそのデータセットのメタデータが空になる。

### 開発

```bash
uv sync
uv run pytest
```
