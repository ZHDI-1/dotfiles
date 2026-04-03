#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v fnm >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  if prefix="$(brew --prefix fnm 2>/dev/null)"; then
    export PATH="$prefix/bin:$PATH"
  fi
fi

if ! command -v fnm >/dev/null 2>&1; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "error: curl is required to install fnm" >&2
    exit 1
  fi

  curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
fi

if [[ -x "$HOME/.local/share/fnm/fnm" ]]; then
  ln -sf "$HOME/.local/share/fnm/fnm" "$HOME/.local/bin/fnm"
fi

if ! command -v fnm >/dev/null 2>&1; then
  echo "error: fnm is not installed" >&2
  exit 1
fi

eval "$(fnm env --shell bash)"
fnm install --lts
fnm default lts-latest
fnm use lts-latest
