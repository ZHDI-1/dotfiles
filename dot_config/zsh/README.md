# Zsh Layout

- `env.zsh`: login/session environment and PATH
- `plugins.zsh`: prompt and zinit-managed plugins
- `interactive.zsh`: history, completion, keybindings, shell UX
- `aliases.zsh`: aliases and small functions that must run in the shell
- `completions/`: autoloaded `_command` completion functions (on `fpath`)

Standalone commands live in `~/.local/bin` (`dot_local/bin/` here), not as
shell functions: they work from any shell, script, or tool, and cost nothing at
startup. For example `s3cp`/`s3ls` and `git-bare`.

Host-only files are optional, explicitly ignored by chezmoi, and never created
or populated by the shared configuration:

- `env.local.zsh`: host-specific PATH, proxies, and other environment overrides;
  loaded by `.zprofile` after shared environment and macOS integrations.
- `secrets.local.zsh`: credentials; loaded by `.zprofile` after `env.local.zsh`.
- `interactive.local.zsh`: host-specific functions, aliases, and keybindings;
  loaded last by `.zshrc`, only for interactive shells with a terminal.

Create these files directly under `~/.config/zsh/`, outside the chezmoi source
repository, and use mode `600` for files containing private settings. Do not
`chezmoi add` them or copy their contents into shared modules. A `private_`
source filename controls permissions, not publication. Existing local files
survive an apply unchanged.

Environment files run in login shells; child shells normally inherit exported
variables. Interactive functions are loaded separately for each interactive
terminal shell. Node initialization uses fnm in the shared modules, not NVM or
a version-pinned PATH.
