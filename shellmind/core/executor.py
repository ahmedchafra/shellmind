# shellmind/core/executor.py
import subprocess
import os
import threading
import time
import logging
import shlex
from queue import Queue, Empty
from typing import List, Dict, Optional
from shellmind.core.engine import ShellMindEngine
from shellmind.utils.platform import detect_platform
from shellmind.utils.console import console

logger = logging.getLogger(__name__)

class PersistentShell:
    """Manages a single persistent shell process for stateful command execution."""
    def __init__(self, platform_info):
        self.platform_info = platform_info
        self.process = None
        self.output_queue = Queue()
        self.lock = threading.Lock()

        # Determine shell command with optimizations
        if platform_info["os"] == "windows":
            if platform_info["shell"] == "powershell":
                shell_cmd = ["powershell", "-NoProfile", "-NonInteractive"]
            else:  # CMD
                shell_cmd = ["cmd.exe", "/Q"]  # QUIET MODE: suppresses command echo
        else:  # Linux
            shell_cmd = [os.environ.get("SHELL", "/bin/bash")]

        # Start the shell process
        self.process = subprocess.Popen(
            shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1  # Line buffered
        )

        # Start output reader thread (line-buffered for efficiency)
        def read_output():
            try:
                while True:
                    char = self.process.stdout.read(1)
                    if not char:
                        break
                    self.output_queue.put(char)
            except Exception as e:
                logger.error(f"Error reading shell output: {e}")
        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        # Consume initial banner (Windows CMD only)
        if platform_info["os"] == "windows" and platform_info["shell"] == "cmd":
            time.sleep(0.2)
            while not self.output_queue.empty():
                try:
                    self.output_queue.get_nowait()
                except Empty:
                    break

    def run_command(self, cmd: str, timeout: int = 2) -> Dict[str, object]:
        """Run command with short timeout for responsiveness."""
        with self.lock:
            if self.process.poll() is not None:
                return {"output": "Shell process exited unexpectedly.", "exit_code": -1}

            # Send command
            self.process.stdin.write(cmd + "\n")
            self.process.stdin.flush()

            # Read output for up to `timeout` seconds
            output = ""
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    line = self.output_queue.get(timeout=0.1)
                    output += line
                except Empty:
                    continue
            return {"output": output, "exit_code": 0}

    def close(self):
        if self.process:
            self.process.stdin.close()
            self.process.terminate()
            self.process.wait()

class CommandExecutor:
    def __init__(self, engine: ShellMindEngine, config: Optional[dict] = None, interactive: bool = False) -> None:
        self.engine = engine
        self.platform_info = detect_platform()
        self.context_history: List[Dict[str, object]] = []
        self.max_output_chars = config["ui"]["max_output_chars"] if config else 800
        self.interactive = interactive
        self._persistent_shell: Optional[PersistentShell] = None

    def _get_context_string(self, max_turns: int = 5) -> str:
        """Get recent context history for LLM prompt."""
        if not self.context_history:
            return ""
        recent = self.context_history[-max_turns:]
        parts = []
        for turn in recent:
            output_lines = (turn["output"] or "").split("\n")
            snippet = "\n".join(line for line in output_lines[:3] if line.strip())
            if len([l for l in output_lines if l.strip()]) > 3:
                snippet += "\n..."
            parts.append(
                f"User: {turn['user_query']}\n"
                f"Commands: {'; '.join(turn['commands'])}\n"
                f"Output: {snippet or '(none)'}"
            )
        return "\n---\n".join(parts)

    def _handle_command_result(self, result: Dict[str, object]) -> bool:
        """Handle command execution result. Returns True to continue, False to stop."""
        output_str = str(result.get("output", ""))
        output_display = output_str[:self.max_output_chars]
        if len(output_str) > self.max_output_chars:
            output_display += "\n... (truncated)"
        
        exit_code = result.get("exit_code", 0)
        if exit_code == 0:
            console.print("✅ Success:", style="success")
        else:
            console.print("❌ Command failed:", style="error")
        console.print(output_display)
        return True

    def _run_single_command(self, cmd: str) -> Dict[str, object]:
        """Execute a single shell command, either in persistent or isolated shell."""
        if self.interactive:
            if self._persistent_shell is None:
                self._persistent_shell = PersistentShell(self.platform_info)
            result = self._persistent_shell.run_command(cmd)
            return result
        else:
            # Use per-command subprocess in single-shot mode
            try:
                if self.platform_info["os"] == "windows":
                    if self.platform_info["shell"] == "powershell":
                        result = subprocess.run(
                            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=60
                        )
                    else:
                        result = subprocess.run(
                            cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=60
                        )
                else:
                    shell_path = os.environ.get("SHELL", "/bin/bash")
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        executable=shell_path,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=60
                    )
                return {
                    "output": (result.stdout or "") + (result.stderr or ""),
                    "exit_code": result.returncode
                }
            except subprocess.TimeoutExpired:
                return {"output": "Command timed out after 60 seconds.", "exit_code": -1}
            except UnicodeDecodeError:
                return {"output": "Output contains unprintable/binary data.", "exit_code": -1}
            except PermissionError:
                return {"output": "Permission denied. Try running as administrator/root.", "exit_code": -1}
            except FileNotFoundError:
                return {"output": "Command not found. Check if the tool is installed.", "exit_code": -1}
            except OSError as e:
                return {"output": f"System error: {e}", "exit_code": -1}
            except Exception as e:
                return {"output": f"Unexpected error: {e}", "exit_code": -1}

    def _validate_command(self, cmd: str) -> bool:
        """Validate command for basic security issues (blocking dangerous patterns)."""
        dangerous_patterns = [
            "rm -rf",
            "rm -r /",
            "dd if=",
            "mkfs",
            ":() { : | : & } ;",  # Fork bomb
        ]
        cmd_lower = cmd.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in cmd_lower:
                logger.warning(f"Potentially dangerous command detected: {cmd}")
                return False
        return True

    def _get_validated_input(self, prompt: str, options: List[str]) -> str:
        """Get validated user input with retry logic."""
        option_str = "/".join(options)
        while True:
            try:
                choice = input(f"{prompt} ({option_str}): ").strip().lower()
                if choice in options:
                    return choice
                else:
                    console.print(f"⚠️ Invalid input. Please enter one of: {option_str}", style="warning")
            except KeyboardInterrupt:
                console.print("\n\n⏹️ Execution interrupted by user.", style="error")
                exit(0)
            except EOFError:
                console.print("\n\n⏹️ No input received. Exiting.", style="error")
                exit(0)

    def execute_request(self, user_query: str, show_explanations: bool = False) -> None:
        """Execute a user request with interactive validation."""
        clean_query = user_query.strip().lower()
        if clean_query in ("analyze", "analyse", "--analyze"):
            if not self.context_history:
                console.print("⚠️ No previous command to analyze.", style="warning")
                return
            last = self.context_history[-1]
            try:
                analysis = self.engine.analyze_output(last["output"], last["user_query"])
                console.print(f"\n🧠 Analysis of: \"{last['user_query']}\"", style="ai")
                console.print(f"💡 {analysis}", style="info")
            except Exception as e:
                console.print(f"❌ Analysis failed: {e}", style="error")
            return

        from rich.panel import Panel
        console.print(Panel(
            "[bold]y[/] = run • [bold]n[/] = skip • [bold]s[/] = stop • "
            "[bold]e[/] = edit • [bold]o[/] = run your own • [bold]f[/] = fix error",
            title="[?] Action Keys",
            border_style="dim"
        ))

        try:
            context = self._get_context_string()
            commands = self.engine.generate_commands(user_query, context)
        except Exception as e:
            console.print(f"❌ Command generation failed: {e}", style="error")
            logger.error(f"Command generation error: {e}")
            return

        if not commands:
            console.print("⚠️ No commands to execute.", style="warning")
            return

        console.print(f"\n🧠 Generated [bold]{len(commands)}[/] command(s):", style="ai")

        explanations = []
        if show_explanations:
            for cmd in commands:
                try:
                    explanations.append(self.engine.generate_explanation(cmd))
                except Exception as e:
                    explanations.append(f"⚠️ Explanation failed: {e}")

        executed_commands = []
        all_outputs = []

        i = 0
        while i < len(commands):
            cmd = commands[i]
            console.print(f"\n[[bold]{i+1}/{len(commands)}[/]] {cmd}", style="cyan")

            if show_explanations and i < len(explanations):
                console.print(f"   💡 {explanations[i]}", style="info")

            action = self._get_validated_input("Run?", ['y', 'n', 's', 'e', 'o', 'f'])

            if action == 's':
                console.print("⏹️ Execution stopped by user.", style="error")
                break
            elif action == 'e':
                edited = input(f"Edit command [{cmd}]: ").strip()
                cmd = edited if edited else cmd
                console.print(f"→ Updated to: {cmd}", style="info")
                result = self._run_single_command(cmd)
                executed_commands.append(cmd)
                all_outputs.append(result["output"])
                if not self._handle_command_result(result):
                    break
                i += 1
            elif action == 'f':
                # Error recovery: analyze the failure and suggest fixes
                if all_outputs:
                    last_output = all_outputs[-1]
                    try:
                        fix_prompt = f"The command '{cmd}' failed with this output:\n{last_output}\n\nSuggest a corrected version of the command or an alternative approach."
                        suggestion = self.engine.llm.chat(fix_prompt, stream=False)
                        console.print(f"\n💡 Suggestion: {suggestion}", style="info")
                    except Exception as e:
                        console.print(f"❌ Could not generate fix: {e}", style="error")
                else:
                    console.print("⚠️ No previous output to analyze.", style="warning")
                i += 1
            elif action == 'n':
                console.print("⏭️ Skipped.", style="warning")
                i += 1
            elif action == 'o':
                while True:
                    custom_cmd = input("\n🛠️ Enter your command (empty to return): ").strip()
                    if not custom_cmd:
                        break
                    console.print(f"→ Running: {custom_cmd}", style="info")
                    result = self._run_single_command(custom_cmd)
                    output_str = str(result.get("output", ""))
                    output_display = output_str[:self.max_output_chars]
                    if len(output_str) > self.max_output_chars:
                        output_display += "\n... (truncated)"
                    if result["exit_code"] == 0:
                        console.print("✅ Success:", style="success")
                    else:
                        console.print("❌ Command failed:", style="error")
                    console.print(output_display)

                    self.context_history.append({
                        "user_query": f"[Manual] {custom_cmd}",
                        "commands": [custom_cmd],
                        "output": result["output"],
                        "exit_code": result["exit_code"]
                    })
                continue
            else:  # 'y'
                # Validate command before execution
                if not self._validate_command(cmd):
                    console.print("⚠️ This command appears dangerous. Skipping.", style="warning")
                    i += 1
                    continue
                    
                result = self._run_single_command(cmd)
                executed_commands.append(cmd)
                all_outputs.append(result["output"])
                if not self._handle_command_result(result):
                    break
                i += 1

        # Cleanup persistent shell if used
        if self._persistent_shell:
            self._persistent_shell.close()
            self._persistent_shell = None

        # Add to history and maintain size limit
        self.context_history.append({
            "user_query": user_query,
            "commands": executed_commands,
            "output": "\n".join(str(o) for o in all_outputs),
            "exit_code": 0
        })
        
        # Prevent unbounded history growth
        max_history_size = 100
        if len(self.context_history) > max_history_size:
            self.context_history = self.context_history[-max_history_size:]
            logger.debug(f"Context history trimmed to {max_history_size} items")
