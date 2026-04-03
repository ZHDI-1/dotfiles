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

if ! command -v fnm >/dev/null 2>&1; then
  curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
fi

if [[ "$mode" == "dev" || "$mode" == "full" ]] && command -v cargo >/dev/null 2>&1; then
  cargo_fallback_tools=(
    zellij
    stylua
    taplo-cli
    vivid
  )
  installed_cargo="$(cargo install --list 2>/dev/null || true)"

  for crate in "${cargo_fallback_tools[@]}"; do
    if ! grep -q "^${crate} v" <<<"$installed_cargo"; then
      if ! cargo install --locked "$crate"; then
        printf 'warn: failed to install cargo fallback tool: %s\n' "$crate" >&2
      fi
    fi
  done
fi

missing_manual=()

if [[ "$mode" == "dev" || "$mode" == "full" ]]; then
  for cmd in lua-language-server zls; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing_manual+=("$cmd")
    fi
  done
fi

if ((${#missing_manual[@]} > 0)); then
  printf 'warn: install manually or from an alternate repo: %s\n' "${missing_manual[*]}" >&2
fi
