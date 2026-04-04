#!/usr/bin/env bash
# Common build script for all dataset repositories.
# Called from each dataset's scripts/build.sh.
#
# Usage:
#   scripts/build.sh [target]
#   # target: "local" (default) or "default" (S3)
set -euo pipefail
target="${1:-local}"
script_dir="$(cd "$(dirname "$0")" && pwd)"

uv run fdl pull "$target" || true
uv run fdl run "$target" -- python main.py
uv run fdl push "$target"
uv run python "$script_dir/upload_artifacts.py" "$target"

# Rebuild catalog (local only)
if [ "$target" = "local" ]; then
    catalog_dir="$(pwd)/../dataset-catalog"
    if [ -d "$catalog_dir" ]; then
        echo "Rebuilding catalog..."
        (cd "$catalog_dir" && uv run fdl pull local || true && uv run fdl run local -- python main.py && uv run fdl push local)
    fi
fi
