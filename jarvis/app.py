"""Console interface for Jarvis (text + optional voice)."""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import threading
from datetime import datetime

import anthropic

from . import tools
from .brain import make_brain
from .config import ROOT, USER_NAME, provider_order

# ANSI colours (enabled on Windows 10+ terminals by the os.system('') call below)
CYAN, BLUE, GREY, YELLOW, RED, GREEN, BOLD, RESET = (
    "\033[96m", "\033[94m", "\033[90m", "\033[93m", "\033[91m", "\033[92m", "\033[1m", "\033[0m")

BANNER = rf"""{CYAN}{BOLD}
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝{RESET}
{GREY}  Just A Rather Very Intelligent System — your personal AI assistant{RESET}
"""

HELP = f"""{GREY}Commands:
  /voice    toggle voice mode (talk to Jarvis with your microphone)
  /mute     toggle spoken replies in text mode
  /reset    start a fresh conversation
  /memory   show what Jarvis remembers about you
  /help     show this help
  /exit     quit   (Ctrl+C in voice mode returns to typing){RESET}
"""

_print_lock = threading.Lock()


def say_line(prefix: str, text: str, colour: str) -> None:
    with _print_lock:
        print(f"{colour}{prefix}{RESET} {text}", flush=True)


def ensure_api_key() -> None:
    """Make sure at least one AI provider is usable, signing in to Claude if needed."""
    from .providers import OPENAI_COMPATIBLE
    order = provider_order()
    others = [OPENAI_COMPATIBLE[p][0] for p in order if p in OPENAI_COMPATIBLE and os.environ.get(OPENAI_COMPATIBLE[p][2])]
    if others:
        print(f"{GREEN}AI providers ready (in order): {' → '.join(others)}{RESET}")
    if "claude" not in order or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return
    from .brain_cc import find_claude, login_status
    claude = find_claude()
    if claude:
        ok, _ = login_status(claude)
        if ok:
            print(f"{GREEN}Using your Claude account (no API key needed).{RESET}")
            return
        if others:
            print(f"{YELLOW}Claude account not signed in, so Jarvis will use {others[0]}.{RESET} "
                  f"{GREY}(Run `claude auth login` to add Claude back.){RESET}")
            return
        print(f"{YELLOW}One-time setup: sign in to your Claude account.{RESET}")
        print("A browser window will open. Sign in with the same account you use for Claude,")
        print("then come back here. (No API key or extra payment needed.)\n")
        subprocess.run([claude, "auth", "login"], check=False)
        ok, detail = login_status(claude)
        if ok:
            print(f"{GREEN}Signed in. Starting Jarvis...{RESET}")
            return
        print(f"{RED}Sign-in didn't complete.{RESET} {GREY}{detail[:300]}{RESET}")
        print("You can try again by restarting Jarvis, or paste an API key below instead.")
    else:
        if others:
            return
        print(f"{YELLOW}Jarvis needs either the Claude Code app (to use your Claude account) or an API key.{RESET}")
    print("API keys come from https://console.anthropic.com/settings/keys (paid). Press Enter to quit.")
    print(f"{GREY}(It is saved to {ROOT / '.env'} on this PC only.){RESET}")
    key = getpass.getpass("API key (input hidden): ").strip()
    if not key:
        sys.exit("No key entered. Restart Jarvis to try signing in again.")
    env = ROOT / ".env"
    existing = env.read_text(encoding="utf-8") if env.exists() else ""
    env.write_text(existing.rstrip("\n") + ("\n" if existing else "") + f"ANTHROPIC_API_KEY={key}\n",
                   encoding="utf-8")
    os.environ["ANTHROPIC_API_KEY"] = key


def greeting() -> str:
    h = datetime.now().hour
    part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    return f"Good {part}, {USER_NAME}. Jarvis online. How can I help?"


def main(start_in_voice: bool = False) -> None:
    os.system("")  # enable ANSI escape codes in the Windows console
    print(BANNER)
    ensure_api_key()

    from .voice import Voice
    voice = Voice()
    state = {"voice_mode": start_in_voice, "speak": start_in_voice}

    def notify(msg: str, kind: str = "reminder") -> None:  # timers fire from a background thread
        say_line("\n⏰ JARVIS:", msg, YELLOW)
        voice.say(msg)
        if not state["voice_mode"]:
            with _print_lock:
                print(f"{BOLD}You:{RESET} ", end="", flush=True)

    def confirm(question: str) -> bool:
        voice.wait()
        if state["speak"]:
            voice.say("I need your approval on screen.")
        with _print_lock:
            print(f"{YELLOW}⚠  {question}{RESET}")
        return input(f"{YELLOW}Allow? [y/N]: {RESET}").strip().lower() in ("y", "yes")

    def on_text(text: str) -> None:
        say_line(f"JARVIS ({brain.current}):" if getattr(brain, "current", "") else "JARVIS:", text, CYAN)
        if state["speak"]:
            voice.say(text)

    def on_tool(name: str, args: dict) -> None:
        short = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
        say_line("  ⚙", f"{name}({short})", GREY)

    ctx = tools.ToolContext(confirm=confirm, notify=notify)
    brain = make_brain(ctx, on_text=on_text, on_tool=on_tool)
    ctx.set_language = brain.set_language
    from . import schedule
    schedule.Scheduler(notify=notify)  # alarms + prayer reminders
    if start_in_voice:
        brain.set_voice_mode(True)

    print(HELP)
    say_line("JARVIS:", greeting(), CYAN)
    if state["speak"]:
        voice.say(greeting())

    while True:
        try:
            if state["voice_mode"]:
                voice.wait()
                with _print_lock:
                    print(f"{GREEN}🎙  Listening...{RESET}", end="\r", flush=True)
                user = Voice.listen()
                print(" " * 30, end="\r")
                if not user:
                    continue
                say_line("You (voice):", user, BOLD)
                if user.lower().strip(" .!") in ("stop listening", "text mode", "keyboard mode"):
                    user = "/voice"
                elif user.lower().strip(" .!") in ("goodbye", "goodbye jarvis", "exit", "shut down jarvis"):
                    user = "/exit"
            else:
                user = input(f"{BOLD}You:{RESET} ").strip()
        except KeyboardInterrupt:
            if state["voice_mode"]:
                print(f"\n{GREY}Voice mode off.{RESET}")
                state["voice_mode"] = state["speak"] = False
                brain.set_voice_mode(False)
                continue
            user = "/exit"
        except EOFError:
            user = "/exit"

        if not user:
            continue
        cmd = user.lower()
        if cmd in ("/exit", "/quit", "exit", "quit"):
            bye = f"Goodbye, {USER_NAME}."
            say_line("JARVIS:", bye, CYAN)
            if state["speak"]:
                voice.say(bye, wait=True)
            break
        if cmd == "/help":
            print(HELP)
            continue
        if cmd == "/reset":
            brain.reset()
            say_line("JARVIS:", "Fresh start. What's next?", CYAN)
            continue
        if cmd == "/memory":
            from . import memory
            print(f"{GREY}{memory.as_text()}{RESET}")
            continue
        if cmd == "/mute":
            state["speak"] = not state["speak"]
            say_line("JARVIS:", "Speaking replies." if state["speak"] else "Muted.", CYAN)
            continue
        if cmd == "/voice":
            state["voice_mode"] = not state["voice_mode"]
            state["speak"] = state["voice_mode"]
            brain.set_voice_mode(state["voice_mode"])
            msg = ("Voice mode on. I'm listening. Say 'stop listening' or press Ctrl+C to type instead."
                   if state["voice_mode"] else "Voice mode off.")
            say_line("JARVIS:", msg, CYAN)
            if state["voice_mode"]:
                voice.say("Voice mode on. I'm listening.", wait=True)
            continue

        try:
            brain.ask(user)
        except anthropic.AuthenticationError:
            say_line("JARVIS:", "My API key was rejected. Fix ANTHROPIC_API_KEY in the .env file and restart me.", RED)
            break
