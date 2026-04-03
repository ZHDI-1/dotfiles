#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
packages_dir="$repo_root/packages/fedora"
mode="${1:-full}"

case "$mode" in
  core|dev|full) ;;
  *)
    printf 'error: invalid mode %s\n' "$mode" >&2
    exit 1
    ;;
esac

if ! command -v dnf >/dev/null 2>&1; then
  printf 'error: dnf is not installed\n' >&2
  exit 1
fi

manifests=("$packages_dir/core.txt")

if [[ "$mode" == "dev" || "$mode" == "full" ]]; then
  manifests+=("$packages_dir/dev.txt")
fi

dnf_packages=()

for manifest in "${manifests[@]}"; do
  while IFS= read -r pkg; do
    dnf_packages+=("$pkg")
  done < <(grep -vE '^\s*(#|$)' "$manifest")
done

if ((${#dnf_packages[@]} > 0)); then
  sudo dnf install -y --skip-unavailable "${dnf_packages[@]}"
fi

mkdir -p "$HOME/.local/bin"

if ! command -v fd >/dev/null 2>&1 && command -v fdfind >/dev/null 2>&1; then
  ln -sf "$(command -v fdfind)" "$HOME/.local/bin/fd"
fi
