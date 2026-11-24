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

# KFS / Ceph operations

| Need | Invoke | Boundary |
| --- | --- | --- |
| Pull and interpret monitoring data for a KFS / Ceph incident | `$kfs-ceph-metrics` | Off-cluster, read-only HTTP: perflog, Prometheus, Falcon, kfs-platform |
| Run anything on a production cluster: ceph CLI, admin socket, log pulls, any state change | `$ceph-prod-ops` | Risk tiers: verified read-only ops run directly through `prod/ro.sh`; mutations and wrapper core changes need a double independent review and user approval |

The two skills split at the cluster boundary: querying monitoring endpoints is
free, while touching a cluster host goes through the `$ceph-prod-ops` gate.

# Company docs

| Need | Invoke | Boundary |
| --- | --- | --- |
| Read, create or update a docs.corp.kuaishou.com doc, or fetch its images | `$kuaishou-docs` | Direct takumi API with the user's mfcli login token; writes publish, so only on the user's explicit request |

`$kuaishou-docs` is hidden from mfcli on purpose: it bypasses mfcli and uses its login token directly. mfcli
reads `~/.agents/skills` and `~/.claude/skills`, so hide such skills by name in mfcli's global config
`~/.codeflicker/config.json` → `"skills": {"disabled": [...]}` (the same key mfcli's own skill toggle writes;
`mfcli config set` rejects it). Check with `mfcli skill list --json` (status `off`).
