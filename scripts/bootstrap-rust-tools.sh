#!/usr/bin/env bash
set -euo pipefail

if [[ -d "$HOME/.cargo/bin" ]]; then
  export PATH="$HOME/.cargo/bin:$PATH"
fi

if ! command -v rustup >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  if prefix="$(brew --prefix rustup 2>/dev/null)"; then
    export PATH="$prefix/bin:$PATH"
  fi
fi

if ! command -v rustup >/dev/null 2>&1; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "error: curl is required to install rustup" >&2
    exit 1
  fi

  curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal --default-toolchain stable
  export PATH="$HOME/.cargo/bin:$PATH"
fi

if ! command -v rustup >/dev/null 2>&1; then
  echo "error: rustup is not installed" >&2
  exit 1
fi

if ! rustup show active-toolchain >/dev/null 2>&1; then
  rustup default stable
fi

rustup component add rust-analyzer rust-src rustfmt

if command -v cargo >/dev/null 2>&1; then
  if ! command -v vivid >/dev/null 2>&1; then
    cargo install --locked vivid
  fi
fi
