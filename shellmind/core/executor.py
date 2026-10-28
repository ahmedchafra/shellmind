# shellmind/core/executor.py
import subprocess
import os
import threading
import time
import logging
import re
import shlex
import uuid
from dataclasses import asdict
from pathlib import Path
from queue import Queue, Empty
from typing import Optional

from rich.panel import Panel
from rich.table import Table

from shellmind.config import CONFIG_DIR
from shellmind.core.engine import ShellMindEngine
from shellmind.core.file_changes import FileChangeTracker, FileSnapshot, UndoManager
from shellmind.core.models import (
    CommandPlan,
    ExecutionResult,
    FileChange,
    PlanStep,
    RiskLevel,
    SessionTurn,
    VerificationResult,
)
from shellmind.core.safety import SafetyPolicy
from shellmind.core.sessions import SessionStore
from shellmind.core.workspace import WorkspaceInfo, WorkspaceInspector
from shellmind.utils.platform import detect_platform
from shellmind.utils.console import console

logger = logging.getLogger(__name__)


class PersistentShell:
    """Manages a single persistent shell process for stateful command execution."""

    def __init__(self, platform_info: dict[str, str], timeout: int = 60) -> None:
        self.platform_info = platform_info
        self.timeout = timeout
        self.process: subprocess.Popen[str]
        self.output_queue: Queue[str] = Queue()
        self.lock = threading.Lock()

        # Determine shell command with optimizations
        if platform_info["os"] == "windows":
            if platform_info["shell"] == "powershell":
                shell_cmd = ["powershell", "-NoProfile", "-NonInteractive"]
            else:  # CMD
                shell_cmd = ["cmd.exe", "/Q"]  # QUIET MODE: suppresses command echo
        else:  # Linux
            shell_cmd = [os.environ.get("SHELL", "/bin/bash")]

        # Start the shell process
        self.process = subprocess.Popen(
            shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # Line buffered
        )

        # Start output reader thread (line-buffered for efficiency)
        def read_output():
            try:
                assert self.process.stdout is not None
                while True:
                    char = self.process.stdout.read(1)
                    if not char:
                        break
                    self.output_queue.put(char)
            except Exception as e:
                logger.error(f"Error reading shell output: {e}")

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        # Consume any startup banner before the first command.
        time.sleep(0.1)
        self._drain_output()

    @property
    def is_alive(self) -> bool:
        return self.process.poll() is None

    def _drain_output(self) -> None:
        while True:
            try:
                self.output_queue.get_nowait()
            except Empty:
                return

    def _completion_command(self, marker: str) -> str:
        shell = self.platform_info["shell"]
        if shell == "powershell":
            return (
                "$smSucceeded = $?; "
                "$smExitCode = if ($smSucceeded) { 0 } "
                "elseif ($LASTEXITCODE -is [int] -and $LASTEXITCODE -ne 0) "
                "{ $LASTEXITCODE } else { 1 }; "
                f'Write-Output "{marker}:$smExitCode"'
            )
        if shell == "cmd":
            return f"echo {marker}:%errorlevel%"
        return f"printf '{marker}:%s\\n' \"$?\""

    def run_command(self, cmd: str, timeout: Optional[int] = None) -> ExecutionResult:
        """Run a command and read until a unique marker reports its exit code."""
        with self.lock:
            if self.process.poll() is not None:
                return ExecutionResult("Shell process exited unexpectedly.", -1)

            marker = f"__SHELLMIND_DONE_{uuid.uuid4().hex}__"
            marker_pattern = re.compile(re.escape(marker) + r":(-?\d+)\r?\n?")
            effective_timeout = timeout if timeout is not None else self.timeout

            assert self.process.stdin is not None
            if self.platform_info["shell"] == "powershell":
                # Avoid reporting a stale native-process exit code for a failed cmdlet.
                self.process.stdin.write("$global:LASTEXITCODE = 0\n")
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.write(self._completion_command(marker) + "\n")
            self.process.stdin.flush()

            output = ""
            deadline = time.monotonic() + effective_timeout
            while time.monotonic() < deadline:
                try:
                    output += self.output_queue.get(timeout=0.1)
                except Empty:
                    if self.process.poll() is not None and self.output_queue.empty():
                        return ExecutionResult(
                            output + "\nShell process exited before reporting completion.",
                            -1,
                        )
                    continue

                match = marker_pattern.search(output)
                if match:
                    clean_output = output[: match.start()] + output[match.end() :]
                    return ExecutionResult(clean_output.rstrip("\r\n"), int(match.group(1)))

            self.close()
            return ExecutionResult(
                f"{output.rstrip()}\nCommand timed out after {effective_timeout} seconds.".lstrip(),
                -1,
                timed_out=True,
            )

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)


class CommandExecutor:
    def __init__(
        self,
        engine: ShellMindEngine,
        config: Optional[dict] = None,
        interactive: bool = False,
        session_store: Optional[SessionStore] = None,
        session_id: Optional[str] = None,
    ) -> None:
        config = config or {}
        self.engine = engine
        self.platform_info = detect_platform()
        self.context_history: list[SessionTurn] = []
        self.max_output_chars = config.get("ui", {}).get("max_output_chars", 800)
        self.max_history_turns = config.get("context", {}).get("max_history_turns", 5)
        self.command_timeout = config.get("execution", {}).get("timeout", 60)
        safety_config = config.get("safety", {}) if config else {}
        self.safety_policy = SafetyPolicy(
            enabled=safety_config.get("enabled", True),
            block_dangerous=safety_config.get("block_dangerous", True),
            shell=self.platform_info["shell"],
        )
        self.interactive = interactive
        self._persistent_shell: Optional[PersistentShell] = None
        agent_config = config.get("agent", {})
        self.planning_enabled = agent_config.get("planning", True)
        self.verify_steps = agent_config.get("verify_steps", True)
        self.auto_replan = agent_config.get("auto_replan", True)
        self.max_replans = int(agent_config.get("max_replans", 2))

        workspace_config = config.get("workspace", {})
        self.workspace_enabled = workspace_config.get("enabled", True)
        self.workspace_inspector = WorkspaceInspector(
            max_files=int(workspace_config.get("max_files", 3000))
        )

        undo_config = config.get("undo", {})
        self.undo_enabled = undo_config.get("enabled", True)
        self.undo_max_files = int(undo_config.get("max_files", 2000))
        self.undo_max_file_bytes = int(undo_config.get("max_file_bytes", 512000))
        self.undo_manager = UndoManager()

        history_config = config.get("history", {})
        self._owns_session_store = False
        self.session_store = session_store
        if self.session_store is None and history_config.get("enabled", False):
            database = Path(str(history_config.get("database", "sessions.db")))
            if not database.is_absolute():
                database = CONFIG_DIR / database
            self.session_store = SessionStore(database)
            self._owns_session_store = True

        self.session_id = session_id
        self._resume_cwd: Optional[str] = None
        if self.session_store is not None:
            if session_id:
                if not self.session_store.session_exists(session_id):
                    raise ValueError(f"Unknown ShellMind session: {session_id}")
                self.context_history = self.session_store.load_turns(session_id)
                if self.context_history:
                    saved_cwd = self.context_history[-1].cwd
                    if saved_cwd and Path(saved_cwd).is_dir():
                        self._resume_cwd = saved_cwd
            else:
                self.session_id = self.session_store.create_session(
                    "ShellMind session", str(Path.cwd())
                )

    def _get_context_string(self, max_turns: Optional[int] = None) -> str:
        """Get recent context history for LLM prompt."""
        history_limit = max_turns if max_turns is not None else self.max_history_turns
        recent = self.context_history[-history_limit:]
        parts = []
        for turn in recent:
            output_lines = turn.output.split("\n")
            snippet = "\n".join(line for line in output_lines[:3] if line.strip())
            if len([line for line in output_lines if line.strip()]) > 3:
                snippet += "\n..."
            parts.append(
                f"User: {turn.user_query}\n"
                f"Commands: {'; '.join(turn.commands)}\n"
                f"Exit code: {turn.exit_code}\n"
                f"Working directory: {turn.cwd or '(unknown)'}\n"
                f"Output: {snippet or '(none)'}"
            )
        context = "\n---\n".join(parts)
        if self.workspace_enabled:
            try:
                workspace = self.workspace_inspector.inspect(
                    Path(self._current_working_directory())
                )
                context = (
                    f"{workspace.summary()}\n---\n{context}" if context else workspace.summary()
                )
            except OSError:
                pass
        return context

    def _current_working_directory(self) -> str:
        if (
            not self.interactive
            or self._persistent_shell is None
            or not self._persistent_shell.is_alive
        ):
            return self._resume_cwd or str(Path.cwd())
        shell = self.platform_info["shell"]
        command = (
            "(Get-Location).Path" if shell == "powershell" else ("cd" if shell == "cmd" else "pwd")
        )
        result = self._persistent_shell.run_command(command, timeout=min(self.command_timeout, 10))
        if result.exit_code == 0 and result.output.strip():
            return result.output.strip().splitlines()[-1]
        return str(Path.cwd())

    def _record_turn(self, turn: SessionTurn) -> None:
        self.context_history.append(turn)
        if len(self.context_history) > 100:
            self.context_history = self.context_history[-100:]
        if self.session_store is not None and self.session_id is not None:
            self.session_store.save_turn(self.session_id, turn)

    def record_manual_turn(self, command: str, result: ExecutionResult) -> None:
        self._record_turn(
            SessionTurn(
                user_query=f"[Manual] {command}",
                commands=[command],
                output=result.output,
                exit_code=result.exit_code,
                cwd=self._current_working_directory(),
            )
        )

    def inspect_workspace(self) -> WorkspaceInfo:
        return self.workspace_inspector.inspect(Path(self._current_working_directory()))

    def show_workspace(self) -> None:
        info = self.inspect_workspace()
        console.print(Panel(info.summary(), title="Workspace", border_style="cyan"))

    def _create_plan(self, user_query: str, context: str) -> CommandPlan:
        if self.planning_enabled and hasattr(self.engine, "generate_plan"):
            return self.engine.generate_plan(user_query, context)
        commands = self.engine.generate_commands(user_query, context)
        return CommandPlan(
            user_query,
            [
                PlanStep(
                    id=f"step-{index}",
                    command=command,
                    purpose="Execute generated command",
                    expected_result="Command exits successfully",
                )
                for index, command in enumerate(commands, start=1)
            ],
        )

    def _show_plan(self, plan: CommandPlan, title: str = "Execution Plan") -> None:
        table = Table(title=f"{title}: {plan.goal}", show_lines=True)
        table.add_column("Step", style="bold cyan", no_wrap=True)
        table.add_column("Command", style="cyan")
        table.add_column("Purpose / expected result")
        table.add_column("Files / undo", style="yellow")
        table.add_column("Risk", no_wrap=True)
        for step in plan.steps:
            assessment = self.safety_policy.assess(step.command)
            effects = (
                "\n".join(step.file_effects) if step.file_effects else "No predicted file changes"
            )
            undo = "undo candidate" if step.reversible else "not guaranteed reversible"
            table.add_row(
                step.id,
                step.command,
                f"{step.purpose}\nExpected: {step.expected_result}",
                f"{effects}\n{undo}",
                assessment.level.value,
            )
        console.print(table)

    def _show_file_changes(self, changes: list[FileChange]) -> None:
        if not changes:
            return
        console.print("\n📝 File changes detected:", style="bold yellow")
        for change in changes:
            console.print(f"  {change.kind:8} {change.path}", style="yellow")
            if change.diff:
                console.print(change.diff, style="dim")

    def _track_command_changes(
        self,
        before_root: Path,
        before: FileSnapshot | None,
    ) -> list[FileChange]:
        if not self.undo_enabled or before is None:
            return []
        tracker = FileChangeTracker(
            before_root,
            max_files=self.undo_max_files,
            max_file_bytes=self.undo_max_file_bytes,
        )
        after = tracker.snapshot()
        changes = tracker.compare(before, after)
        self._show_file_changes(changes)
        self.undo_manager.add(before_root, before, changes)
        return changes

    def undo_last(self) -> list[FileChange]:
        changes = self.undo_manager.undo_last()
        if not changes:
            console.print(
                "⚠️ No reversible file change is available in this session.", style="warning"
            )
            return []
        console.print(f"↩️ Restored {len(changes)} file change(s).", style="success")
        for change in changes:
            console.print(f"  {change.path}", style="dim")
        return changes

    def _handle_command_result(self, result: ExecutionResult) -> bool:
        """Handle command execution result. Returns True to continue, False to stop."""
        output_str = result.output
        output_display = output_str[: self.max_output_chars]
        if len(output_str) > self.max_output_chars:
            output_display += "\n... (truncated)"

        if result.exit_code == 0:
            console.print("✅ Success:", style="success")
        else:
            console.print("❌ Command failed:", style="error")
        console.print(output_display)
        return True

    def _run_single_command(self, cmd: str) -> ExecutionResult:
        """Execute a single shell command, either in persistent or isolated shell."""
        if self.interactive:
            if self._persistent_shell is None or not self._persistent_shell.is_alive:
                self._persistent_shell = PersistentShell(
                    self.platform_info,
                    timeout=self.command_timeout,
                )
                if self._resume_cwd:
                    shell = self.platform_info["shell"]
                    if shell == "powershell":
                        escaped = self._resume_cwd.replace("'", "''")
                        change_directory = f"Set-Location -LiteralPath '{escaped}'"
                    elif shell == "cmd":
                        change_directory = f'cd /d "{self._resume_cwd}"'
                    else:
                        change_directory = f"cd {shlex.quote(self._resume_cwd)}"
                    restored = self._persistent_shell.run_command(change_directory)
                    if restored.exit_code != 0:
                        logger.warning("Could not restore session directory: %s", restored.output)
                    self._resume_cwd = None
            return self._persistent_shell.run_command(cmd)
        else:
            # Use per-command subprocess in single-shot mode
            try:
                if self.platform_info["os"] == "windows":
                    if self.platform_info["shell"] == "powershell":
                        subprocess_result = subprocess.run(
                            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=self.command_timeout,
                        )
                    else:
                        subprocess_result = subprocess.run(
                            cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=self.command_timeout,
                        )
                else:
                    shell_path = os.environ.get("SHELL", "/bin/bash")
                    subprocess_result = subprocess.run(
                        cmd,
                        shell=True,
                        executable=shell_path,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.command_timeout,
                    )
                return ExecutionResult(
                    output=(subprocess_result.stdout or "") + (subprocess_result.stderr or ""),
                    exit_code=subprocess_result.returncode,
                )
            except subprocess.TimeoutExpired:
                return ExecutionResult(
                    f"Command timed out after {self.command_timeout} seconds.",
                    -1,
                    timed_out=True,
                )
            except UnicodeDecodeError:
                return ExecutionResult("Output contains unprintable/binary data.", -1)
            except PermissionError:
                return ExecutionResult("Permission denied. Try running as administrator/root.", -1)
            except FileNotFoundError:
                return ExecutionResult("Command not found. Check if the tool is installed.", -1)
            except OSError as e:
                return ExecutionResult(f"System error: {e}", -1)
            except Exception as e:
                return ExecutionResult(f"Unexpected error: {e}", -1)

    def _authorize_command(self, cmd: str) -> bool:
        """Apply the same safety policy to generated, edited, and manual commands."""
        assessment = self.safety_policy.assess(cmd)
        if assessment.level is RiskLevel.SAFE:
            return True

        reasons = "; ".join(assessment.reasons)
        if assessment.level is RiskLevel.BLOCKED:
            logger.warning("Blocked command: %s (%s)", cmd, reasons)
            console.print(f"⛔ Blocked: {reasons}", style="error")
            return False

        if assessment.level is RiskLevel.CAUTION:
            console.print(f"⚠️ Caution: {reasons}", style="warning")
            return True

        console.print(f"⚠️ Destructive operation: {reasons}", style="warning")
        confirmation = self._get_validated_input(
            "Run this destructive command anyway?",
            ["y", "n"],
        )
        return confirmation == "y"

    def run_manual_command(self, cmd: str) -> ExecutionResult:
        """Run a user-authored command through the same policy as generated commands."""
        if not self._authorize_command(cmd):
            return ExecutionResult(
                "Command was not executed because it was blocked or declined.",
                -1,
                blocked=True,
            )
        return self._run_single_command(cmd)

    def close(self) -> None:
        """Close resources owned by this executor."""
        if self._persistent_shell is not None:
            self._persistent_shell.close()
            self._persistent_shell = None
        if self._owns_session_store and self.session_store is not None:
            self.session_store.close()
            self.session_store = None

    def _get_validated_input(self, prompt: str, options: list[str]) -> str:
        """Get validated user input with retry logic."""
        option_str = "/".join(options)
        while True:
            try:
                choice = input(f"{prompt} ({option_str}): ").strip().lower()
                if choice in options:
                    return choice
                else:
                    console.print(
                        f"⚠️ Invalid input. Please enter one of: {option_str}", style="warning"
                    )
            except KeyboardInterrupt:
                console.print("\n\n⏹️ Execution interrupted by user.", style="error")
                raise InterruptedError("Execution interrupted by user.")
            except EOFError:
                console.print("\n\n⏹️ No input received. Exiting.", style="error")
                raise InterruptedError("No input received.")

    def _offer_failure_recovery(
        self,
        cmd: str,
        result: ExecutionResult,
    ) -> tuple[str, ExecutionResult, bool]:
        """Let the user retry, edit, or ask for help after a real failure."""
        while result.exit_code != 0:
            action = self._get_validated_input(
                "Command failed. Next? retry/edit/fix/continue/stop",
                ["r", "e", "f", "c", "s"],
            )
            if action == "c":
                return cmd, result, True
            if action == "s":
                return cmd, result, False
            if action == "f":
                fix_prompt = (
                    "A shell command failed. Explain the likely cause and suggest a corrected "
                    f"command.\nCommand: {cmd}\nExit code: {result.exit_code}\n"
                    f"Output:\n{result.output}"
                )
                try:
                    suggestion = self.engine.llm.chat(fix_prompt, stream=False)
                    console.print(f"\n💡 Suggestion: {suggestion}", style="info")
                except Exception as exc:
                    console.print(f"❌ Could not generate fix: {exc}", style="error")
                continue
            if action == "e":
                edited = input(f"Edit command [{cmd}]: ").strip()
                cmd = edited or cmd

            if not self._authorize_command(cmd):
                continue
            result = self._run_single_command(cmd)
            self._handle_command_result(result)

        return cmd, result, True

    def execute_request(self, user_query: str, show_explanations: bool = False) -> None:
        """Plan, execute, verify, and adapt a user request."""
        clean_query = user_query.strip().lower()
        if clean_query in ("analyze", "analyse", "--analyze"):
            if not self.context_history and self.session_store is not None:
                latest = self.session_store.latest_turn()
                if latest is not None:
                    self.context_history.append(latest)
            if not self.context_history:
                console.print("⚠️ No previous command to analyze.", style="warning")
                return
            last = self.context_history[-1]
            try:
                analysis = self.engine.analyze_output(last.output, last.user_query)
                console.print(f'\n🧠 Analysis of: "{last.user_query}"', style="ai")
                console.print(f"💡 {analysis}", style="info")
            except Exception as exc:
                console.print(f"❌ Analysis failed: {exc}", style="error")
            return
        if clean_query in ("undo", "--undo"):
            self.undo_last()
            return
        if clean_query in ("inspect", "workspace", "--inspect"):
            self.show_workspace()
            return
        if clean_query in ("session", "session id"):
            console.print(f"Session: {self.session_id or '(not persisted)'}", style="info")
            return

        console.print(
            Panel(
                "[bold]y[/] = run • [bold]n[/] = skip • [bold]s[/] = stop • "
                "[bold]e[/] = edit • [bold]o[/] = run your own",
                title="[?] Action Keys",
                border_style="dim",
            )
        )

        context = self._get_context_string()
        try:
            plan = self._create_plan(user_query, context)
        except Exception as exc:
            console.print(f"❌ Planning failed: {exc}", style="error")
            logger.error("Planning error: %s", exc)
            return
        if not plan.steps:
            console.print("⚠️ The plan contains no executable steps.", style="warning")
            return

        self._show_plan(plan)
        steps = list(plan.steps)
        completed_steps: list[PlanStep] = []
        executed_commands: list[str] = []
        all_outputs: list[str] = []
        verification_log: list[dict[str, object]] = []
        change_log: list[dict[str, str]] = []
        final_exit_code = 0
        replans = 0
        retries: dict[str, int] = {}
        index = 0

        while index < len(steps):
            step = steps[index]
            console.print(f"\n[[bold]{index + 1}/{len(steps)}[/]] {step.command}", style="cyan")
            console.print(f"   {step.purpose}", style="info")
            console.print(f"   Expected: {step.expected_result}", style="dim")
            if step.file_effects:
                console.print("   Predicted files: " + ", ".join(step.file_effects), style="yellow")

            action = self._get_validated_input("Run?", ["y", "n", "s", "e", "o"])
            if action == "s":
                console.print("⏹️ Execution stopped by user.", style="error")
                break
            if action == "n":
                console.print("⏭️ Skipped.", style="warning")
                index += 1
                continue
            if action == "o":
                while True:
                    custom = input("\n🛠️ Enter your command (empty to return): ").strip()
                    if not custom:
                        break
                    result = self.run_manual_command(custom)
                    self._handle_command_result(result)
                    self.record_manual_turn(custom, result)
                continue
            if action == "e":
                edited = input(f"Edit command [{step.command}]: ").strip()
                if edited:
                    step.command = edited
                    console.print(f"→ Updated to: {step.command}", style="info")

            if not self._authorize_command(step.command):
                index += 1
                continue

            cwd = Path(self._current_working_directory()).resolve()
            tracker: FileChangeTracker | None = None
            before: FileSnapshot | None = None
            if self.undo_enabled and cwd.exists() and cwd.is_dir():
                tracker = FileChangeTracker(
                    cwd,
                    max_files=self.undo_max_files,
                    max_file_bytes=self.undo_max_file_bytes,
                )
                before = tracker.snapshot()

            result = self._run_single_command(step.command)
            self._handle_command_result(result)
            changes: list[FileChange] = []
            if tracker is not None and before is not None:
                after = tracker.snapshot()
                changes = tracker.compare(before, after)
                self._show_file_changes(changes)
                self.undo_manager.add(cwd, before, changes)
                change_log.extend({"path": change.path, "kind": change.kind} for change in changes)

            if self.verify_steps and hasattr(self.engine, "verify_step"):
                verification = self.engine.verify_step(step, result, changes)
            else:
                verification = VerificationResult(
                    result.exit_code == 0,
                    (
                        "Command exited successfully."
                        if result.exit_code == 0
                        else f"Command exited with code {result.exit_code}."
                    ),
                    "continue" if result.exit_code == 0 else "replan",
                )
            verification_log.append(asdict(verification))
            icon = "✅" if verification.success else "⚠️"
            console.print(f"{icon} Verification: {verification.summary}", style="info")

            executed_commands.append(step.command)
            all_outputs.append(result.output)
            final_exit_code = result.exit_code

            if verification.action == "stop":
                console.print("⏹️ Verifier requested a stop.", style="warning")
                break
            if verification.action == "retry":
                retries[step.id] = retries.get(step.id, 0) + 1
                if retries[step.id] <= 1:
                    console.print("🔁 Retrying this step after verification.", style="warning")
                    continue

            needs_replan = verification.action == "replan" or not verification.success
            can_replan = (
                needs_replan
                and self.auto_replan
                and replans < self.max_replans
                and hasattr(self.engine, "replan")
            )
            if can_replan:
                try:
                    replacement = self.engine.replan(
                        user_query,
                        plan,
                        completed_steps,
                        step,
                        result,
                        self._get_context_string(),
                    )
                    replans += 1
                    plan = replacement
                    steps = list(replacement.steps)
                    index = 0
                    self._show_plan(replacement, title=f"Replanned #{replans}")
                    continue
                except Exception as exc:
                    console.print(f"⚠️ Replanning failed: {exc}", style="warning")

            if result.exit_code != 0 and not verification.success:
                command, result, should_continue = self._offer_failure_recovery(
                    step.command, result
                )
                step.command = command
                final_exit_code = result.exit_code
                if not should_continue:
                    break

            if verification.success:
                completed_steps.append(step)
            index += 1

        turn = SessionTurn(
            user_query=user_query,
            commands=executed_commands,
            output="\n".join(all_outputs),
            exit_code=final_exit_code,
            cwd=self._current_working_directory(),
            metadata={
                "plan": asdict(plan),
                "verifications": verification_log,
                "file_changes": change_log,
                "replans": replans,
            },
        )
        self._record_turn(turn)

    def _execute_legacy_request(self, user_query: str, show_explanations: bool = False) -> None:
        """Execute a user request with interactive validation."""
        clean_query = user_query.strip().lower()
        if clean_query in ("analyze", "analyse", "--analyze"):
            if not self.context_history:
                console.print("⚠️ No previous command to analyze.", style="warning")
                return
            last = self.context_history[-1]
            try:
                analysis = self.engine.analyze_output(last.output, last.user_query)
                console.print(f'\n🧠 Analysis of: "{last.user_query}"', style="ai")
                console.print(f"💡 {analysis}", style="info")
            except Exception as e:
                console.print(f"❌ Analysis failed: {e}", style="error")
            return

        from rich.panel import Panel

        console.print(
            Panel(
                "[bold]y[/] = run • [bold]n[/] = skip • [bold]s[/] = stop • "
                "[bold]e[/] = edit • [bold]o[/] = run your own",
                title="[?] Action Keys",
                border_style="dim",
            )
        )

        try:
            context = self._get_context_string()
            commands = self.engine.generate_commands(user_query, context)
        except Exception as e:
            console.print(f"❌ Command generation failed: {e}", style="error")
            logger.error(f"Command generation error: {e}")
            return

        if not commands:
            console.print("⚠️ No commands to execute.", style="warning")
            return

        console.print(f"\n🧠 Generated [bold]{len(commands)}[/] command(s):", style="ai")

        explanations = []
        if show_explanations:
            for cmd in commands:
                try:
                    explanations.append(self.engine.generate_explanation(cmd))
                except Exception as e:
                    explanations.append(f"⚠️ Explanation failed: {e}")

        executed_commands = []
        all_outputs = []
        final_exit_code = 0

        i = 0
        while i < len(commands):
            cmd = commands[i]
            console.print(f"\n[[bold]{i+1}/{len(commands)}[/]] {cmd}", style="cyan")

            if show_explanations and i < len(explanations):
                console.print(f"   💡 {explanations[i]}", style="info")

            action = self._get_validated_input("Run?", ["y", "n", "s", "e", "o"])

            if action == "s":
                console.print("⏹️ Execution stopped by user.", style="error")
                break
            elif action == "e":
                edited = input(f"Edit command [{cmd}]: ").strip()
                cmd = edited if edited else cmd
                console.print(f"→ Updated to: {cmd}", style="info")
                if not self._authorize_command(cmd):
                    i += 1
                    continue
                result = self._run_single_command(cmd)
                self._handle_command_result(result)
                if result.exit_code != 0:
                    cmd, result, should_continue = self._offer_failure_recovery(cmd, result)
                    if not should_continue:
                        break
                executed_commands.append(cmd)
                all_outputs.append(result.output)
                final_exit_code = result.exit_code
                i += 1
            elif action == "n":
                console.print("⏭️ Skipped.", style="warning")
                i += 1
            elif action == "o":
                while True:
                    custom_cmd = input("\n🛠️ Enter your command (empty to return): ").strip()
                    if not custom_cmd:
                        break
                    console.print(f"→ Running: {custom_cmd}", style="info")
                    result = self.run_manual_command(custom_cmd)
                    output_str = result.output
                    output_display = output_str[: self.max_output_chars]
                    if len(output_str) > self.max_output_chars:
                        output_display += "\n... (truncated)"
                    if result.exit_code == 0:
                        console.print("✅ Success:", style="success")
                    else:
                        console.print("❌ Command failed:", style="error")
                    console.print(output_display)

                    self.context_history.append(
                        SessionTurn(
                            user_query=f"[Manual] {custom_cmd}",
                            commands=[custom_cmd],
                            output=result.output,
                            exit_code=result.exit_code,
                        )
                    )
                continue
            else:  # 'y'
                if not self._authorize_command(cmd):
                    i += 1
                    continue

                result = self._run_single_command(cmd)
                self._handle_command_result(result)
                if result.exit_code != 0:
                    cmd, result, should_continue = self._offer_failure_recovery(cmd, result)
                    if not should_continue:
                        break
                executed_commands.append(cmd)
                all_outputs.append(result.output)
                final_exit_code = result.exit_code
                i += 1

        self.context_history.append(
            SessionTurn(
                user_query=user_query,
                commands=executed_commands,
                output="\n".join(all_outputs),
                exit_code=final_exit_code,
            )
        )

        # Prevent unbounded history growth
        max_history_size = 100
        if len(self.context_history) > max_history_size:
            self.context_history = self.context_history[-max_history_size:]
            logger.debug(f"Context history trimmed to {max_history_size} items")
