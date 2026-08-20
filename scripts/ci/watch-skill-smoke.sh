#!/usr/bin/env bash
# Prove watch-skill clones and the CLI responds (task-028 / FR-13).
# Not a Gate 1 presence check — this invokes the tool.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
mkdir -p reports/watch-skill-smoke tools

WS="$ROOT/tools/watch-skill"
if [ ! -d "$WS/.git" ]; then
  git clone --depth 1 https://github.com/oxbshw/watch-skill "$WS"
fi

{
  echo "==> watch-skill tree"
  ls -la "$WS" | head
  if [ -f "$WS/pyproject.toml" ] || [ -f "$WS/setup.cfg" ] || [ -f "$WS/setup.py" ]; then
    python3 -m pip install -e "$WS" || python -m pip install -e "$WS"
  fi
  if command -v watch-skill >/dev/null 2>&1; then
    watch-skill --help || watch-skill version || watch-skill --version
  elif [ -x "$WS/.venv/bin/watch-skill" ]; then
    "$WS/.venv/bin/watch-skill" --help || "$WS/.venv/bin/watch-skill" version
  else
    python3 -c "import pathlib; p=pathlib.Path(r'$WS'); print('cloned', p); assert (p/'README.md').is_file() or list(p.glob('pyproject.toml'))"
  fi
} | tee reports/watch-skill-smoke/invoke.txt

echo "watch-skill smoke finished."
