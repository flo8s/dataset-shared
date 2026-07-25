"""queria_dataset の CLI。

  python -m queria_dataset validate [--manifest target/manifest.json]
  python -m queria_dataset compile -o dist/dataset.json

カタログの場所は `fdl run` が渡す FDL_CATALOG_PATH / FDL_DATA_URL から取る。
明示したいときは --ducklake / --data-path で上書きする。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import validate as validate_module
from .build import BuildInput, build, to_json
from .errors import Level, Report, SpecError
from .physical import resolve_from_env


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="データセットリポジトリのルート"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="dbt の manifest.json。無ければ lineage と変換 SQL が付かないだけ",
    )
    parser.add_argument("--ducklake", default=None, help="DuckLake カタログのパス")
    parser.add_argument("--data-path", default=None, help="Parquet データディレクトリ")
    parser.add_argument(
        "--parquet",
        type=Path,
        nargs="*",
        default=None,
        help="Parquet ファイル群（DuckLake を使わない Publisher 向け）",
    )
    parser.add_argument("--quiet", action="store_true", help="info を出さない")


def _make_input(args: argparse.Namespace) -> BuildInput:
    catalog, data = resolve_from_env()
    manifest = args.manifest
    if manifest is None:
        default = args.root / "target" / "manifest.json"
        manifest = default if default.is_file() else None
    return BuildInput(
        root=args.root,
        catalog_path=args.ducklake or catalog,
        data_path=args.data_path or data,
        manifest_path=manifest,
        parquet=list(args.parquet) if args.parquet else None,
    )


def _run(args: argparse.Namespace) -> tuple[dict, Report]:
    report = Report()
    artifact = build(_make_input(args), report)
    validate_module.run(artifact, report)
    return artifact, report


def _emit(report: Report, args: argparse.Namespace) -> None:
    rendered = report.render(show_info=not args.quiet)
    if rendered:
        print(rendered, file=sys.stderr)
    errors = len(report.of(Level.ERROR))
    warnings = len(report.of(Level.WARNING))
    print(f"error {errors} / warning {warnings}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="queria_dataset")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="宣言と実データを突き合わせる")
    _add_common(validate_parser)

    compile_parser = sub.add_parser("compile", help="dataset.json を書き出す")
    _add_common(compile_parser)
    compile_parser.add_argument(
        "-o", "--output", type=Path, default=Path("dist/dataset.json")
    )

    args = parser.parse_args(argv)

    try:
        artifact, report = _run(args)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _emit(report, args)
    if report.failed:
        return 1

    if args.command == "compile":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(to_json(artifact), encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
