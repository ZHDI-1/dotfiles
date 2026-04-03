ZINIT_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}/zinit/zinit.git"

if [[ ! -d "${ZINIT_HOME}" ]]; then
  mkdir -p "$(dirname "${ZINIT_HOME}")"
fi

if [[ ! -d "${ZINIT_HOME}/.git" ]]; then
  git clone https://github.com/zdharma-continuum/zinit.git "${ZINIT_HOME}"
fi

source "${ZINIT_HOME}/zinit.zsh"

zinit ice depth=1
zinit light romkatv/powerlevel10k
zinit light zsh-users/zsh-autosuggestions
zinit light zsh-users/zsh-syntax-highlighting
zinit light zsh-users/zsh-completions
zinit snippet https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/plugins/sudo/sudo.plugin.zsh

ZSH_AUTOSUGGEST_STRATEGY=(history completion)
