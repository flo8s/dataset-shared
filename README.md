# dataset-shared

Queria データセットリポジトリの共通スクリプト。

各データセットリポが submodule として参照し、ビルド・デプロイの共通処理を提供する。

## 使い方

各データセットリポで:

```bash
# submodule 追加（初回のみ）
git submodule add https://github.com/flo8s/dataset-shared.git shared

# ビルド
scripts/build.sh local
```

## 提供スクリプト

- `scripts/build-dataset.sh`: データセットのビルド + artifacts push + catalog 自動リビルド
- `scripts/upload_artifacts.py`: dbt artifacts の S3/ローカル push
