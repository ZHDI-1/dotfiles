# Clean history for Pi

Run **`/answers`** inside interactive Pi to view the current branch as user prompts
paired with their latest replies. Press **`q`**, **`Esc`**, or **`f`** to return to
the unchanged full chat and editor. This is a full-screen, read-only overlay, not
a patch to Pi's built-in transcript renderer.

## Selection rules

1. Each persisted `role: "user"` message starts a group. The next user message
   closes it. The last group includes everything saved so far.
2. Within the group, keep the latest normally completed assistant text response
   without tool calls. This replaces intermediate "tests running" replies when a
   later completion arrives before the next prompt.
3. If text blocks explicitly identify themselves as Codex `commentary`, omit
   those blocks from completed replies. Keep final and untagged text blocks.
   Ollama K3 and other untagged providers use normal completion plus no tool calls;
   opaque/old/malformed signatures do not discard otherwise readable text.
4. Never lose a user prompt because it has no completed answer. Show a waiting or
   incomplete notice instead; readable partial output remains clearly labelled.
5. Errors, aborts, and truncation have explicit status. If a failed attempt has no
   text, an earlier reply may remain, but is labelled **earlier reply**, not a new
   successful answer. A successful retry replaces the partial/failed response.
6. Thinking, tool calls/results, custom background notifications, settings and
   summaries do not appear as conversation turns. Notifications do not split a
   group. Images in user prompts are represented by attachment-count placeholders.

The viewer uses **`sessionManager.getBranch()`**, so sibling branches cannot leak
into the view, and original messages remain visible across normal compaction.
It deliberately does not duplicate compaction summaries or `retainedTail` data.
It cannot reconstruct history that an external importer actually discarded.

This is chronological grouping, not a claim that Pi knows an overall task has
finished. If a background result arrives after a later user prompt, its answer
belongs to that later chronological group. Messages injected by extensions using
`sendUserMessage` are indistinguishable from ordinary persisted user messages and
also count as boundaries; custom-message notifications do not.

## Controls

| Key | Action |
|---|---|
| `j` / `k`, Up / Down, Ctrl+N / Ctrl+P | Scroll a line |
| `d` / `u`, Ctrl+D / Ctrl+U | Scroll half a page down / up (Neovim-style) |
| PageDown / PageUp, Ctrl+F / Ctrl+B | Scroll a full page |
| Space | Page down |
| `[` / `]` | Previous / next prompt |
| `g` / `G`, Home / End | Top / bottom |
| Mouse wheel | Scroll in Pi's fullscreen TUI mode |
| `q`, `Esc`, `f`, Ctrl+C | Close viewer, restore full chat; does **not** abort agent |

The view starts at the bottom. While open it refreshes after saved messages,
branch navigation, compaction and agent state changes. Reading earlier text does
not jump back to the bottom when new output arrives; `G` re-enables following.
It does not display unfinished token streams as completed answers.

## Installation

Place this directory at `~/.pi/agent/extensions/clean-history/`. Pi discovers its
`index.ts` on the next startup. To enable it in an already-running Pi, run
`/reload` yourself, then `/answers`. Installation does not reload a live session.
No dependencies need installing: it uses Pi's bundled packages.

No global shortcut is registered, avoiding conflicts with other extensions.
The command is TUI-only and does not try to open terminal UI in RPC/JSON/print
mode. No tools, model switches, thinking changes, provider calls, shell commands,
context transformations, session writes or settings changes are performed.

## Validation

```sh
node --test ~/.pi/agent/extensions/clean-history/tests/verify.mjs
node ~/.pi/agent/extensions/clean-history/tests/typecheck.mjs
```

Tests resolve Pi's global package next to the running Node installation. If Pi is
installed elsewhere, set `PI_PACKAGE_ROOT` to its package directory. Typechecking
requires `tsc` on PATH. Tests use synthetic messages, Pi's real Markdown renderer,
in-memory SessionManager and native extension loader; no model requests or live
session writes are needed.
