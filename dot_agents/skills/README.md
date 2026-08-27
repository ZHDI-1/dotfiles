# Code-learning toolkit

Use these skills for requested code analysis or learning, not as a prerequisite
for routine coding or configuration work. Choose the best match and apply the
steps needed for the question. The user's request determines depth and format.

| Question | Invoke | Boundary |
| --- | --- | --- |
| “What is this unfamiliar repository or major subsystem?” | `$codebase-orient` | Broad runtime map and reading path, not one-function depth |
| “What happens to this one operation from start to finish?” | `$trace-codepath` | One logical operation, including deferred work and retries |
| “How does this concept work across files?” | `$deep-dive-mechanism` | Cross-file model, invariants, lifecycle, failure, and trade-offs |
| “What is really encoded in this function?” | `$function-forensics` | One dense function or tightly bounded implementation cluster |
| “What proves this access and lifetime are safe?” | `$concurrency-lifetime-audit` | Locks, RCU, atomics, ownership, teardown, races, and deadlocks |
| “What code mechanism could cause this symptom?” | `$debug-hypothesis` | Symptom-led, ranked hypotheses and decisive verification |

Overlap rule: start with `$debug-hypothesis` for an observed failure and with
`$concurrency-lifetime-audit` when synchronization or lifetime is itself the
question. Otherwise choose by target size: repository, operation, mechanism, or
function.

Example invocations:

```text
$codebase-orient Map this repository before I make changes.
$trace-codepath Trace one metadata request through retry and completion.
$deep-dive-mechanism Explain capability revocation and recovery across files.
$function-forensics Analyze __choose_mds and its important consumer.
$concurrency-lifetime-audit Prove whether cap->session is valid under this lock.
$debug-hypothesis Determine whether this macro can cause the observed bad state.
```

`CODE_LEARNING_EVIDENCE.md` is shared guidance for the six skills, not an
invocable skill, mandatory report template, or task router.
