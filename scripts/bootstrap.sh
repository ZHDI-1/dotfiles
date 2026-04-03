#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="full"
with_gui="auto"

usage() {
  cat <<'EOF'
usage: ./scripts/bootstrap.sh [--mode core|dev|full] [--with-gui|--without-gui]

modes:
  core   install shell/editor/bootstrap essentials
  dev    install core plus development toolchains
  full   install dev plus macOS GUI packages by default
EOF
}

while (($# > 0)); do
  case "$1" in
    --mode)
      mode="${2:-}"
      shift 2
      ;;
    --mode=*)
      mode="${1#*=}"
      shift
      ;;
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

case "$mode" in
  core|dev|full) ;;
  *)
    printf 'error: invalid mode %s\n' "$mode" >&2
    usage >&2
    exit 1
    ;;
esac

case "$(uname -s)" in
  Darwin)
    exec "$repo_root/scripts/bootstrap-macos.sh" "$mode" "$with_gui"
    ;;
  Linux)
    if command -v dnf >/dev/null 2>&1 || [[ -f /etc/fedora-release ]]; then
      exec "$repo_root/scripts/bootstrap-fedora.sh" "$mode"
    fi
    printf 'error: unsupported Linux distribution for this bootstrap\n' >&2
    exit 1
    ;;
  *)
    printf 'error: unsupported OS %s\n' "$(uname -s)" >&2
    exit 1
    ;;
esac
