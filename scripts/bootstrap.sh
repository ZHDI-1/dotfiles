#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
with_gui="auto"

usage() {
  cat <<'EOF'
usage: ./scripts/bootstrap.sh [--with-gui|--without-gui]

This installs the full package/tool set for the current platform.
On macOS, GUI packages are installed by default and can be disabled.
EOF
}

while (($# > 0)); do
  case "$1" in
    --with-gui)
      with_gui="yes"
      shift
      ;;
    --without-gui)
      with_gui="no"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'error: unknown argument %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$(uname -s)" in
  Darwin)
    "$repo_root/scripts/bootstrap-macos.sh" "$with_gui"
    ;;
  Linux)
    if command -v dnf >/dev/null 2>&1 || [[ -f /etc/fedora-release ]]; then
      "$repo_root/scripts/bootstrap-fedora.sh"
    else
      printf 'error: unsupported Linux distribution for this bootstrap\n' >&2
      exit 1
    fi
    ;;
  *)
    printf 'error: unsupported OS %s\n' "$(uname -s)" >&2
    exit 1
    ;;
esac

"$repo_root/scripts/bootstrap-rust-tools.sh"
"$repo_root/scripts/bootstrap-node-tools.sh"
