# Multi-CLI Comparison

A PySide6 desktop app that sends a single prompt to multiple AI CLI tools simultaneously and shows all responses side by side for easy comparison.

![AI CLI comparison](https://www.dynamsoft.com/codepool/img/2026/03/multi-ai-cli-comparison.png)

## Supported CLIs

| CLI | Binary | Download |
|-----|--------|---------|
| **Qwen Code** | `qwen` | https://github.com/QwenLM/qwen-code |
| **GitHub Copilot CLI** | `copilot` | https://docs.github.com/en/copilot/github-copilot-in-the-cli |
| **OpenCode** | `opencode` | https://opencode.ai |
| **Gemini CLI** | `gemini` | https://github.com/google-gemini/gemini-cli |

When the app starts it checks which CLIs are installed (`shutil.which`).  
- **Installed** → a live response panel is created.  
- **Not installed** → an info panel is shown with the download URL and a suggested install command.

## Requirements

- Python 3.10+
- PySide6

```bash
pip install -r requirements.txt
```

The four CLI tools listed above must be installed and authenticated separately.

## Usage

```bash
python main.py
```

1. Type a prompt in the input box at the bottom.
2. Click **Send** or press **Ctrl+Enter**.
3. Each installed CLI runs concurrently; responses stream into their panels as they arrive.
4. Click **Clear** to reset all response panels.

## Non-interactive invocation

| CLI | Command used |
|-----|-------------|
| Qwen Code | `qwen "<prompt>"` |
| GitHub Copilot CLI | `copilot -p "<prompt>"` |
| OpenCode | `opencode run "<prompt>"` |
| Gemini CLI | `gemini -p "<prompt>"` |

## Project structure

```
multi-cli-comparison/
├── main.py          # PySide6 application
├── requirements.txt
└── README.md
```
