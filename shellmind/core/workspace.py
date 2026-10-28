from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceInfo:
    root: Path
    is_git: bool = False
    branch: str | None = None
    dirty: bool = False
    languages: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    suggested_commands: list[str] = field(default_factory=list)
    file_count: int = 0

    def summary(self) -> str:
        details = [f"Workspace: {self.root}"]
        if self.is_git:
            git_state = f"Git branch: {self.branch or '(unknown)'}"
            details.append(f"{git_state}; dirty: {'yes' if self.dirty else 'no'}")
        if self.languages:
            details.append(f"Languages: {', '.join(self.languages)}")
        if self.manifests:
            details.append(f"Project files: {', '.join(self.manifests)}")
        if self.suggested_commands:
            details.append(f"Known commands: {', '.join(self.suggested_commands)}")
        details.append(f"Indexed files: {self.file_count}")
        return "\n".join(details)


class WorkspaceInspector:
    _LANGUAGES = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".rs": "Rust",
        ".go": "Go",
        ".java": "Java",
        ".cs": "C#",
        ".cpp": "C++",
        ".c": "C",
        ".rb": "Ruby",
        ".php": "PHP",
        ".sh": "Shell",
        ".ps1": "PowerShell",
    }
    _MANIFESTS = {
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "Makefile",
        "docker-compose.yml",
        "compose.yaml",
        "Dockerfile",
    }
    _IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}

    def __init__(self, max_files: int = 3000) -> None:
        self.max_files = max_files

    def inspect(self, start: Path | None = None) -> WorkspaceInfo:
        start = (start or Path.cwd()).resolve()
        root = self._find_root(start)
        info = WorkspaceInfo(root=root, is_git=(root / ".git").exists())
        suffixes: set[str] = set()

        limit_reached = False
        for directory, directories, filenames in os.walk(root):
            directories[:] = [name for name in directories if name not in self._IGNORED]
            for filename in filenames:
                if info.file_count >= self.max_files:
                    limit_reached = True
                    break
                path = Path(directory) / filename
                info.file_count += 1
                suffixes.add(path.suffix.lower())
                if path.name in self._MANIFESTS:
                    info.manifests.append(path.relative_to(root).as_posix())
            if limit_reached:
                break

        info.languages = sorted(
            {language for suffix, language in self._LANGUAGES.items() if suffix in suffixes}
        )
        info.manifests = sorted(set(info.manifests))
        info.suggested_commands = self._discover_commands(root, info.manifests)
        if info.is_git:
            info.branch, info.dirty = self._git_state(root)
        return info

    @staticmethod
    def _find_root(start: Path) -> Path:
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return candidate
        return start

    @staticmethod
    def _git_state(root: Path) -> tuple[str | None, bool]:
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            ).stdout
            return branch or None, bool(status.strip())
        except (OSError, subprocess.SubprocessError):
            return None, False

    @staticmethod
    def _discover_commands(root: Path, manifests: list[str]) -> list[str]:
        commands: list[str] = []
        if "pyproject.toml" in manifests:
            commands.extend(["pytest", "python -m build"])
        if "package.json" in manifests:
            try:
                payload = json.loads((root / "package.json").read_text(encoding="utf-8"))
                scripts = payload.get("scripts", {})
                if isinstance(scripts, dict):
                    commands.extend(f"npm run {name}" for name in scripts)
            except (OSError, ValueError):
                pass
        if "Cargo.toml" in manifests:
            commands.extend(["cargo test", "cargo build"])
        if "go.mod" in manifests:
            commands.extend(["go test ./...", "go build ./..."])
        if "Makefile" in manifests:
            commands.append("make")
        return commands[:12]
