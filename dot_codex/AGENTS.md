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
