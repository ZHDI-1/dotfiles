---
name: trace-codepath
description: Trace one concrete operation or event through execution, state changes, asynchronous work, and completion. Use for an end-to-end flow question, not general architecture or routine edits.
---

# Trace Codepath

Follow one logical operation rather than listing calls. Use the [shared guidance](../CODE_LEARNING_EVIDENCE.md).

1. Identify what starts the operation, its important input state, and what counts as completion. If given a middle function, work backward only far enough to establish this context.
2. Follow the main request or object through decisions and state changes. Explain layer crossings, ownership transfers, and execution-context changes when they matter. Group mechanical helpers.
3. Follow queues, callbacks, sends, and waits to their actual continuation. Identify the progress owner, wake condition, and relevant cancellation or timeout behavior.
4. Explain retries and failure branches that materially affect the operation. Track whether identity and state survive another attempt and what prevents duplicate effects, where established by the code.
5. Stop at completion, explicit failure, a retry with a known wake condition, or a clearly bounded external handoff.

Present the path once in a coherent narrative, with source references at important transitions. Add a compact timeline or concrete example only if it helps. Include observability points when the user needs to locate where an operation stalls; do not append a diagnostic plan to every trace.
