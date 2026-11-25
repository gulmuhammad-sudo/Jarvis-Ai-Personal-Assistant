"""Jarvis's brain: Claude plus an agent loop that runs tools until the task is done."""
from __future__ import annotations

from typing import Callable

import anthropic

from . import memory, tools
from .config import EFFORT, MODEL

SYSTEM_PROMPT = """You are {name}, a personal AI assistant running on {user}'s Windows PC. \
You are calm, capable, quick and a little dryly witty, in the spirit of a loyal British butler-engineer. \
Address the user as "{user}" now and then, not in every sentence.

How you work:
- You can act on the PC through your tools: open apps and websites, find and read files, check system \
health, control media and volume, use the clipboard, look at the screen, set timers, keep notes, \
remember facts long-term, search the live web, and run PowerShell (the user approves each command).
- When asked to do something, do it with the tools rather than explaining how. Chain several tools if needed.
- Use your web search tool for anything current (news, weather, prices, scores, facts you are unsure of).
- When the user shares a lasting personal detail (their name, preferences, people, routines, projects), \
save it with remember_fact without being asked.
- Match the user's language: English gets English; Roman Urdu (Urdu in English letters) gets Roman Urdu.
- But when the user asks for something in a language ("Urdu mein batao", "translate it to Hindi", "Arabic mein likho"), write it in that \
language's own script (Urdu in Urdu script, Hindi in Devanagari, Arabic in Arabic), never in English letters, and stay in it until they ask \
for another language or for Roman. This needs no tool.
- For songs/videos use play_youtube; for namaz times use prayer_times; for clock-time alarms use set_alarm.
- For a longer task (three or more actions that change something), show your steps with make_plan first and report \
each one with plan_step. If the user refuses the plan, don't do it.
- Be concise. Lead with the answer or the result. A sentence or two is usually right; go longer only \
when the user asks for detail or the content needs it.
- Never claim you did something unless a tool confirmed it. If a tool fails, say so plainly and suggest the next step.
- Destructive or irreversible actions (deleting files, shutting down, uninstalling) need a clear request \
from the user; when unsure, ask first.

What you remember about the user from earlier sessions:
{memories}
"""

def system_prompt(template: str | None = None, live: bool = False) -> str:
    """The instructions with the user's chosen assistant name, what to call them, and their profile."""
    from . import schedule
    name = schedule.agent_name()
    text = (template or SYSTEM_PROMPT).format(name=name, user=memory.call_name(), memories=memory.as_text())
    from . import skills
    try:
        text += skills.prompt_text()     # your own rules and saved routines (Tools & Skills page)
    except Exception as e:               # a broken database must never stop the assistant from answering
        print(f"[skills] couldn't load: {e}")
    try:
        from . import people
        text += people.prompt()          # the manner you chose (Daily page, People)
    except Exception as e:
        print(f"[people] couldn't load: {e}")
    from . import languages, tts
    if not live and tts.reading_female():
        text += f"\n{languages.WOMAN}\n"
    from .guard import SYSTEM_RULE
    text += SYSTEM_RULE                  # text from web pages / files is data, never instructions
    if name.lower() != "jarvis":
        text += (f"\nYour name is {name}: the user chose it. Always call yourself {name}. The app, its folders and "
                 "some tool descriptions still say \"Jarvis\"; that is only the program's name, not yours.\n")
    return text


VOICE_ON_NOTE = ("Voice mode is ON: your replies are read aloud. Keep them short and conversational, "
                 "with no markdown, bullet lists, tables or URLs unless the user asks for them.")
VOICE_OFF_NOTE = "Voice mode is OFF: replies are shown as text again; normal formatting is fine."

MAX_STEPS = 25


class ProviderError(Exception):
    """A provider couldn't answer (limit hit, bad key, offline...). The router tries the next one."""


def make_brain(ctx, on_text, on_tool):
    """Build the provider chain from JARVIS_PROVIDERS (see providers.py)."""
    from .providers import MultiBrain
    return MultiBrain(ctx, on_text=on_text, on_tool=on_tool)


def make_claude(ctx, on_text, on_tool):
    """Claude via the Anthropic API (needs ANTHROPIC_API_KEY in .env); None without a key."""
    import os
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return Brain(ctx, on_text=on_text, on_tool=on_tool)
    return None


class Brain:
    def __init__(self, ctx: tools.ToolContext,
                 on_text: Callable[[str], None],
                 on_tool: Callable[[str, dict], None]):
        self.client = anthropic.Anthropic()
        self.ctx = ctx
        self.on_text = on_text
        self.on_tool = on_tool
        self.messages: list[dict] = []
        self._pending_system: str | None = None
        self.system = system_prompt()
        self.tool_defs = tools.TOOL_DEFINITIONS + tools.SERVER_TOOLS

    def reset(self) -> None:
        self.messages = []
        self.system = system_prompt()

    def set_voice_mode(self, on: bool) -> None:
        # Delivered as a mid-conversation system message with the next user turn,
        # so the cached system prompt and history stay untouched.
        self._pending_system = VOICE_ON_NOTE if on else VOICE_OFF_NOTE

    def _call(self):
        return self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            tools=self.tool_defs,
            messages=self.messages,
            output_config={"effort": EFFORT},
            # If the model declines on a safety false-positive, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def ask(self, user_text: str) -> str:
        """Send one user message, run tools until Claude is done, return the final text."""
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        if self._pending_system:
            self.messages.append({"role": "system", "content": self._pending_system})
            self._pending_system = None

        final_text = ""
        try:
            for _ in range(MAX_STEPS):
                if tools.STOP.is_set():                  # you pressed Stop: no more steps
                    self.on_text("Okay, I stopped.")
                    return "Okay, I stopped."
                response = self._call()
                self.messages.append({"role": "assistant", "content": response.content})

                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if text:
                    self.on_text(text)
                    final_text = text

                if response.stop_reason == "refusal":
                    msg = "I'm afraid I can't help with that one."
                    self.on_text(msg)
                    return msg
                if response.stop_reason == "pause_turn":  # long server-side web search: resume
                    continue
                if response.stop_reason == "max_tokens":
                    note = "(My reply was cut off - ask me to continue.)"
                    self.on_text(note)
                    return final_text or note
                if response.stop_reason != "tool_use":
                    return final_text

                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    self.on_tool(block.name, block.input)
                    content, is_error = tools.execute(block.name, block.input, self.ctx, True)
                    result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
                    if is_error:
                        result["is_error"] = True
                    results.append(result)
                self.messages.append({"role": "user", "content": results})

            msg = "That took more steps than I allow myself in one go. Shall I keep going?"
            self.on_text(msg)
            return msg

        except anthropic.AuthenticationError:
            self.messages = self.messages[:checkpoint]
            raise ProviderError("the Anthropic API key was rejected")
        except anthropic.RateLimitError:
            self.messages = self.messages[:checkpoint]
            raise ProviderError("the Anthropic API rate limit was hit")
        except anthropic.APIStatusError as e:
            self.messages = self.messages[:checkpoint]
            raise ProviderError(f"the Anthropic API returned {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            self.messages = self.messages[:checkpoint]
            raise ProviderError("couldn't reach the Anthropic API (check the internet connection)")
