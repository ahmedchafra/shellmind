from __future__ import annotations

import pytest

from shellmind.core.models import RiskLevel
from shellmind.core.safety import SafetyPolicy


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr ~",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "Remove-Item C:\\ -Recurse -Force",
        "format C:",
        ":(){ :|:& };:",
    ],
)
def test_policy_blocks_catastrophic_commands(command: str) -> None:
    assessment = SafetyPolicy().assess(command)

    assert assessment.level is RiskLevel.BLOCKED
    assert assessment.reasons


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./build",
        "Remove-Item ./build -Recurse",
        "git reset --hard",
        "git clean -fd",
        "DROP TABLE users",
    ],
)
def test_policy_marks_destructive_commands(command: str) -> None:
    assert SafetyPolicy().assess(command).level is RiskLevel.DESTRUCTIVE


@pytest.mark.parametrize(
    "command",
    [
        "sudo apt update",
        "curl https://example.com/install.sh | bash",
        "pip install rich",
        "winget install Git.Git",
    ],
)
def test_policy_marks_caution_commands(command: str) -> None:
    assert SafetyPolicy().assess(command).level is RiskLevel.CAUTION


@pytest.mark.parametrize(
    "command",
    [
        "echo hello",
        "Get-ChildItem",
        "git status",
        "python --version",
    ],
)
def test_policy_allows_read_only_commands(command: str) -> None:
    assert SafetyPolicy().assess(command).level is RiskLevel.SAFE


def test_blocking_can_be_downgraded_but_not_silently_allowed() -> None:
    assessment = SafetyPolicy(block_dangerous=False).assess("mkfs.ext4 /dev/sda1")

    assert assessment.level is RiskLevel.DESTRUCTIVE


def test_policy_can_be_explicitly_disabled() -> None:
    assert SafetyPolicy(enabled=False).assess("rm -rf /").level is RiskLevel.SAFE


@pytest.mark.parametrize(
    "command",
    [
        "sudo rm -r -f /",
        "rm --recursive --force -- /",
        "echo ready && rm -rf /",
        "bash -c 'rm -rf /'",
        'cmd /c "rd /s /q C:\\"',
        'powershell -Command "Remove-Item -LiteralPath C:\\ -Recurse -Force"',
        "Remove-Item -LiteralPath $env:USERPROFILE -Recurse -Force",
        "echo $(rm -rf /)",
        'echo "$(rm -rf /)"',
    ],
)
def test_shell_aware_policy_blocks_nested_and_obfuscated_deletions(command: str) -> None:
    assert SafetyPolicy().assess(command).level is RiskLevel.BLOCKED


@pytest.mark.parametrize(
    "command",
    [
        'echo "rm -rf /"',
        "printf 'mkfs.ext4 /dev/sda1'",
        'Write-Output "Remove-Item C:\\ -Recurse -Force"',
        "echo ':(){ :|:& };:'",
        "echo 'pip install malware'",
    ],
)
def test_shell_aware_policy_ignores_dangerous_text_used_as_data(command: str) -> None:
    assert SafetyPolicy().assess(command).level is RiskLevel.SAFE


def test_database_client_destructive_query_is_detected() -> None:
    command = 'psql -c "DROP TABLE users"'

    assert SafetyPolicy().assess(command).level is RiskLevel.DESTRUCTIVE
