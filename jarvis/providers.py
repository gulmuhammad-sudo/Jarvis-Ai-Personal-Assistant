"""Multi-provider brain: local AI (Ollama), Gemini, Groq, OpenRouter, DeepSeek (and optionally Claude), with fallback.

Local AI goes first when Ollama is running with a suitable model (Settings: "Prefer local AI"), so the assistant
works offline and nothing leaves the PC; cloud providers are the backup (or the other way round if you prefer).

JARVIS_PROVIDERS in .env sets the order. Jarvis asks the first provider that is
configured; if it fails (limit hit, bad key, offline) *before doing anything on the
PC*, the same message goes to the next provider. Each provider keeps its own
conversation, and turns answered by other providers are passed along as context.
"""
from __future__ import annotations

import json
import os
import re
import socket
import time
from typing import Callable

from . import languages, local_ai, schedule, tools
from .brain import VOICE_OFF_NOTE, system_prompt, VOICE_ON_NOTE, ProviderError, make_claude
from .config import provider_order

# name: (label, base_url, key env var, model env var, models to try in order, can see images)
# The model env var may also hold a comma-separated list.
OPENAI_COMPATIBLE = {
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
               "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-3.5-flash-lite,gemini-3.5-flash,gemini-flash-lite-latest", True),
    "groq": ("Groq", "https://api.groq.com/openai/v1",
             "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b,openai/gpt-oss-20b", False),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1",
                   "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
                   "nvidia/nemotron-3.5-super-vl:free,nvidia/nemotron-3-ultra-550b-a55b:free,inclusionai/ling-3.2-flash:free", True),
    "deepseek": ("DeepSeek", "https://api.deepseek.com",
                 "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-chat", False),
}
MAX_STEPS = 25
KEEP_MESSAGES = 30          # history kept per provider (free tiers have small token limits)
URDU_NOTE = """
URDU MODE IS ON: the user is speaking to you in Urdu. Always reply in natural, simple Urdu written in Urdu script
(for example: “جی سر، میں نے الارم لگا دیا ہے۔”). Your reply is read aloud by an Urdu voice, so keep it short and conversational,
with no markdown. Keep app names, numbers and technical terms in English letters only when that is clearer.
"""
ENGLISH_NOTE = """
ENGLISH MODE: reply in English again (or Roman Urdu if the user writes in Roman Urdu).
"""
TOOL_DISCIPLINE = """
Tool rules (important):
- Saying you did something is not doing it. To act (set a timer, open an app, save a note...), you must call the tool.
- Call every tool you need first, and only write your reply once all tool results are back.
- Only report an action as done if its tool result in this conversation confirms it.
"""


def _retry_after(e) -> float | None:
    try:
        return float(e.response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        m = re.search(r"try again in ([\d.]+)s", str(e))
        return float(m.group(1)) if m else None


class OpenAICompatBrain:
    """Gemini / Groq / DeepSeek through their OpenAI-compatible chat APIs, with Jarvis's tools."""

    def __init__(self, name: str, ctx: tools.ToolContext,
                 on_text: Callable[[str], None], on_tool: Callable[[str, dict], None]):
        import openai
        self.openai = openai
        label, base_url, key_env, model_env, default_model, vision = OPENAI_COMPATIBLE[name]
        self.label, self.vision = label, vision
        self.models = [m.strip() for m in (os.environ.get(model_env) or default_model).split(",") if m.strip()]
        self.model = self.models[0]
        self.client = openai.OpenAI(api_key=os.environ[key_env], base_url=base_url,
                                    max_retries=1, timeout=60)
        self.ctx, self.on_text, self.on_tool = ctx, on_text, on_tool
        defs = tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS
        self.tool_defs = [{"type": "function", "function": {
            "name": d["name"], "description": d["description"], "parameters": d["input_schema"]}}
            for d in defs]
        self.messages: list[dict] = []
        self._note: str | None = None
        self.language = "en"   # "ur" adds the Urdu instructions to every request
        self.reset()

    def reset(self) -> None:
        self.system = system_prompt() + TOOL_DISCIPLINE
        self.messages = []

    def set_voice_mode(self, on: bool) -> None:
        self._note = VOICE_ON_NOTE if on else VOICE_OFF_NOTE

    def _trim(self) -> None:
        # Drop old screenshots (they are huge) and keep the recent history only,
        # always starting at a plain user message so tool calls stay paired with results.
        for m in self.messages[:-1]:
            if m["role"] == "user" and isinstance(m.get("content"), list):
                m["content"] = "[an earlier screenshot was shown here]"
        if len(self.messages) > KEEP_MESSAGES:
            cut = len(self.messages) - KEEP_MESSAGES
            while cut < len(self.messages) and not (
                    self.messages[cut]["role"] == "user" and isinstance(self.messages[cut]["content"], str)):
                cut += 1
            self.messages = self.messages[cut:]

    def ask(self, user_text: str) -> str:
        """Try each of this provider's models in turn until one answers."""
        start = self.models.index(self.model) if self.model in self.models else 0
        order = self.models[start:] + self.models[:start]  # the last model that worked goes first
        for i, model in enumerate(order):
            self.model = model
            try:
                return self._ask_once(user_text)
            except ProviderError as e:
                if getattr(e, "acted", False) or getattr(e, "permanent", False) or i + 1 == len(order):
                    raise
        raise ProviderError(f"{self.label}: no model available")

    def _create(self):
        """One model call, riding out short per-minute limits, malformed tool calls and "request too large"."""
        tool_defs = self.tool_defs
        for attempt in range(3):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": self.system + (URDU_NOTE if self.language == "ur" else languages.reply_note(self.language))}] + self.messages,
                    tools=tool_defs)
            except self.openai.RateLimitError as e:
                wait = _retry_after(e)
                if wait is None or wait > 20 or attempt == 2:
                    raise
                time.sleep(wait + 0.5)  # e.g. Groq's tokens-per-minute window: wait it out
            except self.openai.BadRequestError as e:
                if "tool" not in str(e).lower() or attempt == 2:
                    raise
                # The model produced an invalid tool call (e.g. a misspelt tool name): ask again.
            except self.openai.APIStatusError as e:
                slim = self._everyday_tools()
                if e.status_code != 413 or attempt == 2 or len(slim) >= len(tool_defs):
                    raise
                tool_defs = slim                 # too large for this service's free limit: only the everyday tools

    def _everyday_tools(self) -> list[dict]:
        """The tools a small request keeps: the everyday ones, and those already in use in this conversation."""
        used = {c["function"]["name"] for m in self.messages if m.get("role") == "assistant" for c in m.get("tool_calls") or []}
        keep = set(LOCAL_TOOLS) | used | {"make_plan", "plan_step", "manage_windows", "set_brightness", "delegate"}
        return [d for d in self.tool_defs if d["function"]["name"] in keep]

    def _ask_once(self, user_text: str) -> str:
        checkpoint = len(self.messages)
        content = f"[{self._note}]\n\n{user_text}" if self._note else user_text
        self.messages.append({"role": "user", "content": content})
        acted = False
        final = ""
        try:
            for _ in range(getattr(self, "max_steps", MAX_STEPS)):
                if tools.STOP.is_set():                  # you pressed Stop: no more steps
                    self._note = None
                    final = "Okay, I stopped."
                    self.on_text(final)
                    return final
                resp = self._create()
                if not resp.choices:
                    raise ProviderError(f"{self.label} returned an empty response")
                msg = resp.choices[0].message
                self.messages.append(msg.model_dump(exclude_none=True))
                if msg.content and msg.content.strip():
                    final = msg.content.strip()
                    self.on_text(final)
                if not msg.tool_calls:
                    self._note = None
                    return final

                images = []
                for call in msg.tool_calls:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = None
                    if not isinstance(args, dict):
                        result, is_error = "Invalid JSON arguments; please retry the call.", True
                    else:
                        self.on_tool(call.function.name, args)
                        acted = True
                        result, is_error = tools.execute(call.function.name, args, self.ctx, True)
                    if isinstance(result, list):  # screenshot: text + image blocks
                        text = " ".join(b.get("text", "") for b in result if b.get("type") == "text")
                        if self.vision:
                            images += [b for b in result if b.get("type") == "image"]
                            text += " The image follows in the next message."
                        else:
                            text += " (This model can't view images, so describe that limitation to the user.)"
                        result = text
                    self.messages.append({"role": "tool", "tool_call_id": call.id,
                                          "content": ("ERROR: " if is_error else "") + str(result)})
                if images:
                    self.messages.append({"role": "user", "content": [
                        {"type": "text", "text": "Here is the screenshot you requested:"},
                        *[{"type": "image_url", "image_url": {
                            "url": f"data:{b['source']['media_type']};base64,{b['source']['data']}"}}
                          for b in images]]})
            msg = "That took more steps than I allow myself in one go. Shall I keep going?"
            self.on_text(msg)
            return msg
        except ProviderError:
            self.messages = self.messages[:checkpoint]
            raise
        except (self.openai.APIConnectionError, self.openai.APIStatusError) as e:
            self.messages = self.messages[:checkpoint]
            status = getattr(e, "status_code", None)
            reason = {401: "the API key was rejected", 403: "access was denied",
                      404: f"model '{self.model}' wasn't found", 429: "its free limit was hit"}.get(
                status, f"error {status}" if status else "it couldn't be reached")
            err = ProviderError(f"{self.label} ({self.model}): {reason}")
            err.acted = acted
            err.permanent = status in (401, 403)  # bad key: don't keep retrying this provider
            raise err
        finally:
            self._trim()


# A small local model gets the everyday tools only: all ~47 tool descriptions would fill its context.
LOCAL_TOOLS = ("get_datetime", "system_status", "open_website", "search_web_in_browser", "open_application",
               "open_path", "find_files", "read_text_file", "save_note", "list_notes", "remember_fact",
               "recall_memories", "set_timer", "list_timers", "cancel_timer", "media_control", "clipboard",
               "web_search", "fetch_webpage", "get_weather", "play_youtube", "set_alarm", "list_alarms",
               "close_app", "take_screenshot", "write_file", "tasks", "calendar", "notes")


def prefer_local() -> bool:
    return schedule.get_setting("prefer_local", True) is not False


class OllamaBrain:
    """Local AI through Ollama's /api/chat, with the same tool loop as the cloud providers."""

    def __init__(self, ctx: tools.ToolContext, on_text: Callable[[str], None], on_tool: Callable[[str, dict], None],
                 model: str):
        self.label, self.ctx, self.on_text, self.on_tool = "Local AI", ctx, on_text, on_tool
        have = local_ai.models()
        self.models = [m["name"] for m in have if m["tools"]] or [model]
        self.model = model
        self.vision = any(m["name"] == model and m["vision"] for m in have)
        defs = [d for d in tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS if d["name"] in LOCAL_TOOLS]
        self.tool_defs = [{"type": "function", "function": {"name": d["name"], "description": d["description"],
                                                            "parameters": d["input_schema"]}} for d in defs]
        self.language = "en"
        self._note: str | None = None
        self.reset()

    def reset(self) -> None:
        self.system = system_prompt() + TOOL_DISCIPLINE
        self.messages: list[dict] = []

    def set_voice_mode(self, on: bool) -> None:
        self._note = VOICE_ON_NOTE if on else VOICE_OFF_NOTE

    def ask(self, user_text: str) -> str:
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": f"[{self._note}]\n\n{user_text}" if self._note else user_text})
        system = self.system + (URDU_NOTE if self.language == "ur" else languages.reply_note(self.language))
        acted, final = False, ""
        try:
            for _ in range(getattr(self, "max_steps", MAX_STEPS)):
                if tools.STOP.is_set():
                    final = "Okay, I stopped."
                    self.on_text(final)
                    return final
                msg = local_ai.chat(self.model, [{"role": "system", "content": system}] + self.messages, self.tool_defs)
                calls = msg.get("tool_calls") or []
                content = (msg.get("content") or "").strip()
                self.messages.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
                if not calls:
                    final = content or "(no answer)"
                    self.on_text(final)
                    self._note = None
                    return final
                for call in calls:
                    fn = call.get("function") or {}
                    name, args = fn.get("name", ""), fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = None
                    if not isinstance(args, dict) or name not in LOCAL_TOOLS:
                        result, err = f"Can't use {name!r} here; use one of the listed tools.", True
                    else:
                        self.on_tool(name, args)
                        acted = True
                        result, err = tools.execute(name, args, self.ctx, True)
                    if isinstance(result, list):         # a screenshot: a text-only model can't look at it
                        result = " ".join(b.get("text", "") for b in result if b.get("type") == "text") + \
                                 " (This local model can't see images.)"
                    self.messages.append({"role": "tool", "tool_name": name,
                                          "content": ("ERROR: " if err else "") + str(result)[:8000]})
            final = "That took more steps than I allow myself in one go. Shall I keep going?"
            self.on_text(final)
            return final
        except (OSError, ValueError) as e:           # Ollama stopped, or the model isn't there any more
            self.messages = self.messages[:checkpoint]
            err = ProviderError(f"Local AI ({self.model}): {type(e).__name__}: {str(e)[:120]}")
            err.acted = acted
            raise err
        finally:
            if len(self.messages) > KEEP_MESSAGES:
                cut = len(self.messages) - KEEP_MESSAGES
                while cut < len(self.messages) and self.messages[cut]["role"] != "user":
                    cut += 1
                self.messages = self.messages[cut:]


# ---------------- routing: which AI gets this message ----------------
# Words that mean "look at something" (English, Roman Urdu, Urdu script): send it to an AI that can see images.
_VISION = re.compile(r"\b(?:(?:screen|image|picture|photo|dekh|tasveer|tasvir|tasweer)\w*|pics?\b|look at|see this|"
                     r"what'?s on)|"
                     r"اسکرین|سکرین|تصویر|دیکھو|دیکھیں|دیکھ", re.I)
_net = {"at": 0.0, "up": True}


def needs_vision(text: str) -> bool:
    return bool(_VISION.search(text or ""))


def online(timeout: float = 1.5) -> bool:
    """Is there an internet connection? (One quick TCP connect, remembered for 20 s.)"""
    if time.time() - _net["at"] < 20:
        return _net["up"]
    up = False
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            socket.create_connection(host, timeout=timeout).close()
            up = True
            break
        except OSError:
            pass
    _net.update(at=time.time(), up=up)
    return up


def route(backends: list[tuple[str, object]], text: str) -> tuple[list[tuple[str, object]], str]:
    """The AIs to try for this message, in order, and why (\"\" = the normal order)."""
    order, why = list(backends), ""
    has_cloud = any(label != "Local AI" for label, _ in order)
    if has_cloud and not online():
        local = [(l, b) for l, b in order if l == "Local AI"]
        return local, "no internet: using the AI on this PC"
    if order and needs_vision(text) and not getattr(order[0][1], "vision", False):
        seeing = [(l, b) for l, b in order if getattr(b, "vision", False)]
        if seeing:
            order = seeing + [(l, b) for l, b in order if not getattr(b, "vision", False)]
            why = f"needs to see: {seeing[0][0]} can look at images"
    return order, why


def chain() -> list[str]:
    """Providers to try, in order: JARVIS_PROVIDERS, with local AI first (or last) unless it's listed there."""
    names = provider_order()
    if "ollama" not in names:
        names = ["ollama", *names] if prefer_local() else [*names, "ollama"]
    return names


class MultiBrain:
    """Routes each message through the provider chain, falling back on failure."""

    def __init__(self, ctx: tools.ToolContext,
                 on_text: Callable[[str], None], on_tool: Callable[[str, dict], None],
                 on_provider: Callable[[str], None] | None = None):
        self.on_text, self.on_tool = on_text, on_tool
        self.on_provider = on_provider or (lambda label: None)
        self.current = ""
        self._acted = False
        self.turns: list[tuple[str, str]] = []  # (user, reply) across all providers
        self.backends: list[tuple[str, object]] = []
        self.seen: dict[str, int] = {}
        self.skipped: list[str] = []
        self.down: dict[str, str] = {}      # label -> reason (removed for this session)
        self.limited: dict[str, str] = {}   # label -> last temporary error

        for name in chain():
            try:
                if name == "ollama":
                    model = local_ai.pick_model() if local_ai.running() else None
                    if not model:
                        continue                       # Ollama not running / no suitable model: skip quietly
                    backend = OllamaBrain(ctx, self._text, self._tool, model)
                    label = backend.label
                elif name == "claude":
                    backend = make_claude(ctx, self._text, self._tool)
                    if backend is None:                          # no ANTHROPIC_API_KEY
                        self.skipped.append("Claude (no ANTHROPIC_API_KEY)")
                        continue
                    label = "Claude"
                elif name in OPENAI_COMPATIBLE:
                    if not os.environ.get(OPENAI_COMPATIBLE[name][2]):
                        continue  # no key for this provider: skip silently
                    backend = OpenAICompatBrain(name, ctx, self._text, self._tool)
                    label = backend.label
                else:
                    self.skipped.append(f"{name} (unknown provider)")
                    continue
            except Exception as e:  # a broken provider must not stop Jarvis starting
                self.skipped.append(f"{name} ({e})")
                continue
            self.backends.append((label, backend))
            self.seen[label] = 0
        self.order = [label for label, _ in self.backends]      # the .env order ("Automatic")
        self.preferred = ""                                     # "" = automatic

    @property
    def names(self) -> list[str]:
        return [label for label, _ in self.backends]

    def _text(self, text: str) -> None:
        self.on_text(text)

    def _tool(self, name: str, args: dict) -> None:
        self._acted = True
        self.on_tool(name, args)

    def reset(self) -> None:
        self.turns.clear()
        for label, b in self.backends:
            b.reset()
            self.seen[label] = 0

    def use(self, label: str | None, model: str | None = None) -> str:
        """Talk to this AI first (the others stay as backups). None / "auto" = the .env order."""
        by_label = {l.lower(): (l, b) for l, b in self.backends}
        if not label or label.lower() in ("auto", "automatic"):
            self.backends.sort(key=lambda lb: self.order.index(lb[0]) if lb[0] in self.order else 99)
            self.preferred = ""
            self.current = self.backends[0][0] if self.backends else ""
            self.on_provider(self.current)
            return f"Automatic: {' → '.join(l for l, _ in self.backends)}."
        hit = by_label.get(label.lower()) or next((v for k, v in by_label.items() if k.startswith(label.lower()[:4])), None)
        if not hit:
            raise ValueError(f"{label} isn't available. Connected: {', '.join(self.names) or 'none'}.")
        lab, backend = hit
        if model:
            models = getattr(backend, "models", [])
            if model not in models:
                raise ValueError(f"{lab} has no model {model}. Choose from: {', '.join(models)}.")
            backend.model = model
        self.backends.sort(key=lambda lb: (lb[0] != lab, self.order.index(lb[0]) if lb[0] in self.order else 99))
        self.preferred = self.current = lab
        self.on_provider(lab)
        return f"Now using {lab}" + (f" ({getattr(backend, 'model', '')})" if getattr(backend, "model", "") else "") + "."

    def options(self) -> dict:
        return {"preferred": self.preferred or "auto",
                "providers": [{"label": l, "models": list(getattr(b, "models", [])), "model": getattr(b, "model", "")}
                              for l, b in sorted(self.backends, key=lambda lb: self.order.index(lb[0]) if lb[0] in self.order else 99)]}

    def refresh_system(self) -> None:
        """The profile or memories changed: rebuild the instructions, keeping the conversation."""
        for _, b in self.backends:
            if isinstance(b, (OpenAICompatBrain, OllamaBrain)):
                b.system = system_prompt() + TOOL_DISCIPLINE
            elif hasattr(b, "system") and not hasattr(b, "_pending_note"):     # Anthropic API backend
                b.system = system_prompt()

    def set_voice_mode(self, on: bool) -> None:
        for _, b in self.backends:
            b.set_voice_mode(on)

    def set_language(self, lang: str) -> None:
        """'ur' = reply in Urdu (Urdu script, for the Urdu voice); 'en' = English."""
        note = URDU_NOTE if lang == "ur" else (languages.reply_note(lang) or ENGLISH_NOTE)
        for _, b in self.backends:
            if hasattr(b, "language"):
                b.language = lang
            elif hasattr(b, "_pending_note"):      # Claude account backend
                b._pending_note = note.strip()
            elif hasattr(b, "_pending_system"):    # Anthropic API backend
                b._pending_system = note.strip()

    def ask(self, user_text: str) -> str:
        if not self.backends:
            msg = ("No AI is set up yet. For free AI on this PC (works offline), install Ollama and download a model "
                   "on the AI Models page; or add a free Gemini or Groq key in Settings.")
            self.on_text(msg)
            return msg
        failures: list[str] = []
        failed: set[str] = set()
        order, why = route(self.backends, user_text)
        if not order:
            msg = ("There's no internet connection, and there's no AI on this PC yet. Install Ollama and download a "
                   "model on the AI Models page to use me offline.")
            self.on_text(msg)
            return msg
        if why:
            self.on_tool("routing", {"to": order[0][0], "why": why})
        for label, backend in order:
            missed = self.turns[self.seen[label]:]
            prompt = user_text
            if missed:  # turns this provider didn't see because another one answered them
                history = "\n".join(f"User: {u}\n{schedule.agent_name()}: {r}" for u, r in missed[-8:])
                prompt = (f"[Earlier in this conversation (answered while you were unavailable):\n{history}]\n\n"
                          f"{user_text}")
            self.current = label
            self.on_provider(label)
            self._acted = False
            try:
                reply = backend.ask(prompt)
            except ProviderError as e:
                failures.append(f"{label}: {e}")
                failed.add(label)
                if getattr(e, "permanent", False) and len(self.backends) > 1:
                    # Signed out / bad key: stop trying it until Jarvis restarts.
                    self.backends = [(l, b) for l, b in self.backends if l != label]
                    self.down[label] = str(e)
                else:
                    self.limited[label] = str(e)
                if self._acted or getattr(e, "acted", False):
                    # Already did something on the PC: don't repeat it on another model.
                    msg = f"{label} stopped partway through ({e}). Please check what was done and ask again."
                    self.on_text(msg)
                    return msg
                nxt = next((name for name, _ in order if name not in failed), None)
                if nxt:
                    self.on_tool("switching_model", {"from": label, "to": nxt, "reason": str(e)})
                continue
            self.limited.pop(label, None)
            self.turns.append((user_text, reply))
            self.seen[label] = len(self.turns)
            return reply
        msg = "None of my AI providers could answer right now:\n" + "\n".join(f"- {f}" for f in failures)
        self.on_text(msg)
        return msg


def provider_status(brain) -> list[dict]:
    """Status of every provider in JARVIS_PROVIDERS, for the HUD's LLM panel."""
    names = getattr(brain, "names", [])
    down = getattr(brain, "down", {})
    limited = getattr(brain, "limited", {})
    current = getattr(brain, "current", "")
    out = []
    for name in chain():
        if name == "ollama":
            label = "Local AI"
            if label in down:
                out.append({"label": label, "status": "offline", "detail": down[label]})
            elif label in names:
                model = next((getattr(b, "model", "") for l, b in getattr(brain, "backends", []) if l == label), "")
                status = "active" if label == current else ("limited" if label in limited else "connected")
                out.append({"label": label, "status": status, "detail": limited.get(label, f"{model} (on this PC)")})
            elif not local_ai.installed():
                out.append({"label": label, "status": "not set up", "detail": "install Ollama (free) to use AI offline"})
            elif not local_ai.running():
                out.append({"label": label, "status": "offline", "detail": "Ollama isn't running"})
            else:
                out.append({"label": label, "status": "not set up", "detail": "download a model on the AI Models page"})
            continue
        if name == "claude":
            label, detail = "Claude", "your Claude account"
        elif name in OPENAI_COMPATIBLE:
            label = OPENAI_COMPATIBLE[name][0]
            detail = (os.environ.get(OPENAI_COMPATIBLE[name][3]) or OPENAI_COMPATIBLE[name][4]).split(",")[0]
            if not os.environ.get(OPENAI_COMPATIBLE[name][2]):
                out.append({"label": label, "status": "no key", "detail": "add a key in .env"})
                continue
        else:
            continue
        if label in down:
            out.append({"label": label, "status": "offline", "detail": down[label]})
        elif label in names:
            status = "active" if label == current else ("limited" if label in limited else "connected")
            out.append({"label": label, "status": status, "detail": limited.get(label, detail)})
        else:
            out.append({"label": label, "status": "offline", "detail": "not available"})
    return out
