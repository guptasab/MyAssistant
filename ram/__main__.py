"""Top-level entry. `python -m squire [--channel cli|all]`

Squire — your personal AI life-OS assistant (mysquire.ai)
"""
from __future__ import annotations

import asyncio
import signal
import sys

import typer
from loguru import logger

from ram.core import registry, scheduler
from ram.core.agent import get_agent
from ram.core.config import settings
from ram.skills.notify import register_channel

app = typer.Typer(add_completion=False, help="Squire — your personal AI assistant (mysquire.ai)")


async def _run(channels_arg: str, sandbox: bool = False) -> None:
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(settings.ram_data_dir / "logs" / "squire.log", rotation="10 MB", retention=5, level="DEBUG")

    # Check at least one LLM provider is configured
    from ram.core.llm import list_providers
    active = {k: v for k, v in list_providers().items() if v}
    if not active:
        # Check if this looks like a first-run situation
        from ram.core.onboarding_wizard import needs_onboard
        if needs_onboard():
            logger.warning(
                "\n"
                "  ╔══════════════════════════════════════════════════╗\n"
                "  ║   Welcome to Squire! Looks like a first run.    ║\n"
                "  ║   Run the setup wizard to get started in         ║\n"
                "  ║   about 3 minutes:                               ║\n"
                "  ║                                                  ║\n"
                "  ║     python -m squire onboard                     ║\n"
                "  ║                                                  ║\n"
                "  ╚══════════════════════════════════════════════════╝"
            )
        else:
            logger.error(
                "No LLM provider configured.\n"
                "Add at least one to .env — free options:\n"
                "  GROQ_API_KEY=...        (groq.com — free tier)\n"
                "  GEMINI_API_KEY=...      (aistudio.google.com — free tier)\n"
                "  DEEPSEEK_API_KEY=...    (platform.deepseek.com — very cheap)\n"
                "  OPENROUTER_API_KEY=...  (openrouter.ai — 100+ models)\n"
                "Or run Ollama locally for fully private, free AI.\n"
                "Tip: run `python -m squire onboard` for guided setup."
            )
        return
    logger.info(f"Active LLM providers: {', '.join(active.keys())}")

    # Load plugins
    try:
        from ram.core.plugin_registry import load_all_plugins
        plugin_count = load_all_plugins()
        if plugin_count:
            logger.info(f"Loaded {plugin_count} plugin(s)")
    except Exception as e:
        logger.debug(f"Plugin load: {e}")

    # Connect MCP servers
    try:
        from ram.core.mcp_client import load_mcp_servers
        mcp_count = load_mcp_servers()
        if mcp_count:
            logger.info(f"Registered {mcp_count} MCP tool(s)")
    except Exception as e:
        logger.debug(f"MCP client: {e}")

    registry.discover()
    agent = get_agent()
    handle = agent.handle

    # Sandbox mode
    if sandbox:
        from ram.core.sandbox import SandboxSession
        logger.warning("🏖️  SANDBOX MODE — no real actions will be taken")
        sb = SandboxSession()
        sb.__enter__()
        original_handle = handle
        async def sandboxed_handle(msg, user_id="cli"):
            return await original_handle(msg, user_id)
        handle = sandboxed_handle

    channels = []
    requested = {c.strip() for c in channels_arg.split(",")}
    want_all = "all" in requested

    from ram.channels.cli_channel import CLIChannel
    from ram.channels.discord_channel import DiscordChannel
    from ram.channels.telegram_channel import TelegramChannel
    from ram.channels.http_channel import HTTPChannel
    from ram.channels.whatsapp_channel import WhatsAppChannel
    from ram.channels.sms_channel import SMSChannel

    if want_all or "cli" in requested:
        channels.append(CLIChannel(handle))
    if want_all or "discord" in requested:
        channels.append(DiscordChannel(handle))
    if want_all or "telegram" in requested:
        channels.append(TelegramChannel(handle))
    if want_all or "http" in requested:
        channels.append(HTTPChannel(handle))
    if want_all or "whatsapp" in requested:
        channels.append(WhatsAppChannel(handle))
    if want_all or "sms" in requested:
        channels.append(SMSChannel(handle))

    if "tray" in requested:
        import threading
        from ram.channels.tray_channel import TrayChannel
        tray = TrayChannel()
        tray_thread = threading.Thread(target=tray.run, daemon=True)
        tray_thread.start()
        logger.info("Windows tray channel started")

    for ch in channels:
        register_channel(ch)

    def notify(user_id: str, text: str) -> None:
        for ch in channels:
            try:
                coro = ch.send(user_id, text)
                if asyncio.iscoroutine(coro):
                    asyncio.create_task(coro)
            except Exception as e:
                logger.warning(f"notify on {ch.name}: {e}")

    scheduler.start(notify)
    await asyncio.gather(*(ch.start() for ch in channels), return_exceptions=True)

    if any(ch.name != "cli" for ch in channels):
        stop = asyncio.Event()
        try:
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, stop.set)
                except NotImplementedError:
                    pass
            await stop.wait()
        except (KeyboardInterrupt, SystemExit):
            pass


@app.command()
def run(
    channel: str = typer.Option("cli", "--channel", "-c",
                                help="Comma-separated: cli,discord,telegram,http,whatsapp,sms,tray,all"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run in sandbox mode (no real-world actions)"),
):
    """Run Squire with the selected channels."""
    asyncio.run(_run(channel, sandbox=sandbox))


@app.command()
def skills():
    """List all registered skills."""
    registry.discover()
    for s in registry.all_skills():
        active = "✓" if all(getattr(settings, r.lower(), "") for r in s.requires) else "·"
        print(f"  {active} {s['name']}: {s['description']}")


@app.command()
def providers():
    """Show LLM providers + routing per task."""
    from ram.core.llm import list_providers, available_models, pick
    p = list_providers()
    print("== LLM Providers ==")
    for k, v in p.items():
        print(f"  [{'✓' if v else ' '}] {k}")
    active = sum(p.values())
    print(f"\n{active}/{len(p)} enabled")
    print("\n== Routing (best model per task) ==")
    for task in ("reasoning", "fast", "draft", "search", "vision", "embed", "code", "cheap", "private"):
        m = pick(task)
        print(f"  {task:<10} -> {m.provider+'/'+m.model if m else '(none)'}")


@app.command()
def doctor():
    """Run the Squire health and security audit."""
    from ram.core.doctor import run_doctor, format_report
    results = run_doctor()
    print(format_report(results))
    fails = sum(1 for r in results if r.status == "fail")
    raise SystemExit(1 if fails > 0 else 0)


@app.command()
def onboard():
    """Interactive first-run setup wizard.

    Guides you through choosing an AI provider, connecting Gmail/Calendar,
    setting up a messaging channel, and testing Squire — in about 3 minutes.
    No technical knowledge required.

    Examples:
        squire onboard               # Run the full wizard
    """
    from ram.core.onboarding_wizard import run_wizard
    run_wizard()


@app.command()
def mcp():
    """Start Squire as an MCP server (stdio transport).

    Use this to connect Squire tools to Claude Code, Cursor, Codex, etc.

    Add to .claude/settings.json:
        {"mcpServers": {"squire": {"command": "python", "args": ["-m", "squire", "mcp"]}}}
    """
    from ram.core.mcp_server import run_stdio_server
    registry.discover()
    run_stdio_server()


@app.command()
def plugin(
    action: str = typer.Argument(help="install | list | remove | check"),
    name:   str = typer.Argument(default="", help="Plugin name or path"),
):
    """Manage Squire plugins.

    Examples:
        squire plugin list
        squire plugin install ./my_plugin_dir
        squire plugin remove my_plugin
    """
    from ram.core.plugin_registry import (
        list_plugins, install_plugin_from_dir, remove_plugin, load_all_plugins
    )
    if action == "list":
        plugins = list_plugins()
        if not plugins:
            print("No plugins installed. Plugins go in ~/.squire/plugins/")
            return
        print(f"Installed plugins ({len(plugins)}):")
        for p in plugins:
            loaded = "✓" if p.get("_loaded") else "·"
            print(f"  {loaded} {p.get('name','?')} v{p.get('version','?')} — {p.get('description','')}")
    elif action == "install":
        if not name:
            print("Usage: squire plugin install <path>")
            return
        if install_plugin_from_dir(name):
            print(f"✅ Plugin installed: {name}")
        else:
            print(f"❌ Install failed — check that {name}/squire_plugin.json exists")
    elif action == "remove":
        if not name:
            print("Usage: squire plugin remove <name>")
            return
        if remove_plugin(name):
            print(f"✅ Plugin removed: {name}")
        else:
            print(f"Plugin not found: {name}")
    elif action == "check":
        count = load_all_plugins()
        print(f"Plugin check: {count} plugin(s) loaded successfully")
    else:
        print(f"Unknown action: {action}. Use: install | list | remove | check")


@app.command()
def backup():
    """Create a backup zip of the data directory."""
    from ram.core.backup import export_zip
    print(export_zip())


if __name__ == "__main__":
    app()
