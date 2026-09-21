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
        echo "Error: 'aws' CLI not found. Please install it." >&2
        return 1
    fi
}

_s3_resolve_path() {
    local s3_path="$1"

    if [[ "$s3_path" == s3://* ]]; then
        echo "$s3_path"
        return
    fi

    if [[ -z "$DEFAULT_S3_BUCKET" ]]; then
        echo "Warning: No default bucket set. Using path as-is: $s3_path" >&2
        echo "$s3_path"
        return
    fi

    echo "s3://${DEFAULT_S3_BUCKET}/${s3_path#/}"
}

_s3_aws() {
    _s3_check_deps || return 1

    local -a s3_base_cmd=("aws")

    if [[ -n "$S3_ENDPOINT_URL" ]]; then
        s3_base_cmd+=("--endpoint-url" "$S3_ENDPOINT_URL")
    fi

    if [[ -n "$S3_COMMON_FLAGS" ]]; then
        local -a common_flags_array
        if [[ -n "${ZSH_VERSION:-}" ]]; then
            common_flags_array=("${(z)S3_COMMON_FLAGS}")
        else
            read -r -a common_flags_array <<< "$S3_COMMON_FLAGS"
        fi
        s3_base_cmd+=("${common_flags_array[@]}")
    fi

    "${s3_base_cmd[@]}" "$@"
}

_s3_run() {
    _s3_aws s3 "$@"
}

_s3ls_usage() {
    cat >&2 <<'EOF_USAGE'
Usage: s3ls [-h|--human-readable] [s3_key_or_path]

List the default bucket, a shorthand key in that bucket, or an s3:// URI.
  -h, --human-readable  Display sizes in human-readable units.
      --help            Show this help text.
EOF_USAGE
}

s3ls() {
    local human_readable=0
    local s3_path_arg=
    local s3_path
    local -a ls_args

    while (($# > 0)); do
        case "$1" in
            -h|--human-readable)
                human_readable=1
                ;;
            --help)
                _s3ls_usage
                return 0
                ;;
            --)
                shift
                if [[ -n "$s3_path_arg" ]] || (($# > 1)); then
                    _s3ls_usage
                    return 1
                fi
                s3_path_arg="${1:-}"
                break
                ;;
            -*)
                echo "Error: Unknown s3ls option: $1" >&2
                _s3ls_usage
                return 1
                ;;
            *)
                if [[ -n "$s3_path_arg" ]]; then
                    _s3ls_usage
                    return 1
                fi
                s3_path_arg="$1"
                ;;
        esac
        shift
    done

    if [[ -z "$s3_path_arg" ]]; then
        if [[ -n "$DEFAULT_S3_BUCKET" ]]; then
            s3_path="s3://${DEFAULT_S3_BUCKET}/"
        else
            s3_path="s3://"
        fi
    else
        s3_path=$(_s3_resolve_path "$s3_path_arg")
    fi

    echo "Listing: $s3_path..." >&2
    ls_args=(ls "$s3_path")
    if [[ "$human_readable" == 1 ]]; then
        ls_args+=(--human-readable)
    fi
    _s3_run "${ls_args[@]}" || {
        echo "Error: Failed to list '$s3_path'" >&2
        return 1
    }
}

_s3cp_usage() {
    cat >&2 <<'EOF_USAGE'
Usage: s3cp <source> <destination>

Copy a file between the local filesystem and S3, or between two s3:// URIs.
Shorthand S3 keys use DEFAULT_S3_BUCKET. When neither path is an s3:// URI,
a local-looking destination such as ./ selects a download; otherwise an
existing source is uploaded and a missing source is downloaded. Use an explicit
s3:// URI to resolve an ambiguous local/remote filename.

Examples:
  s3cp ./file.txt my-key.txt
  s3cp my-key.txt ./
  s3cp ./file.txt s3://other-bucket/my-key.txt
  s3cp s3://other-bucket/my-key.txt ./
EOF_USAGE
}

_s3_is_local_destination_hint() {
    case "$1" in
        .|..|/*|./*|../*) return 0 ;;
        *) return 1 ;;
    esac
}

s3cp() {
    if [[ "${1:-}" == --help ]]; then
        _s3cp_usage
        return 0
    fi
    if [[ "${1:-}" == -- ]]; then
        shift
    fi
    if [[ $# -ne 2 ]]; then
        _s3cp_usage
        return 1
    fi

    local source="$1"
    local destination="$2"
    local resolved_source="$source"
    local resolved_destination="$destination"
    local operation=copy

    if [[ "$source" == s3://* && "$destination" == s3://* ]]; then
        operation=copy
    elif [[ "$source" == s3://* ]]; then
        operation=download
    elif [[ "$destination" == s3://* ]]; then
        operation=upload
    elif _s3_is_local_destination_hint "$destination"; then
        operation=download
        resolved_source=$(_s3_resolve_path "$source")
    elif [[ -e "$source" || -L "$source" ]]; then
        operation=upload
        resolved_destination=$(_s3_resolve_path "$destination")
    else
        operation=download
        resolved_source=$(_s3_resolve_path "$source")
    fi

    if [[ "$operation" == upload && ! -f "$source" ]]; then
        echo "Error: Local file not found or not a regular file: $source" >&2
        return 1
    fi

    case "$operation" in
        upload) echo "Uploading: $resolved_source -> $resolved_destination..." >&2 ;;
        download) echo "Downloading: $resolved_source -> $resolved_destination..." >&2 ;;
        *) echo "Copying: $resolved_source -> $resolved_destination..." >&2 ;;
    esac
    _s3_run cp "$resolved_source" "$resolved_destination" || {
        echo "Error: Failed to copy '$resolved_source' to '$resolved_destination'" >&2
        return 1
    }
}

# Print remote completion candidates, one per line. Object listing is bounded
# and uses short timeouts so an unavailable endpoint does not block the shell.
_s3_remote_candidates() {
    local typed="$1"
    local bucket key bucket_fragment candidate
    local explicit_uri=0
    local display_leading_slash=

    if [[ "$typed" == s3://* ]]; then
        explicit_uri=1
        candidate=${typed#s3://}
        if [[ "$candidate" != */* ]]; then
            bucket_fragment="$candidate"
            if [[ -n "$DEFAULT_S3_BUCKET" && "$DEFAULT_S3_BUCKET" == "$bucket_fragment"* ]]; then
                printf 's3://%s/\n' "$DEFAULT_S3_BUCKET"
            fi
            while IFS= read -r bucket; do
                [[ -n "$bucket" && "$bucket" == "$bucket_fragment"* ]] || continue
                printf 's3://%s/\n' "$bucket"
            done < <(
                AWS_MAX_ATTEMPTS=1 _s3_aws \
                    --cli-connect-timeout 2 --cli-read-timeout 5 --no-paginate \
                    s3api list-buckets --query 'Buckets[].Name' --output text \
                    2>/dev/null | tr '\t' '\n'
            )
            return 0
        fi
        bucket=${candidate%%/*}
        key=${candidate#*/}
    else
        [[ -n "$DEFAULT_S3_BUCKET" ]] || return 0
        bucket="$DEFAULT_S3_BUCKET"
        key=${typed#/}
        [[ "$typed" == /* ]] && display_leading_slash=/
    fi

    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] || continue
        if [[ "$explicit_uri" == 1 ]]; then
            printf 's3://%s/%s\n' "$bucket" "$candidate"
        else
            printf '%s%s\n' "$display_leading_slash" "$candidate"
        fi
    done < <(
        AWS_MAX_ATTEMPTS=1 _s3_aws \
            --cli-connect-timeout 2 --cli-read-timeout 5 --no-paginate \
            s3api list-objects-v2 --bucket "$bucket" --prefix "$key" \
            --delimiter / --max-keys 200 \
            --query '[CommonPrefixes[].Prefix, Contents[].Key][]' --output text \
            2>/dev/null | tr '\t' '\n'
    )
}

# Bash completion helpers.
_s3_bash_completion_add() {
    local candidate="$1"
    local existing
    for existing in "${COMPREPLY[@]}"; do
        [[ "$existing" == "$candidate" ]] && return 0
    done
    COMPREPLY+=("$candidate")
}

_s3_bash_complete_local() {
    local current="$1"
    local candidate
    while IFS= read -r candidate; do
        [[ -d "$candidate" && "$candidate" != */ ]] && candidate+=/
        _s3_bash_completion_add "$candidate"
    done < <(compgen -f -- "$current")
}

_s3_bash_complete_remote() {
    local current="$1"
    local candidate
    while IFS= read -r candidate; do
        _s3_bash_completion_add "$candidate"
    done < <(_s3_remote_candidates "$current")
}

_s3ls_bash_completion() {
    local current="${COMP_WORDS[COMP_CWORD]}"
    local candidate word
    local path_count=0
    local options_ended=0
    local i
    COMPREPLY=()

    for ((i = 1; i < COMP_CWORD; i++)); do
        word=${COMP_WORDS[i]}
        if [[ "$options_ended" == 0 && "$word" == -- ]]; then
            options_ended=1
        elif [[ "$options_ended" == 0 && \
                ( "$word" == -h || "$word" == --human-readable || "$word" == --help ) ]]; then
            :
        else
            path_count=$((path_count + 1))
        fi
    done

    if [[ "$options_ended" == 0 && "$current" == -* ]]; then
        while IFS= read -r candidate; do
            _s3_bash_completion_add "$candidate"
        done < <(compgen -W '-h --human-readable --help' -- "$current")
    elif ((path_count == 0)); then
        _s3_bash_complete_remote "$current"
    fi
    compopt -o filenames -o nospace 2>/dev/null || true
}

_s3cp_bash_completion() {
    local current="${COMP_WORDS[COMP_CWORD]}"
    local source=
    local candidate word
    local operand_count=0
    local options_ended=0
    local i
    COMPREPLY=()

    for ((i = 1; i < COMP_CWORD; i++)); do
        word=${COMP_WORDS[i]}
        if [[ "$options_ended" == 0 && "$word" == -- ]]; then
            options_ended=1
        elif [[ "$options_ended" == 0 && "$word" == --help ]]; then
            :
        else
            operand_count=$((operand_count + 1))
            [[ "$operand_count" == 1 ]] && source="$word"
        fi
    done

    if [[ "$options_ended" == 0 && "$current" == -* ]]; then
        while IFS= read -r candidate; do
            _s3_bash_completion_add "$candidate"
        done < <(compgen -W '--help' -- "$current")
    elif ((operand_count == 0)); then
        if [[ "$current" == s3://* ]]; then
            _s3_bash_complete_remote "$current"
        else
            _s3_bash_complete_local "$current"
            case "$current" in
                /*|./*|../*) ;;
                *) _s3_bash_complete_remote "$current" ;;
            esac
        fi
    elif ((operand_count == 1)); then
        if [[ "$current" == s3://* ]]; then
            _s3_bash_complete_remote "$current"
        elif [[ "$source" == s3://* ]]; then
            _s3_bash_complete_local "$current"
        elif [[ -e "$source" || -L "$source" ]]; then
            _s3_bash_complete_remote "$current"
        else
            _s3_bash_complete_local "$current"
        fi
    fi

    compopt -o filenames -o nospace 2>/dev/null || true
}

# Zsh uses its native completion API instead of Bash's COMP_WORDS/COMPREPLY.
_s3_zsh_complete_remote() {
    local current="$1"
    local candidate
    local -a candidates=()

    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] && candidates+=("$candidate")
    done < <(_s3_remote_candidates "$current")

    (( ${#candidates[@]} > 0 )) && compadd -S '' -- "${candidates[@]}"
}

_s3ls_zsh_completion() {
    local current="${words[CURRENT]}"
    local word
    local path_count=0
    local options_ended=0
    local i

    for ((i = 2; i < CURRENT; i++)); do
        word=${words[i]}
        if [[ "$options_ended" == 0 && "$word" == -- ]]; then
            options_ended=1
        elif [[ "$options_ended" == 0 && \
                ( "$word" == -h || "$word" == --human-readable || "$word" == --help ) ]]; then
            :
        else
            path_count=$((path_count + 1))
        fi
    done

    if [[ "$options_ended" == 0 && "$current" == -* ]]; then
        compadd -S '' -- -h --human-readable --help
    elif ((path_count == 0)); then
        _s3_zsh_complete_remote "$current"
    fi
}

_s3cp_zsh_completion() {
    local current="${words[CURRENT]}"
    local source=
    local word
    local operand_count=0
    local options_ended=0
    local i

    for ((i = 2; i < CURRENT; i++)); do
        word=${words[i]}
        if [[ "$options_ended" == 0 && "$word" == -- ]]; then
            options_ended=1
        elif [[ "$options_ended" == 0 && "$word" == --help ]]; then
            :
        else
            operand_count=$((operand_count + 1))
            [[ "$operand_count" == 1 ]] && source="$word"
        fi
    done

    if [[ "$options_ended" == 0 && "$current" == -* ]]; then
        compadd -S '' -- --help
    elif ((operand_count == 0)); then
        if [[ "$current" == s3://* ]]; then
            _s3_zsh_complete_remote "$current"
        else
            _files
            case "$current" in
                /*|./*|../*) ;;
                *) _s3_zsh_complete_remote "$current" ;;
            esac
        fi
    elif ((operand_count == 1)); then
        if [[ "$current" == s3://* ]]; then
            _s3_zsh_complete_remote "$current"
        elif [[ "$source" == s3://* ]]; then
            _files
        elif [[ -e "$source" || -L "$source" ]]; then
            _s3_zsh_complete_remote "$current"
        else
            _files
        fi
    fi
}

if [[ -n "${BASH_VERSION:-}" ]]; then
    complete -F _s3ls_bash_completion s3ls
    complete -F _s3cp_bash_completion s3cp
elif [[ -n "${ZSH_VERSION:-}" ]] && command -v compdef >/dev/null 2>&1; then
    compdef _s3ls_zsh_completion s3ls
    compdef _s3cp_zsh_completion s3cp
fi



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
