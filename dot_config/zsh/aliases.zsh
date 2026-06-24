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

alias codexside='_codexside'
alias codexs='_codexside'

# Keep cat on the system binary while syspolicyd/Homebrew exec checks are unstable.
# alias cat='bat'
alias rsync-firefox='rsync /Applications/Firefox.app/Contents/Resources/config.cfg /Users/zhdi/develop/firefox-hack/backup-configjs/config.cfg'

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
