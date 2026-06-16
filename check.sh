#!/usr/bin/env bash
set -e

echo "==> ruff"
ruff check .

echo "==> black"
black --check .

echo "==> pytest"
pytest

echo ""
echo "All checks passed — safe to push."
