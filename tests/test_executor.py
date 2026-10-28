from __future__ import annotations

from pathlib import Path

import pytest

from shellmind.core.executor import CommandExecutor, PersistentShell
from shellmind.core.models import (
    CommandPlan,
    ExecutionResult,
    PlanStep,
    VerificationResult,
)
from shellmind.core.sessions import SessionStore
from shellmind.utils.platform import detect_platform


class FakeEngine:
    pass


class SequencedEngine:
    def __init__(self, commands: list[list[str]]) -> None:
        self.commands = iter(commands)

    def generate_commands(self, user_query: str, context: str = "") -> list[str]:
        return next(self.commands)

    def generate_explanation(self, command: str) -> str:
        return "explanation"


def _echo_command(text: str, shell: str) -> str:
    return f'Write-Output "{text}"' if shell == "powershell" else f"echo {text}"


def _failure_command(shell: str) -> str:
    if shell == "powershell":
        return "cmd /c exit 7"
    if shell == "cmd":
        return "cmd /c exit 7"
    return "sh -c 'exit 7'"


def _change_directory_command(path: Path, shell: str) -> str:
    if shell == "powershell":
        return f"Set-Location -LiteralPath '{path}'"
    if shell == "cmd":
        return f'cd /d "{path}"'
    return f"cd '{path}'"


def _working_directory_command(shell: str) -> str:
    if shell == "powershell":
        return "(Get-Location).Path"
    return "cd" if shell == "cmd" else "pwd"


@pytest.mark.integration
def test_persistent_shell_reports_output_and_real_exit_code(tmp_path) -> None:
    platform_info = detect_platform()
    shell = PersistentShell(platform_info, timeout=10)
    try:
        success = shell.run_command(_echo_command("hello-shellmind", platform_info["shell"]))
        failure = shell.run_command(_failure_command(platform_info["shell"]))
    finally:
        shell.close()

    assert "hello-shellmind" in success.output
    assert success.exit_code == 0
    assert failure.exit_code == 7


@pytest.mark.integration
def test_powershell_cmdlet_failure_does_not_reuse_stale_exit_code() -> None:
    platform_info = detect_platform()
    if platform_info["shell"] != "powershell":
        pytest.skip("PowerShell-specific exit-code behavior")

    shell = PersistentShell(platform_info, timeout=10)
    try:
        native_failure = shell.run_command("cmd /c exit 7")
        cmdlet_failure = shell.run_command("Write-Error 'expected failure' -ErrorAction Continue")
    finally:
        shell.close()

    assert native_failure.exit_code == 7
    assert cmdlet_failure.exit_code == 1


@pytest.mark.integration
def test_persistent_shell_preserves_working_directory(tmp_path) -> None:
    platform_info = detect_platform()
    shell = PersistentShell(platform_info, timeout=10)
    try:
        changed = shell.run_command(_change_directory_command(tmp_path, platform_info["shell"]))
        current = shell.run_command(_working_directory_command(platform_info["shell"]))
    finally:
        shell.close()

    assert changed.exit_code == 0
    assert str(tmp_path).lower() in current.output.lower()


@pytest.mark.integration
def test_executor_keeps_one_shell_across_ai_requests(tmp_path, monkeypatch) -> None:
    platform_info = detect_platform()
    engine = SequencedEngine(
        [
            [_change_directory_command(tmp_path, platform_info["shell"])],
            [_working_directory_command(platform_info["shell"])],
        ]
    )
    config = {
        "ui": {"max_output_chars": 1000},
        "context": {"max_history_turns": 5},
        "execution": {"timeout": 10},
        "safety": {"enabled": True, "block_dangerous": True},
    }
    executor = CommandExecutor(engine, config=config, interactive=True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    try:
        executor.execute_request("change directory")
        first_shell = executor._persistent_shell
        executor.execute_request("show current directory")
        second_shell = executor._persistent_shell
    finally:
        executor.close()

    assert first_shell is not None
    assert second_shell is first_shell
    assert str(tmp_path).lower() in executor.context_history[-1].output.lower()


def test_manual_commands_use_safety_policy(monkeypatch) -> None:
    executor = CommandExecutor(FakeEngine())

    def fail_if_called(command: str) -> ExecutionResult:
        raise AssertionError(f"blocked command was executed: {command}")

    monkeypatch.setattr(executor, "_run_single_command", fail_if_called)

    result = executor.run_manual_command("mkfs.ext4 /dev/sda1")

    assert result.blocked is True
    assert result.exit_code == -1


def test_context_respects_configured_history_limit() -> None:
    config = {
        "ui": {"max_output_chars": 100},
        "context": {"max_history_turns": 1},
        "execution": {"timeout": 5},
        "safety": {"enabled": True, "block_dangerous": True},
    }
    executor = CommandExecutor(FakeEngine(), config=config)
    from shellmind.core.models import SessionTurn

    executor.context_history.extend(
        [
            SessionTurn("first", ["echo first"], "first", 0),
            SessionTurn("second", ["echo second"], "second", 0),
        ]
    )

    context = executor._get_context_string()

    assert "second" in context
    assert "first" not in context


class ReplanningEngine:
    def __init__(self) -> None:
        self.replan_calls = 0

    def generate_plan(self, user_query: str, context: str = "") -> CommandPlan:
        return CommandPlan(
            user_query,
            [PlanStep("first", "bad-command", "Try first route", "It succeeds")],
        )

    def verify_step(
        self,
        step: PlanStep,
        result: ExecutionResult,
        changes: object = None,
    ) -> VerificationResult:
        if result.exit_code:
            return VerificationResult(False, "First route failed", "replan")
        return VerificationResult(True, "Alternative route worked", "continue")

    def replan(self, *args: object, **kwargs: object) -> CommandPlan:
        self.replan_calls += 1
        return CommandPlan(
            "use an alternative",
            [PlanStep("alternative", "good-command", "Try fallback", "It succeeds")],
        )


def test_executor_replans_remaining_work_after_verification_failure(monkeypatch) -> None:
    engine = ReplanningEngine()
    executor = CommandExecutor(
        engine,  # type: ignore[arg-type]
        config={
            "agent": {"planning": True, "verify_steps": True, "auto_replan": True},
            "history": {"enabled": False},
            "workspace": {"enabled": False},
            "undo": {"enabled": False},
            "safety": {"enabled": True, "block_dangerous": True},
        },
    )
    results = iter([ExecutionResult("not found", 1), ExecutionResult("done", 0)])
    monkeypatch.setattr(executor, "_run_single_command", lambda command: next(results))
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    executor.execute_request("complete the task")

    assert engine.replan_calls == 1
    assert executor.context_history[-1].commands == ["bad-command", "good-command"]
    assert executor.context_history[-1].exit_code == 0
    assert executor.context_history[-1].metadata["replans"] == 1


def test_resumed_session_restores_saved_working_directory(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "history.db")
    session_id = store.create_session("test", str(tmp_path))
    from shellmind.core.models import SessionTurn

    store.save_turn(
        session_id,
        SessionTurn("previous", ["pwd"], str(tmp_path), 0, cwd=str(tmp_path)),
    )
    executor = CommandExecutor(
        FakeEngine(),  # type: ignore[arg-type]
        config={"workspace": {"enabled": False}},
        interactive=True,
        session_store=store,
        session_id=session_id,
    )
    try:
        assert executor._current_working_directory() == str(tmp_path)
    finally:
        executor.close()
        store.close()
