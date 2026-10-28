from pathlib import Path

from shellmind.core.file_changes import FileChangeTracker, UndoManager


def test_file_changes_are_detected_and_can_be_undone(tmp_path: Path) -> None:
    kept = tmp_path / "kept.txt"
    deleted = tmp_path / "deleted.txt"
    created = tmp_path / "created.txt"
    kept.write_text("before\n", encoding="utf-8")
    deleted.write_text("restore me\n", encoding="utf-8")

    tracker = FileChangeTracker(tmp_path)
    before = tracker.snapshot()
    kept.write_text("after\n", encoding="utf-8")
    deleted.unlink()
    created.write_text("new\n", encoding="utf-8")

    changes = tracker.compare(before, tracker.snapshot())
    assert {(change.path, change.kind) for change in changes} == {
        ("created.txt", "created"),
        ("deleted.txt", "deleted"),
        ("kept.txt", "modified"),
    }
    assert any("-before" in change.diff and "+after" in change.diff for change in changes)

    undo = UndoManager()
    undo.add(tmp_path, before, changes)
    undone = undo.undo_last()

    assert len(undone) == 3
    assert kept.read_text(encoding="utf-8") == "before\n"
    assert deleted.read_text(encoding="utf-8") == "restore me\n"
    assert not created.exists()


def test_large_modified_files_are_not_advertised_as_undoable(tmp_path: Path) -> None:
    large = tmp_path / "large.bin"
    large.write_bytes(b"before")
    tracker = FileChangeTracker(tmp_path, max_file_bytes=1)
    before = tracker.snapshot()
    large.write_bytes(b"after")
    changes = tracker.compare(before, tracker.snapshot())

    undo = UndoManager()
    undo.add(tmp_path, before, changes)

    assert undo.available == 0
