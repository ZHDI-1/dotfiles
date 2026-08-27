---
name: deep-dive-mechanism
description: Explain a cross-file concept, protocol, lifecycle, or state machine when the conceptual mechanism is the question. Not for a simple API/configuration question, one function, or symptom-led debugging.
---

# Deep Dive Mechanism

Explain how the mechanism works rather than paraphrasing files. Use the [shared guidance](../CODE_LEARNING_EVIDENCE.md).

1. Establish the problem solved and the scope of the requested explanation.
2. Identify the entities, important state, and who may change it. Distinguish authoritative state from cached, provisional, or derived information when that distinction affects behavior.
3. Derive the relevant invariants and transitions from implementation sites, including failure or recovery paths that maintain them.
4. Connect this model to the main structures and functions. Use a representative operation when it makes their interaction clearer.
5. Explain design trade-offs supported by the code or documentation. Mark inferred intent and unresolved behavior instead of inventing rationale.

Introduce concepts before implementation names. Use diagrams for actual relationships or transitions, not as required decoration. Cover concurrency only as needed to explain the mechanism; a complete safety audit is a separate question. Stop when the requested behavior and its important limits are clear, without expanding every adjacent subsystem.
