# dotfiles

Managed with [chezmoi](https://www.chezmoi.io/).

## Bootstrap

```sh
sh -c "$(curl -fsLS get.chezmoi.io)" -- init --apply ZHDI-1
```

## Notes

- `~/.config/nvim` is managed as an external git repo via `.chezmoiexternal.toml`.
- macOS-only files are gated by `.chezmoiignore.tmpl`.
- `create_*.tmpl` files are placeholders for machine-local secrets and are only created if missing.
