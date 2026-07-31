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
- `macros/drop_build_leftovers.sql`: dbt が run の終わりに残す `__dbt_backup` / `__dbt_tmp` を落とす。incremental モデルを `--full-refresh` で作り直すと、置き換え前のテーブルがコピーとして残ったまま run が終わり、そのまま公開されてしまう。該当するデータセットの `dbt_project.yml` で `on-run-end: "{{ drop_build_leftovers() }}"` を設定する

## 提供スクリプト

- `scripts/build-dataset.sh`: `queria sync`（pull → ビルド → push）を回す
- `scripts/migrate_metadata.py`: メタデータを `dataset.yml` へ移す（リポジトリごとに 1 回）

## 記述の規約

データセットについて分かったことを、カラム・テーブル・データセットのどの階層に
書くか、`keywords` に何を入れるかは
[docs.queria.io/publish/writing-descriptions](https://docs.queria.io/publish/writing-descriptions)
にある。ここには置かない。このリポジトリを submodule で参照するのは queria 自身の
データセットだけだが、規約はすべての発行者に等しく効くため。

クックブックの原稿だけは事情が違う。各リポジトリの `docs/*.md` に置いたものが
docs.queria.io のクックブックに取り込まれる。取り込みはカタログに登録済みの
リポジトリからしか行われないので、これは first-party 固有の話になる。

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

**`[meta]` と `meta.*` はすぐには消さない。** カタログが `dataset.json` を読むように
なる前に消すと、本番でそのデータセットのメタデータが空になる。

**`ai_context` は廃止する。** 移行スクリプトは `fdl.toml` から持ってこられないものと
して挙げているが、書いても読む先が無いので手で埋める必要はない。既に書いてある
リポジトリは、`instructions` を各階層の説明へ、`synonyms` を `keywords` へ畳んで
外す。畳み終わってから `queria` の `DATASET_KEYS` とスキーマからも落とす。

### 開発

```bash
uv sync
uv run pytest
```
