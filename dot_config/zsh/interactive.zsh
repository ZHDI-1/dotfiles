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

setopt autocd
setopt extendedglob
setopt hist_ignore_space
setopt hist_ignore_all_dups
# share_history already appends each command as it runs; the zsh manual says
# to leave inc_append_history off when share_history is set.
setopt share_history

eval "$(zoxide init zsh --cmd cd --hook pwd)"

# Rescan fpath and run compaudit at most once a day; otherwise trust the dump
# (-C). Adding or removing a file in an fpath dir (chezmoi apply, brew install,
# a plugin update) makes that dir newer than the dump, so rebuild it then.
autoload -Uz compinit
() {
  local dump="${ZDOTDIR:-$HOME}/.zcompdump" dir
  for dir in $fpath; do
    if [[ "$dir" -nt "$dump" ]]; then
      rm -f -- "$dump"
      return
    fi
  done
}
if [[ -n ${ZDOTDIR:-$HOME}/.zcompdump(#qN.mh-24) ]]; then
  compinit -C
else
  # compinit only rewrites the dump when fpath changed; touch it so the next
  # 24 hours take the fast path.
  compinit && touch "${ZDOTDIR:-$HOME}/.zcompdump"
fi
zstyle ':completion:*' completer _extensions _complete _approximate
zstyle ':completion:*' use-cache on
zstyle ':completion:*' cache-path "${HOME}/.cache/zsh/.zsh-completion-cache"
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'

# vivid output depends only on the theme and the vivid binary, so cache it and
# regenerate when vivid is newer than the cache. Write to a temp file and rename
# it, so a shell starting at the same moment never reads a half-written file.
() {
  local theme=gruvbox-light
  local cache="${XDG_CACHE_HOME:-${HOME}/.cache}/zsh/ls-colors-${theme}"
  if (( $+commands[vivid] )) && [[ ! -s "$cache" || "$commands[vivid]" -nt "$cache" ]]; then
    mkdir -p "${cache:h}" &&
      vivid generate "$theme" >| "${cache}.$$" &&
      mv -f "${cache}.$$" "$cache" ||
      rm -f "${cache}.$$"
  fi
  [[ -s "$cache" ]] && export LS_COLORS="$(<"$cache")"
}
# export COMP_COLORS="bd=1;38;2;215;153;33:ca=0;38;2;40;40;40;48;2;204;36;29:cd=3;38;2;250;189;47:di=0;38;2;69;133;136:do=1;38;2;211;134;155:ex=1;38;2;184;187;38:fi=0;38;2;235;219;178;48;2;40;40;40:ln=3;38;2;131;165;152:mh=1:mi=0;38;2;235;219;178;48;2;251;73;52:no=0;38;2;235;219;178:or=3;38;2;251;73;52:ow=1;38;2;184;187;38:pi=0;38;2;177;98;134:rs=0:sg=0;38;2;40;40;40;48;2;214;93;14:so=1;38;2;177;98;134:st=0;38;2;235;219;178;48;2;69;133;136:su=0;38;2;235;219;178;48;2;204;36;29:tw=3;38;2;235;219;178;48;2;69;133;136:"

zstyle ':completion:*' list-colors ''
zstyle ':completion:*' list-colors "${(s.:.)LS_COLORS}"
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
eval "$(direnv hook zsh)"

if (( $+commands[orbctl] )); then
  eval "$(orbctl completion zsh)"
  compdef _orb orbctl
  compdef _orb orb
fi
