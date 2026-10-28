import json
from pathlib import Path

from shellmind.core.workspace import WorkspaceInspector


def test_workspace_inspector_finds_project_facts(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "build": "vite build"}}),
        encoding="utf-8",
    )
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "index.ts").write_text("export {};\n", encoding="utf-8")

    info = WorkspaceInspector().inspect(nested)

    assert info.root == tmp_path
    assert info.is_git is True
    assert info.languages == ["Python", "TypeScript"]
    assert info.manifests == ["package.json", "pyproject.toml"]
    assert "pytest" in info.suggested_commands
    assert "npm run test" in info.suggested_commands
    assert "Languages: Python, TypeScript" in info.summary()
