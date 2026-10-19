# Harness versions

Store deliberately selected base harnesses here after choosing an executor.
Do not treat this directory as a native upstream harness tree yet.

Harness2 can edit system prompts, guardrails, memory, tool guidance, subagents,
skills, scripts, and plugins. File names and supported components depend on the
selected substrate. Use its `surface()` schema and validators when materializing
a harness instead of inventing a common file layout.

Keep candidate harnesses, execution evidence, and accumulated experimental lessons
under ignored `runs/`. Promote useful harness versions into this directory after
reviewing their contents.

Sandbox resource limits, network policy, credentials, and task verification logic
must remain outside the editable harness tree.
