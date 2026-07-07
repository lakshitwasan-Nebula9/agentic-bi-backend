#!/bin/bash
# Fired by settings.json only when the Bash command starts with "git commit".
# Check lint first; only auto-fix and block if there are actual violations.

# Prefer the project virtualenv's tools so the hook works even when it runs in a
# shell that hasn't activated the venv (e.g. spawned non-interactively).
if [ -x "venv/bin/ruff" ]; then
  PATH="$PWD/venv/bin:$PATH"
elif [ -x "venv/Scripts/ruff.exe" ]; then
  PATH="$PWD/venv/Scripts:$PATH"
fi

ruff_ok=0
black_ok=0
ruff check . >/dev/null 2>&1 && ruff_ok=1
black --check . -q >/dev/null 2>&1 && black_ok=1

if [ $ruff_ok -eq 1 ] && [ $black_ok -eq 1 ]; then
  echo "Lint clean."
  exit 0
fi

echo "=== Pre-commit lint: violations found — auto-fixing ==="
ruff check . --fix 2>&1 || true
black . -q 2>&1 || true

if ! ruff check . >/dev/null 2>&1 || ! black --check . -q >/dev/null 2>&1; then
  echo "Lint still failing after auto-fix. Fix manually before committing."
  exit 2
fi

echo "Auto-fixed. Re-stage the changed files and retry the commit:"
git diff --name-only 2>/dev/null
exit 2
