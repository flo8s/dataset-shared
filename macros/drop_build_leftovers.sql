{# dbt がモデルを作り直すとき、既存テーブルを __dbt_backup に改名して置き換え、
   そのコピーを落とすのは「次に同じモデルを回したときの冒頭」。run が終わった
   時点ではカタログに残っている。

   table マテリアライズなら同じ run の中で落ちるが、incremental を --full-refresh
   で作り直した場合は残ったまま run が終わる。DuckLake のカタログはビルドが
   終わった時点の姿がそのまま公開されるので、テーブル 1 本分まるごとのコピーが
   次のビルドまで公開され続ける（houjin_bangou で 348MB / 584万行）。

   dbt 自身が 1 回あとに落とすものを、この run の後始末として済ませる。
   incremental モデルを持つデータセットの dbt_project.yml で:

     on-run-end: "{{ drop_build_leftovers() }}"

   落とすのは dbt が所有する 2 つの名前で終わるものだけ。SQL は返さず、
   ここで実行して空文字を返す（dbt は空のフックを成功として飛ばす）。 #}

{% macro drop_build_leftovers() %}
  {% if not execute %}
    {% do return('') %}
  {% endif %}

  {% set query %}
    select table_schema, table_name, table_type
    from information_schema.tables
    where table_catalog = '{{ target.database }}'
      and (
        ends_with(table_name, '__dbt_backup')
        or ends_with(table_name, '__dbt_tmp')
      )
    order by table_schema, table_name
  {% endset %}

  {% for row in run_query(query) %}
    {% set kind = 'view' if 'VIEW' in row[2] | upper else 'table' %}
    {% set target_relation = '"' ~ target.database ~ '"."' ~ row[0] ~ '"."' ~ row[1] ~ '"' %}
    {% do log('drop ' ~ kind ~ ' ' ~ row[0] ~ '.' ~ row[1] ~ ' (dbt の作業用リレーション)', info=true) %}
    {% do run_query('drop ' ~ kind ~ ' if exists ' ~ target_relation) %}
  {% endfor %}

  {% do return('') %}
{% endmacro %}
