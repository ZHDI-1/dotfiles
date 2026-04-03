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

alias cat='bat'
alias rsync-firefox='rsync /Applications/Firefox.app/Contents/Resources/config.cfg /Users/zhdi/develop/firefox-hack/backup-configjs/config.cfg'

structlk() {
  ggrep -PriIzo "\\s*$1\\s*\\{\\n((?!};).*\\n)*\\};\\n" "$2"
}
