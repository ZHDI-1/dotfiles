#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
packages_dir="$repo_root/packages/macos"
mode="${1:-full}"
with_gui="${2:-auto}"

case "$mode" in
  core|dev|full) ;;
  *)
    printf 'error: invalid mode %s\n' "$mode" >&2
    exit 1
    ;;
esac

case "$with_gui" in
  auto|yes|no) ;;
  *)
    printf 'error: invalid gui mode %s\n' "$with_gui" >&2
    exit 1
    ;;
esac

if ! command -v brew >/dev/null 2>&1; then
  printf 'error: Homebrew is not installed\n' >&2
  printf 'install: https://brew.sh/\n' >&2
  exit 1
fi

brewfiles=(
  "$packages_dir/taps.Brewfile"
  "$packages_dir/core.Brewfile"
)

if [[ "$mode" == "dev" || "$mode" == "full" ]]; then
  brewfiles+=("$packages_dir/dev.Brewfile")
fi

if [[ "$with_gui" == "yes" || ( "$with_gui" == "auto" && "$mode" == "full" ) ]]; then
  brewfiles+=("$packages_dir/gui.Brewfile")
fi

for brewfile in "${brewfiles[@]}"; do
  brew bundle --file "$brewfile" --no-upgrade
done
