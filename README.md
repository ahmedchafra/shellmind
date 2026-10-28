# ShellMind 🧠💻

**A cloud-first, agentic terminal assistant with automatic local fallback.**

ShellMind turns a natural-language goal into a visible shell execution plan. It explains what each
step is meant to accomplish, asks for approval, executes the command, observes the real result, and
can retry or create a replacement plan when the original approach fails.

It supports Windows PowerShell, Windows CMD, and Linux Bash. By default, ShellMind tries configured
Ollama Cloud models in order and falls back to a local Ollama model when cloud access is missing or
unavailable.

> ShellMind is an alpha project. It can execute real commands and modify real files. Read every plan
> and command before approving it, use version control, and avoid testing it on irreplaceable data.

![ShellMind terminal interface](<Capture d'écran 2026-05-04 155511.png>)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

## Table of contents

- [Why ShellMind](#why-shellmind)
- [How the agent loop works](#how-the-agent-loop-works)
- [Feature guide](#feature-guide)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Detailed walkthrough](#detailed-walkthrough)
- [Command reference](#command-reference)
- [Configuration](#configuration)
- [Data, cloud, and privacy behavior](#data-cloud-and-privacy-behavior)
- [Safety and undo boundaries](#safety-and-undo-boundaries)
- [Architecture](#architecture)
- [Development and testing](#development-and-testing)
- [Troubleshooting](#troubleshooting)
- [What comes next](#what-comes-next)

## Why ShellMind

Traditional natural-language terminal tools often stop after generating a command. ShellMind is
designed around the entire task:

1. Understand the current project and recent session context.
2. Produce a structured, reviewable plan.
3. Classify the risk of every command.
4. Ask the user before each generated step.
5. Execute in the detected native shell.
6. Capture the real output and exit code.
7. Detect file changes caused by the step.
8. Verify whether the expected result was achieved.
9. Retry, replan, stop, or continue based on evidence.
10. Save the task so it can be analyzed or resumed later.

This makes ShellMind useful for multi-step development and system tasks rather than only one-line
command translation.

## How the agent loop works

```text
Natural-language goal
        │
        ▼
Workspace + session context
        │
        ▼
Structured execution plan
        │
        ▼
User approval for each step ───────────────┐
        │                                  │
        ▼                                  │
Shell command execution                   │
        │                                  │
        ├── real output and exit code      │
        ├── observed file changes          │
        └── expected result                │
        │                                  │
        ▼                                  │
Dynamic verification                      │
        │                                  │
        ├── continue ──────────────────────┤
        ├── retry once ────────────────────┘
        ├── create a replacement plan
        └── stop
```

Replanning is bounded by configuration. The default maximum is two replacement plans per request,
which prevents an unsuccessful task from entering an uncontrolled loop.

## Feature guide

### 1. Visual execution plans

ShellMind asks the model for strict plan JSON and validates it before anything can run. Every plan
step contains:

- A stable step ID.
- One executable, single-line shell command.
- The purpose of the command.
- An observable expected result.
- Predicted files that may be created or modified.
- Whether the step appears reasonably reversible.
- A locally calculated risk classification.

The plan is displayed as a Rich table before execution. Replacement plans are displayed the same
way, so a replan is never hidden from the user.

### 2. Dynamic verification and replanning

After a step runs, ShellMind does not assume that exit code `0` means the whole goal was achieved.
The verifier receives:

- The command and its stated purpose.
- The expected result.
- The real exit code.
- Captured stdout and stderr.
- The actual file changes observed around that step.

The verifier can return one of four actions:

| Action | Meaning |
|---|---|
| `continue` | The step produced sufficient evidence of success. |
| `retry` | Try the same step one additional time. |
| `replan` | Replace the remaining work with a new plan based on the failure evidence. |
| `stop` | Stop because continuing is inappropriate or unlikely to help. |

A non-zero exit code deterministically requests replanning without spending another model call just
to discover that the command failed. If replanning is unavailable or unsuccessful, ShellMind falls
back to interactive recovery: retry, edit, ask the model for a suggested fix, continue, or stop.

Relevant configuration:

```yaml
agent:
  planning: true
  verify_steps: true
  auto_replan: true
  max_replans: 2
```

### 3. Predicted and observed file changes

Before approval, the plan shows the file effects predicted by the model. Around each approved step,
ShellMind also takes bounded snapshots of the active working directory and compares them afterward.

It reports:

- Created files.
- Modified files.
- Deleted files.
- Unified diffs for small UTF-8 text files.
- The path and change type for binary or oversized files without loading their full content.

Common dependency and build directories such as `.git`, `.venv`, `node_modules`, `dist`, and
`build` are pruned. File counts and captured file sizes are bounded to keep the feature usable on
larger repositories.

### 4. Limited file undo

Type `undo` during the same ShellMind process to restore the most recent reversible file-change
record. Repeated `undo` commands walk backward through available records.

ShellMind can:

- Restore a small file that was modified.
- Recreate a small file that was deleted.
- Remove a file that was newly created.

ShellMind cannot reliably undo:

- Package installations or removals.
- Database mutations.
- Network requests or remote service changes.
- Process state and environment changes.
- Git commits, resets, rebases, or other repository-history operations.
- Large files whose contents were not captured.
- Changes made after the ShellMind process exits.

Undo is a convenience layer, not a substitute for Git, backups, snapshots, or transactional tools.

### 5. Persistent SQLite sessions

When history is enabled, ShellMind records structured turns in SQLite. A stored turn includes:

- The original request.
- Every executed command.
- Combined command output.
- Final exit code.
- Working directory.
- The final structured plan.
- Verification decisions.
- Observed file-change metadata.
- The number of replans.

Use:

```bash
sm sessions
sm resume <session-id>
```

`sm sessions` lists recent session IDs, update times, turn counts, titles, and working directories
without initializing an LLM. Resuming a session reloads its recent context and restores the last
valid working directory when the interactive shell starts.

Session persistence and undo are deliberately separate: session context survives a restart, while
undo snapshots do not.

### 6. Workspace intelligence

ShellMind inspects the current workspace before planning the first request. It discovers:

- The nearest Git repository root.
- Current Git branch.
- Whether the working tree is dirty.
- Detected programming languages.
- Project manifests such as `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, `Makefile`,
  and Docker/Compose files.
- Useful commands inferred from the project, including Python, npm, Rust, Go, and Make commands.
- A bounded indexed-file count.

Inspect the same information directly, without starting a model:

```bash
sm inspect
```

The resulting summary is included in planning context so commands can match the repository instead
of treating every request as an isolated shell question.

### 7. Stateful interactive shell

Running `sm` without a request starts an interactive session backed by one persistent shell process.
This means shell state survives between approved commands and later requests inside that session:

- `cd` changes the working directory for later steps.
- Environment variables remain available.
- Shell-local state remains available until ShellMind exits.
- Real command exit codes are captured with unique completion markers.
- Commands wait for completion or the configured timeout instead of using a fixed read delay.

Exiting ShellMind does not change the parent terminal's directory or environment.

Programs that require a real terminal/PTY, full-screen interface, interactive password prompt, or
continuous input may not work correctly yet.

### 8. Manual control and approvals

Every generated plan step presents these choices:

| Key | Action |
|---|---|
| `y` | Run the displayed command. |
| `n` | Skip the step. |
| `s` | Stop the request. |
| `e` | Edit the command before running it. |
| `o` | Temporarily enter manual command mode. |

Pressing Enter on an empty interactive prompt also opens manual mode. Manual and edited commands go
through the same local safety policy as generated commands.

### 9. Shell-aware command policy

The policy parses common Bash, PowerShell, and CMD command forms instead of checking only raw
substrings. It inspects chained commands, pipelines, wrappers such as `sudo` and `env`, nested shell
commands, and command substitutions.

Risk levels are:

| Level | Behavior |
|---|---|
| `safe` | Normal approval flow. |
| `caution` | Show a reason, then continue to the normal approval flow. |
| `destructive` | Require an additional explicit confirmation. |
| `blocked` | Do not execute the command. |

Current examples include:

- Blocking filesystem formatting, disk partition commands, fork bombs, and raw writes to block
  devices.
- Blocking recursive deletion of roots, home paths, system roots, drive roots, and network shares.
- Treating general recursive deletion as destructive.
- Warning about privilege escalation, package installation, downloaded content passed into a shell,
  destructive database operations, `git reset --hard`, and forced `git clean`.

The policy reduces obvious risk, but it is not a complete shell sandbox and cannot understand every
possible side effect.

### 10. Strict model output validation

ShellMind does not execute arbitrary prose returned by a model. Command lists, plans, verification
results, and replacement plans use strict JSON shapes. Invalid JSON, unexpected fields, empty
command lists, duplicate step IDs, multiline command strings, and invalid field types fail closed.

Previous output is marked as untrusted data in model prompts so text printed by a command is not
treated as an instruction.

### 11. Cloud-first model selection with local fallback

The default model mode is `cloud`:

1. If `OLLAMA_API_KEY` exists, ShellMind checks configured cloud models in order.
2. It selects the first available cloud model.
3. If that model later fails, it tries the remaining configured cloud models.
4. If cloud initialization or all cloud requests fail, it switches to local Ollama.
5. If no cloud API key exists, it immediately uses the configured local model.

Use `--local` to bypass cloud selection for a single invocation:

```bash
sm --local "explain the largest files in this directory"
```

Use `--model` to override both model selections for one invocation:

```bash
sm --model llama3.1:8b "list stopped services"
```

### 12. Context-aware follow-up requests

Recent structured turns are added to later prompts up to `context.max_history_turns`. Context
includes the request, executed commands, exit code, working directory, and a bounded output snippet.

This supports follow-ups such as:

```text
shellmind > find the three largest log files
shellmind > compress those files into logs.zip
shellmind > verify the archive and tell me its size
```

Long-term history comes from SQLite; the model only receives the configured recent window.

### 13. Output analysis

Use `analyze` to ask the model to interpret the most recent recorded result and suggest concrete next
commands:

```bash
sm analyze
```

In an interactive or resumed session, `analyze` uses that session's latest turn. A new one-shot
analysis can use the latest persisted turn when no in-memory turn exists.

### 14. Command explanations

Explain a command without executing it:

```bash
sm --explain "tar -czf backup.tar.gz project/"
```

Inside interactive mode:

```text
shellmind > --explain "Get-ChildItem -Recurse | Sort-Object Length -Descending"
```

### 15. Optional offline voice input

Voice mode records microphone input until Enter is pressed and transcribes it with
`faster-whisper` using the `base.en` model on CPU with `int8` computation. The temporary WAV file is
removed after transcription.

```bash
sm --voice
```

Or type `voice` inside an interactive session. Voice dependencies are imported lazily, so normal
ShellMind use does not require the audio or Whisper packages.

## Installation

ShellMind is not published on PyPI yet. Install it from source.

### Requirements

- Python 3.10 or newer.
- Ollama installed and available.
- A local Ollama model for fallback.
- Optional `OLLAMA_API_KEY` for Ollama Cloud.
- Windows PowerShell/CMD or Linux Bash.

### 1. Install and start Ollama

Install Ollama from [ollama.com](https://ollama.com), then ensure its local service is running:

```bash
ollama serve
```

Pull the default local fallback model, or configure a model you already have:

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
```

### 2. Install ShellMind

```bash
git clone https://github.com/ahmedchafra/shellmind.git
cd shellmind
python -m pip install -e .
```

For voice support:

```bash
python -m pip install -e ".[voice]"
```

For development tools:

```bash
python -m pip install -e ".[dev]"
```

### 3. Configure cloud access

Linux:

```bash
export OLLAMA_API_KEY="your-key"
```

Windows PowerShell:

```powershell
$env:OLLAMA_API_KEY = "your-key"
```

To make the PowerShell variable persistent for future terminals:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_API_KEY", "your-key", "User")
```

Cloud access is optional. Without the key, ShellMind uses the local fallback model.

## Quick start

```bash
# Start the recommended interactive agent session
sm

# Run a one-shot task
sm "find all .log files modified today"

# Force local inference for this task
sm --local "summarize disk usage by top-level directory"

# Inspect the current project without calling a model
sm inspect

# List and resume saved sessions
sm sessions
sm resume <session-id>

# Analyze the previous result
sm analyze

# Explain without executing
sm --explain "git log --oneline --decorate -10"

# Dictate a request when voice dependencies are installed
sm --voice
```

## Detailed walkthrough

The following is illustrative; exact commands depend on the active operating system and model.

```text
$ sm
ShellMind: Your AI Terminal Assistant
Session: 9f2d9b5a42c1

shellmind > run the tests and fix the simplest failure

Execution Plan: identify and address the simplest test failure
┌────────┬────────────────────┬─────────────────────┬──────────────────┬──────┐
│ Step   │ Command            │ Purpose / expected  │ Files / undo     │ Risk │
├────────┼────────────────────┼─────────────────────┼──────────────────┼──────┤
│ step-1 │ pytest -q          │ Find failing tests  │ No predicted ... │ safe │
└────────┴────────────────────┴─────────────────────┴──────────────────┴──────┘

[[1/1]] pytest -q
Run? (y/n/s/e/o): y
... one test fails ...
❌ Command failed:
⚠️ Verification: Command exited with code 1.

Replanned #1: fix the discovered failure and rerun its test
┌────────┬─────────────────────────────┬──────────────────────┬───────────────┐
│ step-1 │ ... targeted edit command  │ Correct the failure  │ modified: ... │
│ step-2 │ pytest path/to/test.py -q  │ Confirm the fix      │ no changes    │
└────────┴─────────────────────────────┴──────────────────────┴───────────────┘
```

The important behavior is the transition: ShellMind uses the real failure output to replace the
remaining plan instead of blindly continuing with commands designed for a different result.

## Command reference

### Top-level commands

| Command | Description | Starts an LLM? |
|---|---|---|
| `sm` | Start a new interactive session. | Yes |
| `sm "<request>"` | Plan and execute one request. | Yes |
| `sm inspect` | Display workspace and Git information. | No |
| `sm workspace` | Alias for `sm inspect`. | No |
| `sm sessions` | List recent persisted sessions. | No |
| `sm history` | Alias for `sm sessions`. | No |
| `sm resume <id>` | Resume an interactive session. | Yes |
| `sm analyze` | Analyze the latest available command result. | Yes |
| `sm --explain "<command>"` | Explain a command without executing it. | Yes |
| `sm --voice` | Record and transcribe a spoken request. | Yes |

### Options

| Option | Description |
|---|---|
| `-h`, `--help` | Show CLI usage. |
| `--local` | Force local Ollama for this invocation. |
| `--model MODEL` | Override the configured model for this invocation. |
| `--explain` | Explain the supplied command instead of executing it. |
| `--voice` | Capture the request from the microphone. |
| `--debug` | Show logging plus detected OS, shell, active mode, and active model. |

### Interactive commands

| Input | Description |
|---|---|
| Any natural-language request | Build and execute a plan. |
| Empty Enter | Open manual shell-command mode. |
| `analyze` | Analyze the previous result. |
| `inspect` or `workspace` | Show current workspace facts. |
| `undo` | Restore the latest available file-change record. |
| `session` | Show the current persistent session ID. |
| `voice` | Record a spoken request. |
| `--explain <command>` | Explain a command. |
| `help` | Show interactive help. |
| `quit`, `exit`, or `q` | Close ShellMind. |

## Configuration

On first run, ShellMind creates:

```text
~/.shellmind/config.yaml
```

The default configuration is equivalent to:

```yaml
llm:
  mode: cloud
  cloud_models:
    - gpt-oss:120b
    - deepseek-v3.1:671b
    - qwen3-coder:480b
    - kimi-k2:1t
  local_model: llama3.1:8b-instruct-q4_K_M
  timeout: 60

ui:
  show_explanations: false
  confirm_commands: true
  max_output_chars: 2000

context:
  max_history_turns: 5

execution:
  timeout: 60

agent:
  planning: true
  verify_steps: true
  auto_replan: true
  max_replans: 2

history:
  enabled: true
  database: sessions.db

workspace:
  enabled: true
  max_files: 3000

undo:
  enabled: true
  max_files: 2000
  max_file_bytes: 512000

safety:
  enabled: true
  block_dangerous: true
```

### Configuration reference

| Key | Default | Effect |
|---|---:|---|
| `llm.mode` | `cloud` | `cloud`/`auto` try cloud then local; `local` skips cloud. |
| `llm.cloud_models` | Model list | Cloud models tried in order. |
| `llm.local_model` | `llama3.1:8b-instruct-q4_K_M` | Local fallback model. |
| `llm.timeout` | `60` | Reserved model timeout setting; command execution uses `execution.timeout`. |
| `ui.show_explanations` | `false` | Compatibility setting; structured plans already show purpose and expected result. |
| `ui.confirm_commands` | `true` | Reserved UI preference; generated plan steps currently always request approval. |
| `ui.max_output_chars` | `2000` | Maximum result characters printed before display truncation. Full bounded output remains available to the workflow. |
| `context.max_history_turns` | `5` | Recent turns sent back as model context. |
| `execution.timeout` | `60` | Maximum seconds for one command before timeout handling. |
| `agent.planning` | `true` | Use structured plans; disabling it uses the command-list compatibility path. |
| `agent.verify_steps` | `true` | Run post-step verification. |
| `agent.auto_replan` | `true` | Allow replacement plans after unexpected results. |
| `agent.max_replans` | `2` | Maximum replacement plans per request. |
| `history.enabled` | `true` | Persist structured sessions to SQLite. |
| `history.database` | `sessions.db` | Absolute path or filename under `~/.shellmind`. |
| `workspace.enabled` | `true` | Include workspace inspection in planning context. |
| `workspace.max_files` | `3000` | Maximum files indexed per inspection. |
| `undo.enabled` | `true` | Capture bounded file snapshots around commands. |
| `undo.max_files` | `2000` | Maximum files captured per snapshot. |
| `undo.max_file_bytes` | `512000` | Maximum bytes retained for any individual file. |
| `safety.enabled` | `true` | Enable local command risk classification. |
| `safety.block_dangerous` | `true` | Block blocked-class commands; when false they become destructive and need extra confirmation. |

Unknown settings are ignored. User settings are merged into the built-in defaults by section, so a
partial configuration does not need to repeat every value.

## Data, cloud, and privacy behavior

ShellMind is cloud-first by default. When a cloud model is active, the prompt sent to Ollama Cloud
may include:

- The current request.
- Workspace facts such as project type, branch, manifests, and known commands.
- Recent commands, output snippets, exit codes, and working directories.
- Verification evidence and failure output during replanning.

There is currently no cloud privacy filter or automatic secret redaction. Do not send sensitive
repository details, credentials, tokens, private keys, or confidential command output to a cloud
model. Use `--local` or set `llm.mode: local` when the workspace must remain local.

ShellMind itself does not add a telemetry service, but local SQLite history contains task data and
command output. Protect or disable that database when working with sensitive information:

```yaml
history:
  enabled: false
```

Default data locations:

```text
~/.shellmind/config.yaml
~/.shellmind/sessions.db
```

## Safety and undo boundaries

ShellMind combines model-side planning with local validation, explicit approval, and bounded undo,
but none of these mechanisms makes arbitrary shell execution risk-free.

Important boundaries:

- Generated steps require approval, but approved commands run with the current user's permissions.
- A safe classification means no known risky pattern was detected; it does not prove harmlessness.
- Shell syntax is complex, and platform-specific behavior may bypass incomplete static analysis.
- Model output can be wrong even when it matches the required JSON schema.
- File undo does not cover external side effects.
- Persistent session history is not encrypted by ShellMind.
- Cloud prompt filtering and secret redaction are not implemented yet.

Recommended operating practices:

- Work in a Git repository and review `git diff` regularly.
- Commit or stash valuable work before large tasks.
- Read the purpose, command, expected result, file effects, and risk for every step.
- Prefer a disposable test directory for early experimentation.
- Use local mode for sensitive work.
- Keep backups for data that cannot be recreated.

## Architecture

```text
shellmind/
├── cli.py                  # Entry point, modes, commands, and session UI
├── config.py               # User configuration loading and merging
├── defaults.py             # Built-in defaults
├── core/
│   ├── engine.py           # Strict prompts, plans, verification, and replanning
│   ├── executor.py         # Approval and plan/execute/verify/replan orchestration
│   ├── file_changes.py     # Bounded snapshots, diffs, and active-process undo
│   ├── models.py           # Typed plans, results, risks, changes, and turns
│   ├── safety.py           # Local risk classification policy
│   ├── sessions.py         # SQLite session persistence
│   ├── shell_parser.py     # Cross-shell static command parsing
│   └── workspace.py        # Project, language, manifest, command, and Git discovery
├── llm/
│   └── ollama_client.py    # Cloud model sequence and local fallback
├── utils/
│   ├── console.py          # Rich console theme
│   └── platform.py         # Operating-system and shell detection
└── voice/
    └── stt.py              # Optional microphone recording and Whisper transcription
```

The main runtime path is:

```text
cli.py → ShellMindEngine → CommandExecutor → native shell
                         ↘ safety / workspace / file changes / sessions
```

## Development and testing

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the full local quality gate:

```bash
pytest -p no:cacheprovider
black --check shellmind tests
flake8 shellmind tests
mypy --no-incremental shellmind
```

The suite covers strict model response parsing, shell parsing, safety classification, configuration,
cloud/local fallback, persistent shell behavior, real exit codes, planning, verification,
replanning, file diffs, undo, workspace inspection, and SQLite sessions.

GitHub Actions runs the quality gate on Windows and Ubuntu with Python 3.10 and Python 3.13.

## Troubleshooting

### Local model cannot be reached

Ensure Ollama is running:

```bash
ollama serve
ollama list
```

Confirm that the configured `llm.local_model` exists locally.

### Cloud is not selected

Check that `OLLAMA_API_KEY` is available in the same terminal that runs `sm`. Use `--debug` to see
the active backend and model:

```bash
sm --debug "list this directory"
```

If no key is present or cloud model checks fail, local fallback is expected behavior.

### A command times out

Increase:

```yaml
execution:
  timeout: 180
```

Commands that wait for interactive input may still require future PTY support rather than a longer
timeout.

### Voice input is unavailable

Install the optional dependencies:

```bash
python -m pip install -e ".[voice]"
```

Then verify that the operating system allows microphone access and that the default input device is
working.

### A session cannot be resumed

Run `sm sessions` and copy the exact ID. If history was disabled or the SQLite database was moved,
the old session will not be visible from the current configuration.

### Undo reports that nothing is available

Undo only exists for reversible file changes captured during the current process. The command may
not have changed a tracked file, the file may have exceeded the capture limit, or ShellMind may have
been restarted.

### A full-screen or interactive program hangs

ShellMind does not yet provide a PTY-backed adapter. Stop the operation and run programs such as
interactive editors, password-prompting SSH sessions, and full-screen tools directly in the parent
terminal.

## What comes next

The next milestone should strengthen the new agent loop before adding a larger interface:

1. **Dogfood and harden features 1–6.** Exercise real Python, JavaScript, Rust, and mixed repositories;
   improve verification prompts and test failure/replan paths against realistic output.
2. **Add `--dry-run`.** Generate and display a plan without executing or prompting for commands.
3. **Add `--json`.** Produce stable machine-readable plans and results for scripts, CI, and tests.
4. **Add `sm doctor`.** Diagnose Ollama, API keys, cloud models, local models, shell detection,
   configuration, session storage, and optional voice dependencies.
5. **Add PTY-backed execution.** Support commands that need terminal semantics or interactive input.
6. **Prepare a real release.** Finalize packaging, add a changelog, verify clean installation, and
   publish to PyPI.
7. **Implement feature 7: diagnostic workflows.** Add evidence-driven runbooks for test failures,
   build failures, Git problems, processes, services, networking, containers, and dependencies.
8. **Implement feature 8: full-screen TUI.** Present live plan state, output, approvals, diffs,
   verification, and session navigation.
9. **Implement feature 9: teaching mode.** Offer optional shell explanations, alternatives, and
   post-task summaries.
10. **Return to the deferred privacy/security milestone.** Add secret redaction, cloud-context
    controls, and more advanced policy hardening after the requested product features are stable.

See [ROADMAP.md](ROADMAP.md) for the detailed engineering backlog and completion criteria.

## Current limitations

- Alpha quality; not yet published on PyPI.
- Windows and Linux only; macOS is not officially supported.
- No PTY-backed interactive execution.
- No Docker image.
- No dry-run or JSON CLI output yet.
- No diagnostic runbook framework yet.
- No full-screen TUI or teaching mode yet.
- No cloud privacy filter or secret redaction yet.
- Undo is bounded and active-process only.

## License

MIT — use, modify, and share freely.
