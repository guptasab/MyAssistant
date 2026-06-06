"""CLI channel — interactive terminal, great for local dev and testing."""
from __future__ import annotations

import asyncio

from rich.console import Console
from rich.prompt import Prompt

from myassistant.channels.base import Channel

CLI_USER = "cli"


class CLIChannel(Channel):
    name = "cli"

    def __init__(self, handle):
        super().__init__(handle)
        self.console = Console()

    async def start(self) -> None:
        self.console.print("[bold cyan]MyAssistant[/bold cyan] is ready. Type 'exit' to quit.\n")
        loop = asyncio.get_event_loop()
        while True:
            user_text = await loop.run_in_executor(None, lambda: Prompt.ask("[bold green]you[/bold green]"))
            if user_text.strip().lower() in {"exit", "quit", ":q"}:
                break
            reply = await self.handle(CLI_USER, user_text)
            self.console.print(f"[bold magenta]MyAssistant[/bold magenta]: {reply.text}\n")
            if reply.actions_taken:
                self.console.print(f"[dim]actions: {', '.join(reply.actions_taken)}[/dim]\n")

    async def send(self, user_id: str, text: str) -> None:
        self.console.print(f"\n[bold yellow]MyAssistant (push)[/bold yellow]: {text}\n")
