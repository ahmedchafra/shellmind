# shellmind/core/engine.py
import logging
import shlex
from typing import List
from shellmind.utils.platform import detect_platform
from shellmind.llm.ollama_client import OllamaClientWrapper

logger = logging.getLogger(__name__)

class ShellMindEngine:
    def __init__(self, llm_client: OllamaClientWrapper):
        self.llm = llm_client
        self.platform_info = detect_platform()

    def _build_command_prompt(self, user_query: str, context: str = "") -> str:
        """Build a contextual prompt for command generation."""
        os_name = "Windows" if self.platform_info["os"] == "windows" else "Linux"
        shell = self.platform_info["shell"]

        if self.platform_info["os"] == "windows":
            if shell == "cmd":
                restrictions = "Do NOT use ./, /, ~, or Unix paths. Use plain names (e.g., 'demo') or backslashes. Forward slashes (/) are acceptable in file paths."
            else:  # powershell
                restrictions = "Do NOT use ./ unless in quotes. Prefer .\\ or bare names. Forward slashes (/) are also acceptable."
        else:  # linux
            restrictions = "Prefer bare relative names (e.g., 'demo'). Use ./ only if necessary. Always use forward slashes (/) in paths."

        return f"""You are ShellMind: an intelligent terminal assistant for {os_name} ({shell}).

CRITICAL RULES:
- NEVER output 'cd', 'export', 'set', 'alias', 'source', 'pushd', 'popd' unless the user's request is SOLELY about that action.
- For file content generation, PREFER a single efficient command (e.g., 'cat > file <<EOF' or 'echo -e "a\\nb" > file').
- For lists or multi-line output, AVOID repeating 'echo ... >> file' — use heredoc or multi-line echo.
- Use forward slashes (/) in file paths — they work reliably on Windows and Linux.
- Output ONLY executable commands — one command per line, but combine logically related actions into one line if efficient.
- You have access to the output of previous commands. Use exact values (IPs, paths, versions, ports) from that output.
- If the user refers to "that service", "those files", or similar, infer from context.
- Assume current directory unless user specifies a path.
- {restrictions}

Previous interaction context (use for reference):
{context}

User request:
{user_query}

Commands:"""

    def _build_explain_prompt(self, command: str) -> str:
        """Build a prompt to explain a shell command."""
        return f"""Explain this shell command in one clear, beginner-friendly sentence:
{command}

Explanation:"""

    def analyze_output(self, output: str, original_goal: str) -> str:
        """Analyze command output and suggest next steps."""
        prompt = f"""You are ShellMind, a sysadmin and security expert.

Original user goal: {original_goal}
Command output:
{output}

Analyze this output and:
1. Summarize key findings (open ports, versions, errors, files, etc.)
2. Highlight risks or opportunities
3. Suggest 1–3 specific next shell commands to advance the goal

Respond in clear, concise English. No markdown, no code blocks.
"""
        try:
            return self.llm.chat(prompt, stream=False).strip()
        except Exception as e:
            raise RuntimeError(f"Analysis failed: {e}")

    def generate_commands(self, user_query: str, context: str = "") -> List[str]:
        """Generate shell commands from natural language query."""
        prompt = self._build_command_prompt(user_query, context)
        try:
            raw = self.llm.chat(prompt, stream=False)
        except Exception as e:
            raise RuntimeError(f"LLM generation failed: {e}")

        if raw.startswith("```") and raw.endswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        commands = [line.strip() for line in raw.split("\n") if line.strip()]
        if not commands:
            raise ValueError("LLM returned empty or invalid command list.")
        
        # Log command generation for debugging
        logger.debug(f"Generated {len(commands)} command(s) for: {user_query}")
        return commands

    def generate_explanation(self, command: str) -> str:
        """Generate explanation for a shell command."""
        prompt = self._build_explain_prompt(command)
        try:
            return self.llm.chat(prompt, stream=False).strip()
        except Exception as e:
            logger.error(f"Explanation generation failed: {e}")
            return f"⚠️ Failed to explain: {e}"