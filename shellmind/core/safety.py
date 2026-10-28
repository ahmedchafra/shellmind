from __future__ import annotations

import re
from collections.abc import Iterable

from shellmind.core.models import RiskAssessment, RiskLevel
from shellmind.core.shell_parser import ParsedCommand, parse_shell_commands


class SafetyPolicy:
    """Classify commands from parsed shell tokens without evaluating them."""

    _SHELLS = {"bash", "sh", "zsh", "fish", "pwsh", "powershell", "cmd"}
    _PACKAGE_MANAGERS = {
        "pip",
        "pip3",
        "npm",
        "pnpm",
        "yarn",
        "apt",
        "apt-get",
        "dnf",
        "yum",
        "pacman",
        "brew",
        "winget",
        "choco",
    }
    _DOWNLOADERS = {"curl", "wget", "irm", "invoke-restmethod"}
    _DATABASE_CLIENTS = {"mysql", "mariadb", "psql", "sqlite3", "sqlcmd"}

    def __init__(
        self,
        enabled: bool = True,
        block_dangerous: bool = True,
        shell: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.block_dangerous = block_dangerous
        self.shell = shell

    def assess(self, command: str) -> RiskAssessment:
        if not self.enabled:
            return RiskAssessment(RiskLevel.SAFE)

        findings: list[tuple[RiskLevel, str]] = []
        parsed = parse_shell_commands(command)
        self._assess_parsed(parsed, findings)

        unquoted = self._unquoted_text(command)
        if re.search(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", unquoted):
            findings.append((RiskLevel.BLOCKED, "fork bombs are blocked"))

        executables = {item.executable for item in parsed}
        if executables & self._DOWNLOADERS and executables & self._SHELLS:
            findings.append(
                (RiskLevel.CAUTION, "downloads content and passes it to a command shell")
            )

        if not findings:
            return RiskAssessment(RiskLevel.SAFE)

        level = max((finding[0] for finding in findings), key=self._severity)
        if level is RiskLevel.BLOCKED and not self.block_dangerous:
            level = RiskLevel.DESTRUCTIVE
        reasons = tuple(dict.fromkeys(reason for _level, reason in findings))
        return RiskAssessment(level, reasons)

    def _assess_parsed(
        self,
        commands: Iterable[ParsedCommand],
        findings: list[tuple[RiskLevel, str]],
    ) -> None:
        for command in commands:
            executable = command.executable
            args = list(command.arguments)
            lowered_args = [argument.lower() for argument in args]

            if executable in self._SHELLS:
                nested = self._nested_shell_command(executable, args)
                if nested:
                    self._assess_parsed(parse_shell_commands(nested), findings)

            if self._looks_elevated(command):
                findings.append((RiskLevel.CAUTION, "command requests elevated privileges"))

            if executable.startswith("mkfs") or executable == "wipefs":
                findings.append(
                    (RiskLevel.BLOCKED, "filesystem formatting or signature removal is blocked")
                )
                continue

            if executable in {
                "format",
                "format.com",
                "diskpart",
                "clear-disk",
                "initialize-disk",
            }:
                findings.append(
                    (RiskLevel.BLOCKED, "disk formatting or partition operations are blocked")
                )
                continue

            if executable == "dd" and any(self._is_block_device_output(arg) for arg in args):
                findings.append((RiskLevel.BLOCKED, "raw writes to a block device are blocked"))

            if self._is_delete_command(executable):
                self._assess_delete(executable, args, findings)

            if executable == "git":
                self._assess_git(lowered_args, findings)

            if executable in self._DATABASE_CLIENTS:
                sql = " ".join(lowered_args)
                if re.search(r"\b(?:drop\s+(?:database|schema|table)|truncate\s+table)\b", sql):
                    findings.append(
                        (RiskLevel.DESTRUCTIVE, "database operation can permanently remove data")
                    )
            elif executable == "drop" and lowered_args[:1] in (["database"], ["schema"], ["table"]):
                findings.append(
                    (RiskLevel.DESTRUCTIVE, "database operation can permanently remove data")
                )
            elif executable == "truncate" and lowered_args[:1] == ["table"]:
                findings.append(
                    (RiskLevel.DESTRUCTIVE, "database operation can permanently remove data")
                )

            if executable in self._PACKAGE_MANAGERS and any(
                argument in {"install", "add"} for argument in lowered_args
            ):
                findings.append((RiskLevel.CAUTION, "installs software or dependencies"))

            if executable == "start-process" and self._has_option(args, "verb"):
                verb_value = self._option_value(args, "verb")
                if verb_value and verb_value.lower() == "runas":
                    findings.append((RiskLevel.CAUTION, "command requests elevated privileges"))

    def _assess_delete(
        self,
        executable: str,
        args: list[str],
        findings: list[tuple[RiskLevel, str]],
    ) -> None:
        recursive = self._has_recursive_flag(executable, args)
        force = self._has_force_flag(args)
        targets = self._targets(args)

        if recursive and any(self._is_protected_root(target) for target in targets):
            findings.append(
                (
                    RiskLevel.BLOCKED,
                    "recursive deletion targets a root, home, system, or share directory",
                )
            )
        elif recursive:
            findings.append((RiskLevel.DESTRUCTIVE, "recursive deletion can remove many files"))
        elif force and any(self._is_protected_root(target) for target in targets):
            findings.append(
                (RiskLevel.BLOCKED, "forced deletion targets a protected root directory")
            )

    @staticmethod
    def _is_delete_command(executable: str) -> bool:
        return executable in {"rm", "remove-item", "ri", "rmdir", "rd", "del", "erase"}

    @staticmethod
    def _has_recursive_flag(executable: str, args: list[str]) -> bool:
        for argument in args:
            lowered = argument.lower()
            if lowered in {"--recursive", "-recurse"}:
                return True
            if lowered.startswith("-") and not lowered.startswith("--") and "r" in lowered[1:]:
                return True
            if executable in {"rmdir", "rd", "del", "erase"} and lowered.startswith("/"):
                if "s" in lowered[1:]:
                    return True
        return False

    @staticmethod
    def _has_force_flag(args: list[str]) -> bool:
        for argument in args:
            lowered = argument.lower()
            if lowered in {"--force", "-force", "/q"}:
                return True
            if lowered.startswith("-") and not lowered.startswith("--") and "f" in lowered[1:]:
                return True
        return False

    @staticmethod
    def _targets(args: list[str]) -> list[str]:
        targets: list[str] = []
        index = 0
        while index < len(args):
            argument = args[index]
            lowered = argument.lower()
            if lowered in {"-path", "-literalpath"} and index + 1 < len(args):
                targets.append(args[index + 1])
                index += 2
                continue
            if argument == "--":
                targets.extend(args[index + 1 :])
                break
            is_windows_switch = lowered in {"/s", "/q", "/f", "/a", "/p"}
            if (
                not argument.startswith("-")
                and not is_windows_switch
                or re.match(r"^[A-Za-z]:[/\\]", argument)
            ):
                targets.append(argument)
            index += 1
        return targets

    @staticmethod
    def _is_protected_root(target: str) -> bool:
        normalized = target.strip().strip("'\"")
        lowered = normalized.lower().rstrip()
        if lowered in {"/", "/*", "//", "~", "~/", "$home", "${home}"}:
            return True
        if lowered.startswith(("$home/", "${home}/")):
            return True
        if lowered.startswith(
            ("$env:userprofile", "$env:systemroot", "%userprofile%", "%systemroot%")
        ):
            return True
        if re.fullmatch(r"[a-z]:(?:[/\\]+(?:\*)?)?", lowered):
            return True
        if re.fullmatch(r"[/\\]{2}[^/\\]+[/\\][^/\\]+[/\\]?", normalized):
            return True
        return False

    @staticmethod
    def _is_block_device_output(argument: str) -> bool:
        lowered = argument.lower().replace(" ", "")
        return bool(re.match(r"of=/dev/(?:sd|hd|nvme|mmcblk)", lowered))

    @staticmethod
    def _assess_git(
        lowered_args: list[str],
        findings: list[tuple[RiskLevel, str]],
    ) -> None:
        if not lowered_args:
            return
        if lowered_args[0] == "reset" and "--hard" in lowered_args[1:]:
            findings.append((RiskLevel.DESTRUCTIVE, "Git operation can discard uncommitted work"))
        if lowered_args[0] == "clean" and any(
            option.startswith("-") and "f" in option for option in lowered_args[1:]
        ):
            findings.append((RiskLevel.DESTRUCTIVE, "Git operation can discard uncommitted work"))

    @staticmethod
    def _nested_shell_command(executable: str, args: list[str]) -> str | None:
        lowered = [argument.lower() for argument in args]
        switches = {
            "cmd": {"/c", "/k"},
            "powershell": {"-command", "-c"},
            "pwsh": {"-command", "-c"},
        }
        expected = switches.get(executable, {"-c"})
        for index, argument in enumerate(lowered):
            if argument in expected and index + 1 < len(args):
                return " ".join(args[index + 1 :])
        return None

    @staticmethod
    def _looks_elevated(command: ParsedCommand) -> bool:
        first = command.raw.lstrip().split(maxsplit=1)[0].lower() if command.raw.strip() else ""
        return first in {"sudo", "runas"}

    @staticmethod
    def _has_option(args: list[str], name: str) -> bool:
        normalized = {f"-{name.lower()}", f"/{name.lower()}"}
        return any(argument.lower() in normalized for argument in args)

    @staticmethod
    def _option_value(args: list[str], name: str) -> str | None:
        normalized = {f"-{name.lower()}", f"/{name.lower()}"}
        for index, argument in enumerate(args[:-1]):
            if argument.lower() in normalized:
                return args[index + 1]
        return None

    @staticmethod
    def _unquoted_text(command: str) -> str:
        output: list[str] = []
        quote: str | None = None
        escaped = False
        for char in command:
            if escaped:
                escaped = False
                output.append(" ")
                continue
            if char in ("`", "^"):
                escaped = True
                output.append(" ")
                continue
            if quote:
                if char == quote:
                    quote = None
                output.append(" ")
                continue
            if char in ("'", '"'):
                quote = char
                output.append(" ")
            else:
                output.append(char)
        return "".join(output)

    @staticmethod
    def _severity(level: RiskLevel) -> int:
        return {
            RiskLevel.SAFE: 0,
            RiskLevel.CAUTION: 1,
            RiskLevel.DESTRUCTIVE: 2,
            RiskLevel.BLOCKED: 3,
        }[level]
