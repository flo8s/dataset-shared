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

## 提供モジュール

`shared/` は名前空間パッケージとして各データセットのルートから import できる。
`sys.path` をいじる必要も、依存に足す必要もない。

### `credentials.py`: 書き込み先の secret を生かし続ける

**DuckDB は認証情報の期限を見て取り直さない。** `REFRESH auto` を付けても、
チェーンが走るのは secret を作った瞬間だけ。1 時間走るビルドは途中で 403
（`SignatureDoesNotMatch`）を食って死ぬ。**secret を作り直したときだけ**
チェーンが走り直す。

```python
from shared.credentials import Secret

secret = Secret(conn)
if Secret.needed():
    secret.install()

for batch in batches:
    secret.refresh_if_due()   # 切れ目で呼ぶ。間隔は helper が決める
    write(batch)
```

`refresh_if_due()` は間隔（既定 10 分）が来るまで何もしないので、数秒ごとの
ループから呼んでよい。

**切れ目が要る。** 1 本の文が期限をまたいで走り続ける場合、その間に何も挟めない
ので救えない。そのときは文を割るか、アカウントの TTL を伸ばす
（`user_profiles.credential_ttl_seconds`）。

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
