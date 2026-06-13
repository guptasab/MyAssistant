"""Core agent loop: multi-provider LLM + tool use + memory.

Correctness hardening (competition-grade):
  • Sensitive tools → confirmation gate (user must say YES/NO before execution)
  • Every action → undo stack (5-min window) + audit log
  • Multi-step complex requests → plan-then-execute (numbered plan, user approves)
  • "undo" keyword → reverse last reversible action
  • "dry run" prefix → preview without executing

The agent is provider-agnostic. By default uses Anthropic (prompt caching +
best tool-use). Any provider in config/env activates as fallback.
"""
from __future__ import annotations

import asyncio
import json
import re
import traceback
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from myassistant.core import memory, registry
from myassistant.core.config import settings


SYSTEM_PROMPT_TEMPLATE = """You are {agent_name}, an always-on personal + family + professional life assistant by {agent_website}.

You carry the mental load across three life areas:
  • FAMILY   — kids, school, carpools, meals, household to-dos, shared calendar
  • PERSONAL — health, habits, journal, friends, finances, travel, wishlist
  • WORK     — projects, tasks, meetings, email triage, code, cloud infra, expenses

Channels: SMS, WhatsApp, Discord, Telegram, mobile PWA, Windows tray, CLI, HTTP, Alexa, Google Home.

─── Behaviour rules ───────────────────────────────────────────
1. READ before you WRITE. Always use a read/search tool first so you have facts,
   then act. Never guess at data that could be fetched.
2. CONFIRM before irreversible or external-facing actions:
   • sending email/replies, placing orders, calling/texting people
   • deleting data, schedule changes affecting others, large expenses
   • running shell commands, deploying code, modifying cloud resources
   A ConfirmationRequired response will be shown to the user automatically —
   you do NOT need to ask again; just call the sensitive tool and the framework
   handles the gate.
3. DRY-RUN mode: if the user message starts with "dry run" or "preview",
   describe what you WOULD do — don't call any mutating tools.
4. PLAN complex tasks: if a task requires >2 sequential sensitive steps,
   call `plan_task` first to draft a numbered plan, let the user approve,
   then execute step by step with progress updates.
5. UNDO: if user says "undo", call `undo_last_action`.
6. CODING: for any debug/fix/review task, start with reading code and logs
   before suggesting changes. Call `debug_prod` for "debug last call in prod".
7. Timezone: {tz}. Today is {today}.
8. Privacy: never share family data outside household.

Long-term memory about {owner}:
{facts}

Skills are provided as tools. Prefer a tool over guessing.
If a needed integration is missing, name the exact env var needed."""


@dataclass
class AgentReply:
    text: str
    audio_path: str | None = None
    actions_taken: list[str] = None
    pending_confirmation: bool = False

    def __post_init__(self):
        if self.actions_taken is None:
            self.actions_taken = []


# ── dry-run detection ──────────────────────────────────────────────────────
_DRY_RUN_RE = re.compile(r"^\s*(dry[\s_-]?run|preview|what would you do|simulate)\b", re.I)


class Agent:
    def __init__(self):
        self.client = None
        try:
            from anthropic import Anthropic
            if settings.anthropic_api_key:
                self.client = Anthropic(api_key=settings.anthropic_api_key)
        except ImportError:
            pass
        self.model = settings.myassistant_model_main

    def _system_blocks(self) -> list[dict]:
        facts = memory.all_facts()
        facts_str = "\n".join(f"- {k}: {v}" for k, v in facts.items()) or "(none yet)"
        text = SYSTEM_PROMPT_TEMPLATE.format(
            agent_name=settings.squire_agent_name,
            agent_website=settings.squire_agent_website,
            owner=settings.myassistant_owner_name,
            tz=settings.myassistant_timezone,
            today=datetime.now().strftime("%A, %B %d %Y %H:%M"),
            facts=facts_str,
        )
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def _tools(self, dry_run: bool = False) -> list[dict]:
        skills = registry.available_skills()
        if dry_run:
            # Exclude all sensitive tools in dry-run mode
            skills = [s for s in skills if not s.sensitive]
        tools = [s.to_anthropic_tool() for s in skills]
        if tools:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    # ── confirmation gate ──────────────────────────────────────────────────
    async def _check_pending_confirmation(self, user_id: str, user_text: str) -> AgentReply | None:
        """If user has a pending confirmation and just replied YES/NO, handle it."""
        from myassistant.core import confirm as conf
        pending = conf.get_pending(user_id)
        if not pending:
            return None
        decision = conf.parse_user_response(user_text)
        if decision is None:
            # Not a yes/no — re-show the prompt
            return AgentReply(
                text=f"Still waiting on your answer.\n\n{conf.prompt_text(pending)}",
                pending_confirmation=True,
            )
        result = conf.resolve(pending.id, decision)
        if not decision:
            try:
                from myassistant.core import audit
                audit.record(user_id, "cancel:" + pending.skill_name, json.loads(pending.args_json))
            except Exception:
                pass
            return AgentReply(text=f"✓ Cancelled — {pending.description} not executed.")

        # User said YES → execute
        sk = registry.get(pending.skill_name)
        if not sk:
            return AgentReply(text="ERROR: skill not found — action cancelled.")
        args = json.loads(pending.args_json)
        try:
            logger.info(f"[confirmed] running {pending.skill_name}({args})")
            out = sk.func(**args)
            if asyncio.iscoroutine(out):
                out = await out
            out = str(out)[:3000]
        except Exception as e:
            out = f"ERROR: {e}\n{traceback.format_exc()[-400:]}"

        # Push to undo stack
        try:
            from myassistant.core import undo as undo_mod
            undo_mod.push(user_id, pending.skill_name, pending.description, reversible=False)
        except Exception:
            pass
        try:
            from myassistant.core import audit
            audit.record(user_id, pending.skill_name, args, result=out[:200])
        except Exception:
            pass

        memory.append_message(user_id, "user", f"[confirmed {pending.skill_name}]")
        # Feed result back through the agent for a natural reply
        history = memory.recent_messages(user_id, limit=20)
        history.append({"role": "user", "content":
            f"Action completed. Result: {out}\nSummarise in 1-2 sentences."})
        if self.client:
            try:
                resp = await asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model, max_tokens=300,
                    system=self._system_blocks(), messages=history,
                )
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                return AgentReply(text=text or out, actions_taken=[pending.skill_name])
            except Exception:
                pass
        return AgentReply(text=f"✓ Done: {out}", actions_taken=[pending.skill_name])

    # ── undo handler ──────────────────────────────────────────────────────
    async def _handle_undo(self, user_id: str) -> AgentReply | None:
        from myassistant.core import undo as undo_mod
        entry = undo_mod.pop(user_id)
        if not entry:
            return AgentReply(text="Nothing recent to undo (either nothing was done, "
                                   "it's been > 5 min, or the action wasn't reversible).")
        if not entry.undo_skill:
            return AgentReply(text=f"'{entry.description}' can't be automatically undone — "
                                   f"it was marked irreversible. Check the audit log for details.")
        sk = registry.get(entry.undo_skill)
        if not sk:
            return AgentReply(text=f"Undo skill '{entry.undo_skill}' not found.")
        args = json.loads(entry.undo_args_json)
        try:
            out = sk.func(**args)
            if asyncio.iscoroutine(out):
                out = await out
            return AgentReply(text=f"↩️ Undone: {entry.description}\n{out}")
        except Exception as e:
            return AgentReply(text=f"Undo failed: {e}")

    # ── sensitive tool interception ────────────────────────────────────────
    async def _run_tool(self, name: str, args: dict, user_id: str,
                        dry_run: bool = False) -> tuple[str, bool]:
        """Returns (result, was_intercepted_for_confirmation)."""
        sk = registry.get(name)
        if not sk:
            return f"ERROR: unknown skill {name}", False

        if dry_run and sk.sensitive:
            return f"[DRY RUN] Would call {name}({json.dumps(args)[:200]})", False

        if sk.sensitive:
            # Intercept — gate on confirmation
            from myassistant.core import confirm as conf

            # Try to get a human description from the skill
            desc = _describe_action(name, args)

            # Attempt a dry-run preview if the skill supports it
            dry_preview = ""
            try:
                dry_args = {**args, "dry_run": True}
                if "dry_run" in sk.func.__code__.co_varnames:
                    dr = sk.func(**dry_args)
                    if asyncio.iscoroutine(dr):
                        dr = await dr
                    dry_preview = str(dr)[:400]
            except Exception:
                pass

            pending = conf.create(user_id, name, args, desc, dry_preview)
            return conf.prompt_text(pending), True  # intercepted

        # Normal (non-sensitive) execution
        try:
            logger.info(f"-> tool {name}({args})")
            try:
                from myassistant.core import audit
                audit.record(user_id, name, args)
            except Exception:
                pass
            result = sk.func(**args)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)[:8000], False
        except Exception as e:
            logger.exception(f"skill {name} failed")
            return f"ERROR running {name}: {e}\n{traceback.format_exc()[-500:]}", False

    async def _agent_loop_anthropic(self, history: list[dict], actions: list[str],
                                    user_id: str, dry_run: bool = False) -> AgentReply:
        for _ in range(12):
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model, max_tokens=3000,
                system=self._system_blocks(), tools=self._tools(dry_run),
                messages=history,
            )
            asst_blocks = [b.model_dump() for b in resp.content]
            history.append({"role": "assistant", "content": asst_blocks})
            memory.append_message(user_id, "assistant", asst_blocks)

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                return AgentReply(text=text or "(no response)", actions_taken=actions)

            tool_results = []
            intercepted_any = False
            for tu in tool_uses:
                out, intercepted = await self._run_tool(tu.name, tu.input, user_id, dry_run)
                if intercepted:
                    intercepted_any = True
                    # Return the confirmation prompt immediately — stop the loop
                    return AgentReply(
                        text=out,
                        actions_taken=actions,
                        pending_confirmation=True,
                    )
                actions.append(f"{tu.name}({json.dumps(tu.input)[:120]})")
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
            history.append({"role": "user", "content": tool_results})

        return AgentReply(text="(stopped after 12 tool-call rounds)", actions_taken=actions)

    def _gemini_tools(self, dry_run: bool = False):
        """Convert skills to Gemini function declarations.
        Only include skills that have actual integrations configured, plus always-on
        built-in skills (kb, memory, canvas, tasks, etc.) that need no credentials.
        """
        from google.genai import types as gtypes
        from myassistant.core.config import settings as cfg
        all_skills = registry.available_skills()
        if dry_run:
            all_skills = [s for s in all_skills if not s.sensitive]

        # Skills that require credentials: only include if those creds are set
        # Skills with no requires: only include core built-ins to keep the list small
        ALWAYS_INCLUDE_PREFIXES = (
            "kb_", "remember", "recall", "forget", "memory", "canvas_",
            "list_tasks", "add_task", "complete_task", "update_task",
            "onboarding", "what_can_you_do", "notify_owner",
            "web_search", "weather", "news_",
        )
        skills = []
        for s in all_skills:
            if s.requires:
                # Has dependencies — registry already verified creds exist
                skills.append(s)
            elif any(s.name.startswith(p) for p in ALWAYS_INCLUDE_PREFIXES):
                skills.append(s)
        # Hard cap to avoid Gemini timeouts
        skills = skills[:128]
        declarations = []
        for s in skills:
            at = s.to_anthropic_tool()
            schema = at.get("input_schema", {})
            props = {}
            for k, v in schema.get("properties", {}).items():
                t = v.get("type", "string")
                gtype = {
                    "string": "STRING", "integer": "INTEGER", "number": "NUMBER",
                    "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT",
                }.get(t, "STRING")
                if gtype == "ARRAY":
                    item_type = v.get("items", {}).get("type", "string")
                    item_gtype = {
                        "string": "STRING", "integer": "INTEGER", "number": "NUMBER",
                        "boolean": "BOOLEAN",
                    }.get(item_type, "STRING")
                    props[k] = gtypes.Schema(
                        type="ARRAY",
                        description=v.get("description", ""),
                        items=gtypes.Schema(type=item_gtype),
                    )
                else:
                    props[k] = gtypes.Schema(type=gtype, description=v.get("description", ""))
            declarations.append(gtypes.FunctionDeclaration(
                name=at["name"],
                description=at.get("description", ""),
                parameters=gtypes.Schema(
                    type="OBJECT",
                    properties=props,
                    required=schema.get("required", []),
                ) if props else None,
            ))
        return [gtypes.Tool(function_declarations=declarations)] if declarations else []

    async def _agent_loop_router(self, history: list[dict], actions: list[str],
                                  user_id: str, dry_run: bool = False) -> AgentReply:
        """Gemini-native tool-use loop — used when no Anthropic key is configured."""
        from myassistant.core.config import settings as cfg
        key = getattr(cfg, "google_api_key", "") or getattr(cfg, "gemini_api_key", "")
        if not key:
            # Pure text fallback if no Gemini key either
            from myassistant.core.llm import llm_chat
            msgs = []
            for m in history:
                c = m["content"]
                txt = c if isinstance(c, str) else " ".join(
                    b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"
                )
                if txt:
                    msgs.append({"role": m["role"], "content": txt})
            sys_text = self._system_blocks()[0]["text"]
            out = await asyncio.to_thread(llm_chat, msgs, task="reasoning", system=sys_text, max_tokens=1024)
            return AgentReply(text=out, actions_taken=actions)

        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=key).aio  # use async client — no thread blocking
        sys_text = self._system_blocks()[0]["text"]
        tools = self._gemini_tools(dry_run)

        # Build contents list from history, enforcing alternating user/model turns
        def _to_contents(hist):
            contents = []
            last_role = None
            for m in hist:
                role = "user" if m["role"] == "user" else "model"
                # Skip consecutive same-role turns — Gemini requires strict alternation
                if role == last_role:
                    continue
                c = m["content"]
                if isinstance(c, str):
                    if c.strip():
                        contents.append(gtypes.Content(role=role, parts=[gtypes.Part(text=c)]))
                        last_role = role
                elif isinstance(c, list):
                    parts = []
                    for b in c:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text" and b.get("text", "").strip():
                            parts.append(gtypes.Part(text=b["text"]))
                        elif b.get("type") == "tool_use":
                            parts.append(gtypes.Part(function_call=gtypes.FunctionCall(
                                name=b["name"], args=b.get("input", {})
                            )))
                        elif b.get("type") == "tool_result":
                            parts.append(gtypes.Part(function_response=gtypes.FunctionResponse(
                                name=b.get("tool_use_id", "tool"),
                                response={"result": str(b.get("content", ""))},
                            )))
                    if parts:
                        contents.append(gtypes.Content(role=role, parts=parts))
                        last_role = role
            return contents

        gcfg = gtypes.GenerateContentConfig(
            system_instruction=sys_text,
            tools=tools,
            max_output_tokens=3000,
        )

        contents = _to_contents(history)

        last_tool_output = ""
        for _ in range(12):
            try:
                resp = await asyncio.wait_for(
                    client.models.generate_content(
                        model="gemini-3.5-flash",
                        contents=contents,
                        config=gcfg,
                    ),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning("Gemini call timed out after 30s")
                return AgentReply(text=last_tool_output or "(request timed out — please try again)", actions_taken=actions)

            # Check for function calls
            fn_calls = [p.function_call for p in resp.candidates[0].content.parts
                        if hasattr(p, "function_call") and p.function_call]

            if not fn_calls:
                text = "".join(
                    p.text for p in resp.candidates[0].content.parts
                    if hasattr(p, "text") and p.text
                ).strip()
                return AgentReply(text=text or last_tool_output or "(no response)", actions_taken=actions)

            # Append model turn
            contents.append(resp.candidates[0].content)

            # Execute each function call and append results; loop back for text response
            fn_results = []
            for fc in fn_calls:
                args = dict(fc.args) if fc.args else {}
                out, intercepted = await self._run_tool(fc.name, args, user_id, dry_run)
                if intercepted:
                    return AgentReply(text=out, actions_taken=actions, pending_confirmation=True)
                actions.append(f"{fc.name}({json.dumps(args)[:120]})")
                last_tool_output = str(out)
                fn_results.append(gtypes.Part(function_response=gtypes.FunctionResponse(
                    name=fc.name,
                    response={"result": last_tool_output},
                )))

            contents.append(gtypes.Content(role="user", parts=fn_results))

        return AgentReply(text=last_tool_output or "(stopped after 12 rounds)", actions_taken=actions)

    async def handle(self, user_id: str, user_text: str) -> AgentReply:
        # ── undo shortcut ──────────────────────────────────────────────────
        if re.match(r"^\s*undo\b", user_text, re.I):
            return await self._handle_undo(user_id)

        # ── confirmation resolution ────────────────────────────────────────
        reply = await self._check_pending_confirmation(user_id, user_text)
        if reply is not None:
            return reply

        # ── direct skill shortcut: "skill_name" or "skill_name arg=val" ──────
        _direct = _parse_direct_skill(user_text)
        if _direct:
            sk_name, sk_args = _direct
            out, intercepted = await self._run_tool(sk_name, sk_args, user_id)
            if not intercepted:
                memory.append_message(user_id, "user", user_text)
                memory.append_message(user_id, "assistant", out)
                return AgentReply(text=out, actions_taken=[f"{sk_name}({json.dumps(sk_args)[:80]})"])

        # ── dry-run detection ──────────────────────────────────────────────
        dry_run = bool(_DRY_RUN_RE.match(user_text))

        # ── persist incoming message (incognito-aware) ─────────────────────
        memory.append_message(user_id, "user", user_text)

        # ── load history: recent messages + compressed summaries ───────────
        history = memory.recent_messages(user_id)

        # Prepend last 3 conversation summaries so old context isn't lost
        summaries = memory.get_summaries(user_id)
        if summaries:
            summary_text = "## Previous conversation summaries\n" + "\n\n".join(
                f"[{s['from_date']} -> {s['to_date']}] {s['summary']}"
                for s in summaries[-3:]
            )
            history = [
                {"role": "user",      "content": summary_text},
                {"role": "assistant", "content": "(Noted — I have context from previous sessions.)"},
                *history,
            ]

        actions: list[str] = []

        # ── dispatch to LLM ────────────────────────────────────────────────
        if self.client:
            try:
                result = await self._agent_loop_anthropic(history, actions, user_id, dry_run)
                if settings.memory_auto_learn and not memory.is_incognito(user_id):
                    asyncio.create_task(_bg_extract_facts(user_id))
                return result
            except Exception as e:
                logger.warning(f"anthropic agent loop failed, falling back to router: {e}")

        from myassistant.core.llm import list_providers
        if not any(list_providers().values()):
            return AgentReply(text=(
                "(MyAssistant has no LLM provider configured — set ANTHROPIC_API_KEY "
                "or any of OPENAI/GEMINI/AZURE/etc.)"
            ))
        result = await self._agent_loop_router(history, actions, user_id, dry_run)

        if settings.memory_auto_learn and not memory.is_incognito(user_id):
            asyncio.create_task(_bg_extract_facts(user_id))

        return result


async def _bg_extract_facts(user_id: str) -> None:
    """Run auto-fact extraction in the background so it doesn't block the reply."""
    try:
        memory.auto_extract_facts(user_id)
    except Exception as exc:
        logger.debug(f"auto_extract_facts background task failed: {exc}")


def _describe_action(skill_name: str, args: dict) -> str:
    """Convert a skill call into plain English for the confirmation prompt."""
    templates = {
        "send_email": "Send an email to {to} — subject: {subject}",
        "voice_call_say": "Call {to_number} and say: {message}",
        "voice_call_ivr": "Call {to_number} with IVR",
        "group_text": "Group-text all {role} members: {message}",
        "imessage_send": "Send iMessage to {chat_guid}: {text}",
        "ha_call": "Home Assistant: {domain}.{service} on {entity_id}",
        "plaid_sync_transactions": "Sync Plaid transactions (last {days} days)",
        "ooo_autoresponder": "Set Gmail OOO {start} → {end}",
        "auto_rsvp": "RSVP {response} to calendar event {event_id}",
        "vault_store": "Store secret '{name}' in vault",
        "vault_reveal": "Reveal vault secret '{name}'",
        "print_text": "Print: {title}",
        "exec_shell": "Run shell command: {command}",
        "git_commit": "Git commit with message: {message}",
        "git_push": "Git push {branch}",
        "github_create_issue": "Open GitHub issue in {repo}: {title}",
        "github_comment": "Comment on {repo}#{number}",
        "linear_create_issue": "Create Linear issue in {team_key}: {title}",
        "notion_create_page": "Create Notion page: {title}",
        "doordash_draft_order": "Order from {restaurant} on DoorDash",
    }
    tmpl = templates.get(skill_name)
    if tmpl:
        try:
            return tmpl.format(**{k: str(v)[:60] for k, v in args.items()})
        except Exception:
            pass
    arg_summary = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:3])
    return f"{skill_name}({arg_summary})"


def _parse_direct_skill(text: str) -> tuple[str, dict] | None:
    """If text is exactly a skill name (optionally with key=val args), return (name, args).
    Examples: "kb_status", "kb_search query=divorce", "kb_ingest folder_path=C:/docs"
    Returns None if not a direct skill invocation.
    """
    text = text.strip()
    # Must start with a known skill name (word chars + underscores)
    m = re.match(r'^([a-z][a-z0-9_]+)(.*)?$', text, re.I)
    if not m:
        return None
    candidate = m.group(1)
    sk = registry.get(candidate)
    if not sk:
        return None
    # Parse optional key=value pairs
    args = {}
    rest = (m.group(2) or "").strip()
    if rest:
        for pair in re.finditer(r'(\w+)=("([^"]*?)"|\'([^\']*?)\'|(\S+))', rest):
            k = pair.group(1)
            v = pair.group(3) or pair.group(4) or pair.group(5) or ""
            args[k] = v
    return candidate, args


_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent

