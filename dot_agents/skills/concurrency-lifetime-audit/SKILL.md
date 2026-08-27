---
name: concurrency-lifetime-audit
description: Audit synchronization and object lifetime when safety, races, references, teardown, or deadlocks are the explicit question. Not a mandatory audit for every code explanation or change.
---

# Concurrency & Lifetime Audit

Organize the audit around the accesses and safety properties in question. Use the [shared guidance](../CODE_LEARNING_EVIDENCE.md).

1. Bound the objects, fields, and execution contexts. Establish which contexts can overlap and what serialization is actually present.
2. Trace creation, publication, ownership, reference acquisition/transfer/release, and destruction for the relevant objects. Include error, cancellation, and asynchronous users. A container reference does not automatically keep every nested pointer alive.
3. Identify what each lock, RCU domain, atomic operation, or external rule protects. Check the corresponding readers, writers, and teardown sites. Separate indivisible access from memory ordering and compound invariants.
4. For important dereferences, explain the chain from a stable root to relationship protection, nested-object lifetime, access, and release. Track pointers escaping an unlock, RCU exit, wait, or callback. RCU read-side validity does not itself establish post-unlock lifetime.
5. Check relevant lock nesting, re-entry, blocking operations, and progress dependencies. Support a lock-order edge with an acquisition path; support a deadlock claim with a feasible cycle or re-entry, not a list of locks.
6. Use a feasible interleaving to expose a suspected race or explain a non-obvious protection. State the exact reference, ordering edge, lock, or grace period that prevents the harmful schedule.

Report supported safety arguments, concrete defects, and unresolved gaps. Use ownership tables or lock graphs when they make the relationships easier to compare. Recommend a focused runtime diagnostic only for a material gap that static evidence cannot settle. Do not automatically build stress tests or run sanitizers for a read-only audit.
