"""ShellMind command-line entry point."""

import argparse
import logging
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Optional

from rich.table import Table

from shellmind.assets import get_banner
from shellmind.config import CONFIG_DIR, init_config, load_config
from shellmind.core.engine import ShellMindEngine
from shellmind.core.executor import CommandExecutor
from shellmind.core.sessions import SessionStore
from shellmind.core.workspace import WorkspaceInspector
from shellmind.llm.ollama_client import OllamaClientWrapper
from shellmind.utils.console import console

warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

logger = logging.getLogger(__name__)


def _load_transcriber() -> Optional[Callable[[], Optional[str]]]:
    """Import the optional voice stack only when voice input is requested."""
    try:
        from shellmind.voice.stt import transcribe_from_microphone
    except ImportError:
        return None
    return transcribe_from_microphone


def show_help_and_exit() -> None:
    """Display compact usage information and exit."""
    console.print('Usage: sm "<your request>"', style="info")
    console.print("Run sm alone to start an interactive session.", style="info")
    console.print("\nExamples:", style="info")
    console.print('  sm "find all .log files modified today"', style="dim")
    console.print("  sm inspect", style="dim")
    console.print("  sm sessions", style="dim")
    console.print("  sm resume <session-id>", style="dim")
    console.print('  sm --explain "rm -rf *"', style="dim")
    sys.exit(0)


def _session_database(config: dict) -> Path:
    database = Path(str(config.get("history", {}).get("database", "sessions.db")))
    return database if database.is_absolute() else CONFIG_DIR / database


def show_sessions(config: dict) -> None:
    """List recent persisted sessions without initializing an LLM."""
    with SessionStore(_session_database(config)) as store:
        sessions = store.list_sessions()
    if not sessions:
        console.print("No ShellMind sessions have been recorded yet.", style="warning")
        return

    table = Table(title="ShellMind Sessions")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Updated")
    table.add_column("Turns", justify="right")
    table.add_column("Title")
    table.add_column("Working directory", style="dim")
    for session in sessions:
        table.add_row(
            session.id,
            session.updated_at.replace("T", " ")[:19],
            str(session.turn_count),
            session.title,
            session.cwd,
        )
    console.print(table)
    console.print("Resume with: sm resume <session-id>", style="info")


def show_workspace(config: dict) -> None:
    """Inspect the current workspace without initializing an LLM."""
    workspace_config = config.get("workspace", {})
    inspector = WorkspaceInspector(max_files=int(workspace_config.get("max_files", 3000)))
    console.print(inspector.inspect().summary(), style="info")


def _model_settings(config: dict, model_override: Optional[str] = None) -> tuple[list[str], str]:
    if model_override:
        return [model_override], model_override
    cloud_config = config["llm"].get("cloud_models")
    if isinstance(cloud_config, str):
        cloud_models = [cloud_config]
    elif isinstance(cloud_config, list):
        cloud_models = cloud_config
    else:
        cloud_models = [config["llm"].get("cloud_model", "gpt-oss:120b")]
    return cloud_models, config["llm"]["local_model"]


def _create_llm(
    config: dict,
    mode: Literal["local", "cloud", "auto"],
    model_override: Optional[str] = None,
) -> Optional[OllamaClientWrapper]:
    cloud_models, local_model = _model_settings(config, model_override)
    try:
        return OllamaClientWrapper(
            mode=mode,
            cloud_models=cloud_models,
            local_model=local_model,
        )
    except Exception as exc:
        console.print(f"Failed to initialize LLM: {exc}", style="error")
        console.print(
            "Make sure Ollama is running or OLLAMA_API_KEY is set for cloud.",
            style="info",
        )
        return None


def start_interactive_session(config: dict, resume_id: Optional[str] = None) -> None:
    """Start or resume an interactive agent session."""
    llm = _create_llm(config, config["llm"]["mode"])
    if llm is None:
        return
    engine = ShellMindEngine(llm)
    try:
        executor = CommandExecutor(
            engine,
            config=config,
            interactive=True,
            session_id=resume_id,
        )
    except ValueError as exc:
        console.print(f"Failed to resume session: {exc}", style="error")
        return

    if sys.stdin.isatty():
        console.print(get_banner(), highlight=False)
    console.print("ShellMind: Your AI Terminal Assistant", style="ai")
    console.print(
        "Describe a goal, review the plan, and let ShellMind verify each step.", style="info"
    )
    if executor.session_id:
        console.print(f"Session: {executor.session_id}", style="dim")
    console.print("Commands: help, analyze, inspect, undo, session, voice, quit\n", style="dim")

    try:
        while True:
            try:
                user_input = input("shellmind > ").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\nGoodbye!", style="info")
                break

            if not user_input:
                console.print("Manual mode. Press Enter on an empty line to return.", style="info")
                while True:
                    try:
                        command = input("shell > ").strip()
                    except (KeyboardInterrupt, EOFError):
                        console.print("")
                        break
                    if not command:
                        break
                    result = executor.run_manual_command(command)
                    executor._handle_command_result(result)
                    executor.record_manual_turn(command, result)
                continue

            lowered = user_input.lower()
            if lowered in ("quit", "exit", "q"):
                console.print("Goodbye!", style="info")
                break
            if lowered in ("help", "--help", "h"):
                console.print("\nShellMind interactive commands", style="bold")
                console.print("  <request>             Plan and carry out a task", style="dim")
                console.print('  --explain "<command>" Explain a shell command', style="dim")
                console.print("  analyze               Analyze the previous result", style="dim")
                console.print("  inspect               Show project and Git context", style="dim")
                console.print(
                    "  undo                  Restore the last tracked file change", style="dim"
                )
                console.print("  session               Show this session's ID", style="dim")
                console.print("  voice                 Dictate a request", style="dim")
                console.print("  quit                  Leave the session\n", style="dim")
                continue
            if lowered == "voice":
                transcriber = _load_transcriber()
                if transcriber is None:
                    console.print(
                        "Voice is unavailable. Install the 'voice' optional dependencies.",
                        style="warning",
                    )
                    continue
                console.print("Speak your command. Press Enter when done.", style="info")
                spoken_text = transcriber()
                if not spoken_text:
                    continue
                user_input = spoken_text
            if user_input.startswith("--explain "):
                command = user_input[len("--explain ") :].strip()
                if not command:
                    console.print('Usage: --explain "<command>"', style="warning")
                    continue
                try:
                    console.print(engine.generate_explanation(command), style="info")
                except Exception as exc:
                    console.print(f"Explanation failed: {exc}", style="error")
                continue

            try:
                executor.execute_request(
                    user_input,
                    show_explanations=config["ui"]["show_explanations"],
                )
            except Exception as exc:
                console.print(f"Execution failed: {exc}", style="error")
    finally:
        executor.close()


def main() -> None:
    """Run the ShellMind CLI."""
    parser = argparse.ArgumentParser(prog="sm", description="ShellMind: AI terminal agent")
    parser.add_argument("query", nargs="*", help="Natural-language request")
    parser.add_argument("--explain", action="store_true", help="Explain instead of execute")
    parser.add_argument("--local", action="store_true", help="Force the local model")
    parser.add_argument("--debug", action="store_true", help="Show diagnostic details")
    parser.add_argument("--model", type=str, help="Override the selected model")
    parser.add_argument("--voice", action="store_true", help="Use voice input")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(name)s - %(levelname)s - %(message)s",
    )
    user_input = " ".join(args.query).strip()

    if args.voice:
        transcriber = _load_transcriber()
        if transcriber is None:
            console.print("Voice input is unavailable.", style="error")
            console.print("Install with: pip install shellmind[voice]", style="info")
            return
        console.print("Speak your command. Press Enter when done.", style="info")
        spoken_text = transcriber()
        if not spoken_text:
            console.print("No input received.", style="warning")
            return
        user_input = spoken_text

    init_config()
    config = load_config()

    if user_input.lower() in ("sessions", "history"):
        show_sessions(config)
        return
    if user_input.lower() in ("inspect", "workspace"):
        show_workspace(config)
        return
    if args.query and args.query[0].lower() == "resume":
        if len(args.query) != 2:
            console.print("Usage: sm resume <session-id>", style="warning")
            return
        start_interactive_session(config, resume_id=args.query[1])
        return
    if not user_input:
        start_interactive_session(config)
        return

    mode: Literal["local", "cloud", "auto"] = "local" if args.local else config["llm"]["mode"]
    llm = _create_llm(config, mode, args.model)
    if llm is None:
        return

    engine = ShellMindEngine(llm)
    if args.explain:
        try:
            console.print(engine.generate_explanation(user_input), style="info")
        except Exception as exc:
            console.print(f"Explanation failed: {exc}", style="error")
        return

    executor = CommandExecutor(engine, config=config)
    try:
        if args.debug:
            console.print(
                f"OS={executor.platform_info['os']}, shell={executor.platform_info['shell']}",
                style="info",
            )
            console.print(f"Mode={llm.active_mode}, model={llm.active_model}", style="info")
        executor.execute_request(
            user_input,
            show_explanations=config["ui"]["show_explanations"],
        )
    except Exception as exc:
        console.print(f"Execution failed: {exc}", style="error")
    finally:
        executor.close()


if __name__ == "__main__":
    main()
