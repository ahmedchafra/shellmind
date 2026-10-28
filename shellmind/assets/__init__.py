import os


def get_banner():
    try:
        asset_dir = os.path.join(os.path.dirname(__file__), "banner.txt")
        with open(asset_dir, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "🧠 ShellMind: Your AI Terminal Co-Pilot\n"
