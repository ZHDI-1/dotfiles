# Code-learning toolkit validation

Validated on 2026-07-30 with Codex CLI 0.146.0.

## Installation and preservation baseline

- The requested user skill root, `/home/zhdi/.agents/skills`, did not exist
  before creation.
- Neither `/home/zhdi/.codex/AGENTS.md` nor
  `/home/zhdi/.codex/AGENTS.override.md` existed. The global file was therefore
  created rather than replacing user content.
- Managed system skills, plugin caches, `config.toml`, authentication, and
  state files under `/home/zhdi/.codex` were not changed.
- The read-only code fixture was
  `/home/zhdi/build_part/ceph-client/5.14.0`, clean branch `5.14.0`, commit
  `6fe6861bc9d0ac68dd9983f9305e7eba4a693f3d`. It remained clean after testing.

## Structural and discovery checks

Dependency-free checks established that all six skill folders:

- contain one nonempty `SKILL.md`;
- use exactly `name` and `description` frontmatter keys;
- have a hyphen-case name matching the folder;
- have a nonempty description below 1,024 characters with a positive trigger
  and negative boundary;
- contain no scaffold placeholders;
- stay below 500 lines;
- link directly to the existing shared evidence contract.

Each `agents/openai.yaml` contains only quoted `display_name`,
`short_description`, and `default_prompt` interface values. Every short
description is 25–64 characters, and every default prompt includes the exact
`$skill-name`.

All local Markdown references resolve within the skill root. The index is 32
lines and names all six invocations without copying their workflows.

The bundled `quick_validate.py` could not start because this installation's
Python environment lacks its `yaml` module dependency. No dependency was
installed solely for validation. Instead, `codex debug prompt-input` exercised
the running Codex YAML parser and discovered all six skills at their exact
`/home/zhdi/.agents/skills/.../SKILL.md` paths. The check passed both from
`/home/zhdi` and from the mounted Ceph fixture.

The same prompt-input check showed the marked code-learning section from
`/home/zhdi/.codex/AGENTS.md` in the global instruction input. Its begin and end
markers each occur exactly once.

## Activation simulations

A fresh ephemeral, read-only Codex process selected:

| Scenario | Result |
| --- | --- |
| A: first repository visit | `codebase-orient` |
| B: one metadata request end to end | `trace-codepath` |
| C: capabilities across files and lifecycle | `deep-dive-mechanism` |
| D: one dense chooser function | `function-forensics` |
| E: nested pointer, lock, teardown, and ordering proof | `concurrency-lifetime-audit` |
| F: symptom caused by a precedence-sensitive macro | `debug-hypothesis` |

Contrast probes also passed:

- whole-repository architecture selected `codebase-orient`, not function
  forensics;
- post-unlock pointer validity selected `concurrency-lifetime-audit`, not
  orientation;
- one writeback request selected `trace-codepath`;
- writeback as a lifecycle and invariant model selected
  `deep-dive-mechanism`;
- a hang inside a named chooser selected `debug-hypothesis`.

## Output-behavior simulations

Scenario A's dry run began with runtime entities, state owners, boundaries, and
representative flows; it explicitly rejected directory and symbol inventories
and stopped at a prioritized reading path.

Scenario B tracked one logical request through queue ownership, wake-up,
transport callback, retry, completion, and cleanup. It explicitly refused to
stop at enqueue, wait registration, send, or retry scheduling.

Scenario C began with the problem, authority, entities, and invariants, then
constructed capability issue, use, revocation, recovery, and destruction before
mapping structures and functions.

Scenario D forward-tested `function-forensics` on `__choose_mds` in the Ceph
client. The result:

- compressed local declarations into the routing inputs and sentinel;
- explained the RCU-to-`igrab`/`ihold` lifetime transition;
- identified exactly what `i_ceph_lock` stabilizes;
- explained why only `s_mds` escapes as a scalar and why `iput` follows unlock;
- established that the returned rank is a candidate, not a final routing
  decision;
- followed caller validation, session opening, waiting, forwarding, retry, and
  completion;
- found meaningful asymmetries and an operationally dead mode assignment
  without turning every oddity into a bug.

The same run found a precedence defect in `CEPH_MDS_IS_READY` and a
debug-evaluation-dependent potential null dereference, demonstrating that
semantic logging arguments and downstream correction received more attention
than syntax.

Scenario E forward-tested `concurrency-lifetime-audit` on
`cap->session->s_mds`. It did not stop at “the inode lock protects the cap.”
It searched publication, mutation, all session-unregister call sites, cap
teardown, reference ownership, and relevant lock edges. The supported safety
chain required both `i_ceph_lock` and the session registry or teardown-held
reference; the report included a counterfactual interleaving, sleepability
check, bounded reverse-order search, and runtime lockdep/KASAN verification.

Scenario F first passed a minimal precedence fixture, producing the actual
parse, concrete values, a truth table, expected versus actual behavior,
downstream qualification, competing hypotheses, and a focused assertion. It
was then forward-tested on the real Ceph `CEPH_MDS_IS_READY` macro. For a
zero-state, non-laggy map hole, the analysis proved that random fallback can
choose an unusable rank and that `__do_request` then queues the synchronous
request on `waiting_for_map`; runtime attribution was correctly left dependent
on correlated logs and the captured MDS map.

## Limitations

- Implicit model routing is probabilistic. The positive, negative, and overlap
  probes passed, but future Codex versions should rerun them after metadata
  changes.
- Static analysis cannot prove a runtime occurrence. The Ceph precedence
  consequence is proven for its triggering map state; observing that state in a
  reported incident still requires logs or a focused test.
- The concurrency search was bounded to the fixture's `fs/ceph` implementation
  and its relevant callers. The report states that scope rather than claiming a
  universal kernel proof.
- A Codex session started before these files were created may need a fresh
  session or restart if its UI does not refresh, although fresh-process
  discovery succeeded.
