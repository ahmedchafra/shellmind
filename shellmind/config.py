# shellmind/config.py
import os
import yaml
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any
from .defaults import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

# Use XDG_CONFIG_HOME or ~/.shellmind for config directory
_xdg_config_home = os.getenv("XDG_CONFIG_HOME")
CONFIG_DIR = (
    Path(_xdg_config_home) / "shellmind" if _xdg_config_home else Path.home() / ".shellmind"
)
CONFIG_PATH = CONFIG_DIR / "config.yaml"


def init_config() -> None:
    """Create default config.yaml in user directory if missing."""
    if not CONFIG_PATH.exists():
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, indent=2, sort_keys=False)
            logger.info(f"✨ Created default config at {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Failed to create config: {e}")


def load_config() -> dict[str, Any]:
    """Load user config with fallback to defaults."""
    config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config: dict[str, Any] = yaml.safe_load(f) or {}

            # Merge user config (only top-level dict keys)
            for key in config:
                if key in user_config and isinstance(user_config[key], dict):
                    if isinstance(config[key], dict):
                        config[key].update(user_config[key])
            logger.debug(f"Config loaded from {CONFIG_PATH}")
        except Exception as e:
            logger.warning(f"Failed to load config: {e}. Using defaults.")
    else:
        logger.debug(f"Config file not found at {CONFIG_PATH}, using defaults")

    return config
