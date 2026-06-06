"""Windows system tray channel for Ram.

Features:
  • System tray icon (right-click menu: Chat, Briefing, Quit)
  • Global hotkey: Win+Shift+R (or Ctrl+Alt+R fallback) → toggle chat window
  • Tkinter popup chat window with scrollable history
  • Notification toasts for proactive messages
  • Runs in its own thread; agent calls are async via asyncio.run_coroutine_threadsafe

Usage:
  python -m ram --channel tray
"""
from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Callable

from loguru import logger


# ── Toast notification ────────────────────────────────────────────────────
class Toast:
    """Small auto-dismiss popup notification."""

    def __init__(self, message: str, duration: float = 4.0) -> None:
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        # Position bottom-right
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"380x80+{sw-400}+{sh-120}")
        frame = tk.Frame(self.root, bg="#1a1a2e", padx=12, pady=8)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(frame, text="🐏 Ram", font=("Segoe UI", 10, "bold"),
                 fg="#7b68ee", bg="#1a1a2e").pack(anchor="w")
        tk.Label(frame, text=message[:120], font=("Segoe UI", 9),
                 fg="#e0e0e0", bg="#1a1a2e", wraplength=340, justify="left"
                 ).pack(anchor="w")
        self.root.after(int(duration * 1000), self.root.destroy)
        self.root.mainloop()

    @staticmethod
    def show(message: str, duration: float = 4.0) -> None:
        t = threading.Thread(target=Toast, args=(message, duration), daemon=True)
        t.start()


# ── Chat window ───────────────────────────────────────────────────────────
class ChatWindow:
    BG = "#0f0f1a"
    FG = "#e0e0e0"
    INPUT_BG = "#1e1e30"
    ACCENT = "#7b68ee"
    USER_COLOR = "#a0cfff"
    RAM_COLOR = "#b8f0b8"

    def __init__(self, send_fn: Callable[[str], None]) -> None:
        self.send_fn = send_fn
        self.root = tk.Toplevel()
        self.root.title("Ram — Personal Assistant")
        self.root.geometry("560x640")
        self.root.configure(bg=self.BG)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._build_ui()

    def _build_ui(self) -> None:
        # Header
        hdr = tk.Frame(self.root, bg=self.ACCENT, height=40)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="🐏 Ram  •  Personal Assistant",
                 font=("Segoe UI", 11, "bold"), fg="white", bg=self.ACCENT
                 ).pack(side=tk.LEFT, padx=12, pady=8)

        # Message area
        self.chat_area = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD,
            bg=self.BG, fg=self.FG,
            font=("Consolas", 10),
            state=tk.DISABLED, relief=tk.FLAT,
            padx=10, pady=10,
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0))
        self.chat_area.tag_config("user", foreground=self.USER_COLOR, font=("Consolas", 10, "bold"))
        self.chat_area.tag_config("ram",  foreground=self.RAM_COLOR)
        self.chat_area.tag_config("ts",   foreground="#555577", font=("Consolas", 8))
        self.chat_area.tag_config("warn", foreground="#ffcc44")

        # Status bar
        self.status_var = tk.StringVar(value="ready")
        tk.Label(self.root, textvariable=self.status_var,
                 font=("Segoe UI", 8), fg="#666699", bg=self.BG,
                 anchor="w").pack(fill=tk.X, padx=10)

        # Input row
        input_frame = tk.Frame(self.root, bg=self.INPUT_BG)
        input_frame.pack(fill=tk.X, padx=8, pady=8)
        self.input_var = tk.StringVar()
        self.entry = tk.Entry(input_frame, textvariable=self.input_var,
                              font=("Segoe UI", 11),
                              bg=self.INPUT_BG, fg=self.FG,
                              insertbackground=self.FG,
                              relief=tk.FLAT)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4), pady=6)
        self.entry.bind("<Return>", self._on_send)
        self.entry.bind("<Up>", self._history_up)
        self.entry.bind("<Down>", self._history_down)

        send_btn = tk.Button(input_frame, text="Send",
                             command=self._on_send,
                             bg=self.ACCENT, fg="white",
                             font=("Segoe UI", 10, "bold"),
                             relief=tk.FLAT, padx=14, pady=4,
                             cursor="hand2")
        send_btn.pack(side=tk.RIGHT, padx=(0, 8))

        # Quick-action buttons
        quick_frame = tk.Frame(self.root, bg=self.BG)
        quick_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        for label, cmd in [("📋 Briefing", "what's my briefing?"),
                            ("📅 Today", "what's on my calendar today?"),
                            ("✅ Tasks", "show my pending tasks"),
                            ("💰 Spend", "how much have I spent this month?"),
                            ("⚙️ Settings", "__open_settings__")]:
            tk.Button(quick_frame, text=label, command=lambda c=cmd: self._quick(c),
                      bg="#1e1e30", fg="#a0a0cc",
                      font=("Segoe UI", 8), relief=tk.FLAT, padx=6, pady=2,
                      cursor="hand2").pack(side=tk.LEFT, padx=2)

        self._history: list[str] = []
        self._history_idx = -1

    def _quick(self, cmd: str) -> None:
        if cmd == "__open_settings__":
            import webbrowser
            from ram.core.config import settings as cfg
            webbrowser.open(f"http://localhost:{cfg.ram_http_port}/admin")
            return
        self.input_var.set(cmd)
        self._on_send()

    def _on_send(self, event=None) -> None:
        text = self.input_var.get().strip()
        if not text:
            return
        self._history.insert(0, text)
        self._history_idx = -1
        self.input_var.set("")
        self.append_message("You", text, "user")
        self.status_var.set("thinking…")
        self.entry.config(state=tk.DISABLED)
        self.send_fn(text)

    def _history_up(self, event=None) -> None:
        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.input_var.set(self._history[self._history_idx])

    def _history_down(self, event=None) -> None:
        if self._history_idx > 0:
            self._history_idx -= 1
            self.input_var.set(self._history[self._history_idx])
        else:
            self._history_idx = -1
            self.input_var.set("")

    def append_message(self, sender: str, text: str, tag: str = "ram") -> None:
        ts = time.strftime("%H:%M")
        self.chat_area.config(state=tk.NORMAL)
        self.chat_area.insert(tk.END, f"\n[{ts}] ", "ts")
        self.chat_area.insert(tk.END, f"{sender}: ", tag)
        # Detect warning prefix
        display_tag = "warn" if text.startswith("⚠️") else tag
        self.chat_area.insert(tk.END, text + "\n", display_tag)
        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)

    def reply_received(self, text: str) -> None:
        self.append_message("Ram", text, "ram")
        self.status_var.set("ready")
        self.entry.config(state=tk.NORMAL)
        self.entry.focus_set()
        # If it's a confirmation prompt, highlight it
        if "⚠️" in text and "YES" in text:
            self.status_var.set("⚠️ Waiting for confirmation")

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.entry.focus_set()

    def hide(self) -> None:
        self.root.withdraw()


# ── Tray channel ─────────────────────────────────────────────────────────
class TrayChannel:
    """System tray + chat window channel."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._root: tk.Tk | None = None
        self._chat: ChatWindow | None = None
        self._reply_q: queue.Queue = queue.Queue()
        self._user_id = "tray_user"

    def _start_agent_loop(self) -> None:
        """Run asyncio event loop in a background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _send_message(self, text: str) -> None:
        """Called from Tkinter thread; dispatches to asyncio thread."""
        async def _task():
            from ram.core.agent import get_agent
            try:
                reply = await get_agent().handle(self._user_id, text)
                self._reply_q.put(reply.text)
            except Exception as e:
                self._reply_q.put(f"ERROR: {e}")

        asyncio.run_coroutine_threadsafe(_task(), self._loop)

    def _poll_replies(self) -> None:
        """Poll reply queue every 100ms from Tkinter main loop."""
        while not self._reply_q.empty():
            reply = self._reply_q.get_nowait()
            if self._chat:
                self._chat.reply_received(reply)
        if self._root:
            self._root.after(100, self._poll_replies)

    def _setup_tray(self) -> None:
        """Set up pystray icon."""
        try:
            import pystray
            from PIL import Image, ImageDraw

            # Draw a simple teal circle icon
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse([4, 4, 60, 60], fill="#7b68ee")
            d.text((16, 16), "R", fill="white")

            def on_open_chat(icon, item):
                if self._chat and self._root:
                    self._root.after(0, self._chat.show)

            def on_briefing(icon, item):
                self._send_message("what's my morning briefing?")
                if self._chat and self._root:
                    self._root.after(0, self._chat.show)

            def on_open_settings(icon, item):
                import webbrowser
                from ram.core.config import settings as cfg
                webbrowser.open(f"http://localhost:{cfg.ram_http_port}/admin")

            def on_quit(icon, item):
                icon.stop()
                if self._root:
                    self._root.after(0, self._root.quit)

            menu = pystray.Menu(
                pystray.MenuItem("💬 Open Chat  (Ctrl+Alt+R)", on_open_chat, default=True),
                pystray.MenuItem("📋 Morning Briefing", on_briefing),
                pystray.MenuItem("⚙️  Settings", on_open_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Ram", on_quit),
            )
            icon = pystray.Icon("Ram", img, "Ram — Personal Assistant", menu)
            # Run tray in background thread
            threading.Thread(target=icon.run, daemon=True).start()
        except ImportError:
            logger.warning("pystray/Pillow not installed — tray icon disabled. "
                           "Install with: pip install pystray Pillow")

    def _bind_hotkey(self) -> None:
        """Bind global hotkey Ctrl+Alt+R to toggle chat window."""
        try:
            import keyboard
            def _toggle():
                if self._chat:
                    if self._root:
                        self._root.after(0, self._chat.show)
            keyboard.add_hotkey("ctrl+alt+r", _toggle)
            logger.info("Global hotkey Ctrl+Alt+R registered")
        except ImportError:
            logger.debug("keyboard package not installed — hotkey disabled. pip install keyboard")

    def run(self) -> None:
        """Main entry point — blocks until quit."""
        # Start asyncio thread
        t = threading.Thread(target=self._start_agent_loop, daemon=True)
        t.start()
        # Wait for loop
        while self._loop is None:
            time.sleep(0.01)

        # Build Tk root (hidden — windows are Toplevels)
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("Ram")

        # Build chat window
        self._chat = ChatWindow(send_fn=self._send_message)
        self._chat.show()

        # Setup tray + hotkey
        self._setup_tray()
        self._bind_hotkey()

        # Poll reply queue
        self._root.after(100, self._poll_replies)

        # Welcome message
        self._chat.append_message("Ram",
            "👋 Hi! I'm Ram, your personal assistant. "
            "Ask me anything — I can help with your schedule, tasks, finances, "
            "emails, code, and much more. Type or click a quick-action below.", "ram")

        # Proactive briefing
        self._send_message("give me a short welcome briefing")

        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            pass


def run_tray() -> None:
    TrayChannel().run()
