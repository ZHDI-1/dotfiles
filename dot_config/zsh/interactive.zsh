[[ -o interactive ]] && [[ -t 0 ]] && [[ -t 1 ]] || return 0

typeset -U fpath FPATH
fpath=(
  "${HOME}/.config/zsh/completions"
  "/opt/homebrew/share/zsh/site-functions"
  $fpath
)

eval "$(fzf --zsh)"
export FZF_DEFAULT_OPTS='-m --no-height --layout=reverse --border=bottom --color=selected-fg:#F3F3A6,hl:#83AC7C,selected-hl:#91921C,current-hl:#A1AE61'
export FZF_DEFAULT_COMMAND='fd --type f --type l --type b --type c --type s --color=never --hidden'
export FZF_CTRL_T_COMMAND="${FZF_DEFAULT_COMMAND}"
export FZF_CTRL_T_OPTS="--preview 'bat --color=always --line-range :50 {}' --preview-window=border-bottom"

export HISTFILE="${HOME}/.zsh_history"
export HISTSIZE=100000000
export SAVEHIST="${HISTSIZE}"
export HISTCONTROL="erasedups"

setopt autocd
setopt extendedglob
setopt hist_ignore_space
setopt hist_ignore_all_dups
setopt share_history
setopt inc_append_history

eval "$(zoxide init zsh --cmd cd --hook pwd)"

autoload -U compinit && compinit
zstyle ':completion:*' completer _extensions _complete _approximate
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path "${HOME}/.cache/zsh/.zsh-completion-cache"
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'

export LS_COLORS="$(vivid generate gruvbox-light-hard)"
export COMP_COLORS="bd=1;38;2;215;153;33:ca=0;38;2;40;40;40;48;2;204;36;29:cd=3;38;2;250;189;47:di=0;38;2;69;133;136:do=1;38;2;211;134;155:ex=1;38;2;184;187;38:fi=0;38;2;235;219;178;48;2;40;40;40:ln=3;38;2;131;165;152:mh=1:mi=0;38;2;235;219;178;48;2;251;73;52:no=0;38;2;235;219;178:or=3;38;2;251;73;52:ow=1;38;2;184;187;38:pi=0;38;2;177;98;134:rs=0:sg=0;38;2;40;40;40;48;2;214;93;14:so=1;38;2;177;98;134:st=0;38;2;235;219;178;48;2;69;133;136:su=0;38;2;235;219;178;48;2;204;36;29:tw=3;38;2;235;219;178;48;2;69;133;136:"

zstyle ':completion:*' list-colors ''
zstyle ':completion:*' list-colors "${(s.:.)COMP_COLORS}"
zstyle ':completion:*' menu select interactive

zmodload zsh/complist
bindkey -M menuselect 'h' vi-backward-char
bindkey -M menuselect 'j' vi-down-line-or-history
bindkey -M menuselect 'k' vi-up-line-or-history
bindkey -M menuselect 'l' vi-forward-char

bindkey -e
autoload -U edit-command-line
autoload -U select-word-style
zle -N edit-command-line
select-word-style bash
bindkey '^X^E' edit-command-line
bindkey '^u' backward-kill-line

unsetopt beep

eval "$(fnm env --shell zsh --use-on-cd)"

if (( $+commands[orbctl] )); then
  eval "$(orbctl completion zsh)"
  compdef _orb orbctl
  compdef _orb orb
fi
