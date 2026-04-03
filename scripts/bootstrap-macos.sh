#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
brewfile="$repo_root/Brewfile"

if ! command -v brew >/dev/null 2>&1; then
  printf 'error: Homebrew is not installed\n' >&2
  printf 'install: https://brew.sh/\n' >&2
  exit 1
fi

brew bundle --file "$brewfile" --no-upgrade
