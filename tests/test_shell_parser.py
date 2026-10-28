from __future__ import annotations

from shellmind.core.shell_parser import parse_shell_commands


def test_splits_operators_outside_quotes() -> None:
    commands = parse_shell_commands('echo "a && b" && git status | wc -l')

    assert [command.executable for command in commands] == ["echo", "git", "wc"]
    assert commands[0].arguments == ("a && b",)


def test_unwraps_privilege_and_environment_wrappers() -> None:
    commands = parse_shell_commands("sudo env MODE=test rm --recursive ./build")

    assert commands[0].executable == "rm"
    assert commands[0].arguments == ("--recursive", "./build")


def test_preserves_windows_paths() -> None:
    commands = parse_shell_commands('Remove-Item -LiteralPath "C:\\Program Files\\Demo" -Recurse')

    assert commands[0].executable == "remove-item"
    assert commands[0].arguments[1] == "C:\\Program Files\\Demo"


def test_extracts_command_substitutions() -> None:
    commands = parse_shell_commands("echo $(rm -rf /)")

    assert [command.executable for command in commands] == ["echo", "rm"]


def test_extracts_substitution_inside_double_quotes_but_not_single_quotes() -> None:
    double_quoted = parse_shell_commands('echo "$(rm -rf /)"')
    single_quoted = parse_shell_commands("echo '$(rm -rf /)'")

    assert [command.executable for command in double_quoted] == ["echo", "rm"]
    assert [command.executable for command in single_quoted] == ["echo"]
