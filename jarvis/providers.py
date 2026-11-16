"""Multi-provider brain: Gemini, Groq, OpenRouter, DeepSeek (and optionally Claude) with automatic fallback.

JARVIS_PROVIDERS in .env sets the order. Jarvis asks the first provider that is
configured; if it fails (limit hit, bad key, offline) *before doing anything on the
PC*, the same message goes to the next provider. Each provider keeps its own
conversation, and turns answered by other providers are passed along as context.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

from . import languages, memory, schedule, tools
from .brain import SYSTEM_PROMPT, VOICE_OFF_NOTE, system_prompt, VOICE_ON_NOTE, ProviderError, make_claude
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
        """One model call, riding out short per-minute limits and malformed tool calls."""
        for attempt in range(3):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": self.system + (URDU_NOTE if self.language == "ur" else languages.reply_note(self.language))}] + self.messages,
                    tools=self.tool_defs)
            except self.openai.RateLimitError as e:
                wait = _retry_after(e)
                if wait is None or wait > 20 or attempt == 2:
                    raise
                time.sleep(wait + 0.5)  # e.g. Groq's tokens-per-minute window: wait it out
            except self.openai.BadRequestError as e:
                if "tool" not in str(e).lower() or attempt == 2:
                    raise
                # The model produced an invalid tool call (e.g. a misspelt tool name): ask again.

    def _ask_once(self, user_text: str) -> str:
        checkpoint = len(self.messages)
        content = f"[{self._note}]\n\n{user_text}" if self._note else user_text
        self.messages.append({"role": "user", "content": content})
        acted = False
        final = ""
        try:
            for _ in range(MAX_STEPS):
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
                        result, is_error = tools.execute(call.function.name, args, self.ctx)
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

        for name in provider_order():
            try:
                if name == "claude":
                    backend = make_claude(ctx, self._text, self._tool)
                    if getattr(backend, "claude", True) is None:  # Claude Code not installed
                        self.skipped.append("Claude (Claude Code not installed)")
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
            if isinstance(b, OpenAICompatBrain):
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
            msg = "No AI provider is set up. Sign in to Claude or add an API key to .env."
            self.on_text(msg)
            return msg
        failures: list[str] = []
        failed: set[str] = set()
        for label, backend in list(self.backends):
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
                nxt = next((name for name, _ in self.backends if name not in failed), None)
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
    for name in provider_order():
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
