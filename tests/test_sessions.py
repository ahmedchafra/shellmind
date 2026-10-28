from pathlib import Path

from shellmind.core.models import SessionTurn
from shellmind.core.sessions import SessionStore


def test_session_store_persists_and_resumes_turns(tmp_path: Path) -> None:
    database = tmp_path / "sessions.db"
    turn = SessionTurn(
        user_query="create a report",
        commands=["echo report"],
        output="report\n",
        exit_code=0,
        cwd=str(tmp_path),
        metadata={"replans": 1},
    )

    with SessionStore(database) as store:
        session_id = store.create_session("ShellMind session", str(tmp_path))
        store.save_turn(session_id, turn)
        assert store.session_exists(session_id)
        assert store.load_turns(session_id) == [turn]
        assert store.latest_turn() == turn
        summary = store.list_sessions()[0]
        assert summary.id == session_id
        assert summary.title == "create a report"
        assert summary.turn_count == 1

    with SessionStore(database) as reopened:
        assert reopened.load_turns(session_id) == [turn]
