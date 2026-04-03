#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$repo_root/packages/fedora.txt"

if ! command -v dnf >/dev/null 2>&1; then
  printf 'error: dnf is not installed\n' >&2
  exit 1
fi

mapfile -t dnf_packages < <(grep -vE '^\s*(#|$)' "$manifest")

if ((${#dnf_packages[@]} > 0)); then
  sudo dnf install -y "${dnf_packages[@]}"
fi

mkdir -p "$HOME/.local/bin"

if ! command -v fd >/dev/null 2>&1 && command -v fdfind >/dev/null 2>&1; then
  ln -sf "$(command -v fdfind)" "$HOME/.local/bin/fd"
fi

if ! command -v fnm >/dev/null 2>&1; then
  curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell
fi

if command -v cargo >/dev/null 2>&1; then
  cargo_fallback_tools=(
    zellij
    stylua
    taplo-cli
    vivid
  )
  installed_cargo="$(cargo install --list 2>/dev/null || true)"

  for crate in "${cargo_fallback_tools[@]}"; do
    if ! grep -q "^${crate} v" <<<"$installed_cargo"; then
      cargo install --locked "$crate"
    fi
  done
fi

missing_manual=()

for cmd in lua-language-server zls; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    missing_manual+=("$cmd")
  fi
done

if ((${#missing_manual[@]} > 0)); then
  printf 'warn: install manually or from an alternate repo: %s\n' "${missing_manual[*]}" >&2
fi
