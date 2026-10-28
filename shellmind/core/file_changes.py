from __future__ import annotations

import difflib
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from shellmind.core.models import FileChange


@dataclass(frozen=True)
class _FileState:
    digest: str
    content: bytes | None


FileSnapshot = dict[str, _FileState]


@dataclass
class UndoRecord:
    root: Path
    before: FileSnapshot
    changes: list[FileChange]


class FileChangeTracker:
    """Capture bounded workspace snapshots for change display and limited undo."""

    _IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}

    def __init__(
        self,
        root: Path,
        max_files: int = 2000,
        max_file_bytes: int = 512_000,
    ) -> None:
        self.root = root.resolve()
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    def snapshot(self) -> FileSnapshot:
        snapshot: FileSnapshot = {}
        if not self.root.exists() or not self.root.is_dir():
            return snapshot
        for directory, directories, filenames in os.walk(self.root):
            directories[:] = [name for name in directories if name not in self._IGNORED]
            for filename in filenames:
                if len(snapshot) >= self.max_files:
                    return snapshot
                path = Path(directory) / filename
                relative = path.relative_to(self.root)
                try:
                    stat = path.stat()
                    content = path.read_bytes() if stat.st_size <= self.max_file_bytes else None
                    digest = (
                        hashlib.sha256(content).hexdigest()
                        if content is not None
                        else f"large:{stat.st_size}:{stat.st_mtime_ns}"
                    )
                    snapshot[relative.as_posix()] = _FileState(digest, content)
                except OSError:
                    continue
        return snapshot

    def compare(
        self,
        before: FileSnapshot,
        after: FileSnapshot,
    ) -> list[FileChange]:
        changes: list[FileChange] = []
        for path in sorted(before.keys() | after.keys()):
            old = before.get(path)
            new = after.get(path)
            if old is None and new is not None:
                changes.append(FileChange(path, "created", self._diff(path, None, new.content)))
            elif old is not None and new is None:
                changes.append(FileChange(path, "deleted", self._diff(path, old.content, None)))
            elif old is not None and new is not None and old.digest != new.digest:
                changes.append(
                    FileChange(path, "modified", self._diff(path, old.content, new.content))
                )
        return changes

    @staticmethod
    def _decode(content: bytes | None) -> list[str] | None:
        if content is None or b"\x00" in content:
            return None
        try:
            return content.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return None

    def _diff(self, path: str, before: bytes | None, after: bytes | None) -> str:
        old_lines = self._decode(before)
        new_lines = self._decode(after)
        if old_lines is None and before is not None:
            return ""
        if new_lines is None and after is not None:
            return ""
        diff = difflib.unified_diff(
            old_lines or [],
            new_lines or [],
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
        return "".join(diff)[:8000]


class UndoManager:
    def __init__(self) -> None:
        self._records: list[UndoRecord] = []

    @property
    def available(self) -> int:
        return len(self._records)

    def add(
        self,
        root: Path,
        before: FileSnapshot,
        changes: list[FileChange],
    ) -> None:
        restorable = [
            change
            for change in changes
            if change.kind == "created"
            or (change.path in before and before[change.path].content is not None)
        ]
        if restorable:
            self._records.append(UndoRecord(root.resolve(), before, restorable))

    def undo_last(self) -> list[FileChange]:
        if not self._records:
            return []
        record = self._records.pop()
        undone: list[FileChange] = []
        for change in reversed(record.changes):
            target = (record.root / change.path).resolve()
            try:
                target.relative_to(record.root)
            except ValueError:
                continue
            previous = record.before.get(change.path)
            try:
                if change.kind == "created":
                    if target.is_file():
                        target.unlink()
                        undone.append(change)
                elif previous is not None and previous.content is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(previous.content)
                    undone.append(change)
            except OSError:
                continue
        return undone
