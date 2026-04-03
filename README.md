# dotfiles

Managed with [chezmoi](https://www.chezmoi.io/).

## Bootstrap

```sh
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply ZHDI-1
```

## Packages

```sh
./scripts/bootstrap.sh
```

```sh
./scripts/bootstrap.sh --mode core
./scripts/bootstrap.sh --mode dev
./scripts/bootstrap.sh --mode full --without-gui
```

## Notes

- `~/.config/nvim` is managed as an external git repo via `.chezmoiexternal.toml`.
- macOS-only files are gated by `.chezmoiignore.tmpl`.
- `create_*.tmpl` files are placeholders for machine-local secrets and are only created if missing.
- Package bootstrap is mode-based: `core` for essentials, `dev` for toolchains, `full` for the workstation setup.
