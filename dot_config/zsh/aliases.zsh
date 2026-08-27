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

S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-http://bs3-hb1.corp.kuaishou.com}"
S3_COMMON_FLAGS="${S3_COMMON_FLAGS:---no-sign-request}"
DEFAULT_S3_BUCKET="${DEFAULT_S3_BUCKET:-infra-kfs}"
export AWS_EC2_METADATA_DISABLED=true

_s3_check_deps() {
  if ! command -v aws >/dev/null 2>&1; then
    print -u2 "Error: 'aws' CLI not found. Please install it."
    return 1
  fi
}

_s3_resolve_path() {
  local s3_path="$1"

  if [[ "$s3_path" == s3://* ]]; then
    print -r -- "$s3_path"
    return
  fi

  if [[ -z "$DEFAULT_S3_BUCKET" ]]; then
    print -u2 "Warning: No default bucket set. Using path as-is: $s3_path"
    print -r -- "$s3_path"
    return
  fi

  print -r -- "s3://${DEFAULT_S3_BUCKET}/${s3_path#/}"
}

_s3_run() {
  _s3_check_deps || return 1

  local -a s3_base_cmd=(aws s3)

  if [[ -n "$S3_ENDPOINT_URL" ]]; then
    s3_base_cmd+=(--endpoint-url "$S3_ENDPOINT_URL")
  fi

  if [[ -n "$S3_COMMON_FLAGS" ]]; then
    local -a common_flags_array
    common_flags_array=("${(@z)S3_COMMON_FLAGS}")
    s3_base_cmd+=("${common_flags_array[@]}")
  fi

  "${s3_base_cmd[@]}" "$@"
}

s3ls() {
  local s3_path_arg="${1:-}"
  local s3_path

  if [[ -z "$s3_path_arg" ]]; then
    if [[ -n "$DEFAULT_S3_BUCKET" ]]; then
      s3_path="s3://${DEFAULT_S3_BUCKET}/"
    else
      s3_path="s3://"
    fi
  else
    s3_path=$(_s3_resolve_path "$s3_path_arg")
  fi

  print -u2 "Listing: $s3_path..."
  _s3_run ls "$s3_path" || {
    print -u2 "Error: Failed to list '$s3_path'"
    return 1
  }
}

s3up() {
  if (( $# != 2 )); then
    print -u2 "Usage: s3up <local_file> <s3_key_or_path>"
    print -u2 "Example (default bucket): s3up ./file.txt my-key.txt"
    print -u2 "Example (full path):    s3up ./file.txt s3://other-bucket/my-key.txt"
    return 1
  fi

  local local_file="$1"
  local s3_path_arg="$2"
  local s3_path
  s3_path=$(_s3_resolve_path "$s3_path_arg")

  if [[ ! -f "$local_file" ]]; then
    print -u2 "Error: Local file not found: $local_file"
    return 1
  fi

  print -u2 "Uploading: $local_file -> $s3_path..."
  _s3_run cp "$local_file" "$s3_path" || {
    print -u2 "Error: Failed to upload '$local_file' to '$s3_path'"
    return 1
  }
}

s3down() {
  if (( $# == 0 || $# > 3 )); then
    print -u2 "Usage: s3down <s3_key_or_path> [local_path] [--recursive]"
    print -u2 "Example (file):      s3down my-key.txt ./"
    print -u2 "Example (directory): s3down my-directory/ ./my-directory --recursive"
    return 1
  fi

  local s3_path_arg="$1"
  local local_path="${2:-.}"
  local recursive_flag="${3:-}"
  local s3_path

  if [[ -n "$recursive_flag" && "$recursive_flag" != "--recursive" ]]; then
    print -u2 "Error: Unknown option: $recursive_flag"
    return 1
  fi

  s3_path=$(_s3_resolve_path "$s3_path_arg")

  print -u2 "Downloading: $s3_path -> $local_path..."
  _s3_run cp "$s3_path" "$local_path" ${recursive_flag:+"$recursive_flag"} || {
    print -u2 "Error: Failed to download '$s3_path' to '$local_path'"
    return 1
  }
}


relay() {
        TERM=xterm-256color ssh relay "$@"
}

git-bare() {
  emulate -L zsh
  setopt ERR_RETURN PIPE_FAIL

  if (( $# < 1 )); then
    cat >&2 <<'EOF'
usage:
  git-bare [<git-clone-options>...] [--] <repo> [<dir>]

examples:
  git-bare git@github.com:ceph/ceph.git
  git-bare git@github.com:ceph/ceph.git ceph-dev

  git-bare --filter=blob:none git@github.com:ceph/ceph.git
  git-bare --depth 100 --branch main -- git@github.com:ceph/ceph.git ceph
EOF
    return 2
  fi

  local cwd=${PWD:A}
  local last_arg=$argv[-1]

  #
  # Remember what existed before cloning. This lets us distinguish:
  #
  #   git-bare /some/existing/repo.git
  #
  # from an explicitly supplied destination directory.
  #
  local last_was_bare=false
  if [[ -d "$last_arg" ]] &&
     [[ "$(command git --git-dir="$last_arg" \
          rev-parse --is-bare-repository 2>/dev/null)" == true ]]
  then
    last_was_bare=true
  fi

  typeset -A before_dirs
  local d

  for d in "$cwd"/*(N/); do
    before_dirs[${d:A}]=1
  done

  #
  # Let git itself parse all clone options.
  #
  print -- "==> cloning bare repository"
  command git clone --bare "$@" || return

  local bare_dir=
  local explicit_dir=false

  #
  # If the final argument became a bare repository, and wasn't one before,
  # it was an explicit clone destination:
  #
  #   git-bare URL foo
  #                    ^
  #
  if [[ "$last_was_bare" == false ]] &&
     [[ -d "$last_arg" ]] &&
     [[ "$(command git --git-dir="$last_arg" \
          rev-parse --is-bare-repository 2>/dev/null)" == true ]]
  then
    bare_dir=${last_arg:A}
    explicit_dir=true
  fi

  #
  # Otherwise find the new bare repository Git created in $PWD.
  #
  if [[ -z "$bare_dir" ]]; then
    local -a candidates=()

    for d in "$cwd"/*(N/); do
      [[ -n "${before_dirs[${d:A}]-}" ]] && continue

      if [[ "$(command git --git-dir="$d" \
             rev-parse --is-bare-repository 2>/dev/null)" == true ]]
      then
        candidates+=("${d:A}")
      fi
    done

    if (( ${#candidates} == 1 )); then
      bare_dir=$candidates[1]
    else
      print -u2 \
        "git-bare: clone succeeded, but cannot identify the new bare repository"
      return 1
    fi
  fi

  local hub gitdir

  #
  # Explicit destination ".git":
  #
  #   mkdir foo
  #   cd foo
  #   git-bare URL .git
  #
  # already has exactly the desired layout.
  #
  if [[ "${bare_dir:t}" == ".git" ]]; then
    gitdir=$bare_dir
    hub=${bare_dir:h}

  elif [[ "$explicit_dir" == true ]]; then
    #
    # Explicit destination:
    #
    #   git clone --bare URL foo
    #
    # produces:
    #
    #   foo/{HEAD,objects,...}
    #
    # Convert to:
    #
    #   foo/.git/{HEAD,objects,...}
    #
    local tmp="${bare_dir}.git-bare-tmp.$$"

    [[ ! -e "$tmp" ]] || {
      print -u2 "git-bare: temporary path already exists: $tmp"
      return 1
    }

    command mv -- "$bare_dir" "$tmp" || return
    mkdir -p -- "$bare_dir" || {
      command mv -- "$tmp" "$bare_dir"
      return 1
    }

    command mv -- "$tmp" "$bare_dir/.git" || return

    hub=$bare_dir
    gitdir="$bare_dir/.git"

  else
    #
    # Automatic destination:
    #
    #   git clone --bare .../kwaifs.git
    #
    # Git chooses:
    #
    #   kwaifs.git/
    #
    # We want:
    #
    #   kwaifs/
    #     .git/
    #
    local parent=${bare_dir:h}
    local bare_name=${bare_dir:t}
    local hub_name=${bare_name%.git}

    # Normally clone --bare adds/preserves .git. Be defensive in case it
    # doesn't.
    if [[ "$hub_name" == "$bare_name" ]]; then
      hub_name=$bare_name
    fi

    hub="$parent/$hub_name"

    if [[ "$hub" == "$bare_dir" ]]; then
      #
      # Extremely unusual fallback: convert in place.
      #
      local tmp="${bare_dir}.git-bare-tmp.$$"

      command mv -- "$bare_dir" "$tmp" || return
      mkdir -p -- "$bare_dir" || {
        command mv -- "$tmp" "$bare_dir"
        return 1
      }

      command mv -- "$tmp" "$bare_dir/.git" || return

      gitdir="$bare_dir/.git"

    else
      [[ ! -e "$hub" ]] || {
        print -u2 \
          "git-bare: desired hub directory already exists: $hub"
        print -u2 \
          "git-bare: bare clone was left untouched at: $bare_dir"
        return 1
      }

      mkdir -p -- "$hub" || return
      command mv -- "$bare_dir" "$hub/.git" || return

      gitdir="$hub/.git"
    fi
  fi

  #
  # Detect clone remote. This also supports:
  #
  #   git-bare --origin upstream ...
  #
  local -a remotes
  remotes=("${(@f)$(command git --git-dir="$gitdir" remote)}")

  if (( ${#remotes} != 1 )); then
    print -u2 \
      "git-bare: expected exactly one remote, found ${#remotes}"
    return 1
  fi

  local remote=$remotes[1]

  #
  # A clone --bare initially creates:
  #
  #   refs/heads/foo
  #
  # directly from the remote.
  #
  # Restore normal development-clone fetch semantics:
  #
  #   remote refs/heads/foo
  #            |
  #            v
  #   refs/remotes/origin/foo
  #
  command git --git-dir="$gitdir" config --replace-all \
    "remote.${remote}.fetch" \
    "+refs/heads/*:refs/remotes/${remote}/*"

  command git --git-dir="$gitdir" config fetch.prune true
  command git --git-dir="$gitdir" config worktree.guessRemote true

  #
  # Preserve the branch referenced by bare HEAD.
  #
  local default_ref=
  local default_branch=

  default_ref=$(
    command git --git-dir="$gitdir" symbolic-ref -q HEAD 2>/dev/null
  ) || true

  if [[ "$default_ref" == refs/heads/* ]]; then
    default_branch=${default_ref#refs/heads/}
  fi

  print -- "==> fetching all remote branches"

  command git --git-dir="$gitdir" \
    fetch "$remote" --prune || return

  #
  # Create:
  #
  #   refs/remotes/origin/HEAD -> origin/main
  #
  # if the server advertises a default branch.
  #
  command git --git-dir="$gitdir" \
    remote set-head "$remote" --auto >/dev/null 2>&1 || true

  #
  # clone --bare created local branches for everything that existed at
  # clone time. Now that origin/* exists, those are redundant.
  #
  # Remove them only when:
  #
  #   refs/heads/foo == refs/remotes/origin/foo
  #
  # Keep HEAD's branch.
  #
  print -- "==> cleaning duplicate local branches"

  local ref branch local_oid remote_oid

  while IFS= read -r ref; do
    branch=${ref#refs/heads/}

    [[ -n "$default_branch" &&
       "$branch" == "$default_branch" ]] && continue

    local_oid=$(
      command git --git-dir="$gitdir" \
        rev-parse "$ref" 2>/dev/null
    ) || continue

    remote_oid=$(
      command git --git-dir="$gitdir" \
        rev-parse "refs/remotes/$remote/$branch" 2>/dev/null
    ) || {
      print -u2 "    keep   $branch (no $remote/$branch)"
      continue
    }

    if [[ "$local_oid" == "$remote_oid" ]]; then
      print -- "    remove $branch"

      command git --git-dir="$gitdir" \
        update-ref -d "$ref" "$local_oid" || return
    else
      print -u2 \
        "    keep   $branch (differs from $remote/$branch)"
    fi
  done < <(
    command git --git-dir="$gitdir" \
      for-each-ref --format='%(refname)' refs/heads/
  )

  #
  # Give the retained HEAD branch normal upstream configuration.
  #
  if [[ -n "$default_branch" ]] &&
     command git --git-dir="$gitdir" \
       show-ref --verify --quiet \
       "refs/remotes/$remote/$default_branch"
  then
    command git --git-dir="$gitdir" config \
      "branch.$default_branch.remote" "$remote"

    command git --git-dir="$gitdir" config \
      "branch.$default_branch.merge" \
      "refs/heads/$default_branch"
  fi

  print
  print -- "==> worktree hub ready"
  print -- "    root:    $hub"
  print -- "    git dir: $gitdir"
  print -- "    remote:  $remote"
  print -- "    HEAD:    ${default_branch:-unknown}"

  print
  print -- "Remote branches:"
  command git --git-dir="$gitdir" \
    for-each-ref \
    --format='  %(refname:short)' \
    "refs/remotes/$remote/"

  if [[ -n "$default_branch" ]]; then
    print
    print -- "Create the first worktree:"
    print -- "  cd ${(q)hub}"
    print -- \
      "  git --git-dir=.git worktree add ${(q)default_branch} ${(q)default_branch}"
  fi
}
