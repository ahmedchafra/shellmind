# Import necessary modules for OS and process introspection
import os           # For accessing environment variables
import platform     # For detecting the operating system
import psutil       # For inspecting running processes and their hierarchy
import logging

logger = logging.getLogger(__name__)


def detect_platform() -> dict:
    """
    Detects the current operating system and the active shell (terminal) environment.
    
    Returns:
        dict: A dictionary with two keys:
              - 'os': either "windows" or "linux"
              - 'shell': either "powershell", "cmd" (on Windows), or "bash" (on Linux)
    
    Raises:
        RuntimeError: If the OS is neither Windows nor Linux.
    """
    
    # Get the current OS name in lowercase (e.g., 'windows', 'linux', 'darwin')
    system = platform.system().lower()

    # === WINDOWS DETECTION ===
    if system == "windows":
        try:
            # Get the current Python process
            current = psutil.Process()
            # Get its immediate parent process (e.g., the terminal that launched Python) our command sm
            parent = current.parent()
            # Get the grandparent (e.g., the terminal app like Windows Terminal, VS Code, or cmd.exe itself)
            grandparent = parent.parent() if parent else None

            # 1️⃣ First, check the GRANDPARENT process — this is often the *actual shell*
            if grandparent:
                gp_name = grandparent.name().lower()
                # If grandparent is PowerShell (powershell.exe or pwsh.exe)
                if "powershell" in gp_name or "pwsh" in gp_name:
                    return {"os": "windows", "shell": "powershell"}
                # If grandparent is CMD (cmd.exe)
                if "cmd" in gp_name:
                    return {"os": "windows", "shell": "cmd"}

            # 2️⃣ Fallback: if no grandparent, check the PARENT process
            if parent:
                p_name = parent.name().lower()
                if "powershell" in p_name or "pwsh" in p_name:
                    return {"os": "windows", "shell": "powershell"}
                if "cmd" in p_name:
                    return {"os": "windows", "shell": "cmd"}

        except Exception:
            # If any error occurs (e.g., process access denied), silently continue
            pass

        # 3️⃣ Last resort: use environment variables
        # PowerShell always sets $PSModulePath; CMD does not
        if "PSMODULEPATH" in os.environ:
            return {"os": "windows", "shell": "powershell"}
        else:
            return {"os": "windows", "shell": "cmd"}

    # === LINUX DETECTION ===
    elif system == "linux":
        # Assume bash as the default shell (most common on Linux)
        return {"os": "linux", "shell": "bash"}

    # === UNSUPPORTED OS ===
    else:
        # Only Windows and Linux are supported by ShellMind
        raise RuntimeError(f"Unsupported OS: {system}. Only Windows and Linux are supported.")