#!/usr/bin/env python3
"""
Multi-CLI Comparison Tool
Send one prompt to multiple AI CLI apps and compare their responses side by side.
"""

import re
import sys
import os
import platform
import shutil
import subprocess
import markdown as md_lib

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSplitter, QFrame, QSizePolicy,
    QTextBrowser,
)
from PySide6.QtCore import Qt, QThread, Signal, QEvent, QUrl
from PySide6.QtGui import QFont, QTextCursor, QDesktopServices, QKeyEvent


# ── ANSI escape-code stripper ────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_IS_WINDOWS = platform.system() == "Windows"


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def build_cmd(args: list[str]) -> list[str]:
    """On Windows .CMD/.BAT scripts cannot be spawned directly; wrap with cmd /c.
    If the binary is already a .exe, no wrapping is needed."""
    if _IS_WINDOWS and not args[0].lower().endswith(".exe"):
        return ["cmd", "/c"] + args
    return args


def _find_real_copilot() -> str | None:
    """Find the real copilot binary, skipping the VS Code PS1/BAT wrapper.

    The wrapper script at .../copilotCli/copilot.ps1 does an interactive
    version check (Read-Host) that blocks when stdin is /dev/null.
    By excluding that directory from PATH we can locate the real .exe.
    """
    wrapper_path = shutil.which("copilot")
    if not wrapper_path:
        return None

    # If it's already a real executable (not a wrapper), use it directly
    if wrapper_path.lower().endswith(".exe"):
        return wrapper_path

    # Remove the wrapper's directory from PATH and search again
    wrapper_dir = os.path.dirname(os.path.abspath(wrapper_path))
    filtered = [p for p in os.environ.get("PATH", "").split(os.pathsep)
                if os.path.normcase(os.path.abspath(p)) != os.path.normcase(wrapper_dir)]
    old_path = os.environ["PATH"]
    os.environ["PATH"] = os.pathsep.join(filtered)
    try:
        real = shutil.which("copilot")
    finally:
        os.environ["PATH"] = old_path
    return real


# ── CLI definitions ──────────────────────────────────────────────────────────

# Resolve the real copilot binary once at import time (may be None)
_REAL_COPILOT = _find_real_copilot()

CLI_DEFS = [
    {
        "id": "qwen",
        "name": "Qwen Code",
        # positional arg = one-shot / non-interactive by default
        "cmd": lambda p: ["qwen", p],
        "color": "#4A9EEB",
        "download_url": "https://github.com/QwenLM/qwen-code",
        "install_hint": "npm install -g @qwen-code/qwen-code",
    },
    {
        "id": "copilot",
        "name": "GitHub Copilot CLI",
        # Use the resolved real binary to bypass the PS1 wrapper's version check
        "cmd": lambda p: [_REAL_COPILOT, "-p", p] if _REAL_COPILOT else ["copilot", "-p", p],
        "color": "#9B6FE8",
        "download_url": "https://docs.github.com/en/copilot/github-copilot-in-the-cli",
        "install_hint": "gh extension install github/gh-copilot",
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        "cmd": lambda p: ["opencode", "run", p],
        "color": "#E8623A",
        "download_url": "https://opencode.ai",
        "install_hint": "npm install -g opencode-ai",
    },
    {
        "id": "gemini",
        "name": "Gemini CLI",
        # -p / --prompt = non-interactive headless mode
        "cmd": lambda p: ["gemini", "-p", p],
        "color": "#34A853",
        "download_url": "https://github.com/google-gemini/gemini-cli",
        "install_hint": "npm install -g @google/gemini-cli",
    },
]


# ── Worker thread ────────────────────────────────────────────────────────────

class CLIWorker(QThread):
    """Runs a CLI subprocess in a background thread; streams stdout line-by-line."""

    output_chunk = Signal(str)          # emitted for each output chunk
    finished = Signal(bool, str)        # (success, error_message)

    def __init__(self, cmd: list[str]):
        super().__init__()
        self._cmd = cmd
        self._cancelled = False
        self._process: subprocess.Popen | None = None

    def cancel(self):
        self._cancelled = True
        if self._process and self._process.poll() is None:
            self._process.kill()

    def run(self):
        try:
            self._process = subprocess.Popen(
                self._cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in iter(self._process.stdout.readline, ""):
                if self._cancelled:
                    self._process.kill()
                    self.finished.emit(False, "Cancelled")
                    return
                self.output_chunk.emit(strip_ansi(line))
            self._process.stdout.close()
            self._process.wait()
            rc = self._process.returncode
            if rc == 0:
                self.finished.emit(True, "")
            else:
                self.finished.emit(False, f"Process exited with code {rc}")
        except FileNotFoundError:
            self.finished.emit(False, f"Command not found: {self._cmd[0]}")
        except Exception as exc:
            self.finished.emit(False, str(exc))


# ── Per-CLI panel ────────────────────────────────────────────────────────────

# ── Markdown → HTML converter ───────────────────────────────────────────────

_MD_EXTENSIONS = ["fenced_code", "tables", "nl2br", "sane_lists"]

_MD_CSS = """
<style>
body  { font-family:'Segoe UI',sans-serif; background:#0d0d1a; color:#e0e0e0;
         margin:10px; line-height:1.6; font-size:13px; }
h1,h2,h3,h4 { color:#7ec8e3; margin-top:14px; }
code  { background:#1e1e35; padding:2px 5px; border-radius:3px;
        font-family:Consolas,monospace; color:#a0e0a0; font-size:12px; }
pre   { background:#1e1e35; padding:10px 14px; border-radius:6px;
        overflow-x:auto; border:1px solid #333; }
pre code { background:none; padding:0; color:#a0e0a0; }
a     { color:#4A9EEB; }
blockquote { border-left:3px solid #555; margin:0; padding-left:12px;
             color:#aaa; }
table { border-collapse:collapse; width:100%; }
th,td { border:1px solid #444; padding:6px 10px; }
th    { background:#1a1a2e; }
tr:nth-child(even) { background:#111122; }
hr    { border:none; border-top:1px solid #333; }
</style>
"""


def markdown_to_html(text: str) -> str:
    body = md_lib.markdown(text, extensions=_MD_EXTENSIONS)
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>{_MD_CSS}</head>
<body>{body}</body></html>"""


class CLIPanel(QFrame):
    """
    Panel for a single CLI tool.
    - If the tool is installed: shows a live-updating response text area with
      a toggle button to switch between raw Markdown and rendered HTML.
    - If the tool is missing:  shows a styled info card with the download URL.
    """

    def __init__(self, cli_def: dict, available: bool, parent=None):
        super().__init__(parent)
        self.cli_def = cli_def
        self.available = available
        self._worker: CLIWorker | None = None
        self._raw_text: str = ""          # accumulated plain-text output
        self._rendered_mode: bool = False  # False = raw markdown, True = HTML
        self._setup_ui()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self):
        color = self.cli_def["color"]
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            CLIPanel {{
                border: 2px solid {color};
                border-radius: 8px;
                background-color: #1a1a2e;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Header row ──────────────────────────────────────────────────────
        header = QHBoxLayout()

        name_lbl = QLabel(self.cli_def["name"])
        name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {color}; border: none;")
        header.addWidget(name_lbl)
        header.addStretch()

        # Toggle button (only meaningful for available panels)
        self._toggle_btn = QPushButton("⟳ Render")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setFixedSize(84, 22)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d45;
                color: #aaa;
                border: 1px solid #555;
                border-radius: 4px;
                font-size: 11px;
                padding: 0 6px;
            }
            QPushButton:checked {
                background-color: #3a5a3a;
                color: #a0e0a0;
                border-color: #4caf50;
            }
            QPushButton:hover { background-color: #383858; color: #ddd; }
        """)
        self._toggle_btn.setVisible(self.available)
        self._toggle_btn.toggled.connect(self._on_toggle)
        header.addWidget(self._toggle_btn)

        self.status_lbl = QLabel()
        self.status_lbl.setStyleSheet("color: #888; font-size: 11px; border: none; margin-left:6px;")
        header.addWidget(self.status_lbl)

        layout.addLayout(header)

        # ── Content area ────────────────────────────────────────────────────
        _text_style = """
            background-color: #0d0d1a;
            color: #e0e0e0;
            border: 1px solid #333;
            border-radius: 4px;
        """

        # Raw markdown view (plain QTextBrowser, monospace)
        self.text_area = QTextBrowser()
        self.text_area.setOpenLinks(False)
        self.text_area.anchorClicked.connect(
            lambda url: QDesktopServices.openUrl(url)
        )
        self.text_area.setFont(QFont("Consolas", 10))
        self.text_area.setStyleSheet(f"QTextBrowser {{ {_text_style} }}")
        layout.addWidget(self.text_area)

        # Rendered HTML view
        self.render_area = QTextBrowser()
        self.render_area.setOpenLinks(False)
        self.render_area.anchorClicked.connect(
            lambda url: QDesktopServices.openUrl(url)
        )
        self.render_area.setStyleSheet(f"QTextBrowser {{ {_text_style} }}")
        self.render_area.setVisible(False)
        layout.addWidget(self.render_area)

        if self.available:
            self._set_status_ready()
        else:
            self._show_download_info()

    # ── Toggle handler ───────────────────────────────────────────────────────

    def _on_toggle(self, checked: bool):
        self._rendered_mode = checked
        if checked:
            self._toggle_btn.setText("✎ Markdown")
            self.render_area.setHtml(markdown_to_html(self._raw_text))
            self.text_area.setVisible(False)
            self.render_area.setVisible(True)
        else:
            self._toggle_btn.setText("⟳ Render")
            self.render_area.setVisible(False)
            self.text_area.setVisible(True)

    def _set_status(self, text: str, color: str):
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color}; font-size: 11px; border: none; margin-left:6px;")

    def _set_status_ready(self):
        self._set_status("● Ready", "#4caf50")

    # ── Not-installed state ──────────────────────────────────────────────────

    def _show_download_info(self):
        self._set_status("● Not installed", "#f44336")
        url = self.cli_def["download_url"]
        hint = self.cli_def["install_hint"]
        name = self.cli_def["name"]
        color = self.cli_def["color"]
        html = f"""
<div style="color:#e0e0e0; font-family:'Segoe UI',sans-serif; padding:16px;">
  <p style="font-size:16px; font-weight:bold; color:{color};">{name}</p>
  <p style="color:#f44336; font-size:13px;">&#9888; Not installed on this system</p>
  <p style="font-size:12px; color:#aaa; margin-top:16px;">Download / Documentation:</p>
  <p style="margin-top:4px;">
    <a href="{url}" style="color:#4A9EEB; font-size:13px;">{url}</a>
  </p>
  <hr style="border:none; border-top:1px solid #333; margin:16px 0;" />
  <p style="font-size:12px; color:#aaa;">Suggested install command:</p>
  <p style="background:#111; padding:10px 14px; border-radius:6px;
            font-family:Consolas,monospace; font-size:12px; color:#a0e0a0;
            margin-top:4px;">
    {hint}
  </p>
  <p style="font-size:11px; color:#666; margin-top:8px;">
    (Verify with the official documentation — install commands may change.)
  </p>
</div>
"""
        self.text_area.setHtml(html)

    # ── Query handling ───────────────────────────────────────────────────────

    def start_query(self, prompt: str):
        """Launch the CLI with the given prompt."""
        if not self.available:
            return

        # Cancel any in-progress run
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()

        self._raw_text = ""
        self.text_area.clear()
        self.render_area.clear()
        # Switch back to raw view for live streaming
        if self._rendered_mode:
            self._toggle_btn.setChecked(False)
        self._set_status("● Running…", "#ff9800")

        cmd = build_cmd(self.cli_def["cmd"](prompt))
        self._worker = CLIWorker(cmd)
        self._worker.output_chunk.connect(self._append_text)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _append_text(self, text: str):
        self._raw_text += text
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()

    def _on_finished(self, success: bool, error_msg: str):
        if success:
            self._set_status("● Done", "#4caf50")
        elif error_msg == "Cancelled":
            self._set_status("● Cancelled", "#888888")
        else:
            self._set_status("● Error", "#f44336")
            self._append_text(f"\n[Error: {error_msg}]\n")
        # If user was in rendered mode while streaming, refresh the rendered view
        if self._rendered_mode:
            self.render_area.setHtml(markdown_to_html(self._raw_text))

    def clear_response(self):
        """Clear response text and reset status (only for available panels)."""
        if not self.available:
            return
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        self._raw_text = ""
        self.text_area.clear()
        self.render_area.clear()
        if self._rendered_mode:
            self._toggle_btn.setChecked(False)
        self._set_status_ready()


# ── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._panels: list[CLIPanel] = []
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Multi-CLI Comparison")
        self.setMinimumSize(1100, 640)
        self.resize(1400, 820)

        # ── App-wide dark theme ──────────────────────────────────────────────
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #12121f;
                color: #e0e0e0;
                font-family: "Segoe UI", sans-serif;
            }

            /* Send button */
            QPushButton#send_btn {
                background-color: #4A9EEB;
                color: white;
                border: none;
                padding: 8px 24px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton#send_btn:hover  { background-color: #5aadf5; }
            QPushButton#send_btn:pressed { background-color: #3a8edb; }
            QPushButton#send_btn:disabled { background-color: #444; color: #777; }

            /* Clear button */
            QPushButton#clear_btn {
                background-color: #2d2d45;
                color: #bbb;
                border: 1px solid #444;
                padding: 8px 24px;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton#clear_btn:hover  { background-color: #383858; color: #ddd; }
            QPushButton#clear_btn:pressed { background-color: #222238; }

            /* Prompt input */
            QTextEdit#prompt_input {
                background-color: #1a1a2e;
                color: #e0e0e0;
                border: 2px solid #333;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
            }
            QTextEdit#prompt_input:focus {
                border-color: #4A9EEB;
            }

            /* Splitter handle */
            QSplitter::handle {
                background-color: #2a2a3e;
                width: 4px;
            }
            QSplitter::handle:hover {
                background-color: #4A9EEB;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Title ────────────────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_lbl = QLabel("Multi-CLI Comparison")
        title_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #e0e0e0;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        self._avail_lbl = QLabel()
        self._avail_lbl.setStyleSheet("color: #888; font-size: 12px;")
        title_row.addWidget(self._avail_lbl)
        root.addLayout(title_row)

        # ── CLI panels ───────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        available_count = 0
        for cli_def in CLI_DEFS:
            avail = shutil.which(cli_def["id"]) is not None
            panel = CLIPanel(cli_def, avail)
            splitter.addWidget(panel)
            self._panels.append(panel)
            if avail:
                available_count += 1

        # Equal initial widths
        splitter.setSizes([300] * len(CLI_DEFS))
        root.addWidget(splitter, stretch=1)

        self._avail_lbl.setText(
            f"{available_count}/{len(CLI_DEFS)} CLIs installed"
        )

        # ── Prompt area ──────────────────────────────────────────────────────
        prompt_frame = QFrame()
        prompt_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #333;
                border-radius: 8px;
            }
        """)
        pf_layout = QVBoxLayout(prompt_frame)
        pf_layout.setContentsMargins(10, 8, 10, 10)
        pf_layout.setSpacing(6)

        hint_lbl = QLabel("Prompt  —  press Ctrl+Enter to send")
        hint_lbl.setStyleSheet("color: #666; font-size: 11px; border: none;")
        pf_layout.addWidget(hint_lbl)

        input_row = QHBoxLayout()

        self._prompt_input = QTextEdit()
        self._prompt_input.setObjectName("prompt_input")
        self._prompt_input.setFixedHeight(80)
        self._prompt_input.setPlaceholderText(
            "Type your prompt here and press Send (or Ctrl+Enter)…"
        )
        self._prompt_input.installEventFilter(self)
        input_row.addWidget(self._prompt_input)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("send_btn")
        self._send_btn.setFixedWidth(110)
        self._send_btn.clicked.connect(self._send_prompt)
        btn_col.addWidget(self._send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("clear_btn")
        clear_btn.setFixedWidth(110)
        clear_btn.clicked.connect(self._clear_all)
        btn_col.addWidget(clear_btn)

        btn_col.addStretch()
        input_row.addLayout(btn_col)
        pf_layout.addLayout(input_row)

        root.addWidget(prompt_frame)

        # Disable Send if no CLIs are available
        if available_count == 0:
            self._send_btn.setEnabled(False)
            self._send_btn.setToolTip("No CLI tools are installed")

    # ── Event filter (Ctrl+Enter) ────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._prompt_input and event.type() == QEvent.Type.KeyPress:
            key_ev: QKeyEvent = event  # type: ignore[assignment]
            ctrl = Qt.KeyboardModifier.ControlModifier
            if (
                key_ev.key() == Qt.Key.Key_Return
                and key_ev.modifiers() & ctrl
            ):
                self._send_prompt()
                return True
        return super().eventFilter(obj, event)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _send_prompt(self):
        prompt = self._prompt_input.toPlainText().strip()
        if not prompt:
            return
        self._prompt_input.clear()
        for panel in self._panels:
            panel.start_query(prompt)

    def _clear_all(self):
        for panel in self._panels:
            panel.clear_response()


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Multi-CLI Comparison")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
