---
name: debug-hypothesis
description: Diagnose an observed bug, crash, hang, wrong state, or performance regression using evidence and code-level causes. Not for general explanations, speculative audits, or straightforward configuration requests.
---

# Debug Hypothesis

Start from the symptom, not a favorite suspicious line. Use the [shared guidance](../CODE_LEARNING_EVIDENCE.md).

1. Separate observed and expected behavior. Gather the relevant version, configuration, timing, reproduction conditions, and diagnostics without inventing missing facts.
2. Trace code paths capable of producing the symptom. Find the transition where behavior diverges. For a hang, identify the wait, progress owner, and missing wake condition. For a slowdown, distinguish added work from waiting or contention.
3. Keep only credible competing explanations. For each unresolved candidate, connect the mechanism and preconditions to supporting or conflicting evidence and identify an observation that distinguishes it. Do not manufacture alternatives after the cause is established.
4. Demonstrate a suspected defect as triggering state → incorrect transition → downstream effect → observed symptom. Use exact evaluation for expression bugs or a feasible interleaving for races; distinguish a proven consequence from an unobserved runtime trigger.
5. Choose the smallest useful diagnostic by information gained, cost, and risk. Inspect existing evidence before creating instrumentation or reproducers.

Return the supported cause and fix when requested, or the remaining uncertainty and a focused next check. Separate mitigation from a proper fix when relevant. Do not edit code for diagnosis-only requests, create a test suite merely to support an explanation, or continue investigating after the question is resolved.
