---
name: codebase-orient
description: Map a repository or major subsystem when the user asks for architecture, onboarding, or a reading path. Not a prerequisite for ordinary coding, configuration, or file-management tasks.
---

# Codebase Orient

Build a runtime map at the depth requested. Use the [shared guidance](../CODE_LEARNING_EVIDENCE.md).

1. Read the main documentation and manifests that identify what the project runs or provides. Follow relevant launch/build wrappers when their behavior is unclear.
2. Locate entry points, major components, important state owners, and the boundaries between them. Infer architecture from responsibilities and interactions, not directory size or naming alone.
3. Trace one or two representative flows sufficient to connect those components. Include background work or a persistence boundary when central to the system; keep helper functions summarized.
4. Map the relevant source areas to that runtime model. Distinguish generated, vendored, and peripheral code where useful.
5. Give a short reading path if requested or useful. Identify supported build/run/test entry points without executing setup merely for orientation.

Explain the system's purpose first, then its components and interactions. A small object graph can help; label ownership versus control flow accurately. Stop when the reader can locate the important code and understand how the system fits together. Do not turn the map into an inventory or mandatory multi-section report.
