#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$(uname -s)" in
  Darwin)
    exec "$repo_root/scripts/bootstrap-macos.sh"
    ;;
  Linux)
    if command -v dnf >/dev/null 2>&1 || [[ -f /etc/fedora-release ]]; then
      exec "$repo_root/scripts/bootstrap-fedora.sh"
    fi
    printf 'error: unsupported Linux distribution for this bootstrap\n' >&2
    exit 1
    ;;
  *)
    printf 'error: unsupported OS %s\n' "$(uname -s)" >&2
    exit 1
    ;;
esac
