#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
packages_dir="$repo_root/packages/macos"
with_gui="${1:-auto}"

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
  "$packages_dir/packages.Brewfile"
)

if [[ "$with_gui" == "yes" || "$with_gui" == "auto" ]]; then
  brewfiles+=("$packages_dir/gui.Brewfile")
fi

for brewfile in "${brewfiles[@]}"; do
  brew bundle --file "$brewfile" --no-upgrade
done
