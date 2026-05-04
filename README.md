# ShellMind 🧠💻  
**Your AI Terminal Assistant — Free, Private, and Powerful**

> 💬 *"Just say what you want. ShellMind writes, explains, and runs the right commands — safely."*

ShellMind translates natural language into **safe, platform-aware shell commands** for Windows (CMD/PowerShell) and Linux (Bash).  
It works **100% offline** with local LLMs (Ollama), or uses **free cloud models** when available — **no OpenAI, no credit card, no spying**.

![alt text](<Capture d'écran 2026-05-04 155511.png>)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

---

## ✨ Key Features

| Feature | Status |
|--------|--------|
| 🗣️ **Voice Input** | Optional (via Whisper, offline) |
| ☁️ **Cloud + Local LLM** | Ollama Cloud (`gpt-oss:120b`, etc.) + local (`llama3.1:8b`) |
| 🖥️ **Cross-Platform** | ✅ Windows (CMD/PowerShell), ✅ Linux (Bash) |
| 🔒 **Safety by Design** | Never runs without confirmation; blocks dangerous patterns |
| 💡 **Command Explanations** | On-demand plain-English explanations |
| 📊 **Output Analysis** | `sm analyze` → AI interprets results + suggests next steps |
| 🧠 **Context-Aware** | Remembers output for multi-turn workflows |
| 🎯 **Interactive Mode** | Full session with `cd`, `ssh`, manual commands (`o`), and error recovery (`f`) |
| 🛠️ **Manual Override** | Edit, skip, or run your own commands anytime |

> ❌ **Not yet supported**: macOS, Docker, persistent history across sessions

---

## 🚀 Quick Start (Local Dev)

> ⚠️ **Note**: ShellMind is **not on PyPI yet** — install from source.

### 1. Install Ollama
- Download from [ollama.com](https://ollama.com)
- Run: `ollama serve` (usually auto-starts)

### 2. Install ShellMind
```bash
git clone https://github.com/ahmedchafra/shellmind.git
cd shellmind
pip install -e .
```

> 💡 Add `[voice]` if you want speech-to-text:  
> ```bash
> pip install -e .[voice]
> ```

### 3. Use It!
```bash
# Single command
sm "find all .log files modified today"

# Interactive session (recommended)
sm

# Analyze last output
sm analyze

# Explain a command
sm --explain "tar -czf backup.tar.gz folder/"

# Voice input (if installed)
sm --voice
```



## 🎮 Interactive Mode Demo

```text
$ sm
🧠 > create folder demo and go inside it
[[1/2]] mkdir demo
Run? y
✅ Success:
[[2/2]] cd demo        ← Now works! (persistent shell)
Run? y
✅ Success:

🧠 > list files
[[1/1]] ls
Run? y
✅ Success: (empty)

🧠 > exit
👋 Goodbye!
$ pwd  # Still in original directory — safe!
/home/user
```

> ✅ In interactive mode, `cd`, `export`, `ssh`, and manual commands (`o`) **work as expected** thanks to the **persistent shell session**.

---

## ⚙️ Configuration

On first run, ShellMind creates `~/.shellmind/config.yaml`. Customize it:

```yaml
llm:
  mode: cloud          # 'cloud' or 'local'
  cloud_models:        # tried in order
    - gpt-oss:120b
    - deepseek-v3.1:671b
  local_model: llama3.1:8b-instruct-q4_K_M

ui:
  show_explanations: false
  max_output_chars: 2000
```

For cloud mode, set your API key:
```bash
# Linux/macOS
export OLLAMA_API_KEY="your_key"

# Windows (PowerShell)
$env:OLLAMA_API_KEY = "your_key"
```

---

## 🏗️ Architecture

```
shellmind/
├── cli.py               # Entry point (`sm`)
├── core/
│   ├── engine.py        # LLM prompt engineering
│   └── executor.py      # Persistent shell + safety
├── llm/                 # Ollama client (cloud/local fallback)
├── utils/               # Platform detection, console
└── voice/               # Optional Whisper STT
```

---

## 📋 Roadmap (Planned)

- [ ] Publish to PyPI
- [ ] Add unit tests
- [ ] Session persistence (SQLite)
- [ ] Safety layer (block `rm -rf /`)
- [ ] macOS support
- [ ] Docker image

---

## 🌟 Why ShellMind?

- **Free & open**: No paywalls, no telemetry
- **Private**: Runs offline by default
- **Smart**: Understands context, recovers from errors
- **Safe**: You control every command
- **Practical**: Solves real terminal pain points

> 🧠 **Built for developers, sysadmins, and learners who want terminal power — without memorizing commands.**

---

## 📄 License
MIT — use, modify, and share freely.

