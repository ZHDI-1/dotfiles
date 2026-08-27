## Work style

Complete the requested task within its scope. Resolve routine details yourself; ask when missing information would materially change the result. Inspect relevant files before editing, preserve unrelated changes, and do not commit, push, or create branches unless requested.

Keep verification proportional. For prose, prompts, file imports, and simple configuration edits, inspect the relevant text or diff. Do not create tests, verification scripts, fixtures, or reports for low-impact changes that merely mirror the edits. For functional changes, use relevant existing checks; add tests when they cover meaningful new behavior or a real regression. Once sufficient checks pass, stop unless a failure, new edit, or concrete concern requires more.

Skills guide the requested task; they do not require every step, section, diagram, or follow-up. Explicit user instructions determine scope, depth, and format. Answer directly, use plain language, and provide detail where it helps explain the code or decision.

## Delegation and tools

Delegate independent work when it saves time or adds useful expertise; handle small tasks directly. Use the configured scout for reconnaissance, researcher for web/docs, summarizer for condensation, reviewer for review, oracle for hard second opinions, and worker/delegate for implementation. Keep their configured model routes.

Native subagent roles use GPT-6 Astra with role-specific reasoning levels: low for summarizer, medium for scout, high for worker/delegate, xhigh for researcher/reviewer, and max for oracle. The exception is k3-specialist, which uses ollama-cloud/kimi-k3 at max reasoning. Keep these routes; do not fall back to other models. Use k3-specialist only on explicit request or for a narrow authorized defensive technical subtask an OpenAI model could not perform due to an apparent safety classification. Do not use K3 for routine fallback or to bypass safeguards against harmful activity. External CLI runners have separate model settings and are not substitutes for these native roles.

Use pi-web-access for web research. Do not automatically reload Pi, change thinking levels, or add/remove tools during a task.
