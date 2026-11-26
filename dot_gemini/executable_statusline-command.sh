#!/usr/bin/env bash
# Antigravity CLI (agy) status line modeled on ~/.claude/statusline-command.sh
# and Codex TUI [tui].status_line:
#   model-with-reasoning · current-dir · project-name · git-branch · branch-changes
#   · run-state · context-used · quota/limits · tasks/subagents
# Items without data are omitted. Quota/limits show remaining percentage;
# context shows used percentage.

input=$(cat)
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/agy-statusline"
export GIT_OPTIONAL_LOCKS=0

model="" effort="" cwd="" project_dir="" vcs_branch=""
agent_state="" ctx_used="" quota_left="" five_left="" week_left=""
task_count="" subagent_count=""

if [[ -n $input ]]; then
	IFS=$'\x1f' read -r model effort cwd project_dir vcs_branch \
		agent_state ctx_used quota_left five_left week_left \
		task_count subagent_count _sentinel < <(
		jq -r '
		  def pct:
		    if . == null then ""
		    elif (type == "number") then round
		    else "" end;
		  def norm_pct:
		    if . == null then null
		    elif (type == "number") then (if . <= 1 and . > 0 then . * 100 else . end)
		    else null end;
		  def ctx_pct:
		    if .context_window.used_percentage != null then .context_window.used_percentage
		    elif .context_window.remaining_percentage != null then (100 - .context_window.remaining_percentage)
		    elif (.context_window.total_input_tokens != null and (.context_window.context_window_size // 0) > 0) then
		      (.context_window.total_input_tokens * 100 / .context_window.context_window_size)
		    else null end;
		  def bucket_rem:
		    if type == "object" then
		      if .remaining_fraction != null then (.remaining_fraction * 100)
		      elif .remaining_percentage != null then .remaining_percentage
		      elif .used_percentage != null then (100 - .used_percentage)
		      else null end
		    elif type == "number" then norm_pct
		    else null end;
		  def pick_bucket($re):
		    if (.quota | type) == "object" then
		      (.quota | to_entries | map(select(.key | test($re; "i"))) | first | .value // null | bucket_rem)
		    else null end;
		  def model_str:
		    (if (.model | type) == "object" then (.model.display_name // .model.id // "")
		     elif (.model | type) == "string" then .model
		     else "" end);
		  def quota_5h:
		    if (.quota | type) == "object" then
		      if (model_str | test("claude|opus|sonnet|gpt"; "i")) then
		        ((.quota["3p-5h"] // null | bucket_rem) // pick_bucket("5h"))
		      else
		        ((.quota["gemini-5h"] // null | bucket_rem) // pick_bucket("5h"))
		      end
		    else null end;
		  def quota_weekly:
		    if (.quota | type) == "object" then
		      if (model_str | test("claude|opus|sonnet|gpt"; "i")) then
		        ((.quota["3p-weekly"] // null | bucket_rem) // pick_bucket("weekly"))
		      elif (model_str | test("argon"; "i")) then
		        (pick_bucket("argon.*weekly") // (.quota["gemini-weekly"] // null | bucket_rem) // pick_bucket("weekly"))
		      else
		        ((.quota["gemini-weekly"] // null | bucket_rem) // pick_bucket("weekly"))
		      end
		    else null end;
		  def quota_rem:
		    if (.quota | type) == "number" then (.quota | norm_pct)
		    elif (.quota | type) == "object" then
		      (if (.quota.remaining_fraction != null or .quota.remaining_percentage != null or .quota.used_percentage != null) then
		         (.quota | bucket_rem)
		       else
		         ([.quota[] | bucket_rem | select(. != null)] | if length > 0 then min else null end)
		       end)
		    else null end;
		  [
		    model_str,
		    (if (.effort | type) == "object" then (.effort.level // .effort.name // "")
		     elif (.effort | type) == "string" then .effort
		     else (.reasoning_effort // "") end),
		    (.workspace.current_dir // .cwd // .workspace_dir // ""),
		    (.workspace.project_dir // ""),
		    (.vcs.branch // ""),
		    (.agent_state // ""),
		    (ctx_pct | pct),
		    (quota_rem | pct),
		    ((quota_5h // (.rate_limits.five_hour.used_percentage | if . == null then null else 100 - . end)) | pct),
		    ((quota_weekly // (.rate_limits.seven_day.used_percentage | if . == null then null else 100 - . end)) | pct),
		    (if (.task_count | type) == "number" then .task_count
		     elif (.bg_tasks | type) == "array" then (.bg_tasks | length)
		     else 0 end),
		    (if (.subagents | type) == "array" then (.subagents | length)
		     elif (.subagents | type) == "number" then .subagents
		     else 0 end),
		    "_"
		  ] | map(tostring) | join("\u001f")' <<<"$input" 2>/dev/null || true
	)
fi

# Gruvbox mid-tone palette: readable on both light and dark variants.
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

# model-with-reasoning (avoid duplicating effort if display_name already embeds it)
if [[ -n $model ]]; then
	model_label=$model
	if [[ -n $effort && "${model,,}" != *"${effort,,}"* ]]; then
		model_label+=" $effort"
	fi
	parts+=("$BOLD$(fg "$BLUE")$model_label$RESET")
fi

# current-dir
[[ -n $cwd ]] && add "$AQUA" "${cwd/#$HOME/\~}"

# project-name, git-branch, branch-changes
toplevel=""
if [[ -n $cwd && -d $cwd ]]; then
	toplevel=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || true)
fi
project=${toplevel:-$project_dir}
[[ -n $project ]] && add "$PURPLE" "${project##*/}"

branch=""
if [[ -n $toplevel ]]; then
	branch=$(git -C "$cwd" symbolic-ref --short -q HEAD 2>/dev/null ||
		git -C "$cwd" rev-parse --short HEAD 2>/dev/null || true)
fi
branch=${branch:-$vcs_branch}
[[ -n $branch ]] && add "$YELLOW" "$branch"

if [[ -n $toplevel ]]; then
	# Committed changes against the default branch, cached on (HEAD, base).
	base_ref=$(git -C "$cwd" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)
	if [[ -z $base_ref ]]; then
		for b in main master; do
			git -C "$cwd" show-ref -q --verify "refs/heads/$b" && base_ref=$b && break
		done
	fi
	head=$(git -C "$cwd" rev-parse -q --verify HEAD 2>/dev/null || true)
	base=${base_ref:+$(git -C "$cwd" rev-parse -q --verify "$base_ref^{commit}" 2>/dev/null || true)}
	if [[ -n $head && -n $base ]]; then
		key=$(printf '%s' "$toplevel" | cksum | cut -d' ' -f1)
		cache="$cache_dir/branch-changes/$key"
		c_head="" c_base="" added=0 removed=0
		[[ -r $cache ]] && read -r c_head c_base added removed <"$cache" || true
		if [[ $c_head != "$head" || $c_base != "$base" ]]; then
			added=0 removed=0
			if mb=$(git -C "$cwd" merge-base "$base" "$head" 2>/dev/null) && [[ $mb != "$head" ]]; then
				stat=$(git -C "$cwd" diff --shortstat "$mb" "$head" 2>/dev/null || true)
				[[ $stat =~ ([0-9]+)\ insertion ]] && added=${BASH_REMATCH[1]}
				[[ $stat =~ ([0-9]+)\ deletion ]] && removed=${BASH_REMATCH[1]}
			fi
			mkdir -p "${cache%/*}" 2>/dev/null && echo "$head $base $added $removed" >"$cache" 2>/dev/null || true
		fi
		((added || removed)) &&
			parts+=("$(fg "$GREEN")+$added$RESET $(fg "$RED")-$removed$RESET")
	fi
fi

# run-state
case "${agent_state,,}" in
working|tool_use|tool|executing|running) add "$ORANGE" "Working" ;;
thinking|reasoning|planning) add "$PURPLE" "Thinking" ;;
waiting*) add "$YELLOW" "Waiting" ;;
*) add "$GRAY" "Ready" ;;
esac

# context-used
[[ -n $ctx_used ]] && add "$(usage_color "$ctx_used")" "Context $ctx_used% used"

# quota / rate limits (remaining)
if [[ -n $five_left || -n $week_left ]]; then
	[[ -n $five_left ]] && add "$(usage_color $((100 - five_left)))" "5h $five_left%"
	[[ -n $week_left ]] && add "$(usage_color $((100 - week_left)))" "weekly $week_left%"
elif [[ -n $quota_left ]]; then
	add "$(usage_color $((100 - quota_left)))" "Quota $quota_left%"
fi

# tasks / subagents
if [[ $task_count =~ ^[0-9]+$ ]] && ((task_count > 0)); then
	add "$BLUE" "Tasks $task_count"
fi
if [[ $subagent_count =~ ^[0-9]+$ ]] && ((subagent_count > 0)); then
	add "$BLUE" "Agents $subagent_count"
fi

((${#parts[@]} == 0)) && exit 0
sep=" $(fg "$GRAY")·$RESET "
out=${parts[0]}
for p in "${parts[@]:1}"; do out+="$sep$p"; done
printf '%s\n' "$out"
