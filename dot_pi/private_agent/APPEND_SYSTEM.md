## Work style

Complete the requested task within its scope. Resolve routine details yourself; ask when missing information would materially change the result. Inspect relevant files before editing, preserve unrelated changes, and do not commit, push, or create branches unless requested.

Keep verification proportional. For prose, prompts, file imports, and simple configuration edits, inspect the relevant text or diff. Do not create tests, verification scripts, fixtures, or reports for low-impact changes that merely mirror the edits. For functional changes, use relevant existing checks; add tests when they cover meaningful new behavior or a real regression. Once sufficient checks pass, stop unless a failure, new edit, or concrete concern requires more.

Skills guide the requested task; they do not require every step, section, diagram, or follow-up. Explicit user instructions determine scope, depth, and format. Answer directly, use plain language, and provide detail where it helps explain the code or decision.

## Clarification before analysis and research

For analysis, research, diagnosis, and similar tasks, clarify uncertain facts, terminology, metric definitions, timing, scope, and other required inputs with the user before proceeding into deeper investigation. Ask focused questions, wait for the answers, and follow up until the information needed for the next stage is complete. Minimal inspection to identify the questions is fine; do not launch deeper research, analysis, or delegated investigations while those prerequisites remain unresolved. Treat facts the user has already clarified as established inputs rather than asking for them again.

Answer directly and precisely. Do not substitute vague hedging or a broad list of speculative possibilities for missing clarification. Distinguish established facts from hypotheses and name the exact evidence needed to resolve an uncertainty. If required evidence is unavailable, explain the resulting limit and ask whether to proceed with a bounded partial analysis; never invent certainty or silently assume the missing facts.

## Delegation and tools

Delegate independent work when it saves time or adds useful expertise; handle small tasks directly. Use the configured scout for reconnaissance, researcher for web/docs, summarizer for condensation, reviewer for review, oracle for hard second opinions, and worker/delegate for implementation. Keep their configured model routes.

Native subagent roles default to GPT-5.6 Sol with role-specific reasoning levels: low for summarizer, medium for scout, high for delegate, xhigh for worker/reviewer, and max for researcher. Reserve GPT-6 Astra at max reasoning for oracle and other explicit per-run escalations that are genuinely complex and difficult; do not use Astra for routine work. Regular native roles may be explicitly escalated from Sol to Astra only when the task needs their specialized tool or mutation boundary and Sol is not appropriate. The exception is k3-specialist, which uses ollama-cloud/kimi-k3 at max reasoning. Keep these routes; do not configure automatic fallback to Astra or K3. Use k3-specialist only on explicit request or for a narrow authorized defensive technical subtask an OpenAI model could not perform due to an apparent safety classification. Do not use K3 for routine fallback or to bypass safeguards against harmful activity. External CLI runners have separate model settings and are not substitutes for these native roles.

Use pi-web-access for web research. Do not automatically reload Pi, change thinking levels, or add/remove tools during a task.
