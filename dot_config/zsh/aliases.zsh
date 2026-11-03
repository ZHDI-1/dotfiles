alias cr='cd $(git rev-parse --show-toplevel)'
alias xargs='xargs '
alias l=' lsd '
alias ls=' lsd '
alias la=' lsd -a '
alias ll=' lsd -lh --header '
alias lla=' lsd -lah --header '
alias lt=' lsd -h --tree '
alias lta=' lsd -lah --tree '
alias llt=' lsd -lh --tree'
alias llta=' lsd -alh --tree'

alias cd=' cd'
alias cdb=' cd ..'

alias nvimc='nvim -S ~/.config/nvim/Session.vim'
alias n='nvim'

# Keep the tmux server independent of exports from the launching shell.
# Pane shells load the current environment settings from their startup files.
tmux() {
  emulate -L zsh

  local -a tmux_env tmux_path
  local tmux_var
  # Keep only the system dirs this host has (no /opt/homebrew/bin on Linux).
  tmux_path=(/opt/homebrew/bin /usr/local/bin /usr/bin /bin /usr/sbin /sbin)
  tmux_path=(${^tmux_path}(N-/))
  tmux_env=(
    "PATH=${(j.:.)tmux_path}"
    'SHELL=/bin/zsh'
  )

  # Preserve connection context so commands inside panes target their server.
  # Terminal capabilities and SSH forwarding must also survive the cleanup.
  for tmux_var in \
    HOME USER LOGNAME TMPDIR TMUX_TMPDIR ZDOTDIR XDG_CONFIG_HOME \
    TERM TERMINFO TERMINFO_DIRS COLORTERM TERM_PROGRAM TERM_PROGRAM_VERSION \
    LANG LC_ALL LC_COLLATE LC_CTYPE LC_MESSAGES LC_MONETARY LC_NUMERIC LC_TIME \
    SSH_AUTH_SOCK SSH_AGENT_PID SSH_CONNECTION SSH_TTY DISPLAY XAUTHORITY \
    TMUX TMUX_PANE; do
    if (( ${+parameters[$tmux_var]} )); then
      tmux_env+=("${tmux_var}=${(P)tmux_var}")
    fi
  done

  /usr/bin/env -i "${tmux_env[@]}" tmux "$@"
}


c() {
  local codex_dir
  codex_dir="$(mktemp -d "${TMPDIR:-/tmp}/codex.XXXXXXXXXX")" || return

  (
    cd "$codex_dir" || exit
    codex e --skip-git-repo-check "$@"
  )
}

_codexside() {
  local codex_dir
  codex_dir="$(mktemp -d "${TMPDIR:-/tmp}/codexside.XXXXXXXXXX")" || return

  (
    cd "$codex_dir" || exit
    command codex "$@"
  )
}

_piside() {
  local pi_dir
  pi_dir="$(mktemp -d "${TMPDIR:-/tmp}/piside.XXXXXXXXXX")" || return

  (
    cd "$pi_dir" || exit
    command pi "$@"
  )
}

_claudeside() {
  local claude_dir
  claude_dir="$(mktemp -d "${TMPDIR:-/tmp}/claudeside.XXXXXXXXXX")" || return

  (
    cd "$claude_dir" || exit
    command claude "$@"
  )
}

alias codexs='_codexside'
alias claudes='_claudeside'
alias pis='_piside'

# Keep cat on the system binary while syspolicyd/Homebrew exec checks are unstable.
# alias cat='bat'

structlk() {
  ggrep -PriIzo "\\s*$1\\s*\\{\\n((?!};).*\\n)*\\};\\n" "$2"
}

# Download best available YouTube/Bilibili audio as Apple Music-importable M4A.
yt-audio() {
  if (( $# == 0 )); then
    print -u2 "usage: yt-audio <youtube-or-bilibili-url> [yt-dlp options]"
    return 2
  fi

  yt-dlp \
    --cookies-from-browser firefox \
    --extract-audio \
    --audio-format m4a \
    --audio-quality 0 \
    --embed-metadata \
    --embed-thumbnail \
    --convert-thumbnails jpg \
    --no-playlist \
    -f "bestaudio/best" \
    -o "%(title).200B [%(id)s].%(ext)s" \
    "$@"
}

relay() {
        TERM=xterm-256color ssh relay "$@"
}
