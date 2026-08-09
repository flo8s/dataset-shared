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

## 記述の規約

データセットについて分かったことを、カラム・テーブル・データセットのどの階層に
書くか、`keywords` に何を入れるかは
[docs.queria.io/publish/writing-descriptions](https://docs.queria.io/publish/writing-descriptions)
にある。ここには置かない。このリポジトリを submodule で参照するのは queria 自身の
データセットだけだが、規約はすべての発行者に等しく効くため。

クックブックの原稿だけは事情が違う。各リポジトリの `docs/*.md` に置いたものが
docs.queria.io のクックブックに取り込まれる。取り込みはカタログに登録済みの
リポジトリからしか行われないので、これは first-party 固有の話になる。

メタデータは `dataset.yml` と `*.table.yml` にだけ書く。dbt の `meta:` には書かない。
配布されるのは `queria compile` が出力する `dataset.json` で、その入力は宣言だけ。

**`ai_context` は廃止する。** 書いても読む先が無いので埋める必要はない。既に書いてある
リポジトリは、`instructions` を各階層の説明へ、`synonyms` を `keywords` へ畳んで
外す。畳み終わってから `queria` の `DATASET_KEYS` とスキーマからも落とす。

