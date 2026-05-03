import logging
from rich.console import Console
from rich.theme import Theme

logger = logging.getLogger(__name__)

shellmind_theme = Theme({
    "info": "bold cyan",
    "warning": "bold yellow",
    "error": "bold red",
    "success": "bold green",
    "ai": "bold blue",
    "prompt": "bold magenta",
    "dim": "dim",
})

console = Console(theme=shellmind_theme)