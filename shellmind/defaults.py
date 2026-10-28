# shellmind/defaults.py
DEFAULT_CONFIG = {
    "llm": {
        "mode": "cloud",  # cloud-first with automatic local fallback
        "cloud_models": ["gpt-oss:120b", "deepseek-v3.1:671b", "qwen3-coder:480b", "kimi-k2:1t"],
        "local_model": "llama3.1:8b-instruct-q4_K_M",
        "timeout": 60,
    },
    "ui": {"show_explanations": False, "confirm_commands": True, "max_output_chars": 2000},
    "context": {"max_history_turns": 5},
    "execution": {"timeout": 60},
    "agent": {
        "planning": True,
        "verify_steps": True,
        "auto_replan": True,
        "max_replans": 2,
    },
    "history": {"enabled": True, "database": "sessions.db"},
    "workspace": {"enabled": True, "max_files": 3000},
    "undo": {"enabled": True, "max_files": 2000, "max_file_bytes": 512000},
    "safety": {"enabled": True, "block_dangerous": True},
}
