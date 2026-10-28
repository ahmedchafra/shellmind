from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCommand:
    executable: str
    arguments: tuple[str, ...]
    raw: str


def _split_segments(command: str) -> list[str]:
    """Split a command line on shell operators that occur outside quotes."""
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0

    while index < len(command):
        char = command[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue

        if char in ("\\", "`", "^"):
            current.append(char)
            escaped = True
            index += 1
            continue

        if quote:
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue

        if char in ("'", '"'):
            quote = char
            current.append(char)
            index += 1
            continue

        if char == "#" and (not current or current[-1].isspace()):
            break

        operator_length = 0
        if command[index : index + 2] in ("&&", "||"):
            operator_length = 2
        elif char in (";", "|"):
            operator_length = 1
        elif char == "&" and not (index > 0 and command[index - 1] in (">", "<")):
            operator_length = 1

        if operator_length:
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            index += operator_length
            continue

        current.append(char)
        index += 1

    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments


def _tokenize(segment: str) -> list[str]:
    """Tokenize common Bash, PowerShell, and CMD quoting without evaluating it."""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False

    for char in segment:
        if escaped:
            current.append(char)
            escaped = False
            continue

        if char == "\\":
            current.append(char)
            continue

        if char in ("`", "^") and quote != "'":
            escaped = True
            continue

        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue

        if char in ("'", '"'):
            quote = char
        elif char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)

    if current:
        tokens.append("".join(current))
    return tokens


def _unwrap(tokens: list[str]) -> list[str]:
    """Remove common command wrappers so policy sees the real executable."""
    if not tokens:
        return tokens

    while tokens:
        executable = tokens[0].lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if executable in ("sudo", "command", "nohup"):
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[1:]
            continue
        if executable == "env":
            tokens = tokens[1:]
            while tokens and (tokens[0].startswith("-") or "=" in tokens[0]):
                tokens = tokens[1:]
            continue
        break

    while tokens and "=" in tokens[0] and not tokens[0].startswith(("/", "\\")):
        name, _, _value = tokens[0].partition("=")
        if not name.replace("_", "").isalnum():
            break
        tokens = tokens[1:]
    return tokens


def _command_substitutions(command: str) -> list[str]:
    """Extract unquoted $(...) bodies for recursive policy inspection."""
    substitutions: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command) - 1:
        char = command[index]
        if quote == "'":
            if char == quote:
                quote = None
            index += 1
            continue
        if quote == '"' and char == '"':
            quote = None
            index += 1
            continue
        if quote is None and char in ("'", '"'):
            quote = char
            index += 1
            continue
        if command[index : index + 2] != "$(":
            index += 1
            continue

        start = index + 2
        depth = 1
        nested_quote: str | None = None
        cursor = start
        while cursor < len(command) and depth:
            nested_char = command[cursor]
            if nested_quote:
                if nested_char == nested_quote:
                    nested_quote = None
            elif nested_char in ("'", '"'):
                nested_quote = nested_char
            elif nested_char == "(":
                depth += 1
            elif nested_char == ")":
                depth -= 1
            cursor += 1
        if depth == 0:
            substitutions.append(command[start : cursor - 1])
            index = cursor
        else:
            break
    return substitutions


def parse_shell_commands(command: str) -> list[ParsedCommand]:
    """Parse executable segments without executing expansions or substitutions."""
    parsed: list[ParsedCommand] = []
    for segment in _split_segments(command):
        tokens = _unwrap(_tokenize(segment))
        if not tokens:
            continue
        executable = tokens[0].lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if executable.endswith(".exe"):
            executable = executable[:-4]
        parsed.append(ParsedCommand(executable, tuple(tokens[1:]), segment))
    for substitution in _command_substitutions(command):
        parsed.extend(parse_shell_commands(substitution))
    return parsed
