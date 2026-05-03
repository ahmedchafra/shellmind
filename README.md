# ShellMind 🧠💻

[![PyPI version](https://badge.fury.io/py/shellmind.svg)](https://badge.fury.io/py/shellmind)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-0%2F0-brightgreen.svg)](https://github.com/YOUR_USERNAME/shellmind/actions)

**AI-Powered Terminal Assistant**  
*Speak or type natural language tasks → Get safe, platform-aware shell commands with explanations.*

<img src=\"https://i.imgur.com/demo.gif\" alt=\"Demo\" width=\"800\"/>

## 🚀 Quick Start

### Installation
```bash
pip install shellmind[voice]  # Core + voice support
# or: pip install shellmind     # Core only
```

### Usage Examples
```bash
# Single command
sm \"find all log files over 100MB\"
sm \"analyze /var/log for errors\"

# Interactive mode
sm

# Explain commands
sm --explain \"docker ps --filter \\\"status=running\\\"\"
sm analyze  # Analyze previous output

# Voice (optional)
sm --voice
```

<img src=\"banner.png\" alt=\"Banner\" width=\"100%\"/>

## ✨ Features

| Feature | Status |
|---------|--------|
| 🗣️ Voice Input (Whisper) | ✅ |
| ☁️ Cloud LLM Fallback | ✅ |
| 🖥️ Windows/Linux | ✅ (cmd/pwsh/bash) |
| 🔒 Safety Validations | ✅ |
| 💡 Command Explanations | ✅ |
| 📊 Output Analysis | ✅ |
| 🧠 Session Memory | ✅ |

## 🏗️ Architecture
```
shellmind/
├── cli.py           # Entry point
├── core/
│   ├── engine.py    # LLM prompts
│   └── executor.py  # Shell execution
├── llm/             # Ollama client
├── voice/           # STT
├── utils/           # Console, platform
└── config.yaml      # User config
```

## ⚙️ Configuration
Edit `~/.shellmind/config.yaml`:
```yaml
llm:
  mode: cloud  # or 'local'
  cloud_models:
    - gpt-oss:120b
  local_model: llama3.1:8b-instruct-q4_K_M

ui:
  show_explanations: true
  max_output_chars: 2000
```

**Cloud**: Set `OLLAMA_API_KEY` env var.

## 🛡️ Security
- Blocks dangerous patterns (`rm -rf`, fork bombs)
- **Always** shows commands for approval
- Persistent shell (no `cd` leaks)

## 🧪 Development

```bash
git clone https://github.com/YOUR_USERNAME/shellmind
cd shellmind
pip install -e .[dev,voice]

# Lint
black .
mypy .
flake8 .

# Tests (add your tests!)
pytest tests/
```

## 📋 Roadmap
See [ROADMAP.md](ROADMAP.md) for v0.2.0 plans (tests, PyPI, Docker).

## 🤝 Contributing
1. Fork → PR
2. Add tests
3. `black . && mypy .`

## 📄 License
MIT © [Your Name]

---

⭐ **Star on GitHub** | 🐛 [Issues](https://github.com/YOUR_USERNAME/shellmind/issues)

