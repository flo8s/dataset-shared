# ナレッジをどこに書くか

データセットについて分かったことを書く場所は、いま 6 つある。

- カラムの `description`
- テーブルの `description`
- テーブルの `ai_context`
- データセットの `description`
- データセットの `ai_context`（`instructions` / `synonyms` / `examples`）
- クックブックの原稿（`docs/*.md`）

どれに書くかを毎回考えると、実際には全部が 1 箇所に溜まる。e_stat は
`description` が 2 行、`ai_context.instructions` が 18 行で、6 スキーマ 30 テーブル
分の注意が一番粗い階層に一塊で置かれていた。意味ではなく長さで振り分けた結果になる。

## 原則: それが成り立つ一番小さい範囲に書く

書こうとしている文が真であるための最小の対象を選ぶ。判断はそれだけで付く。

| その文が真なのは | 書く場所 |
|---|---|
| 1 つのカラムについて | カラムの `description` |
| 1 つのテーブルについて | テーブルの `description` |
| そのテーブルを選ぶ / 選ばない判断について | テーブルの `ai_context.instructions` |
| 複数のテーブルにまたがって | データセットの `ai_context.instructions` |
| そのデータセットの呼び名について | `keywords` / `synonyms`（下記） |
| SQL として実行できる | クックブックの原稿 |

**小さい方に書いたら、上には繰り返さない。** 上位に書くのは「複数を見比べないと
言えないこと」だけになる。カラム説明に書いた話をデータセットの `instructions` にも
書くと、片方だけ直る日が来る。

## 何を書くか

事例（[Apache Ossie](https://github.com/apache/ossie)、Snowflake Cortex Analyst、
Hugging Face の dataset card）が共通して挙げるのは次の 5 つ。上 3 つは
`description`、下 2 つは書く場所が分かれる。

1. 粒度（1 行が何を表すか）
2. 定義・出典・算出方法
3. 似ているものとの違い
4. 集計や結合を壊す条件
5. 収録範囲の外にあるもの

4 と 5 は「読まないと間違える」種類の情報で、これが本体になることが多い。
一番小さい範囲に降ろす。

- 「この列は上位項目と内訳が混在する」→ その列の `description`
- 「この表は境界データと粒度が違う」→ その表の `ai_context`
- 「census と boundary は結合の粒度が違う」→ データセットの `instructions`

## keywords と synonyms

両方あるのは、`keywords` が Frictionless 由来、`synonyms` が Ossie 由来で、
別々の系譜が合流しているため。使い分けの基準はこれで足りる。

**他のデータセットにも付きうる語が `keywords`、このデータセットにしか付かない
呼び方が `synonyms`。**

```yaml
keywords: [統計, 人口, 社会]              # 他のデータセットにも付く
ai_context:
  synonyms: [e-Stat, 政府統計, SSDS, 社会・人口統計体系]   # これを指す別名だけ
```

両方に同じ語を入れない。e_stat は `e-Stat` が両方に入っていたが、これは
`synonyms` だけが正しい。

## examples とクックブック

`examples` は**このデータセットで答えられる問い**を 1 行ずつ。クックブックは
**その問いに答える SQL**。重なってよく、むしろ表記を揃えると導線になる。

```yaml
examples:
  - 小地域の年齢構成を地図に出したい     # クックブックの見出しと同じ言い回しにする
```

`examples` に SQL を書かない。長くなったらクックブックに移して、`examples` は
問いだけ残す。

## ai_context のサブフィールドを増やさない

`instructions` / `synonyms` / `examples` の 3 つは Ossie 0.1.1 の推奨フィールドに
合わせてある。制約や非推奨用途を別キーに切り出したくなるが、当面は
`instructions` の中に散文で書く。

Ossie 自身が 0.2.0.dev0 について「Schema is mutable; do not depend on this version
in production」と明記していて、`ai_context` というキー名も
[議論中](https://github.com/apache/ossie/discussions/32)。どのサブフィールドが
どの階層で使えるかも[未解決](https://github.com/apache/ossie/discussions/9)。
独自にキーを増やすと、上流が動いたときに二重に直すことになる。

## 迷ったときの確認

- その文は、書いた場所より小さい対象について言えないか
- 同じことを 2 箇所に書いていないか
- `keywords` と `synonyms` に同じ語が無いか
- `examples` に SQL が混ざっていないか
