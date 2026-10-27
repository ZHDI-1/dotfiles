<!-- imported-from: codex:user:instructions -->
<!-- BEGIN CODE-LEARNING PREFERENCES -->
## Code-learning preferences

- Build a runtime mental model before presenting low-level source detail.
- Do not equate exhaustive output with depth. Weight explanation by semantic
  importance: compress declarations, obvious assignments, straightforward
  logging, and
  mechanical glue; expand locks, ownership, lifetime, concurrency, state
  transitions, retries, callbacks, error paths, fallbacks, invariants, protocol
  boundaries, and surprising choices.
- Prefer connected prose. Use bullets for genuinely parallel items and tables
  only when a matrix or direct comparison improves understanding.
- Distinguish direct code evidence, repository-search findings, inference,
  hypotheses, potential bugs, and runtime-dependent conclusions where the claim
  is made. Search before making repository-wide claims.
- Explain why the code works this way, why the logic is here, and why an
  apparent alternative is not used; do not invent intent.
- Cite relevant files, symbols, and line ranges when available. Do not recurse
  into unrelated subsystems without a reason, and end with a bounded
  next-reading path.
<!-- END CODE-LEARNING PREFERENCES -->

## Flow diagrams

- Use ASCII diagrams by default whenever a flow diagram is needed.
- Do not use Mermaid `flowchart TD` unless the user explicitly requests it.

## Editing configs, settings, and personal scripts (chezmoi)

Dotfiles in `$HOME` are managed by chezmoi (source dir: `~/.local/share/chezmoi`).
Before modifying any config file, settings file, or personal script, including
this agent's own instruction and settings files, check whether chezmoi manages
it:

    chezmoi source-path <absolute target path>

- If it prints a source path, edit that source file, not the copy in `$HOME`;
  a direct edit is overwritten on the next apply. Respect the source-state
  type: a `.tmpl` file is a template (keep the template syntax and check the
  rendered result with `chezmoi cat <target>`), a `modify_` file is a script
  that rewrites the target (change the script, not its output), and a
  `create_` file is only written when the target is missing.
- Run `chezmoi diff <target>` before editing. If the target has drifted from
  the source, ask before applying, because apply would discard those local
  changes.
- Edit the source file directly. Do not use `chezmoi edit`; its hook offers a
  git commit/push.
- After editing, apply only the targets you changed with
  `chezmoi apply <target>...` and confirm `chezmoi diff <target>` is empty.
  Do not commit or push the chezmoi repo unless asked.
- For a new file in a managed directory, create it in the matching source
  directory (`chezmoi source-path <dir>`) using chezmoi naming (`dot_`,
  `private_`, `executable_`, ...), then apply it.
- If it reports "not managed", edit the file in place. This includes files
  inside `.chezmoiexternal.toml` repos such as `~/.config/nvim`, which are
  their own git repos.
