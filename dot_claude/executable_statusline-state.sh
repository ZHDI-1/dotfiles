#!/usr/bin/env bash
# Records the session run-state shown by statusline-command.sh. Called from
# hooks with the hook JSON on stdin:
#   statusline-state.sh Ready|Thinking|Working   write the state
#   statusline-state.sh clear                    remove it (SessionEnd)
# Must stay silent and always exit 0: UserPromptSubmit stdout is injected into
# the conversation and a PreToolUse exit code of 2 blocks the tool.

dir="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline/state"
sid=$(jq -r '.session_id // empty' 2>/dev/null)
sid=${sid//[^a-zA-Z0-9_-]/}
[[ -n $sid ]] || exit 0

if [[ $1 == clear ]]; then
	rm -f "$dir/$sid"
else
	mkdir -p "$dir" && printf '%s\n' "$1" >"$dir/$sid.$$" && mv -f "$dir/$sid.$$" "$dir/$sid"
fi
exit 0
