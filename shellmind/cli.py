# === SHELLMIND CLI - MAIN ENTRY POINT ===
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import argparse
import os
import sys
import logging
from typing import Literal, Optional
from shellmind.llm.ollama_client import OllamaClientWrapper
from shellmind.core.engine import ShellMindEngine
from shellmind.core.executor import CommandExecutor
from shellmind.config import load_config, init_config
from shellmind.assets import get_banner
from shellmind.utils.console import console

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Voice support (optional)
try:
    from shellmind.voice.stt import transcribe_from_microphone
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False


def show_help_and_exit() -> None:
    """Display help message and exit."""
    console.print("💡 Usage: sm \"<your request>\"", style="info")
    console.print("   Or run [bold]sm[/] alone to start an interactive session.", style="info")
    console.print("\n   Examples:", style="info")
    console.print("     sm \"find all .log files modified today\"", style="dim")
    console.print("     sm analyze", style="dim")
    console.print("     sm --explain \"rm -rf *\"", style="dim")
    console.print("     sm                  # Start interactive session", style="dim")
    if VOICE_AVAILABLE:
        console.print("     sm --voice          # Voice input (press Enter when done)", style="dim")
    sys.exit(0)


def start_interactive_session(config: dict) -> None:
    """Start an interactive shell session with AI assistance."""
    mode = config["llm"]["mode"]
    cloud_config = config["llm"].get("cloud_models")
    if isinstance(cloud_config, str):
        cloud_models = [cloud_config]
    elif isinstance(cloud_config, list):
        cloud_models = cloud_config
    else:
        cloud_models = [config["llm"].get("cloud_model", "gpt-oss:120b")]
    local_model = config["llm"]["local_model"]

    try:
        llm = OllamaClientWrapper(
            mode=mode,
            cloud_models=cloud_models,
            local_model=local_model
        )
    except Exception as e:
        console.print(f"❌ Failed to initialize LLM: {e}", style="error")
        console.print("💡 Make sure Ollama is running or OLLAMA_API_KEY is set for cloud.", style="info")
        return

    engine = ShellMindEngine(llm)
    executor = CommandExecutor(engine, config=config, interactive=True)

    if sys.stdin.isatty():
        console.print(get_banner(), highlight=False)

    console.print("🧠 ShellMind: Your AI Terminal Assistant", style="ai")
    console.print("Describe tasks in plain English. Review every command before it runs.\n", style="info")

    console.print("[bold]How to Use[/]", style="bold")
    console.print("• Type natural language: [dim]list large files[/]", style="dim")
    console.print("• Press [dim]Enter[/] for manual commands", style="dim")
    if VOICE_AVAILABLE:
        console.print("• Type [dim]voice[/] for speech input", style="dim")
    console.print("• Explain: [dim]--explain \"tar -czf a.tar.gz dir\"[/]", style="dim")
    console.print("• Analyze last output: [dim]analyze[/]", style="dim")
    console.print("• Exit: [dim]quit, exit, q[/]\n", style="dim")

    console.print("─" * 60 + "\n", style="dim")

    while True:
        try:
            user_input = input("🧠 > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n\n👋 Goodbye!", style="info")
            break

        if not user_input:
            console.print("🛠️ Manual command mode. Press Enter on empty line to return.", style="info")
            while True:
                try:
                    cmd = input("⚡ > ").strip()
                except (KeyboardInterrupt, EOFError):
                    console.print("\n", style="info")
                    break
                if not cmd:
                    break
                try:
                    result = executor._run_single_command(cmd)
                    output_display = result["output"][:executor.max_output_chars]
                    if len(result["output"]) > executor.max_output_chars:
                        output_display += "\n... (truncated)"
                    if result["exit_code"] == 0:
                        console.print("✅ Success:", style="success")
                    else:
                        console.print("❌ Command failed:", style="error")
                    console.print(output_display)

                    executor.context_history.append({
                        "user_query": f"[Manual] {cmd}",
                        "commands": [cmd],
                        "output": result["output"],
                        "exit_code": result["exit_code"]
                    })
                except Exception as e:
                    console.print(f"❌ Error: {e}", style="error")
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("👋 Goodbye!", style="info")
            break

        user_input_lower = user_input.lower()

        # === VOICE COMMAND IN INTERACTIVE MODE ===
        if user_input_lower == "voice":
            if not VOICE_AVAILABLE:
                console.print("🎙️ Voice not available. Install: pip install faster-whisper sounddevice soundfile", style="warning")
            else:
                console.print("🗣️ Speak your command. Press Enter when done.", style="info")
                spoken_text = transcribe_from_microphone()
                if spoken_text:
                    user_input = spoken_text
                else:
                    continue

        if user_input_lower in ("help", "--help", "h"):
            console.print("\n[bold]ShellMind Interactive Commands[/]", style="bold")
            console.print("  --explain \"<cmd>\"   Explain a shell command", style="dim")
            console.print("  analyze              Analyze last command output", style="dim")
            console.print("  (empty Enter)        Manual command mode", style="dim")
            if VOICE_AVAILABLE:
                console.print("  voice                Voice input mode", style="dim")
            console.print("  quit / exit / q      Leave session", style="dim")
            console.print("\n💡 Just type your request in plain English for normal use.", style="info")
            continue

        if user_input_lower in ("analyze", "analyse", "--analyze"):
            if not executor.context_history:
                console.print("⚠️ No previous command to analyze.", style="warning")
                continue
            last = executor.context_history[-1]
            try:
                analysis = engine.analyze_output(last["output"], last["user_query"])
                console.print(f"\n🧠 Analysis of: \"{last['user_query']}\"", style="ai")
                console.print(f"💡 {analysis}", style="info")
            except Exception as e:
                console.print(f"❌ Analysis failed: {e}", style="error")
            continue

        if user_input.startswith("--explain "):
            cmd_to_explain = user_input[len("--explain "):].strip()
            if not cmd_to_explain:
                console.print("⚠️ Usage: --explain \"<command>\"", style="warning")
                continue
            try:
                explanation = engine.generate_explanation(cmd_to_explain)
                console.print(f"💡 {explanation}", style="info")
            except Exception as e:
                console.print(f"❌ Explanation failed: {e}", style="error")
            continue

        show_explanations = config["ui"]["show_explanations"]
        try:
            executor.execute_request(user_input, show_explanations=show_explanations)
        except Exception as e:
            console.print(f"❌ Execution failed: {e}", style="error")


def main() -> None:
    """Main entry point for ShellMind CLI."""
    parser = argparse.ArgumentParser(
        prog="sm",
        description="ShellMind: Your AI terminal assistant"
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Natural language request (e.g., 'list large files')"
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Explain the command instead of running it"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local LLM (skip cloud)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug info (e.g., detected shell)"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Override model (e.g., 'llama3:8b', 'gpt-oss:120b')"
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Use voice input (requires faster-whisper)"
    )

    args = parser.parse_args()
    user_input = " ".join(args.query).strip()

    # === VOICE INPUT ===
    if args.voice:
        if not VOICE_AVAILABLE:
            console.print("🎙️ Voice input not available.", style="error")
            console.print("💡 Install with: pip install faster-whisper sounddevice soundfile", style="info")
            return
        
        console.print("🗣️ Speak your command. Press Enter when done.", style="info")
        user_input = transcribe_from_microphone()
        if not user_input:
            console.print("🔇 No input received. Exiting.", style="warning")
            return

    init_config()
    config = load_config()

    if not user_input:
        start_interactive_session(config)
        return

    # === SINGLE-SHOT MODE ===
    mode: Literal["local", "cloud", "auto"] = "local" if args.local else config["llm"]["mode"]

    if args.model:
        cloud_models = [args.model]
        local_model = args.model
    else:
        cloud_config = config["llm"].get("cloud_models")
        if isinstance(cloud_config, str):
            cloud_models = [cloud_config]
        elif isinstance(cloud_config, list):
            cloud_models = cloud_config
        else:
            cloud_models = [config["llm"].get("cloud_model", "gpt-oss:120b")]
        local_model = config["llm"]["local_model"]

    try:
        llm = OllamaClientWrapper(
            mode=mode,
            cloud_models=cloud_models,
            local_model=local_model
        )
    except Exception as e:
        console.print(f"❌ Failed to initialize LLM: {e}", style="error")
        console.print("💡 Make sure Ollama is running or OLLAMA_API_KEY is set for cloud.", style="info")
        return

    engine = ShellMindEngine(llm)
    executor = CommandExecutor(engine, config=config)

    if args.debug:
        console.print(f"🔍 DEBUG: OS={executor.platform_info['os']}, Shell={executor.platform_info['shell']}", style="info")
        console.print(f"🔍 DEBUG: Mode={llm.active_mode}, Model={llm.active_model}", style="info")

    if args.explain:
        try:
            explanation = engine.generate_explanation(user_input)
            console.print(f"💡 {explanation}", style="info")
        except Exception as e:
            console.print(f"❌ Explanation failed: {e}", style="error")
    else:
        show_explanations = config["ui"]["show_explanations"]
        executor.execute_request(user_input, show_explanations=show_explanations)


if __name__ == "__main__":
    main()