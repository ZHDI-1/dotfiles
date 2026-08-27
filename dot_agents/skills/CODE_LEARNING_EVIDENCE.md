# Shared code-learning guidance

Use this reference for a requested code explanation or investigation. It is not a general workflow for editing files. Apply only the parts needed for the question; the user's requested scope, depth, and format take precedence over these guidelines.

## Evidence

- Start with the relevant implementation and expand to callers, consumers, mutation, or teardown only when they affect the answer. Consult history when current code leaves a material question unresolved.
- Check applicable repository instructions. Establish version and repository state when they matter; do not print a baseline table by default.
- Distinguish source facts, bounded search findings, design inference, and runtime uncertainty. Comments describe intent, not proof.
- Qualify claims such as “all callers,” “never,” or “safe” by the evidence actually examined. A lock name, non-null pointer, or fallback alone is not a correctness argument.
- Explain what cited code does and why it supports the claim. Avoid bare lists of locations.
- Follow asynchronous work to the continuation that matters to the question. Identify who owns progress and what wakes a wait or retry.

## Explanation

State the answer or central idea first. Introduce unfamiliar concepts briefly before their field names and expand them where needed. Give the most detail to decisions, state changes, ownership, concurrency, and failure handling. Group routine declarations, copies, and logging unless their evaluation has important side effects.

Use a concrete example, interleaving, diagram, or table when it clarifies a difficult point. Do not require one of each, force normal/failure scenarios onto every answer, or repeat the same flow in several formats. Treat “line by line” as coverage of meaningful behavior rather than equal prose for every line.

## Scope and stopping

Stop when the question is answered with sufficient evidence. If evidence is missing, state the specific gap and the smallest useful next observation. Do not invent additional hypotheses or follow-up tasks to fill a template.

Read-only analysis normally needs source inspection, not new tests or verification scripts. Suggest or run a focused diagnostic only when it resolves a concrete uncertainty and is within the requested scope. Do not modify code when asked only to explain or diagnose it.
