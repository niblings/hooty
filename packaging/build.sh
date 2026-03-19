#!/usr/bin/env bash
# Build Hooty standalone binary for Linux (onedir mode).
#
# Usage:
#   bash packaging/build.sh
#
# Output:
#   dist/hooty/hooty     (executable + bundled dependencies)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Use a dedicated venv to avoid conflicts with other platform's .venv
export UV_PROJECT_ENVIRONMENT=".buildenv"
export VIRTUAL_ENV="$PROJECT_ROOT/.buildenv"

echo "==> Installing dependencies into .buildenv ..."
uv sync --all-extras
uv pip install pyinstaller

echo "==> Building with PyInstaller (onedir)..."
uv run pyinstaller packaging/hooty.spec --noconfirm

echo "==> Smoke test..."
if ./dist/hooty/hooty --version; then
    echo "==> Build successful!"
else
    echo "==> ERROR: Smoke test failed" >&2
    exit 1
fi

echo ""
echo "Output: dist/hooty/"
du -sh dist/hooty/

echo ""
echo "To package for distribution:"
echo "  tar czf hooty-linux-x86_64.tar.gz -C dist hooty/"
