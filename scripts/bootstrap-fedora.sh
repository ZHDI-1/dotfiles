#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
packages_dir="$repo_root/packages/fedora"
manifest="$packages_dir/packages.txt"

if ! command -v dnf >/dev/null 2>&1; then
  printf 'error: dnf is not installed\n' >&2
  exit 1
fi

dnf_packages=()

while IFS= read -r pkg; do
  dnf_packages+=("$pkg")
done < <(grep -vE '^\s*(#|$)' "$manifest")

if ((${#dnf_packages[@]} > 0)); then
  sudo dnf install -y --setopt=install_weak_deps=False --skip-unavailable "${dnf_packages[@]}"
fi

mkdir -p "$HOME/.local/bin"

if ! command -v fd >/dev/null 2>&1 && command -v fdfind >/dev/null 2>&1; then
  ln -sf "$(command -v fdfind)" "$HOME/.local/bin/fd"
fi
