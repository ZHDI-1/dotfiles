#!/usr/bin/env bash
# Claude Code status line modeled on the Codex TUI [tui].status_line:
#   model-with-reasoning · current-dir · project-name · git-branch · branch-changes
#   · run-state · context-used · five-hour-limit · weekly-limit · task-progress
# Items without data are omitted, as Codex does. Limits show the remaining
# percentage (Codex semantics); context shows the used percentage.
# Run-state is written by hooks via ~/.claude/statusline-state.sh.

input=$(cat)
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline"
claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
export GIT_OPTIONAL_LOCKS=0

IFS=$'\x1f' read -r session_id transcript cwd project_dir model effort \
	ctx_used five_left week_left < <(
	jq -r '
	  def pct: if . == null then "" else round end;
	  [ .session_id // "",
	    .transcript_path // "",
	    .workspace.current_dir // .cwd // "",
	    .workspace.project_dir // "",
	    .model.display_name // .model.id // "",
	    .effort.level // "",
	    (.context_window.used_percentage | pct),
	    (.rate_limits.five_hour.used_percentage | if . == null then null else 100 - . end | pct),
	    (.rate_limits.seven_day.used_percentage | if . == null then null else 100 - . end | pct)
	  ] | map(tostring) | join("\u001f")' <<<"$input"
)

# Gruvbox mid-tone palette: readable on both the light and dark variants.
fg() { printf '\e[38;2;%sm' "$1"; }
RESET=$'\e[0m' BOLD=$'\e[1m'
BLUE='69;133;136' AQUA='104;157;106' PURPLE='177;98;134' YELLOW='215;153;33'
GREEN='152;151;26' RED='204;36;29' ORANGE='214;93;14' GRAY='146;131;116'

# Green/yellow/red by how much of a budget is consumed (0-100).
usage_color() {
	if (($1 >= 80)); then echo "$RED"; elif (($1 >= 50)); then echo "$YELLOW"; else echo "$GREEN"; fi
}

parts=()
add() { parts+=("$(fg "$1")$2$RESET"); }

# model-with-reasoning
[[ -n $model ]] && parts+=("$BOLD$(fg "$BLUE")$model${effort:+ $effort}$RESET")

# current-dir
[[ -n $cwd ]] && add "$AQUA" "${cwd/#$HOME/\~}"

# project-name, git-branch, branch-changes
toplevel=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
project=${toplevel:-$project_dir}
[[ -n $project ]] && add "$PURPLE" "${project##*/}"

if [[ -n $toplevel ]]; then
	branch=$(git -C "$cwd" symbolic-ref --short -q HEAD 2>/dev/null ||
		git -C "$cwd" rev-parse --short HEAD 2>/dev/null)
	[[ -n $branch ]] && add "$YELLOW" "$branch"

	# Committed changes against the default branch, cached on (HEAD, base) so
	# the diff only runs when either moves.
	base_ref=$(git -C "$cwd" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)
	if [[ -z $base_ref ]]; then
		for b in main master; do
			git -C "$cwd" show-ref -q --verify "refs/heads/$b" && base_ref=$b && break
		done
	fi
	head=$(git -C "$cwd" rev-parse -q --verify HEAD 2>/dev/null)
	base=${base_ref:+$(git -C "$cwd" rev-parse -q --verify "$base_ref^{commit}" 2>/dev/null)}
	if [[ -n $head && -n $base ]]; then
		key=$(printf '%s' "$toplevel" | cksum | cut -d' ' -f1)
		cache="$cache_dir/branch-changes/$key"
		read -r c_head c_base added removed 2>/dev/null <"$cache"
		if [[ $c_head != "$head" || $c_base != "$base" ]]; then
			added=0 removed=0
			if mb=$(git -C "$cwd" merge-base "$base" "$head" 2>/dev/null) && [[ $mb != "$head" ]]; then
				stat=$(git -C "$cwd" diff --shortstat "$mb" "$head" 2>/dev/null)
				[[ $stat =~ ([0-9]+)\ insertion ]] && added=${BASH_REMATCH[1]}
				[[ $stat =~ ([0-9]+)\ deletion ]] && removed=${BASH_REMATCH[1]}
			fi
			mkdir -p "${cache%/*}" && echo "$head $base $added $removed" >"$cache"
		fi
		((added || removed)) &&
			parts+=("$(fg "$GREEN")+$added$RESET $(fg "$RED")-$removed$RESET")
	fi
fi

# run-state: hooks record Thinking/Working/Ready. An Esc interrupt fires no
# hook, so if the newest user/assistant entry is the "[Request interrupted by
# user...]" marker, the turn is over. fromjson? skips a half-written last line.
state=Ready
state_file="$cache_dir/state/${session_id//[^a-zA-Z0-9_-]/}"
[[ -n $session_id && -r $state_file ]] && state=$(<"$state_file")
if [[ $state != Ready && -r $transcript ]] &&
	tail -n 8 "$transcript" | jq -Rne '
	  [inputs | fromjson? | select(.type == "user" or .type == "assistant")] | last
	  | .type == "user" and (.message.content
	      | if type == "string" then . else map(.text? // "") | join("") end
	      | startswith("[Request interrupted by user"))' >/dev/null 2>&1; then
	state=Ready
fi
case $state in
Working) add "$ORANGE" "Working" ;;
Thinking) add "$PURPLE" "Thinking" ;;
*) add "$GRAY" "Ready" ;;
esac

# context-used
[[ -n $ctx_used ]] && add "$(usage_color "$ctx_used")" "Context $ctx_used% used"

# five-hour-limit, weekly-limit (remaining)
[[ -n $five_left ]] && add "$(usage_color $((100 - five_left)))" "5h $five_left%"
[[ -n $week_left ]] && add "$(usage_color $((100 - week_left)))" "weekly $week_left%"

# task-progress: Claude Code's task list (TaskCreate/TaskUpdate), when enabled.
list_id=${CLAUDE_CODE_TASK_LIST_ID:-$session_id}
task_dir="$claude_dir/tasks/${list_id//[^a-zA-Z0-9_-]/-}"
if [[ -n $list_id ]] && compgen -G "$task_dir/*.json" >/dev/null; then
	read -r done total < <(jq -rs '[.[] | select(.status != "deleted")]
		| "\(map(select(.status == "completed")) | length) \(length)"' \
		"$task_dir"/*.json 2>/dev/null)
	((total > 0)) && add "$BLUE" "Tasks $done/$total"
fi

sep=" $(fg "$GRAY")·$RESET "
out=${parts[0]}
for p in "${parts[@]:1}"; do out+="$sep$p"; done
printf '%s\n' "$out"
