---
name: function-forensics
description: "Explain one dense function or bounded implementation cluster: its contract, decisions, callers, ownership, and consequences. Use for deep function analysis, not routine edits or a whole-system survey."
---

# Function Forensics

Explain the reasoning encoded in the function. Use the [shared guidance](../CODE_LEARNING_EVIDENCE.md).

1. Read the function and the callers or consumers needed to establish its contract. Identify preconditions, outputs, side effects, and any caller-held lock or lifetime assumptions.
2. Determine whether its result is definitive, provisional, a candidate, or an ownership transfer. Follow downstream validation or correction when the contract relies on it.
3. Explain the main decision order before walking the body. Cover meaningful branches, group routine source ranges, and expand helpers only when they hide a relevant decision, handoff, or ownership change.
4. For subtle accesses, inspect the mutations and teardown needed to explain safety. Distinguish relationship protection from object lifetime and track references across unlocks, waits, and callbacks.
5. Explain significant fallbacks, error handling, and asymmetries. Do not classify an unusual choice as a bug without a triggering state and consequence; use history if it resolves a real ambiguity.

Use concrete inputs or an interleaving for difficult branches when helpful. Match “line by line” depth to semantic importance: expand consequential expressions and compress boilerplate. Present the control flow once, with relevant source ranges, rather than repeating it as a checklist, table, and summary. Stop at the function's contract and the dependencies needed to understand it.
