# dotfiles

Managed with [chezmoi](https://www.chezmoi.io/).

## Bootstrap

```sh
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply ZHDI-1
```

Then run the package/bootstrap helpers from the chezmoi source directory:

```sh
"$(chezmoi source-path)/scripts/bootstrap.sh"
```

```sh
"$(chezmoi source-path)/scripts/bootstrap.sh" --without-gui
"$(chezmoi source-path)/scripts/bootstrap.sh" --with-gui
```

## Notes

- `~/.config/nvim` is managed as an external git repo via `.chezmoiexternal.toml`.
- `README.md`, `scripts/`, and `packages/` stay in the chezmoi source repo and are not applied into `$HOME`.
- macOS-only files are gated by `.chezmoiignore.tmpl`.
- `create_*.tmpl` files are placeholders for machine-local secrets and are only created if missing.
- Package bootstrap always installs the full CLI/dev tool set; only macOS GUI packages remain optional.
- Rust is bootstrapped through `rustup`, not distro Rust packages; this repo only installs the shared toolchain/components and shell-facing tools.
- Node is bootstrapped through `fnm`; this repo only ensures the active Node LTS runtime, and repo-specific npm globals should be installed by the repo that needs them.
