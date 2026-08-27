#!/usr/bin/env bash
# Maintain local bare mirrors for GitHub submodules and use them to initialize
# the current repository's submodules.
set -Eeuo pipefail

self_path=${BASH_SOURCE[0]}
if [[ $self_path != */* ]]; then
  self_path=$(command -v -- "$self_path")
fi
if [[ $self_path != /* ]]; then
  self_path=$(cd "$(dirname "$self_path")" && pwd -P)/$(basename "$self_path")
fi

log()  { printf '[submodule-cache] %s\n' "$*" >&2; }
warn() { printf '[submodule-cache] warning: %s\n' "$*" >&2; }
die()  { printf '[submodule-cache] error: %s\n' "$*" >&2; exit 1; }

is_bare_repo() {
  [[ -d "$1" ]] &&
    [[ "$(git -C "$1" rev-parse --is-bare-repository 2>/dev/null || true)" == true ]]
}

configure_mirror() {
  local mirror=$1 url=$2

  if git -C "$mirror" remote get-url origin >/dev/null 2>&1; then
    git -C "$mirror" remote set-url origin "$url"
  else
    git -C "$mirror" remote add origin "$url"
  fi

  git -C "$mirror" config remote.origin.mirror true
  git -C "$mirror" config --replace-all \
    remote.origin.fetch '+refs/*:refs/*'
}

lock_mirror() {
  local mirror=$1
  LOCK_FD=
  if command -v flock >/dev/null 2>&1; then
    mkdir -p "$(dirname "$mirror")"
    exec {LOCK_FD}>"${mirror}.cache.lock"
    flock "$LOCK_FD"
  fi
}

unlock_mirror() {
  if [[ -n ${LOCK_FD:-} ]]; then
    flock -u "$LOCK_FD" || true
    exec {LOCK_FD}>&-
    LOCK_FD=
  fi
}

refresh_one() {
  local mirror=$1 url shallow

  is_bare_repo "$mirror" || exit 0
  lock_mirror "$mirror"

  url=$(git -C "$mirror" remote get-url origin 2>/dev/null || true)
  if [[ -z "$url" ]]; then
    warn "skipping mirror without origin: $mirror"
    unlock_mirror
    exit 0
  fi

  configure_mirror "$mirror" "$url"
  log "fetch $url"

  shallow=$(git -C "$mirror" rev-parse --is-shallow-repository 2>/dev/null || true)
  if [[ "$shallow" == true ]]; then
    git -C "$mirror" fetch --unshallow --prune origin
  else
    git -C "$mirror" fetch --prune origin
  fi

  unlock_mirror
}

# Private worker used by xargs for parallel mirror refresh.
if [[ ${1:-} == --_refresh-one ]]; then
  (($# == 2)) || exit 2
  refresh_one "$2"
  exit
fi

usage() {
  cat <<'USAGE'
Usage:
  git-submodule-cache.sh [options] [-- SUBMODULE_UPDATE_ARGS...]

Run from the root of a Git worktree. The script:
  1. discovers initialized submodules recursively;
  2. creates missing local GitHub mirrors, preferring existing submodules;
  3. refreshes every mirror under the cache root in parallel;
  4. updates submodules, using a mirror only when it contains the exact
     commit recorded by the superproject;
  5. imports newly discovered nested submodules into the cache.

Options:
  --cache-root DIR   Default: $GIT_SUBMODULE_CACHE or
                     ~/.cache/git-submodules
  --jobs N           Parallel fetch/submodule jobs. Default: online CPUs.
  --offline          Do not refresh mirrors from their remotes.
  --no-update        Maintain the cache, but do not update submodules.
  -h, --help         Show this help.

Examples:
  git-submodule-cache.sh
  git-submodule-cache.sh --jobs 32
  git-submodule-cache.sh -- --depth 1
USAGE
}

cpu_count() {
  local n
  if command -v nproc >/dev/null 2>&1; then
    n=$(nproc)
  else
    n=$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '4')
  fi
  [[ "$n" =~ ^[1-9][0-9]*$ ]] || n=4
  printf '%s\n' "$n"
}

cache_root=${GIT_SUBMODULE_CACHE:-$HOME/.cache/git-submodules}
jobs=${GIT_SUBMODULE_CACHE_JOBS:-$(cpu_count)}
offline=false
do_update=true
submodule_update_args=()

while (($#)); do
  case "$1" in
    --cache-root)
      (($# >= 2)) || die "--cache-root requires a directory"
      cache_root=$2
      shift 2
      ;;
    --cache-root=*)
      cache_root=${1#*=}
      shift
      ;;
    --jobs)
      (($# >= 2)) || die "--jobs requires a positive integer"
      jobs=$2
      shift 2
      ;;
    --jobs=*)
      jobs=${1#*=}
      shift
      ;;
    --offline)
      offline=true
      shift
      ;;
    --no-update)
      do_update=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      submodule_update_args=("$@")
      break
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"
command -v git >/dev/null 2>&1 || die "git is not installed"
command -v xargs >/dev/null 2>&1 || die "xargs is not installed"

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) ||
  die "run this script inside a Git worktree"
repo_root=$(cd "$repo_root" && pwd -P)
cd "$repo_root"

[[ -f .gitmodules ]] || {
  log "no .gitmodules; nothing to do"
  exit 0
}

if [[ "$cache_root" != /* ]]; then
  cache_root="$repo_root/$cache_root"
fi
mkdir -p "$cache_root/github.com"
cache_root=$(cd "$cache_root" && pwd -P)

# URL -> initialized submodule source paths, and URL -> required gitlink SHAs.
declare -A seen_repos=()
declare -A seen_urls=()
declare -A seen_sources=()
declare -A required_commits=()
declare -A url_to_mirror=()
declare -A new_mirrors=()

reset_discovery() {
  seen_repos=()
  seen_urls=()
  seen_sources=()
  required_commits=()
}

is_initialized_repo() {
  local path=$1
  [[ -e "$path/.git" ]] &&
    git -C "$path" rev-parse --git-dir >/dev/null 2>&1
}

absolute_path() {
  local parent=$1 child=$2
  if command -v realpath >/dev/null 2>&1; then
    realpath -m -- "$parent/$child"
  else
    # Fedora has realpath. This fallback works when the directory exists.
    (cd "$parent/$child" 2>/dev/null && pwd -P)
  fi
}

add_source() {
  local url=$1 path=$2
  seen_sources["$url"$'\x1f'"$path"]=1
}

add_required_commit() {
  local url=$1 sha=$2
  [[ -n "$sha" ]] && required_commits["$url"$'\x1f'"$sha"]=1
}

scan_repo() {
  local root=$1 gm key name url relpath child mode sha canonical_root
  local -a keys=()

  canonical_root=$(cd "$root" 2>/dev/null && pwd -P) || return 0
  [[ ${seen_repos[$canonical_root]+yes} ]] && return 0
  seen_repos[$canonical_root]=1

  gm="$canonical_root/.gitmodules"
  [[ -f "$gm" ]] || return 0

  mapfile -t keys < <(
    git config -f "$gm" --name-only \
      --get-regexp '^submodule\..*\.url$' 2>/dev/null || true
  )

  for key in "${keys[@]}"; do
    name=${key#submodule.}
    name=${name%.url}
    url=$(git config -f "$gm" --get "$key" 2>/dev/null || true)
    relpath=$(git config -f "$gm" --get "submodule.$name.path" 2>/dev/null || true)

    if [[ -z "$url" || -z "$relpath" ]]; then
      warn "invalid entry in $gm: $name"
      continue
    fi

    seen_urls[$url]=1
    child=$(absolute_path "$canonical_root" "$relpath" 2>/dev/null || true)

    mode=$(git -C "$canonical_root" ls-files -s -- "$relpath" 2>/dev/null |
      awk 'NR == 1 { print $1 }')
    if [[ "$mode" == 160000 ]]; then
      sha=$(git -C "$canonical_root" rev-parse --verify ":$relpath" 2>/dev/null || true)
      add_required_commit "$url" "$sha"
    fi

    if [[ -n "$child" ]] && is_initialized_repo "$child"; then
      add_source "$url" "$child"
      scan_repo "$child"
    fi
  done
}

# Print the normalized owner/repository portion for supported GitHub URLs.
github_repo_key() {
  local url=${1%/} rel
  case "$url" in
    https://github.com/*)  rel=${url#https://github.com/} ;;
    http://github.com/*)   rel=${url#http://github.com/} ;;
    git://github.com/*)    rel=${url#git://github.com/} ;;
    git@github.com:*)      rel=${url#git@github.com:} ;;
    ssh://git@github.com/*) rel=${url#ssh://git@github.com/} ;;
    *) return 1 ;;
  esac

  rel=${rel%.git}
  [[ "$rel" == */* ]] || return 1
  [[ "$rel" != /* && "$rel" != *'/../'* && "$rel" != '../'* ]] || return 1
  printf '%s\n' "$rel"
}

choose_mirror_path() {
  local url=$1 key canonical legacy
  key=$(github_repo_key "$url") || return 1
  canonical="$cache_root/github.com/$key.git"
  legacy="$cache_root/github.com/$key"

  if is_bare_repo "$canonical"; then
    printf '%s\n' "$canonical"
  elif is_bare_repo "$legacy"; then
    # Reuse caches made by the earlier script that preserved a missing .git.
    printf '%s\n' "$legacy"
  else
    printf '%s\n' "$canonical"
  fi
}

first_usable_source() {
  local url=$1 key source
  for key in "${!seen_sources[@]}"; do
    [[ "$key" == "$url"$'\x1f'* ]] || continue
    source=${key#*$'\x1f'}
    if is_initialized_repo "$source"; then
      printf '%s\n' "$source"
      return 0
    fi
  done
  return 1
}

ensure_mirror() {
  local url=$1 mirror source parent tmp
  ENSURED_MIRROR=
  ENSURED_NEW=false

  mirror=$(choose_mirror_path "$url") || {
    warn "unsupported submodule URL; direct remote will be used: $url"
    return 1
  }

  parent=$(dirname "$mirror")
  mkdir -p "$parent"
  lock_mirror "$mirror"

  if is_bare_repo "$mirror"; then
    configure_mirror "$mirror" "$url"
    ENSURED_MIRROR=$mirror
    unlock_mirror
    return 0
  fi

  if [[ -e "$mirror" ]]; then
    warn "cache path exists but is not a bare repository: $mirror"
    unlock_mirror
    return 1
  fi

  tmp=$(mktemp -d "$parent/.submodule-cache.XXXXXX")
  source=$(first_usable_source "$url" 2>/dev/null || true)

  if [[ -n "$source" ]]; then
    log "seed $url from $source"
    if ! git clone --mirror -- "$source" "$tmp"; then
      rm -rf -- "$tmp"
      unlock_mirror
      return 1
    fi
  elif [[ "$offline" == true ]]; then
    warn "no initialized source for $url while offline"
    rm -rf -- "$tmp"
    unlock_mirror
    return 1
  else
    log "clone $url"
    if ! git clone --mirror -- "$url" "$tmp"; then
      rm -rf -- "$tmp"
      unlock_mirror
      return 1
    fi
  fi

  configure_mirror "$tmp" "$url"
  mv -- "$tmp" "$mirror"
  ENSURED_MIRROR=$mirror
  ENSURED_NEW=true
  unlock_mirror
}

seed_required_objects() {
  local url=$1 mirror=$2 pair sha source_pair source
  local found_source

  for pair in "${!required_commits[@]}"; do
    [[ "$pair" == "$url"$'\x1f'* ]] || continue
    sha=${pair#*$'\x1f'}

    git -C "$mirror" cat-file -e "$sha^{commit}" 2>/dev/null && continue
    found_source=false

    for source_pair in "${!seen_sources[@]}"; do
      [[ "$source_pair" == "$url"$'\x1f'* ]] || continue
      source=${source_pair#*$'\x1f'}
      git -C "$source" cat-file -e "$sha^{commit}" 2>/dev/null || continue

      log "seed object $sha for $url from $source"
      lock_mirror "$mirror"
      if git -C "$mirror" fetch --no-tags --no-write-fetch-head -- "$source" "$sha"; then
        found_source=true
      fi
      unlock_mirror
      [[ "$found_source" == true ]] && break
    done
  done
}

ensure_discovered_mirrors() {
  local url
  for url in "${!seen_urls[@]}"; do
    if ensure_mirror "$url"; then
      url_to_mirror[$url]=$ENSURED_MIRROR
      if [[ "$ENSURED_NEW" == true ]]; then
        new_mirrors[$ENSURED_MIRROR]=1
      fi
      seed_required_objects "$url" "$ENSURED_MIRROR"
    fi
  done
}

discover_all_cache_mirrors() {
  local config candidate
  while IFS= read -r -d '' config; do
    candidate=${config%/config}
    is_bare_repo "$candidate" && printf '%s\0' "$candidate"
  done < <(find "$cache_root" -type f -name config -print0)
}

refresh_mirror_list() {
  (($# > 0)) || return 0
  if ! printf '%s\0' "$@" |
      xargs -0 -r -n 1 -P "$jobs" \
        bash "$self_path" --_refresh-one; then
    warn "one or more mirror refreshes failed; cached commits remain usable"
  fi
  return 0
}

mirror_has_all_required_commits() {
  local url=$1 mirror=$2 pair sha
  for pair in "${!required_commits[@]}"; do
    [[ "$pair" == "$url"$'\x1f'* ]] || continue
    sha=${pair#*$'\x1f'}
    git -C "$mirror" cat-file -e "$sha^{commit}" 2>/dev/null || return 1
  done
  return 0
}

build_cache_git_config() {
  local url mirror file_url
  cache_git_config=(-c protocol.file.allow=always)

  for url in "${!url_to_mirror[@]}"; do
    mirror=${url_to_mirror[$url]}
    if mirror_has_all_required_commits "$url" "$mirror"; then
      file_url="file://$mirror"
      cache_git_config+=(-c "url.${file_url}.insteadOf=${url}")
      log "use cache for $url"
    else
      warn "cache lacks Ceph's pinned commit for $url; using direct remote"
    fi
  done
}

log "repository: $repo_root"
log "cache:      $cache_root"
log "jobs:       $jobs"

reset_discovery
scan_repo "$repo_root"
ensure_discovered_mirrors

if [[ "$offline" == false ]]; then
  mapfile -d '' all_mirrors < <(discover_all_cache_mirrors)
  refresh_mirror_list "${all_mirrors[@]}"

  # A refresh may have added commits that were absent during initial seeding.
  for url in "${!url_to_mirror[@]}"; do
    seed_required_objects "$url" "${url_to_mirror[$url]}"
  done
fi

if [[ "$do_update" == true ]]; then
  build_cache_git_config
  git "${cache_git_config[@]}" submodule sync --recursive
  git "${cache_git_config[@]}" submodule update \
    --init --recursive --jobs "$jobs" \
    "${submodule_update_args[@]}"
fi

# The update can reveal nested .gitmodules that were unavailable before.
reset_discovery
scan_repo "$repo_root"
new_mirrors=()
ensure_discovered_mirrors

if [[ "$offline" == false && ${#new_mirrors[@]} -gt 0 ]]; then
  refresh_mirror_list "${!new_mirrors[@]}"
fi

log "complete"
