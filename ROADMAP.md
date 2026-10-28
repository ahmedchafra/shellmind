# ShellMind Improvement Roadmap

This roadmap is based on the current codebase: a Python CLI that translates natural language into shell commands through Ollama, asks for confirmation, executes commands, and keeps short in-memory context during a session.

## Current State

ShellMind already has a useful foundation:

- CLI entry point with one-shot and interactive modes.
- Ollama local/cloud fallback wrapper.
- Prompt-based command generation, explanation, and output analysis.
- Basic persistent shell support for interactive sessions.
- Optional voice input through Whisper.
- Config file generation and defaults.

The foundation and first agentic milestone are implemented. ShellMind has executable unit and
shell integration tests, marker-based persistent command completion with real exit codes, strict
JSON parsing, shell-aware risk analysis, persistent sessions, workspace inspection, bounded file
change tracking, and a plan/execute/verify/replan loop. Remaining product areas include PTY support,
broader platform coverage, diagnostic workflows, a full-screen TUI, teaching mode, and the deferred
cloud privacy/security pass.

### Implementation status

Completed in the first foundation slice:

- Added typed execution, session, and risk models.
- Added tests for command parsing, configuration, safety, real exit codes, and state across AI requests.
- Replaced fixed two-second reads with unique completion markers and configurable timeouts.
- Kept the interactive shell alive until the ShellMind session exits.
- Applied safety checks to generated, edited, and manual commands.
- Added destructive-operation confirmation and post-failure recovery choices.
- Added shell-aware parsing for chains, pipelines, wrappers, nested shells, quoted data, and command substitutions.
- Added cloud-first selection tests covering successful cloud use and automatic local fallback.
- Changed model output to strict validated JSON that fails closed.
- Kept cloud-first model selection with automatic local fallback and made voice dependencies lazy.

## Agentic Experience Milestone (Features 1–9)

The numbered feature set is the current product direction. Features 1–6 are implemented in this
milestone; 7–9 and the privacy/security expansion are intentionally deferred.

### 1. Visual execution plans — implemented

- The model returns a strict plan schema instead of an unstructured command list.
- Every step includes its command, purpose, expected result, predicted file effects, reversibility,
  and a locally calculated risk level.
- Plans and replacement plans are rendered as Rich tables before execution.

### 2. Dynamic verification and replanning — implemented

- Every executed step is verified using its real exit code, output, expected result, and observed
  file changes.
- The verifier can continue, retry once, request a new plan, or stop.
- Replanning replaces only the remaining work and is bounded by `agent.max_replans` to prevent
  uncontrolled loops.
- Failed replanning falls back to the existing interactive retry/edit/fix/continue/stop flow.

### 3. File-change previews — implemented

- ShellMind snapshots a bounded view of the active working directory before each approved step.
- It reports created, modified, and deleted paths after execution.
- Text changes include bounded unified diffs; binary and oversized files are reported without
  attempting unsafe or expensive content capture.

### 4. Limited undo — implemented

- `undo` restores the most recent reversible tracked file operation in the active process.
- Small modified/deleted files are restored and newly created files are removed.
- Undo does not claim to reverse external services, package changes, databases, Git history, large
  files, or operations from a previous process.

### 5. Persistent sessions — implemented

- Structured turns are stored in SQLite, including commands, result, working directory, and agent
  metadata.
- `sm sessions` lists recent sessions and `sm resume <session-id>` reloads their context.
- Resumed interactive sessions also restore the last valid working directory when their shell starts.

### 6. Workspace intelligence — implemented

- `sm inspect` detects the project/Git root, branch and dirty state, languages, manifests, indexed
  file count, and useful package/build commands without starting an LLM.
- This workspace summary is included in planning context from the first request onward.
- Large dependency and build directories are pruned during bounded scanning.

### 7. Diagnostic workflows — deferred

Planned: reusable, evidence-driven runbooks for tests, build failures, services, networking, Git,
containers, and dependency problems.

### 8. Full-screen TUI — deferred

Planned: live plan state, streaming output, diffs, approvals, session navigation, and keyboard-driven
controls in a dedicated terminal interface.

### 9. Teaching mode — deferred

Planned: optional explanations of why each step was selected, shell concepts, alternatives, and
post-task summaries without slowing down the default expert workflow.

### Deferred privacy and security expansion

Cloud privacy filtering, secret redaction, explicit cloud-context controls, and more advanced policy
hardening remain planned, but they are not part of the current 1–6 implementation milestone.

## Phase 1: Stabilize Core Behavior

### 1. Add a real test suite

Why: This project executes shell commands. Regressions can become dangerous or confusing quickly.

Todo:

- Add unit tests for command parsing in `ShellMindEngine.generate_commands`.
- Mock the LLM client so tests do not require Ollama.
- Add tests for config loading and user config merging.
- Add safety tests for allowed, blocked, and edge-case commands.
- Add executor tests using harmless commands like `echo`, `pwd`, and invalid commands.

Done when:

- `pytest` runs useful tests locally.
- Tests do not call a real LLM or require network access.
- The dangerous command blocklist has explicit coverage.

### 2. Fix persistent shell completion and exit codes

Why: `PersistentShell.run_command` currently reads output for a fixed two seconds and always returns exit code `0`. Long commands can be truncated, failed commands can appear successful, and later output can leak into the next command.

Todo:

- Append a unique end marker after every command.
- Capture the real exit code after each command.
- Read until the marker appears or a configurable timeout expires.
- Make timeout configurable from `llm.timeout` or a new executor setting.
- Add tests for success, failure, timeout, and multi-command interactive state.

Done when:

- Interactive mode correctly reports failures.
- `cd` persists inside the session.
- Output from one command cannot be mixed with the next command.

### 3. Replace substring safety checks with structured policy

Why: The current safety check catches a few obvious strings but misses many dangerous variants and can also block harmless commands accidentally.

Todo:

- Introduce command risk levels: safe, caution, destructive, blocked.
- Parse commands per shell where practical instead of relying only on lowercase substring search.
- Block destructive filesystem targets such as root, home, system directories, recursive deletes, disk formatting, permission changes over broad paths, and fork bombs.
- Add a second confirmation for destructive-but-allowed commands.
- Apply validation to edited commands and manual override commands too, not only generated commands.
- Make the policy configurable but safe by default.

Done when:

- Safety behavior is predictable and tested.
- Manual commands follow the same safety path as generated commands.
- Users get clear reasons when a command is blocked.

## Phase 2: Improve CLI Design and User Experience

### 4. Separate CLI input/output from execution logic

Why: `cli.py` and `executor.py` currently mix prompting, printing, command running, history, safety, and LLM recovery. This makes testing and maintenance harder.

Todo:

- Create small interfaces for prompting, output rendering, command execution, and history.
- Keep `CommandExecutor` focused on execution workflow.
- Move Rich panels and console formatting into a UI/helper module.
- Replace `exit(0)` inside library code with controlled return values or exceptions.

Done when:

- Executor behavior can be tested without interactive stdin.
- CLI remains thin and easy to reason about.

### 5. Improve terminal compatibility and documentation quality

Why: The source files are valid UTF-8, but Windows terminal encodings and fonts can still render Unicode inconsistently. Documentation must also distinguish implemented behavior from planned behavior.

Todo:

- Add explicit UTF-8 handling for CMD and PowerShell output.
- Test emoji output and provide a plain ASCII mode.
- Decide whether to keep emoji-heavy output or offer a plain ASCII mode.
- Add accurate setup instructions for Windows PowerShell, CMD, and Linux.
- Document privacy behavior for cloud vs local modes clearly.

Done when:

- README renders cleanly on GitHub and in terminals.
- `sm --help` and interactive help are readable on Windows and Linux.

### 6. Add non-interactive and dry-run modes

Why: The tool is useful for humans, but automation, demos, and testing need predictable output.

Todo:

- Add `--dry-run` to generate commands without asking to execute.
- Add `--yes` only for explicitly safe commands.
- Add `--json` for scripts and tests.
- Add `--no-color` for CI and simple terminals.

Done when:

- Users can inspect generated commands without prompts.
- CI can exercise the CLI without stdin hacks.

## Phase 3: Strengthen LLM and Prompt Reliability

### 7. Require structured LLM output

Why: The engine currently splits raw LLM text by newline. If the model adds commentary, markdown, numbering, or explanations, ShellMind may treat that as commands.

Todo:

- Ask the model for strict JSON, for example `{ "commands": [...] }`.
- Validate the JSON schema before execution.
- Reject responses with unsupported fields or empty commands.
- Keep markdown cleanup only as a fallback.

Done when:

- Command generation fails closed when the model returns unexpected text.
- Tests cover markdown, numbered lists, comments, empty output, and valid JSON.

### 8. Improve context management

Why: Context is currently in memory only and uses the first few output lines, which may miss important errors or IDs.

Todo:

- Store context as structured records: query, commands, exit codes, stdout, stderr, cwd, timestamp.
- Summarize long outputs before sending them back to the LLM.
- Respect configurable history limits.
- Add optional persistent session history using SQLite.

Done when:

- Follow-up tasks reliably reference earlier files, paths, errors, and command results.
- Users can opt into persistent history.

### 9. Make backend selection transparent

Why: Cloud/local fallback is useful, but users need to know what backend is active and why fallback happened.

Todo:

- Add `sm doctor` to check Ollama local server, cloud API key, configured models, microphone dependencies, and shell detection.
- Add clear backend status in debug mode.
- Avoid logging noisy model failures at warning level during normal fallback.
- Keep the cloud-first default explicit and show users when context will leave the machine.

Done when:

- Users can diagnose setup issues without reading stack traces.
- Privacy expectations match runtime behavior.

## Phase 4: Packaging, Compatibility, and Release

### 10. Prepare for PyPI release

Why: The README says the project is not on PyPI yet, and `pyproject.toml` is missing several release-quality fields.

Todo:

- Add authors, license metadata, README content type, project URLs, classifiers, and Python version requirements.
- Add build and publish workflow.
- Verify package data includes banner assets.
- Add a changelog.

Done when:

- `python -m build` creates installable artifacts.
- A fresh virtual environment can install and run `sm`.

### 11. Add CI quality gates

Why: The project already lists pytest, mypy, black, and flake8, but there is no visible CI workflow.

Todo:

- Add GitHub Actions for Windows and Linux.
- Run formatting checks, linting, type checks, and tests.
- Cache dependencies.
- Add a minimal integration smoke test for `sm --help` or `sm --dry-run`.

Done when:

- Pull requests show clear pass/fail quality checks.
- Windows and Linux compatibility is continuously checked.

### 12. Expand platform support deliberately

Why: macOS is listed as unsupported, but much of the Linux path may work with careful shell detection.

Todo:

- Add macOS detection as `darwin`.
- Detect bash, zsh, fish, PowerShell Core, and CMD more explicitly.
- Document shell-specific limitations.
- Add shell-specific prompt rules and tests.

Done when:

- macOS support is either tested and documented, or explicitly blocked with a helpful message.

## Phase 5: Larger Product Enhancements

### 13. Add a command preview/risk UI

Why: Users should understand what will happen before running generated commands.

Todo:

- Show command, explanation, detected risk level, affected paths, and estimated reversibility.
- Highlight writes, deletes, network calls, privilege escalation, and package installs.
- Offer safer alternatives when possible.

Done when:

- Users can make informed decisions without asking for a separate explanation.

### 14. Add tool modes for common workflows

Why: ShellMind can become more reliable by specializing common tasks instead of relying only on open-ended prompting.

Todo:

- Add modes such as files, git, network, packages, processes, and diagnostics.
- Use deterministic helpers for simple tasks where possible.
- Let the LLM plan while trusted code handles known operations.

Done when:

- Common workflows are faster, safer, and more predictable.

### 15. Improve voice support

Why: Voice is optional but currently basic and CPU-only.

Todo:

- Make Whisper model, device, and compute type configurable.
- Support push-to-talk or fixed-duration recording.
- Show clear installation and microphone troubleshooting in `sm doctor`.
- Clean up temporary files in `finally` blocks.

Done when:

- Voice input behaves predictably and reports actionable errors.

## Suggested Priority Order

1. Harden and dogfood features 1–6 with real repositories and multi-step tasks.
2. Add `--dry-run`, `--json`, and `sm doctor` for automation and setup diagnostics.
3. Add PTY-backed shell adapters and broader platform tests.
4. Prepare the PyPI release and enable the new CI workflow.
5. Implement feature 7 diagnostic workflows, then feature 8 TUI and feature 9 teaching mode.
6. Return to the explicitly deferred privacy filtering, secret redaction, and security expansion.

## Notes From Current Analysis

- The initial suite now covers strict command parsing, configuration, safety, real shell exit codes, and state across requests.
- UTF-8 source text is valid; apparent mojibake during the review came from PowerShell's default file decoding.
- Marker-based completion, real exit codes, persistent interactive state, and configurable timeouts are implemented.
- Generated, edited, and manual commands now share one safety policy.
- `safety.enabled`, `safety.block_dangerous`, `context.max_history_turns`, and `execution.timeout` are wired into runtime behavior.
- Command generation now fails closed unless the model returns the required JSON shape.
- Structured plans, verification, bounded replanning, file diffs, limited undo, SQLite sessions,
  session resume, and workspace intelligence are implemented and covered by tests.
