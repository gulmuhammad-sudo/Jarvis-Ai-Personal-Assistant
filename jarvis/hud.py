"""The Jarvis engine + Command Center server: a local web server that drives hud.html.

Runs only on 127.0.0.1. Every request must carry a random per-launch token, so other
websites open in your browser can't talk to Jarvis or approve commands.
The desktop app (desktop.py) shows this page in its own window.
"""
from __future__ import annotations

import html as _html
import json
import os
import platform
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote

from . import __version__
from . import live as live_mod
from . import agents, alerts, approvals, audit, automations, clock, denoise, docindex, gpu, guard, languages, life, local_ai, mail, local_stt, local_tts, memory, news, notes, planner, plans, schedule, netcheck, skills, software, stt, storage, tools, tts, urdu, wake, winmgr
from .brain import make_brain
from .config import NOTES_DIR
from .providers import provider_status
from .voice import listen as windows_listen

try:
    from . import recorder          # native microphone (sounddevice)
except Exception:                   # missing package or no audio stack: the page records instead
    recorder = None
if os.environ.get("JARVIS_NO_MIC") == "1":   # tests and demo copies: never open the microphone, not even for a spoken yes/no
    recorder = None

try:
    import psutil
except ImportError:
    psutil = None

HTML_FILE = Path(__file__).with_name("hud.html")
FACES = ("globe", "mask", "rings")
PORT = int(os.environ.get("JARVIS_HUD_PORT", "8765"))
TOKEN = secrets.token_urlsafe(24)
WINDOW_HOOK = None      # set by the desktop app: WINDOW_HOOK("show") brings its window back from the tray
STARTUP_HOOK = None     # set by the desktop app: STARTUP_HOOK(on) adds / removes the "start with Windows" shortcut


class Hub:
    """Shared state between the HTTP handlers, the brain worker and the voice loop."""

    def __init__(self) -> None:
        self.subscribers: list[queue.Queue] = []
        self.sub_lock = threading.Lock()
        self.inbox: queue.Queue[str] = queue.Queue()
        self.pending: dict[str, dict] = {}  # confirm id -> {"event", "allow"}
        self.state = "idle"  # idle | listening | thinking
        # spoken replies: as you left them (demo copies with JARVIS_NO_SPEAK=1 stay quiet)
        self.speak = os.environ.get("JARVIS_NO_SPEAK") != "1" and schedule.get_setting("speak", True) is not False
        self.voice_mode = False
        self.busy = False
        self.history: list[dict] = self._restore_history()  # replayed to a page that (re)connects
        self.last_client_seen = time.time()
        self.cpu = 0.0
        self.tool_calls = 0
        self.clients: list[str] = []        # connected HUD pages, oldest first
        self.speaker: str | None = None     # the one page allowed to speak and listen
        self.recent_replies: list[tuple[float, str]] = []
        self.ctx = tools.ToolContext(confirm=self.confirm, notify=self.notify)
        self.ctx.set_language = self.set_language
        self.ctx.set_chat_script = self.set_chat_script
        self.ctx.set_name = self.set_name
        self.ctx.set_theme = self.set_theme
        self.ctx.set_brain = self.set_brain
        self.brain = make_brain(self.ctx, on_text=self.on_text, on_tool=self.on_tool)
        self.language = languages.clean(schedule.get_setting("language", "en"))
        if self.language != "en":
            self.brain.set_language(self.language)
        self.ctx.language = self.language
        self.weather: dict | None = None
        self.recording = None               # the native-mic Recording in progress
        self._listen_lock = threading.Lock()
        self._mic_cache: tuple[float, dict] = (0.0, {})
        self.live: live_mod.LiveSession | None = None     # the live conversation in progress
        self._live_user = ""
        self.voice_engine = schedule.get_setting("voice_engine", "live")
        self.last_source = "typed"          # how the last request came in (voice requests get voice approvals)
        self.trusted: set[str] = set()      # approval kinds you already allowed this session
        self._ids, self._open_tools = 0, {} # Activity: tool id -> waiting for its result
        tools.RESULT_HOOK = self._tool_result
        tools.WORKSPACES_CHANGED = lambda: self.emit("workspaces_changed")
        tools.SOFTWARE_CHANGED = lambda: self.emit("software_changed")
        self.runner = automations.Runner(self.ctx, emit=self.emit, ask=lambda t: self.submit(t, source="scheduled"))
        tools.AUTOMATION_RUN = lambda a: self.runner.start(a, "you asked")
        self.agents = agents.Runner(lambda: self.brain, self.ctx, emit=self.emit, on_tool=self.on_tool)
        tools.AGENT_RUN = self.agents.run
        tools.AUTOMATIONS_CHANGED = lambda: self.emit("automations_changed")
        plans.CHANGED = lambda plan: self.emit("plan", plan=plan)
        self.voice_mode = schedule.get_setting("hands_free", True) is not False   # hands-free from the moment the app opens
        self.brain.set_voice_mode(self.voice_mode)
        self._standby: threading.Thread | None = None   # hands-free (Live): waits locally for your voice
        self._standby_stop = threading.Event()
        self.standby_on = False
        self._quiet_until = 0.0             # the page is speaking / a beep is playing: don't wake up
        self._live_errors: list[float] = []
        self.mic_prompt: dict | None = None # a newly plugged-in microphone waiting for your choice
        self._wake_hit: tuple | None = None # (text, what came after the name, audio) when you called it
        self._wake_checks: list[float] = [] # when we asked Whisper "was the name said?" (free-quota guard)
        self._awake_until = 0.0             # Classic + wake word: follow-up window after you called it
        pref = schedule.get_setting("brain") or {}
        if pref.get("provider") and hasattr(self.brain, "use"):
            try:
                self.brain.use(pref["provider"], pref.get("model"))
            except ValueError:
                pass
        self._confirm_rec = None            # the recording listening for a spoken yes/no
        self._stt_downloading: str | None = None   # local speech model being downloaded
        self._tts_downloading: str | None = None   # voice on this PC being downloaded
        tts.warm_up()                       # first reply shouldn't pay the voice service's start-up cost
        if recorder and os.environ.get("JARVIS_NO_MIC") != "1":     # (automated tests never open the mic)
            threading.Thread(target=recorder.choose_mic, daemon=True).start()   # pick a working mic early
        self.ringer = clock.Ringer(play=lambda label, first: self.alert("alarm", label, force=not first),
                                   changed=lambda rings: self.emit("ringing", rings=rings), missed=lambda text: self.notify(text, "info"),
                                   quiet=lambda: bool(self.live and self.live.active))
        tools.RINGER = self.ringer
        clock.start(self.clock_done, lambda: self.emit("clock_changed"))
        self.scheduler = schedule.Scheduler(notify=self.notify,
                                            run_prompt=lambda text: self.submit(text, source="scheduled"))
        self.scheduler.on_tick = self._tick
        tools.PLANNER_CHANGED = lambda: self.emit("planner_changed")
        docindex.CHANGED = lambda: self.emit("docs_changed")
        self._docs_next = time.time() + 180           # look for new documents a few minutes after the start, then every 6 hours

    # ---------- events to the page ----------
    def emit(self, event_type: str, keep: bool = False, **data) -> None:
        # (not called "kind": reminders send their own kind=alarm/prayer/battery in **data)
        ev = {"type": event_type, "time": datetime.now().strftime("%H:%M:%S"), **data}
        if keep:
            self.history.append(ev)
            self.history = self.history[-200:]
            if self.keep_history():
                storage.add_event(ev)             # kept across restarts (only chat / activity types)
        with self.sub_lock:
            for q in self.subscribers:
                q.put(ev)

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit("state", state=state)

    # ---------- brain callbacks ----------
    def on_text(self, text: str) -> None:
        # The HUD page speaks replies itself (natural neural voice in Edge).
        rid = self._next_id()
        self.emit("jarvis", keep=True, text=text, provider=getattr(self.brain, "current", ""), id=rid)
        self._chat_script_later(rid, text)                # (it is spoken as written; only the chat text changes)
        self.recent_replies = [(t, r) for t, r in self.recent_replies if time.time() - t < 120][-6:]
        self.recent_replies.append((time.time(), text))

    def _next_id(self) -> str:
        self._ids += 1
        return f"{self._launch}{self._ids}"            # unique across restarts (saved history keeps old ids)

    @staticmethod
    def keep_history() -> bool:
        return schedule.get_setting("keep_history", True) is not False

    def _restore_history(self) -> list[dict]:
        """Conversation and activity from earlier sessions (SQLite), so they survive a restart."""
        import secrets as _s
        self._launch = "e" + _s.token_hex(2) + "-"
        if not self.keep_history():
            return []
        out = []
        for ev in storage.recent_events(150):
            ev = {**ev, "old": True}
            if ev.get("type") == "tool":
                ev["pending"] = False             # whatever was running then has long finished
            out.append(ev)
        return out

    def clear_history(self) -> None:
        n = storage.clear_events()
        self.history = []
        audit.record("history_cleared", events=n)
        self.emit("history_cleared")

    def on_tool(self, name: str, args: dict) -> None:
        if name not in ("switching_model", "live_reconnecting", "microphone", "routing"):   # (notices, not actions)
            self.tool_calls += 1
        if name == "remember_fact":            # the assistant saved it itself: don't also ask "Remember this?"
            self.emit("memory_suggest_clear")
        args = guard.for_logs(name, args)
        short = ", ".join(f"{k}={str(v)[:50]}" for k, v in args.items())
        tid = self._next_id()
        if name in tools._HANDLERS:
            self._open_tools.setdefault(name, []).append(tid)
        try:
            full = json.dumps(args, ensure_ascii=False, indent=1)[:3000]
        except (TypeError, ValueError):
            full = str(args)[:3000]
        self.emit("tool", keep=True, name=name, args=short, id=tid, detail=full, pending=name in tools._HANDLERS)

    def _tool_result(self, name: str, args: dict, out, err: bool) -> None:
        """A tool finished: its result goes to the Activity panel (click an item to read it)."""
        waiting = self._open_tools.get(name) or []
        if not waiting:
            return
        tid = waiting.pop(0)
        if isinstance(out, list):              # a screenshot: the picture went to the AI
            out = "Screenshot taken and shown to the AI."
        self.emit("tool_result", keep=True, id=tid, name=name, result=str(out)[:4000], error=bool(err))
        if name == "save_skill" and not err and str(out).startswith(("Saved", "Updated")):
            self.skills_changed()

    def skills_changed(self) -> None:
        """A skill was added/changed/removed: the AI's instructions follow, open pages refresh their list."""
        if hasattr(self.brain, "refresh_system"):
            self.brain.refresh_system()
        self.emit("skills_changed")

    def notify(self, msg: str, kind: str = "reminder") -> None:
        if kind == "alarm":                  # an alarm rings until you stop or snooze it
            label = re.sub(r"^Alarm: (.*) \(\d\d:\d\d\)$", r"\1", msg)
            return self.emit("notify", keep=True, text=msg, kind=kind, ring=self.ringer.start(label, "alarm"))
        self.emit("notify", keep=True, text=msg, kind=kind)

    def clock_done(self, text: str, label: str, ring: bool) -> None:
        """A timer or focus round ended."""
        if ring:
            self.emit("notify", keep=True, text=text, kind="reminder", ring=self.ringer.start(label, "timer"))
        else:
            self.emit("notify", keep=True, text=text, kind="info")

    def alert(self, kind: str = "warn", text: str = "", force: bool = False, tone: str | None = None) -> None:
        """Beep loudly for a warning/alarm (the page asks for this when it shows an alert)."""
        if os.environ.get("JARVIS_NO_SPEAK") == "1":        # demo copies stay quiet
            return
        def hold_mic() -> None:          # a live call shouldn't send the beep to Gemini as if you spoke
            self.quiet_for(alerts.duration(kind) + 0.8)
            if self.live:
                self.live.hold_mic(alerts.duration(kind) + 0.3)
        threading.Thread(target=alerts.beep, args=(kind, text, hold_mic), kwargs={"force": force, "name": tone},
                         daemon=True).start()

    def set_language(self, lang: str) -> None:
        self.language = languages.clean(lang)
        self.ctx.language = self.language
        schedule.set_setting("language", self.language)
        self.brain.set_language(self.language)
        self.emit("settings", voice_mode=self.voice_mode, speak=self.speak, language=self.language)

    def set_name(self, name: str) -> str:
        """Rename the assistant. Every open window reloads with the new name; nothing else changes."""
        name = schedule.set_agent_name(name)          # ValueError for an unusable name
        if hasattr(self.brain, "refresh_system"):
            self.brain.refresh_system()
        self.emit("settings", assistant_name=name)
        return name

    def set_brain(self, provider: str | None, model: str | None = None) -> str:
        """Choose the AI (Gemini / Groq / OpenRouter ...) for typed and Classic-voice messages."""
        if not hasattr(self.brain, "use"):
            raise ValueError("Switching isn't available with this setup.")
        msg = self.brain.use(provider, model)            # ValueError if unknown
        opts = self.brain.options()
        schedule.set_setting("brain", {"provider": opts["preferred"], "model": model})
        self.emit("tool", keep=True, name="switch_ai_model", args=msg)
        self.emit("settings", brain=opts)
        return msg

    # ---------- wake word: only respond after you call its name ----------
    WAKE_FOLLOW_UP = 15                     # seconds it keeps listening for a follow-up before waiting for the name again

    def _tick(self, now: datetime) -> None:
        """Every few seconds: reminders first; a fault in one part doesn't stop the other."""
        try:
            planner.tick(now, self.notify)
        except Exception as e:
            print(f"[planner] {type(e).__name__}: {e}")
        try:
            life.tick(now, self.notify)
        except Exception as e:
            print(f"[life] {type(e).__name__}: {e}")
        try:
            if time.time() >= self._docs_next:
                self._docs_next = time.time() + 6 * 3600
                if not tools.STOP.is_set() and docindex.folders():
                    docindex.start()
        except Exception as e:
            print(f"[documents] {type(e).__name__}: {e}")
        self.runner.tick(now)

    def _upcoming(self) -> list[dict]:
        try:
            return self.scheduler.upcoming() + planner.upcoming()
        except Exception as e:
            print(f"[planner] {type(e).__name__}: {e}")
            return self.scheduler.upcoming()

    def suggest_memories(self) -> bool:
        return schedule.get_setting("suggest_memories", True) is not False

    def _suggest_memory(self, text: str) -> None:
        """You said something lasting about yourself: offer to remember it (never saved without your OK)."""
        if not self.suggest_memories():
            return
        try:
            s = memory.suggest_from(text)
        except Exception as e:
            print(f"[memory] suggestion check failed: {e}")
            return
        if s:
            self.emit("memory_suggest", id=self._next_id(), **s)

    def chat_script(self) -> str:
        """'roman' (default): the chat is typed in English letters; 'urdu': in Urdu script (only when you ask)."""
        return "urdu" if schedule.get_setting("chat_script") == "urdu" else "roman"

    def set_chat_script(self, script: str) -> None:
        schedule.set_setting("chat_script", "urdu" if script == "urdu" else "roman")
        self.emit("settings", chat_script=self.chat_script())

    def _chat_text(self, rid: str, text: str) -> None:
        """Write a chat message in the script you asked for, then update it on screen (a quick free AI call)."""
        if self.chat_script() == "urdu":
            if not urdu.mostly_latin(text):
                return
            out = urdu.to_urdu_script(text)
        else:
            if not urdu.has_other_script(text):
                return
            out = urdu.to_roman(text)
        if not out or out == text:
            return
        for ev in self.history:                     # a page that reconnects gets the new version too
            if ev.get("id") == rid:
                ev["text"] = out
        storage.update_text(rid, out)
        self.emit("jarvis_update", id=rid, text=out)

    def _chat_script_later(self, rid: str, text: str) -> None:
        if (self.chat_script() == "urdu" and urdu.mostly_latin(text)) or \
                (self.chat_script() == "roman" and urdu.has_other_script(text)):
            threading.Thread(target=self._chat_text, args=(rid, text), daemon=True).start()

    def live_on_open(self) -> bool:
        return schedule.get_setting("live_on_open", True) is not False

    def auto_live(self) -> None:
        """Live from the start: open a call as soon as the app is up. Like any call it ends after a few quiet
        minutes, and then hands-free waits for you (or its name) again."""
        if not self.standby_wanted():
            return
        print("[live] starting a call because the app just opened")
        self.live_start(greet=f"[The app just opened. Greet {memory.call_name()} with one short, warm sentence in "
                              f"{languages.name(self.language)} and say you are listening. Say nothing else.]")

    def wake_on(self) -> bool:
        return schedule.get_setting("wake_word", True) is not False

    def _female(self) -> bool:
        return languages.live_female(live_mod.voice()) if self.voice_engine == "live" else tts.reading_female()

    def ack_phrase(self) -> str:
        call = memory.call_name()
        if self.language == "ur":
            return f"جی {call}، میں سن {'رہی' if self._female() else 'رہا'} ہوں۔"
        if self.language == "en":
            return f"Yes {call}, I'm listening."
        return ""

    def _ack_prompt(self) -> str:
        ex = self.ack_phrase()
        how = f'like "{ex}"' if ex else f"in {languages.name(self.language)}"
        return (f"[The user just called your name to get your attention. Reply ONLY with a very short, warm "
                f"acknowledgement {how}, then wait for them to speak. Do not say anything else.]")

    def _check_wake(self, audio, rate: int) -> None:
        """Was the name in this bit of speech? (Whisper on ~1-4 s of audio, on a worker thread.)"""
        try:
            wav = recorder._to_wav(audio, rate)
            # tell Whisper your language: on a 1-second clip its own guess is often wrong (Icelandic, ...)
            if (stt.engines() or ["?"])[0] == "local":     # Settings say "this PC", or there's no internet
                from . import local_stt
                r = {"text": local_stt.transcribe(local_stt.wav_to_pcm(wav), languages.stt_code(self.language))}
            else:
                r = stt._whisper_once(wav, languages.stt_code(self.language))
            text = urdu.from_devanagari(r.get("text", ""))
            if not stt._clean(text) or r.get("no_speech", 0) > 0.6:
                print(f"[wake] just noise ({text[:30]!r})")   # Whisper's "Thank you." on noise
                return
            hit, rest = wake.match(text, schedule.agent_name())
            print(f"[wake] heard {text[:60]!r} -> {'called me' if hit else 'not for me'}")
            if hit:
                self._wake_hit = (text, rest, audio)
        except Exception as e:
            print(f"[wake] check failed: {type(e).__name__}: {str(e)[:100]}")

    # ---------- hands-free in Live mode: wait for your voice locally, then start the call ----------
    def standby_wanted(self) -> bool:
        return bool(self.voice_mode and self.voice_engine == "live" and recorder and live_mod.available()
                    and os.environ.get("JARVIS_HANDSFREE", "on") != "off"      # test copies don't grab the mic
                    and bool(schedule.get_setting("setup_done"))                # not while the welcome setup is open
                    and not (self.live and self.live.active) and not self.recording
                    and not (len(self._live_errors) >= 2 and time.time() - self._live_errors[-2] < 120))

    def standby_start(self, delay: float = 0.0) -> None:
        if self._standby and self._standby.is_alive():
            return
        self._standby_stop.clear()
        self._standby = threading.Thread(target=self._standby_loop, args=(delay,), name="jarvis-standby", daemon=True)
        self._standby.start()

    def standby_halt(self) -> None:
        """Release the microphone (someone else needs it)."""
        self._standby_stop.set()
        t = self._standby
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(2)

    def _standby_loop(self, delay: float) -> None:
        import numpy as np
        import sounddevice as sd
        from scipy import signal as sg
        if self._standby_stop.wait(delay) or not self.standby_wanted():
            return
        dev = recorder.choose_mic()
        if not dev:
            return
        rate, block = dev["rate"], int(dev["rate"] * 0.05)
        ring: list = []
        floor, run, started = float("inf"), 0, time.time()
        use_wake = self.wake_on()
        segment: list | None = None
        silent_blocks = 0
        self._wake_hit = None
        self.standby_on = True
        self.emit("standby", on=True, mic=dev["name"], wake=use_wake)
        print(f"[hands-free] waiting for {'its name' if use_wake else 'your voice'} on {dev['name']}")
        trigger = False
        done = threading.Event()                 # this wait is over (stops the mute watcher)
        recorder._recording.set()
        try:
            with sd.InputStream(device=dev["index"], channels=1, samplerate=rate, dtype="float32", blocksize=block) as st:
                def watch_mute() -> None:                # Teams or the mic key can mute it while we wait.
                    was_muted = False                    # (own thread: the check takes ~1.7 s and the mic
                    while not done.wait(3):              #  must never stop being read meanwhile)
                        muted = bool(recorder.is_muted(dev["name"]))
                        if muted and not was_muted:
                            self._mic_cache = (0.0, {})
                            self.emit("mic_muted", mic=dev["name"])
                        was_muted = muted
                threading.Thread(target=watch_mute, name="jarvis-mute-watch", daemon=True).start()
                while not self._standby_stop.is_set():
                    if not self.standby_wanted():
                        break
                    x = st.read(block)[0][:, 0].copy()
                    ring.append(x)
                    ring = ring[-24:]                                   # the last 1.2 s
                    rms = recorder._voice_rms(x, rate)
                    floor = rms if rms < floor else floor * 0.995 + rms * 0.005
                    quiet = time.time() < self._quiet_until or time.time() - started < 1.0
                    if self._wake_hit:                                  # Whisper heard the name
                        trigger = True
                        break
                    if not use_wake:
                        run = run + 1 if (not quiet and rms > max(0.004, floor * 3.0)) else 0
                        if run >= 6:                                    # 0.3 s of real voice
                            trigger = True
                            break
                        continue
                    # wake word: cut out each bit of close, clear speech and ask Whisper if it's the name
                    loud = not quiet and rms > max(0.006, floor * 4.0)  # near the mic, louder than the room
                    if segment is None:
                        run = run + 1 if loud else 0
                        if run >= 3:
                            segment, silent_blocks, voiced = list(ring[-12:]), 0, run
                    else:
                        segment.append(x)
                        voiced += 1 if loud else 0
                        silent_blocks = silent_blocks + 1 if rms < max(0.004, floor * 2.5) else 0
                        if silent_blocks >= 12 or len(segment) >= 80:   # 0.6 s pause, or 4 s at most
                            now = time.time()
                            self._wake_checks = [t for t in self._wake_checks if now - t < 60]
                            # at least 0.3 s of real voice: a click, cough or door bang isn't worth asking about
                            if voiced >= 6 and len(self._wake_checks) < 12:
                                self._wake_checks.append(now)
                                threading.Thread(target=self._check_wake, args=(np.concatenate(segment), rate),
                                                 daemon=True).start()
                            segment, run = None, 0
        except Exception as e:
            print(f"[hands-free] {type(e).__name__}: {e}")
        finally:
            done.set()
            recorder._recording.clear()
            self.standby_on = False
            self.emit("standby", on=False)
        if trigger and not self._standby_stop.is_set():
            to16 = lambda a: sg.resample_poly(a, 16000 // np.gcd(rate, 16000), rate // np.gcd(rate, 16000)).astype(np.float32) \
                if rate != 16000 else a
            if self._wake_hit:
                text, rest, audio = self._wake_hit
                self._wake_hit = None
                self.emit("wake", keep=True, text=text, command=rest)
                print(f"[wake] {schedule.agent_name()} was called: {'doing ' + repr(rest) if rest else 'saying yes'}")
                # "Maya, mausam batao": the call hears the whole sentence. Just "Maya": a short "yes?" first
                self.live_start(preroll=to16(audio) if rest else None, greet=None if rest else self._ack_prompt(),
                                idle_stop=self.WAKE_FOLLOW_UP, quiet_room=True)
            else:
                print("[hands-free] heard you: starting a live conversation")
                self.live_start(preroll=to16(np.concatenate(ring)))

    def quiet_for(self, seconds: float) -> None:
        self._quiet_until = max(self._quiet_until, time.time() + seconds)

    # ---------- microphones plugged in / out ----------
    def mic_watch(self) -> None:
        known = None
        while True:
            names = recorder.active_mic_names() if recorder else None
            if names is not None:
                if known is not None:
                    for n in names:
                        if n not in known:
                            current = (recorder._chosen or {}).get("name", "")
                            if not current.startswith(n[:28]):
                                self.mic_prompt = {"name": n, "current": current, "all": names, "at": time.time()}
                                print(f"[voice] new microphone plugged in: {n}")
                                self.emit("mic_new", **self.mic_prompt)
                    for n in known:
                        if n not in names:
                            current = (recorder._chosen or {}).get("name", "")
                            if current.startswith(n[:28]):
                                recorder._chosen = None                 # it's gone: pick another next time
                            if self.mic_prompt and self.mic_prompt["name"] == n:
                                self.mic_prompt = None
                            self.emit("mic_gone", name=n, was_current=current.startswith(n[:28]))
                known = names
            time.sleep(3)

    def use_mic(self, name: str | None) -> str | None:
        """Switch microphone, even in the middle of a call (the call restarts on the new mic)."""
        self.mic_prompt = None
        in_call = bool(self.live and self.live.active)
        self.standby_halt()
        if in_call:
            self.live_stop("switching microphone")
            for _ in range(40):
                if not (self.live and self.live.active) and not recorder._recording.is_set():
                    break
                time.sleep(0.1)
        recorder.refresh()
        if name:                                                        # Windows name -> PortAudio name
            match = next((d["name"] for d in recorder.list_mics()
                          if d["name"].startswith(name[:28]) or name.startswith(d["name"][:28])), name)
        else:
            match = None
        chosen = recorder.set_mic(match)
        self._mic_cache = (0.0, {})
        got = chosen and chosen["name"]
        self.emit("tool", keep=True, name="microphone", args=f"using {got}")
        if in_call:
            self.live_start()
        elif self.standby_wanted():
            self.standby_start(0.5)
        return got

    # ---------- first-run setup ----------
    KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}

    def setup_info(self) -> dict:
        prof = memory.profile()
        return {"done": bool(schedule.get_setting("setup_done")), "name": schedule.agent_name(),
                "call": prof.get("call", ""), "user_name": prof.get("name", ""), "language": self.language,
                "languages": languages.choices(), "theme": schedule.theme(), "hands_free": self.voice_mode,
                "engine": self.voice_engine, "live_voice": live_mod.voice(), "live_voices": live_mod.VOICES,
                "wake_word": self.wake_on(),
                "reading_voice": schedule.get_setting("reading_voice") or tts.DEFAULT_VOICE,
                "reading_voices": [{"id": v, "name": n} for v, n in tts.VOICES],
                "keys": {k: bool(os.environ.get(env)) for k, env in self.KEYS.items()}}   # never the keys themselves

    def apply_setup(self, d: dict) -> dict:
        """Save everything from the setup wizard at once."""
        problems = []
        try:
            if d.get("name"):
                self.set_name(str(d["name"]))
        except ValueError as e:
            problems.append(str(e))
        prof = memory.profile()
        for k_in, k_prof in (("call", "call"), ("user_name", "name")):
            if k_in in d:
                prof[k_prof] = str(d[k_in] or "").strip()[:100]
        memory.save_profile(prof)
        if d.get("language"):
            self.set_language(str(d["language"]))
        if d.get("theme") in schedule.THEMES:
            self.set_theme(d["theme"])
        if d.get("live_voice") in live_mod.VOICES:
            schedule.set_setting("live_voice", d["live_voice"])
        if d.get("reading_voice"):
            schedule.set_setting("reading_voice", str(d["reading_voice"])[:60])
        if "wake_word" in d:
            schedule.set_setting("wake_word", bool(d["wake_word"]))
        if d.get("face") in FACES:
            schedule.set_setting("face", d["face"])
        if d.get("engine") in ("live", "classic"):
            self.voice_engine = d["engine"]
            schedule.set_setting("voice_engine", self.voice_engine)
        added = self._save_keys(d.get("keys") or {})
        if "hands_free" in d:
            self.toggle_voice_mode(bool(d["hands_free"]))
        schedule.set_setting("setup_done", True)
        if hasattr(self.brain, "refresh_system"):
            self.brain.refresh_system()
        if self.standby_wanted():
            self.standby_start(1.0)           # hands-free starts once setup is done
        self.emit("settings", setup_done=True, assistant_name=schedule.agent_name(), theme=schedule.theme())
        return {"ok": not problems, "problems": problems, "keys_added": added, **self.setup_info()}

    def _save_keys(self, keys: dict) -> list[str]:
        """Write new API keys to .env (your PC only) and connect those AIs right away."""
        from .config import save_env_keys
        new = {self.KEYS[k]: str(v).strip() for k, v in keys.items() if k in self.KEYS and str(v or "").strip()}
        new = {k: v for k, v in new.items() if re.fullmatch(r"[A-Za-z0-9_\-.:]{16,200}", v)}
        if not new:
            return []
        save_env_keys(new)
        self.rebuild_brain()                    # pick up the new AIs
        return [k for k, env_name in self.KEYS.items() if env_name in new]

    def rebuild_brain(self) -> None:
        """Re-read which AIs are available (new key, Ollama started, model downloaded, local/cloud order)."""
        self.brain = make_brain(self.ctx, on_text=self.on_text, on_tool=self.on_tool)
        self.brain.set_voice_mode(self.voice_mode)
        if self.language != "en":
            self.brain.set_language(self.language)
        self.emit("settings", brain_changed=True)

    # ---------- local speech-to-text ----------
    def stt_download(self, name: str) -> None:
        """Download a local speech model in the background (you pressed Download after seeing its size)."""
        if self._stt_downloading:
            return
        self._stt_downloading = name
        audit.record("speech_model_download", model=name)
        try:
            local_stt.download(name, lambda f: self.emit("stt_download", model=name, frac=round(f, 3)))
            self.emit("stt_download", model=name, frac=1.0, done=True)
        except Exception as e:
            self.emit("stt_download", model=name, done=True, error=f"{type(e).__name__}: {str(e)[:120]}")
        finally:
            self._stt_downloading = None
            self.emit("settings", stt_mode=stt.mode())

    def tts_download(self, voice: str) -> None:
        """Download a voice that speaks on this PC (you pressed Download after seeing its size)."""
        if self._tts_downloading:
            return
        self._tts_downloading = voice
        audit.record("voice_download", voice=voice)
        try:
            local_tts.download(voice, lambda f: self.emit("tts_download", voice=voice, frac=round(f, 3)))
            self.emit("tts_download", voice=voice, frac=1.0, done=True)
        except Exception as e:
            self.emit("tts_download", voice=voice, done=True, error=f"{type(e).__name__}: {str(e)[:120]}")
        finally:
            self._tts_downloading = None

    # ---------- local AI (Ollama) ----------
    def local_info(self) -> dict:
        from .providers import prefer_local
        return {**local_ai.status(), "prefer_local": prefer_local(), "download_page": local_ai.DOWNLOAD_PAGE,
                "pulling": getattr(self, "_pulling", None)}

    def local_pull(self, model: str) -> None:
        """Download a model in the background (you pressed Download, after seeing its size)."""
        if getattr(self, "_pulling", None):
            return
        self._pulling = model
        audit.record("local_model_download", model=model)
        try:
            local_ai.pull(model, lambda status, frac: self.emit("local_pull", model=model, status=status,
                                                              frac=None if frac is None else round(frac, 3)))
            self.emit("local_pull", model=model, status="success", frac=1.0, done=True)
            self.rebuild_brain()
        except Exception as e:
            self.emit("local_pull", model=model, status=f"failed: {str(e)[:120]}", frac=None, done=True, error=True)
        finally:
            self._pulling = None

    def set_theme(self, mode: str) -> None:
        schedule.set_setting("theme", mode if mode in schedule.THEMES else "dark")
        self.emit("settings", theme=schedule.theme())

    def weather_loop(self) -> None:
        """Refresh the footer's location/weather every 30 minutes (every 2 minutes until it first works)."""
        while True:
            try:
                self.weather = schedule.weather()
                time.sleep(1800)
            except Exception:
                time.sleep(120)

    CONFIRM_TIMEOUT = 180
    # once allowed, these aren't asked again until the app restarts; shutdown, deleting files etc. always ask
    TRUSTABLE = {"powershell": "PowerShell commands", "lock": "locking the PC", "wifi_off": "turning Wi-Fi off", "email": "reading your email"}
    # Every kind of approval the tools ask for. Settings > Privacy keeps a rule per kind: "ask" (default),
    # "never" (refused without asking) or "allow" (only for the TRUSTABLE kinds: shutting down, deleting,
    # replacing files and closing apps with unsaved work are always asked).
    PERMISSION_KINDS = {
        "powershell": "Running PowerShell commands",
        "lock": "Locking the PC",
        "wifi_off": "Turning Wi-Fi off",
        "power": "Shutting down, restarting or sleeping the PC",
        "clean": "Moving old files to the Recycle Bin",
        "overwrite": "Replacing a file that already exists",
        "force_close": "Closing an app that has unsaved work",
        "close_system": "Closing a Windows system program",
        "software": "Installing, updating or removing programs (winget)",
        "email": "Reading your email (Gmail) for an answer",
        "email_draft": "Saving a draft in Gmail (never sent)",
        "after_email": "Going online after an email was read",
    }

    def permission(self, kind: str | None) -> str:
        if not kind:
            return "ask"
        rule = (schedule.get_setting("permissions") or {}).get(kind, "ask")
        if rule == "allow" and kind not in self.TRUSTABLE:
            return "ask"
        return rule if rule in ("ask", "allow", "never") else "ask"

    def set_permissions(self, changes: dict) -> dict:
        rules = dict(schedule.get_setting("permissions") or {})
        for kind, rule in (changes or {}).items():
            if kind not in self.PERMISSION_KINDS or rule not in ("ask", "allow", "never"):
                continue
            if rule == "allow" and kind not in self.TRUSTABLE:
                continue                       # never "allow" for shutdown, deleting, replacing files...
            if rule == "ask":
                rules.pop(kind, None)
            else:
                rules[kind] = rule
            if rule != "allow":
                self.trusted.discard(kind)     # "ask" / "never" also ends a yes given earlier in this session
            audit.record("permission_changed", kind=kind, rule=rule)
        schedule.set_setting("permissions", rules)
        self.emit("settings", permissions=self.permissions())
        return self.permissions()

    def permissions(self) -> dict:
        return {k: self.permission(k) for k in self.PERMISSION_KINDS}

    def confirm(self, question: str, kind: str | None = None) -> bool:
        """Ask before something risky. Answered by the Allow / Deny buttons, or by voice ("yes" / "nahi")."""
        rule = self.permission(kind)
        kept = guard.question_for_logs(question, kind)          # what goes into the saved history
        if rule in ("never", "allow"):
            label = self.PERMISSION_KINDS.get(kind or "", kind)
            self.emit("tool", keep=True, name="approval", id=self._next_id(), detail=kept,
                      args=f"{'denied' if rule == 'never' else 'allowed'} automatically: {label} is set to "
                           f"{'Never' if rule == 'never' else 'Allow'} (Settings › Privacy)")
            return rule == "allow"
        if kind and kind in self.trusted:
            self.emit("tool", keep=True, name="approval", args=f"allowed automatically: you already said yes to {self.TRUSTABLE.get(kind, kind)}",
                      id=self._next_id(), detail=kept)
            return True
        cid = secrets.token_hex(6)
        slot = {"event": threading.Event(), "allow": False, "question": question, "asked": time.time(), "kind": kind}
        self.pending[cid] = slot
        in_call = bool(self.live and self.live.active)
        by_voice = in_call or bool(recorder and (self.voice_mode or self.last_source == "voice"))
        self.emit("confirm", id=cid, question=question, voice=by_voice, timeout=self.CONFIRM_TIMEOUT,
                  kind=kind, remember=self.TRUSTABLE.get(kind or "", ""))
        if in_call:
            self.live.hold_mic(2.8)          # don't send the spoken question itself to the call
        elif by_voice:
            threading.Thread(target=self._confirm_by_voice, args=(cid,), daemon=True).start()
        answered = slot["event"].wait(timeout=self.CONFIRM_TIMEOUT)
        self.pending.pop(cid, None)
        if self._confirm_rec:
            self._confirm_rec.stop()
        if not answered:
            self.emit("tool", keep=True, name="approval", args="no answer in 3 minutes: denied")
        self.emit("confirm_done", id=cid)
        return answered and slot["allow"]

    def answer_confirm(self, cid: str, allow: bool, how: str = "click", once: bool = False) -> bool:
        slot = self.pending.get(cid)
        if not slot or slot["event"].is_set():
            return False
        slot["allow"] = bool(allow)
        kind = slot.get("kind")
        remembered = bool(allow and not once and kind in self.TRUSTABLE)
        if remembered:
            self.trusted.add(kind)            # don't ask again for this kind (until the app restarts)
        slot["event"].set()
        self.emit("tool", keep=True, name="approval", id=self._next_id(), detail=guard.question_for_logs(slot["question"], kind),
                  args=f"{'allowed' if allow else 'denied'} by {how}"
                       + (f"; won't ask again for {self.TRUSTABLE[kind]} until the app restarts" if remembered else ""))
        return True

    def emergency_stop(self, how: str = "button") -> None:
        """Stop everything now: the running task (no more tools or steps), waiting approvals (answered "no"),
        the Live call and anything being spoken. Cleared by your next instruction."""
        tools.STOP.set()
        plans.stop()
        for cid in list(self.pending):
            self.answer_confirm(cid, False, how="Stop")
        if self.live and self.live.active:
            self.live_stop("stopped")
        if self.recording:
            self.recording.stop()
        self.ringer.stop()
        audit.record("emergency_stop", how=how)
        print(f"[stop] everything stopped ({how})")
        self.emit("stopped", how=how)
        self.emit("tool", keep=True, name="emergency_stop", id=self._next_id(), args=f"stopped everything ({how})")
        self.set_state("idle")

    def voice_answer(self, text: str) -> bool:
        """If an approval is waiting, a short spoken "yes"/"no" answers it. True if the text was used."""
        if not self.pending:
            return False
        answer = approvals.parse(text)
        cid = next(iter(self.pending), None)
        if answer is None or cid is None or time.time() - self.pending[cid]["asked"] < 1.0:
            return False
        return self.answer_confirm(cid, answer, "voice")

    def _confirm_by_voice(self, cid: str) -> None:
        """Classic mode: listen for the spoken answer (a few tries) while the approval box is open."""
        time.sleep(2.4)                       # let the page finish asking out loud
        for _ in range(4):
            if cid not in self.pending:
                return
            with self._listen_lock:
                if self.recording or (self.live and self.live.active):
                    return                    # you are recording yourself (that answer is used too)
                rec = recorder.Recording()
                self.recording = self._confirm_rec = rec
            try:
                self.emit("confirm_listen", id=cid, state="listening")
                wav = rec.run(on_level=lambda v: self.emit("level", v=round(v, 3)), hands_free=True, max_seconds=8)
                if cid not in self.pending:
                    return
                text = stt.transcribe(wav, self.language)[0] if wav else ""
                if text:
                    print(f"[approval] heard: {text!r}")
                    self.emit("confirm_listen", id=cid, state="heard", text=text)
                    if self.voice_answer(text):
                        return
            except Exception as e:
                print(f"[approval] voice answer failed: {type(e).__name__}: {e}")
                return
            finally:
                self.recording = self._confirm_rec = None
        self.emit("confirm_listen", id=cid, state="off")

    # ---------- workers ----------
    def brain_worker(self) -> None:
        while True:
            text = self.inbox.get()
            self.busy = True
            self.set_state("thinking")
            try:
                self.brain.ask(text)
            except Exception as e:  # keep the HUD alive whatever happens
                self.emit("error", keep=True, text=f"{type(e).__name__}: {e}")
            finally:
                self.busy = False
                self.set_state("idle")

    VOICE_HINT = ("[Spoken by voice: answer in one or two short, natural sentences unless the user asks "
                  "for detail; no lists or markdown.]\n")

    def submit(self, text: str, source: str = "typed") -> None:
        text = text.strip()
        if not text:
            return
        if source != "scheduled":
            tools.STOP.clear()                 # a new instruction: Stop is over
            plans.new_message("" if source in ("typed", "skill") else text)
        rid = self._next_id()
        self.emit("user", keep=True, text=text, source=source, id=rid)
        if source not in ("scheduled", "skill"):        # a skill's own text isn't you talking about yourself
            self._suggest_memory(text)
        if source not in ("typed", "scheduled", "skill"):             # what you typed stays exactly as you typed it
            self._chat_script_later(rid, text)
        if source != "scheduled":
            self.last_source = source
        if source == "typed" and self.live and self.live.active:   # typed during a call: Jarvis answers out loud
            self._live_user = text
            self.live.send_text(text)
            return
        self.inbox.put((self.VOICE_HINT + text) if source == "voice" else text)

    def is_echo(self, text: str) -> bool:
        """True if the mic most likely picked up Jarvis's own voice from the speakers."""
        words = [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2]
        if len(words) < 3:
            return False
        for _, reply in self.recent_replies:
            reply_words = set(re.findall(r"\w+", reply.lower()))
            if sum(w in reply_words for w in words) / len(words) >= 0.75:
                return True
        return False

    def set_speaker(self, cid: str | None) -> None:
        self.speaker = cid
        self.emit("speaker", id=cid)

    def heard(self, text: str, hands_free: bool = False) -> None:
        if self.pending and self.voice_answer(text):     # "yes" / "nahi" to the open approval
            return
        if hands_free and self.wake_on() and time.time() > self._awake_until:
            hit, rest = wake.match(text, schedule.agent_name())
            if not hit:                                  # someone else talking: not for me
                print(f"[wake] ignored (name not said): {text[:60]!r}")
                return
            if not rest:                                 # just the name: "yes, I'm listening"
                self._awake_until = time.time() + self.WAKE_FOLLOW_UP
                self.emit("wake", keep=True, text=text, command="", ack=self.ack_phrase() or "Yes?")
                return
            self.emit("wake", keep=True, text=text, command=rest)
            text = rest
        if hands_free and self.wake_on():
            self._awake_until = time.time() + self.WAKE_FOLLOW_UP + 10    # keep listening for a follow-up
        if self.is_echo(text):
            self.emit("tool", keep=False, name="ignored_echo", args=text[:60])
            return
        low = text.lower().strip(" .!?,")
        if low in ("stop listening", "text mode", "stop hands free", "stop hands-free"):
            self.toggle_voice_mode(False)
        elif text:
            self.submit(text, source="voice")

    # ---------- live conversation (Gemini Live) ----------
    def live_status(self) -> dict:
        s = self.live
        return {"available": live_mod.available(), "engine": self.voice_engine,
                "active": bool(s and s.active), "phase": s.phase if s and s.active else "",
                "voice": live_mod.voice(), "voices": live_mod.VOICES,
                "model": s.model if s and s.active else live_mod.MODEL,
                "pause": schedule.get_setting("live_pause") or "fast"}

    def live_start(self, preroll=None, greet: str | None = None, idle_stop: float | None = None,
                   quiet_room: bool = False) -> None:
        if os.environ.get("JARVIS_NO_MIC") == "1":      # tests and demo copies: not even when the mic button is pressed
            return
        tools.STOP.clear()                     # starting a call is a new instruction
        self.standby_halt()                    # the call needs the microphone
        with self._listen_lock:
            if self.live and self.live.active:
                return
            if self.recording:
                self.recording.stop()
            session = None

            def phase(p: str) -> None:
                self.emit("live", active=bool(session and session.active and p), phase=p, mic=session.mic if session else "")

            def ended(reason: str) -> None:
                print(f"[live] ended: {reason}")
                self.emit("live", keep=True, active=False, phase="", reason=reason)
                if reason == "error":
                    self._live_errors = (self._live_errors + [time.time()])[-3:]
                if reason != "switching microphone" and self.standby_wanted():
                    self.standby_start(2.5)     # hands-free: wait for your voice again

            session = live_mod.LiveSession(
                self.ctx, history=getattr(self.brain, "turns", []), preroll=preroll, greet=greet,
                idle_stop=idle_stop, quiet_room=quiet_room or (self.voice_mode and self.wake_on()),
                on_phase=phase, on_level=lambda v: self.emit("level", v=v),
                on_partial=self._live_partial,
                on_user=self._live_heard, on_reply=self._live_reply, on_tool=self.on_tool,
                on_error=self._live_error, on_end=ended)
            self.live = session
            self.emit("live", keep=True, active=True, phase="connecting", voice=session.voice)
            session.start()

    def live_stop(self, reason: str = "stopped") -> None:
        if self.live:
            self.live.stop(reason)

    def _script(self, text: str) -> str:
        """Live calls write Urdu in Hindi letters: show it in Urdu script (unless you chose Hindi)."""
        return text if self.language == "hi" else urdu.from_devanagari(text)

    def _live_error(self, text: str) -> None:
        if "just got muted" in text:                 # not a fault: Windows (Teams, the mic key) muted the mic
            self._mic_cache = (0.0, {})
            self.emit("mic_muted", mic=self.live.mic if self.live else "")
        else:
            self.emit("error", keep=True, text=text)

    def _live_partial(self, who: str, text: str) -> None:
        text = self._script(text)
        self.emit("live_partial", who=who, text=text)
        if who == "user" and self.pending:
            self.voice_answer(text)            # "yes" / "nahi" said during a live call

    def _live_heard(self, text: str) -> None:
        text = self._script(text)
        self._live_user = text
        plans.new_message(text)
        rid = self._next_id()
        self.emit("user", keep=True, text=text, source="live", id=rid)
        self._suggest_memory(text)
        self._chat_script_later(rid, text)

    def _live_reply(self, text: str, interrupted: bool) -> None:
        text = self._script(text)
        rid = self._next_id()
        self.emit("jarvis", keep=True, text=text, provider="Gemini Live", live=True, id=rid)
        self._chat_script_later(rid, text)
        self.recent_replies = [(t, r) for t, r in self.recent_replies if time.time() - t < 120][-6:]
        self.recent_replies.append((time.time(), text))
        turns = getattr(self.brain, "turns", None)
        if turns is not None:                  # typed follow-ups later still know what was said
            turns.append((self._live_user or "(spoken)", text))
        self._live_user = ""

    def listen_native(self, hands_free: bool = False) -> None:
        """Record from the microphone in Python, transcribe with Whisper, then hand the text to Jarvis."""
        if self.live and self.live.active:     # the live call already has the microphone
            return
        self.standby_halt()
        with self._listen_lock:              # a double click must not start two recordings
            if self.recording:               # second click while recording = "I'm done talking"
                self.recording.stop()
                return
            rec = recorder.Recording()
            self.recording = rec
        last = [0.0]

        def level(v: float) -> None:
            if time.time() - last[0] > 0.08:
                last[0] = time.time()
                self.emit("level", v=round(v, 3))

        result, detail = "nothing", ""
        try:
            self.emit("listen_stage", stage="listening")
            wav = rec.run(on_level=level, hands_free=hands_free)
            if wav:
                self.emit("listen_stage", stage="transcribing")
                text, _ = stt.transcribe(wav, self.language)
                info = dict(stt.LAST)
                if text:
                    result, detail = "heard", text
                    self.heard(text, hands_free=hands_free)
                elif info.get("rejected"):
                    result, detail = "unclear", f"unclear guess rejected: {info.get('text', '')!r}"
                print(f"[voice] whisper lang={info.get('language')} logprob={info.get('logprob', 0):.2f} "
                      f"no_speech={info.get('no_speech', 0):.2f} text={info.get('text', '')!r}")
        except Exception as e:
            result, detail = "error", f"{type(e).__name__}: {e}"
            self.emit("error", keep=True, text=f"Microphone problem: {detail}")
        finally:
            mic = rec.mic or "?"
            self.recording = None
            self.emit("listen_stage", stage="done", result=result, peak=round(rec.peak, 4),
                      started=rec.started, mic=mic, hands_free=hands_free, detail=detail[:200],
                      switched=rec.switched_from, all_dead=rec.all_dead, muted=rec.muted)
            print(f"[voice] {result}: peak={rec.peak:.4f} mic={mic}"
                  + (f" (silent, skipped: {', '.join(rec.switched_from)})" if rec.switched_from else "")
                  + (" ALL MICS SILENT" if rec.all_dead else "") + (f" | {detail[:80]}" if detail else ""))

    def listen_once(self) -> None:
        """Fallback when no Groq/Gemini key: the built-in Windows recognizer (less accurate)."""
        self.set_state("listening")
        text = windows_listen()
        self.set_state("thinking" if self.busy else "idle")
        self.heard(text)

    def cpu_sampler(self) -> None:
        """Measure CPU on its own 1-second cadence so several HUD polls can't skew the reading."""
        while psutil:
            self.cpu = psutil.cpu_percent(interval=1.0)

    def set_speak(self, on: bool) -> None:
        """Spoken replies on / off, remembered for the next time the app opens."""
        self.speak = bool(on) and os.environ.get("JARVIS_NO_SPEAK") != "1"
        schedule.set_setting("speak", bool(on))

    def toggle_voice_mode(self, on: bool) -> None:
        self.voice_mode = on
        schedule.set_setting("hands_free", bool(on))
        if on and self.standby_wanted():
            self.standby_start()
        elif not on:
            self.standby_halt()
        if on:
            self.set_speak(True)                 # hands-free without a voice would leave you waiting for an answer
        self.brain.set_voice_mode(on)
        self.emit("settings", voice_mode=self.voice_mode, speak=self.speak, language=self.language)

    def mic_status(self) -> dict:
        """Chosen mic, Windows mute state and input level (cached briefly: asking Windows is slow)."""
        if not recorder or not recorder._chosen:
            return {"mic": None, "mic_muted": False, "mic_level": None}
        at, cached = self._mic_cache
        if time.time() - at < 3 and cached.get("mic") == recorder._chosen["name"]:
            return cached
        name = recorder._chosen["name"]
        status = {"mic": name, "mic_muted": bool(recorder.is_muted(name)), "mic_level": recorder.level(name)}
        self._mic_cache = (time.time(), status)
        return status

    def stats(self) -> dict:
        out = {"state": self.state, "voice_mode": self.voice_mode, "stt": (stt.engines() or ["windows"])[0],
               "speak": self.speak, "memories": len(memory.all_facts()),
               "provider": getattr(self.brain, "current", "") or (getattr(self.brain, "names", None) or ["none"])[0],
               "providers": getattr(self.brain, "names", []),
               "llms": provider_status(self.brain) + [
                   {"label": "Whisper", "status": "connected" if stt.engines() else "offline",
                    "detail": "speech-to-text via " + {"whisper": "Whisper (Groq)", "gemini": "Gemini",
                                                        "local": "this PC (offline)"}.get(
                        (stt.engines() or ["windows"])[0], "Windows")},
                   {"label": "Neural voice", "status": "connected" if tts.available() else "offline",
                    "detail": tts.DEFAULT_VOICE}],
               "turns": len(getattr(self.brain, "turns", [])), "tool_calls": self.tool_calls,
               "computer": platform.node(), "user": memory.call_name(), "loud_alerts": alerts.loud(),
               "live_on_open": self.live_on_open(), "tray": WINDOW_HOOK is not None, "chat_script": self.chat_script(),
               "plan_mode": plans.mode(), "keep_history": self.keep_history(), "suggest_memories": self.suggest_memories(),
               "memory_counts": memory.counts(),
               "start_with_windows": schedule.get_setting("start_with_windows", True) is not False,
               "assistant_name": schedule.agent_name(), "theme": schedule.theme(),
               "version": __version__, "trusted": sorted(self.trusted), "languages": languages.choices(),
               "permissions": self.permissions(),
               "stt_mode": stt.mode(), "local_stt": {**local_stt.status(), "downloading": self._stt_downloading},
               "tts_mode": tts.mode(), "voice_speed": tts.speed_pct(), "voice_pitch": tts.pitch_hz(),
               "local_tts": {**local_tts.status(), "downloading": self._tts_downloading},
               "permission_kinds": [{"kind": k, "label": v, "can_allow": k in self.TRUSTABLE}
                                    for k, v in self.PERMISSION_KINDS.items()],
               "language_name": languages.name(self.language), "setup_done": bool(schedule.get_setting("setup_done")),
               "reading_voice": schedule.get_setting("reading_voice"),
               "hands_free": self.voice_mode, "standby": self.standby_on, "mic_prompt": self.mic_prompt,
               "wake_word": self.wake_on(), "noise_reduction": denoise.level(), "face": schedule.get_setting("face") or "globe",
               "alert_tone": alerts.tone(), "tones": alerts.TONES,
               "brain": self.brain.options() if hasattr(self.brain, "options") else None,
               "language": self.language,
               "native_mic": bool(recorder),
               "live": self.live_status(),
               **self.mic_status(),
               "location": schedule.get_location().get("city"),
               "weather": self.weather,
               "ringing": self.ringer.list(), "silent": os.environ.get("JARVIS_NO_SPEAK") == "1",
               "timers": sorted([{"id": t["id"], "message": t["label"], "due": datetime.fromtimestamp(t["due"]).strftime("%H:%M"), "kind": "timer", "repeat": "",
                                  "left": int(t["left"])} for t in clock.timers() if not t["paused"]]
                                + self._upcoming(), key=lambda x: x["left"])}
        total, used, _ = shutil.disk_usage(Path.home().anchor)
        out["disk"] = round(used / total * 100, 1)
        if psutil:
            out["cpu"] = self.cpu
            out["ram"] = psutil.virtual_memory().percent
            bat = psutil.sensors_battery()
            out["battery"] = round(bat.percent) if bat else None
            out["plugged"] = bool(bat.power_plugged) if bat else None
            up = int(time.time() - psutil.boot_time())
            out["uptime"] = f"{up // 3600}h {up % 3600 // 60}m"
            net = psutil.net_io_counters()
            out["net"] = {"sent": net.bytes_sent, "recv": net.bytes_recv}
            out["procs"] = len(psutil.pids())
        out.update(gpu.monitor().status())
        return out


HUB: Hub | None = None


def _workspaces() -> list[dict]:
    try:
        return winmgr.list_workspaces()
    except Exception as e:                 # never let a bad row break the Tools page
        print(f"[workspaces] {e}")
        return []


class Handler(BaseHTTPRequestHandler):
    server_version = "Jarvis"

    def log_message(self, *args) -> None:  # keep the console quiet
        pass

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding: only accept requests addressed to localhost.
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    @staticmethod
    def _token_ok(value: str | None) -> bool:
        return secrets.compare_digest(value or "", TOKEN)

    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        path, _, query = self.path.partition("?")
        if path == "/favicon.ico":                         # the app icon in the window / browser tab
            from .config import ICON
            try:
                body = ICON.read_bytes()
            except OSError:
                return self._json({"error": "no icon"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "image/x-icon")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/":
            name = schedule.agent_name()
            html = (HTML_FILE.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                    .replace('"__AGENT__"', json.dumps(name)).replace("__AGENT__", _html.escape(name))
                    .replace("__THEME__", schedule.theme()).replace("__FACE__", schedule.get_setting("face") or "globe")
                    .replace("__USER__", memory.call_name()))
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self._token_ok((parse_qs(query).get("token") or [""])[0]):
            return self._json({"error": "forbidden"}, 403)
        if path == "/api/stats":
            return self._json(HUB.stats())
        if path == "/api/local":                            # AI Models page: Ollama status
            return self._json(HUB.local_info())
        if path == "/api/audit":                            # Settings > Privacy: what it did on this PC
            return self._json({"events": audit.recent(200)})
        if path == "/api/info":
            return self._json({
                "tools": [{"name": d["name"], "description": d["description"].split(". ")[0].rstrip(".") + "."}
                          for d in tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS],
                "memories": memory.all_facts(),
                "graph": memory.graph(),
                "skills": skills.all_skills(),
                "workspaces": _workspaces(),
                "automations": automations.all_automations(),
                "automation_steps": automations.step_choices(),
                "automation_templates": [{**t, "steps_text": [automations.describe_step(s) for s in t["steps"]],
                                          "trigger_text": automations.describe_trigger(t["trigger"])} for t in automations.TEMPLATES],
                "plan": plans.current(),
                "agents": agents.all_agents(), "agent_tools": agents.tool_choices(), "agent_board": agents.board(),
                "notes": sorted((n.name for n in NOTES_DIR.glob("*.md")), reverse=True)})
        if path == "/api/tts_stream":
            return self._tts_stream(query)
        if path == "/api/mics":
            if not recorder:
                return self._json({"mics": [], "chosen": None})
            if not recorder._recording.is_set():
                recorder.refresh()                     # a headset plugged in since start shows up
            chosen = recorder.choose_mic()
            return self._json({"mics": recorder.list_mics(), "chosen": chosen and chosen["name"],
                               "saved": schedule.get_setting("mic")})
        if path == "/api/setup":
            return self._json(HUB.setup_info())
        if path == "/api/profile":
            return self._json({"profile": memory.profile(), "fields": memory.PROFILE_FIELDS})
        if path == "/api/voices":
            return self._json({"neural": tts.available(), "default": tts.DEFAULT_VOICE,
                               "voices": [{"id": v, "name": n} for v, n in tts.VOICES]})
        if path == "/events":
            return self._sse()
        self._json({"error": "not found"}, 404)

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q: queue.Queue = queue.Queue()
        cid = secrets.token_hex(4)
        with HUB.sub_lock:
            HUB.subscribers.append(q)
            HUB.clients.append(cid)
        HUB.set_speaker(cid)  # the newest window becomes the voice; the others stay silent
        try:
            self.wfile.write(f"data: {json.dumps({'type': 'replay', 'client': cid, 'speaker': HUB.speaker, 'events': HUB.history, 'state': HUB.state, 'voice_mode': HUB.voice_mode, 'speak': HUB.speak, 'language': HUB.language, 'pending': [{'id': k, 'question': v['question']} for k, v in list(HUB.pending.items())]})}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                HUB.last_client_seen = time.time()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with HUB.sub_lock:
                if q in HUB.subscribers:
                    HUB.subscribers.remove(q)
                if cid in HUB.clients:
                    HUB.clients.remove(cid)
                remaining = HUB.clients[-1] if HUB.clients else None
            if HUB.speaker == cid:
                HUB.set_speaker(remaining)
            HUB.last_client_seen = time.time()

    def _docs(self, action: str, data: dict) -> None:
        """Document search: the folders you chose, updating, searching, opening a result."""
        try:
            if action == "status":
                return self._json(docindex.status())
            if action == "search":
                return self._json({"hits": docindex.search(str(data.get("query") or ""), limit=20)})
            if action == "add":
                f = docindex.add_folder(str(data.get("path") or ""))
                audit.record("documents_folder_added", path=f["path"])
            elif action == "remove":
                docindex.remove_folder(int(data.get("id", -1)))
                audit.record("documents_folder_removed", id=data.get("id"))
            elif action == "open":
                p = docindex.path_of(int(data.get("id", -1)))
                if not p or not p.is_file():
                    return self._json({"error": "That file isn't there any more."}, 404)
                if p.suffix.lower() not in docindex.KINDS or guard.runs_code(str(p)):
                    return self._json({"error": "I don't open that kind of file."}, 400)
                os.startfile(str(p))
                return self._json({"ok": True})
            elif action != "update":
                return self._json({"error": "unknown action"}, 404)
            if action in ("add", "update"):
                tools.STOP.clear()                     # your click is a new instruction: Stop is over
                docindex.start()
        except (ValueError, TypeError) as e:
            return self._json({"error": str(e)}, 400)
        except OSError as e:
            return self._json({"error": f"Windows said: {e.strerror or e}"}, 500)
        HUB.emit("docs_changed")
        return self._json({"ok": True, **docindex.status()})

    def _planner(self, action: str, data: dict) -> None:
        """The Planner page (agenda, tasks, notes). Your click is the approval here; notes go to the Recycle Bin."""
        out: dict = {"ok": True}
        changed = True
        try:
            if action == "load":
                changed = False
                day = planner.parse_day(data.get("day") or "today")
                first = day.replace(day=1)
                grid = first - timedelta(days=first.weekday())
                today = datetime.now().date()
                out = {"today": today.isoformat(), "day": day.isoformat(), "grid": planner.agenda(grid, 42, extra=False),
                       "next": planner.agenda(day, 7), "tasks": planner.list_tasks(), "done": planner.list_tasks(done=True, limit=40),
                       "projects": planner.projects(), "notes": notes.all_notes(str(data.get("query") or ""))}
            elif action == "task":
                t = planner.save_task(data.get("title"), data.get("notes"), data.get("project"), data.get("due"), data.get("priority"),
                                      int(data["id"]) if data.get("id") else None)
                out["task"] = t
            elif action == "done":
                planner.set_done(int(data["id"]), bool(data.get("on")))
            elif action == "task_delete":
                planner.delete_task(int(data["id"]))
            elif action == "event":
                e = planner.save_event(**{k: data.get(k) for k in ("title", "day", "time", "end_time", "minutes", "place", "notes", "repeat", "until", "remind")},
                                       event_id=int(data["id"]) if data.get("id") else None)
                out["event"] = e
                out["overlaps"] = [planner.describe_event(o) for o in planner.conflicts(e)[:4]]
            elif action == "event_delete":
                planner.delete_event(int(data["id"]))
            elif action == "note_read":
                changed = False
                out = {"name": data.get("name"), "text": notes.read(str(data.get("name") or ""))}
            elif action == "note_save":
                name = str(data.get("name") or "")
                if data.get("new"):
                    out["note"] = notes.save(name, str(data.get("text") or ""), new=True)
                else:
                    out["note"] = notes.save(str(data.get("old") or name), str(data.get("text") or ""))
                    if data.get("old") and data["old"] != name:
                        out["note"] = notes.rename(str(data["old"]), name)
            elif action == "note_delete":
                if not notes.delete(str(data.get("name") or "")):
                    return self._json({"error": "Windows couldn't move it to the Recycle Bin, so it stays."}, 500)
            else:
                return self._json({"error": "unknown action"}, 404)
        except (ValueError, TypeError, KeyError) as e:
            return self._json({"error": str(e) if not isinstance(e, KeyError) else "Something is missing."}, 400)
        except OSError as e:
            return self._json({"error": f"Windows said: {e.strerror or e}"}, 500)
        if changed:
            HUB.emit("planner_changed")
        return self._json(out)

    def _life(self, action: str, data: dict) -> None:
        """The Planner page's Goals, Journal and Money. Your click is the approval here."""
        out: dict = {"ok": True}
        num = lambda k="id": int(data[k]) if data.get(k) else None  # noqa: E731
        pick = lambda *keys: {k: data.get(k) for k in keys}  # noqa: E731
        try:
            if action == "load":
                what = data.get("what")
                if what == "goals":
                    out = {"goals": life.goals(False), "reached": life.goals(True)[:60], "habits": life.habits()}
                elif what == "journal":
                    out = {"entries": life.entries(str(data.get("query") or "")), "moods": life.moods()}
                elif what == "money":
                    month = life.month_of(data.get("month"))
                    out = {"summary": life.summary(month), "rows": life.list_money(month, str(data.get("query") or "")), "bills": life.bills()}
                else:
                    return self._json({"error": "unknown action"}, 404)
                return self._json({**out, "settings": life.settings(), "today": datetime.now().date().isoformat()})
            if action == "goal":
                out["goal"] = life.save_goal(**pick("title", "why", "area", "target", "unit", "due", "steps", "progress"), goal_id=num())
            elif action == "goal_step":
                life.goal_step(num(), data.get("n"), bool(data.get("on")))
            elif action == "goal_done":
                life.goal_done(num(), bool(data.get("on")))
            elif action == "goal_delete":
                life.goal_delete(num())
            elif action == "habit":
                out["habit"] = life.save_habit(**pick("name", "per_week", "remind"), habit_id=num())
            elif action == "habit_mark":
                life.habit_mark(num(), data.get("day"), bool(data.get("on")))
            elif action == "habit_delete":
                life.habit_delete(num())
            elif action == "entry":
                out["entry"] = life.save_entry(data.get("text"), data.get("mood"), data.get("day"), num())
            elif action == "entry_delete":
                life.entry_delete(num())
            elif action == "money":
                out["row"] = life.save_money(data.get("amount"), data.get("kind"), data.get("category"), data.get("note"), data.get("day"), num())
            elif action == "money_delete":
                life.money_delete(num())
            elif action == "budget":
                life.set_budget(data.get("category"), data.get("amount"))
            elif action == "bill":
                out["bill"] = life.save_bill(data.get("name"), data.get("amount"), data.get("category"), data.get("day"), data.get("remind"), num())
            elif action == "bill_paid":
                life.bill_paid(num(), data.get("amount"), data.get("day"))
            elif action == "bill_skip":
                life.bill_skip(num())
            elif action == "bill_delete":
                life.bill_delete(num())
            elif action == "settings":
                before = life.settings()["journal_ai"]
                life.save_settings(data)
                if life.settings()["journal_ai"] != before:
                    audit.record("journal_ai", allowed=not before)
            elif action == "export":
                out["path"] = str(life.export(str(data.get("what"))))
                audit.record("life_export", what=str(data.get("what")))
                return self._json(out)
            else:
                return self._json({"error": "unknown action"}, 404)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            return self._json({"error": str(e) if isinstance(e, ValueError) and str(e)[:1].isupper() else "Something is missing or wrong."}, 400)
        except OSError as e:
            return self._json({"error": f"Windows said: {e.strerror or e}"}, 500)
        HUB.emit("planner_changed")
        return self._json(out)

    def _clock(self, action: str, data: dict) -> None:
        """The Daily page's Clock, and the buttons of something ringing."""
        try:
            num = lambda: int(data.get("id"))                                           # noqa: E731
            if action == "load":
                return self._json(clock.load())
            if action == "timer":
                clock.add(data.get("seconds"), data.get("label"))
            elif action in ("pause", "resume"):
                clock.pause(num(), action == "pause")
            elif action == "extend":
                clock.extend(num(), data.get("seconds"))
            elif action == "cancel":
                clock.cancel(num())
            elif action == "focus":
                clock.focus(data.get("work"), data.get("rest"), data.get("rounds"), data.get("label"))
            elif action == "focus_skip":
                clock.focus_skip()
            elif action == "focus_stop":
                clock.focus_stop()
            elif action == "stopwatch":
                clock.stopwatch_do(str(data.get("do") or ""))
            elif action == "alarm":
                args = (str(data.get("time") or ""), str(data.get("label") or ""), str(data.get("repeat") or "once"),
                        [str(d) for d in data.get("days") or []] if isinstance(data.get("days"), list) else [])
                schedule.update_alarm(num(), *args) if data.get("id") else schedule.add_alarm(*args)
            elif action == "alarm_on":
                schedule.enable_alarm(num(), bool(data.get("on")))
            elif action == "alarm_delete":
                schedule.delete_alarm(num())
            elif action == "place":
                clock.add_place(data.get("place"))
            elif action == "place_remove":
                clock.remove_place(data.get("place"))
            elif action == "ring_minutes":
                clock.set_ring_minutes(data.get("minutes"))
            elif action == "ring_stop":
                HUB.ringer.stop(data.get("id"))
                return self._json({"ok": True})
            elif action == "snooze":
                clock_t = HUB.ringer.snooze(data.get("minutes"), data.get("id"))
                return self._json({"ok": True, "text": clock.describe(clock_t)})
            else:
                return self._json({"error": "unknown action"}, 404)
        except (ValueError, TypeError, KeyError) as e:
            return self._json({"error": str(e) if isinstance(e, ValueError) and "invalid literal" not in str(e) else "Something is missing."}, 400)
        HUB.emit("clock_changed")
        return self._json(clock.load())

    def _news(self, action: str, data: dict) -> None:
        """The Daily page's News: your own clicks."""
        try:
            if action == "load":
                return self._json(news.page())
            if action == "stories":
                got = news.stories(data.get("where"), bool(data.get("fresh")))
                return self._json({**got, "at": datetime.fromtimestamp(got["at"]).strftime("%H:%M")})
            if action == "open":                                  # in your own browser
                s = news.story(data.get("id"))
                if not s:
                    raise ValueError("That story isn't in the list any more.")
                news.mark_read(s["id"])
                os.startfile(s["link"])
                return self._json({"ok": True})
            if action == "save":
                news.save(data.get("id"))
            elif action == "unsave":
                news.unsave(data.get("id"))
            elif action == "feed":
                f = news.add_feed(data.get("url"), data.get("name"))
                audit.record("news_source_added", url=f["url"])
                return self._json({**news.page(), "added": f["id"]})
            elif action == "feed_remove":
                news.remove_feed(data.get("id"))
            elif action == "follow":
                news.follow(data.get("words"))
            elif action == "unfollow":
                news.unfollow(data.get("words"))
            elif action == "briefing":
                schedule.set_setting("news_follow_briefing", bool(data.get("on")))
            else:
                return self._json({"error": "unknown action"}, 404)
        except (ValueError, TypeError, KeyError) as e:
            return self._json({"error": str(e) if isinstance(e, ValueError) and "invalid literal" not in str(e) else "Something is missing."}, 400)
        except OSError as e:
            return self._json({"error": f"Windows said: {e.strerror or e}"}, 500)
        return self._json(news.page())

    def _mail(self, action: str, data: dict) -> None:
        """The Planner page's Email: your own clicks. Nothing here goes to the AI."""
        try:
            if action == "status":
                return self._json(mail.account())
            if action == "connect":
                out = mail.connect(data.get("address"), data.get("password"))
                audit.record("mail_connected")
                return self._json(out)
            if action == "disconnect":
                mail.disconnect()
                audit.record("mail_disconnected")
                return self._json(mail.account())
            if action == "list":
                return self._json({"rows": mail.listing(str(data.get("query") or ""), bool(data.get("unread")), 30), **mail.account()})
            if action == "read":
                return self._json(mail.read(data.get("id")))
            if action == "draft":
                return self._json({"ok": True, **mail.save_draft(data.get("to"), data.get("subject"), data.get("body"), data.get("cc"), data.get("reply_to"))})
            if action == "open":                          # Gmail in your own browser
                os.startfile("https://mail.google.com/mail/u/?authuser=" + quote(mail.account()["address"]))
                return self._json({"ok": True})
            if action == "app_password":
                os.startfile("https://myaccount.google.com/apppasswords")
                return self._json({"ok": True})
        except (ValueError, TypeError, KeyError) as e:
            return self._json({"error": str(e) if isinstance(e, ValueError) else "Something is missing."}, 400)
        except OSError as e:
            return self._json({"error": f"Windows said: {e.strerror or e}"}, 500)
        return self._json({"error": "unknown action"}, 404)

    def _agents(self, action: str, data: dict) -> None:
        """The Agents page: everything is checked again in agents.py."""
        try:
            if action == "save":
                a = agents.save(data.get("name"), data.get("role"), data.get("tools"), data.get("memory"), data.get("id") or None)
                audit.record("agent_saved", name=a["name"], tools=a["tools"], memory=a["memory"])
                HUB.emit("agents_changed")
                return self._json({"ok": True, "agent": a})
            if action == "clear":
                agents.clear_board()
                HUB.emit("agents_changed")
                return self._json({"ok": True})
            a = agents.get(data.get("id"))
            if not a:
                return self._json({"error": "That agent is gone."}, 404)
            if action == "run":
                task = str(data.get("task") or "").strip()
                if not task:
                    return self._json({"error": "Write a task first."}, 400)
                tools.STOP.clear()                     # your click is a new instruction: Stop is over
                threading.Thread(target=HUB.agents.run, args=(a, task), daemon=True, name="agent").start()
                return self._json({"ok": True})
            if action == "delete":
                if not agents.delete(a["id"]):
                    return self._json({"error": "The ready-made agents stay."}, 400)
                audit.record("agent_deleted", name=a["name"])
                HUB.emit("agents_changed")
                return self._json({"ok": True})
        except (ValueError, TypeError) as e:
            return self._json({"error": str(e)}, 400)
        return self._json({"error": "unknown action"}, 404)

    def _automations(self, action: str, data: dict) -> None:
        """The Automations page: everything is checked again in automations.py; your click is the approval here."""
        try:
            raw = data.get("id")
            aid = int(raw) if raw not in (None, "") else None
            if action == "save":
                a = automations.save(data.get("name", ""), data.get("steps"), data.get("trigger"), bool(data.get("enabled")), aid)
                audit.record("automation_saved", name=a["name"], by="you")
                out = {"ok": True, "automation": a}
            elif action == "import":
                a = automations.import_text(data.get("text", ""))
                audit.record("automation_imported", name=a["name"])
                out = {"ok": True, "automation": a}
            elif action == "export":
                return self._json({"text": automations.export(aid or -1)})
            else:
                a = automations.get(aid or -1)
                if not a:
                    return self._json({"error": "That automation is gone."}, 404)
                if action == "run":
                    tools.STOP.clear()                 # your click is a new instruction: Stop is over
                    if not HUB.runner.start(a, "you pressed Run"):
                        return self._json({"error": "Another automation is still running."}, 409)
                    return self._json({"ok": True})
                if action == "enable":
                    automations.set_enabled(a["id"], bool(data.get("on")))
                    audit.record("automation_on" if data.get("on") else "automation_off", name=a["name"])
                elif action == "delete":
                    automations.delete(a["id"])
                    audit.record("automation_deleted", name=a["name"])
                else:
                    return self._json({"error": "unknown action"}, 404)
                out = {"ok": True}
        except (ValueError, TypeError) as e:
            return self._json({"error": str(e)}, 400)
        HUB.emit("automations_changed")
        return self._json(out)

    def do_POST(self) -> None:
        if not self._host_ok() or not self._token_ok(self.headers.get("X-Jarvis-Token")):
            return self._json({"error": "forbidden"}, 403)
        if self.path == "/api/transcribe":
            return self._transcribe()
        if self.path == "/api/tts":
            return self._tts()
        if self.path == "/api/local":
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._json({"error": "bad json"}, 400)
            if "prefer_local" in data:
                schedule.set_setting("prefer_local", bool(data["prefer_local"]))
                HUB.rebuild_brain()
            action = data.get("action")
            if action == "rescan":
                local_ai._cache["models"] = None
                local_ai.start()
                HUB.rebuild_brain()
            elif action == "use" and data.get("model") in [m["name"] for m in local_ai.models(refresh=True)]:
                schedule.set_setting("local_model", data["model"])
                HUB.rebuild_brain()
            elif action == "pull" and data.get("model") in [r[0] for r in local_ai.RECOMMENDED]:
                threading.Thread(target=HUB.local_pull, args=(data["model"],), daemon=True).start()
            elif action == "get_ollama":                    # the free download page, in your normal browser
                os.startfile(local_ai.DOWNLOAD_PAGE)
            return self._json(HUB.local_info())
        if self.path == "/api/history/clear":              # Settings > Privacy: forget the saved conversation
            HUB.clear_history()
            return self._json({"ok": True})
        if self.path == "/api/stop":                        # Emergency stop (button, Esc twice, tray menu)
            threading.Thread(target=HUB.emergency_stop, args=("button",), daemon=True).start()
            return self._json({"ok": True})
        if self.path == "/api/window":                      # the app was opened again: show the window from the tray
            if WINDOW_HOOK:
                threading.Thread(target=WINDOW_HOOK, args=("show",), daemon=True).start()
            return self._json({"ok": bool(WINDOW_HOOK)})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad json"}, 400)

        if self.path == "/api/send":
            HUB.submit(str(data.get("text", "")))
        elif self.path == "/api/listen":
            if HUB.state != "listening":
                threading.Thread(target=HUB.listen_once, daemon=True).start()
        elif self.path == "/api/confirm":
            HUB.answer_confirm(str(data.get("id")), bool(data.get("allow")), "click", once=bool(data.get("once")))
        elif self.path == "/api/approvals/reset":
            HUB.trusted.clear()
            HUB.emit("tool", keep=True, name="approval", args="I'll ask again before every risky action")
        elif self.path == "/api/setup":
            return self._json(HUB.apply_setup(data))
        elif self.path == "/api/settings":
            if "voice_mode" in data:
                HUB.toggle_voice_mode(bool(data["voice_mode"]))
            if data.get("reading_voice"):
                schedule.set_setting("reading_voice", str(data["reading_voice"])[:60])
                if hasattr(HUB.brain, "refresh_system"):
                    HUB.brain.refresh_system()         # (how it speaks of itself in Urdu: rahi / raha)
            if data.get("face") in FACES:
                schedule.set_setting("face", data["face"])
            if "wake_word" in data:
                schedule.set_setting("wake_word", bool(data["wake_word"]))
                if HUB.standby_on:                     # restart the waiting with the new mode
                    threading.Thread(target=lambda: (HUB.standby_halt(), HUB.standby_start(0.3)), daemon=True).start()
            if data.get("noise_reduction") in denoise.LEVELS:
                schedule.set_setting("noise_reduction", data["noise_reduction"])
            if data.get("alert_tone") in alerts.TONES:
                schedule.set_setting("alert_tone", data["alert_tone"])
            if "brain" in data:
                b = data["brain"] or {}
                try:
                    msg = HUB.set_brain(b.get("provider") or "auto", b.get("model") or None)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"ok": True, "message": msg, "brain": HUB.brain.options()})
            if "speak" in data:
                HUB.set_speak(bool(data["speak"]))
                HUB.emit("settings", voice_mode=HUB.voice_mode, speak=HUB.speak, language=HUB.language)
            if "language" in data:
                HUB.set_language(str(data["language"]))
            if "loud_alerts" in data:
                schedule.set_setting("loud_alerts", bool(data["loud_alerts"]))
            if data.get("chat_script") in ("roman", "urdu"):
                HUB.set_chat_script(data["chat_script"])
            if data.get("tts_engine") in ("auto", "online", "local"):
                schedule.set_setting("tts_engine", data["tts_engine"])
            for key, low, high in (("voice_speed", -50, 50), ("voice_pitch", -20, 20)):
                if key in data:
                    try:
                        schedule.set_setting(key, max(low, min(high, int(data[key]))))
                    except (TypeError, ValueError):
                        pass
            if data.get("tts_download") in local_tts.VOICES:
                threading.Thread(target=HUB.tts_download, args=(data["tts_download"],), daemon=True).start()
            if data.get("local_voice") in local_tts.installed():
                v = data["local_voice"]
                schedule.set_setting(f"local_voice_{local_tts.VOICES[v][1]}", v)
            if data.get("stt_engine") in ("auto", "cloud", "local"):
                schedule.set_setting("stt_engine", data["stt_engine"])
            if data.get("local_stt_model") in local_stt.installed():
                schedule.set_setting("local_stt_model", data["local_stt_model"])
            if data.get("stt_download") in local_stt.MODELS:
                threading.Thread(target=HUB.stt_download, args=(data["stt_download"],), daemon=True).start()
            if isinstance(data.get("permissions"), dict):
                HUB.set_permissions(data["permissions"])
            if data.get("plan_mode") in plans.MODES:
                schedule.set_setting("plan_mode", data["plan_mode"])
            if "suggest_memories" in data:
                schedule.set_setting("suggest_memories", bool(data["suggest_memories"]))
            if "keep_history" in data:
                schedule.set_setting("keep_history", bool(data["keep_history"]))
            if "live_on_open" in data:
                schedule.set_setting("live_on_open", bool(data["live_on_open"]))
            if "start_with_windows" in data:
                schedule.set_setting("start_with_windows", bool(data["start_with_windows"]))
                if STARTUP_HOOK:
                    threading.Thread(target=STARTUP_HOOK, args=(bool(data["start_with_windows"]),), daemon=True).start()
            if "theme" in data:
                HUB.set_theme(str(data["theme"]))
            if "assistant_name" in data:
                try:
                    name = HUB.set_name(str(data["assistant_name"]))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                HUB.emit("tool", keep=True, name="renamed", args=f"name={name}")
                return self._json({"ok": True, "assistant_name": name})
        elif self.path == "/api/alert":
            kind = data.get("kind") if data.get("kind") in ("warn", "alarm", "prayer") else "warn"
            tone = data.get("tone") if data.get("tone") in alerts.TONES else None
            HUB.alert(kind, str(data.get("text", ""))[:200], force=bool(data.get("test")), tone=tone)
        elif self.path == "/api/speaking":           # the page is talking: hands-free shouldn't hear it as you
            HUB.quiet_for(600 if data.get("on") else 0.9)
            if not data.get("on"):
                HUB._quiet_until = time.time() + 0.9
        elif self.path == "/api/profile":
            prof = memory.save_profile(data.get("profile") or {})
            if hasattr(HUB.brain, "refresh_system"):
                HUB.brain.refresh_system()
            HUB.emit("tool", keep=True, name="profile", args=f"{sum(1 for v in prof.values() if v)} fields saved")
            return self._json({"ok": True, "profile": prof, "user": memory.call_name()})
        elif self.path == "/api/listen_native":
            if not recorder:
                return self._json({"error": "native microphone not available"}, 501)
            threading.Thread(target=HUB.listen_native, args=(bool(data.get("hands_free")),), daemon=True).start()
        elif self.path == "/api/mic_boost":
            name = (recorder.choose_mic() or {}).get("name") if recorder else None
            lvl = recorder.boost(name, 100) if name else None
            HUB.emit("tool", keep=True, name="microphone", args=f"input level {lvl}%" if lvl is not None else "couldn't change level")
            HUB._mic_cache = (0.0, {})
            return self._json({"ok": lvl is not None, "level": lvl, "mic": name})
        elif self.path == "/api/mic_unmute":
            name = (recorder.choose_mic() or {}).get("name") if recorder else None
            ok = bool(name) and recorder.unmute(name)
            HUB.emit("tool", keep=True, name="microphone", args=f"unmuted {name}" if ok else "couldn't unmute")
            HUB._mic_cache = (0.0, {})
            return self._json({"ok": ok, "mic": name})
        elif self.path == "/api/mic":
            if recorder:
                if data.get("keep"):                   # "keep my current mic" for a newly plugged-in one
                    HUB.mic_prompt = None
                else:
                    threading.Thread(target=HUB.use_mic, args=(data.get("name") or None,), daemon=True).start()
        elif self.path == "/api/live":
            if "engine" in data and data["engine"] in ("live", "classic"):
                HUB.voice_engine = data["engine"]
                schedule.set_setting("voice_engine", HUB.voice_engine)
                if HUB.standby_wanted():
                    HUB.standby_start(0.5)
                elif HUB.voice_engine != "live":
                    HUB.standby_halt()
            if data.get("pause") in live_mod.PAUSES:
                schedule.set_setting("live_pause", data["pause"])      # used from the next call
            if data.get("voice") in live_mod.VOICES:
                schedule.set_setting("live_voice", data["voice"])
            if data.get("interrupt") and HUB.live:
                HUB.live.interrupt()
            if "on" in data:
                if data["on"] and not live_mod.available():
                    return self._json({"error": "Live needs a GEMINI_API_KEY and the google-genai package"}, 501)
                if data["on"]:
                    HUB.live_start()
                else:
                    HUB.live_stop()
            return self._json({"ok": True, **HUB.live_status()})
        elif self.path == "/api/claim":
            if str(data.get("client")) in HUB.clients:
                HUB.set_speaker(str(data["client"]))
        elif self.path == "/api/memory/forget":
            memory.forget(int(data.get("id", -1)))
        elif self.path == "/api/memory/edit":
            return self._json({"message": memory.edit(int(data.get("id", -1)), str(data.get("fact", "")))})
        elif self.path == "/api/memory/update":          # Memory page: category / importance / text
            imp = data.get("importance")
            return self._json({"message": memory.update(int(data.get("id", -1)), data.get("fact"), data.get("category"),
                                                        int(imp) if imp is not None else None)})
        elif self.path == "/api/memory/add":             # "Remember this?" -> Save
            msg = memory.remember(str(data.get("fact", "")), data.get("category"), None, source="suggested")
            HUB.emit("tool", keep=True, name="remember_fact", id=HUB._next_id(), args=f"saved because you said yes: {str(data.get('fact', ''))[:60]}")
            return self._json({"message": msg})
        elif self.path == "/api/skills/save":          # Tools & Skills page: add / change
            try:
                sid = data.get("id")
                s = skills.save(str(data.get("name", "")), str(data.get("instructions", "")),
                                str(data.get("mode") or "ask"), data.get("enabled", True) is not False,
                                int(sid) if sid not in (None, "") else None)
            except (ValueError, TypeError) as e:
                return self._json({"error": str(e)}, 400)
            audit.record("skill_saved", name=s["name"], mode=s["mode"], by="you")
            HUB.skills_changed()
            return self._json({"ok": True, "skill": s})
        elif self.path in ("/api/workspaces/save", "/api/workspaces/delete"):
            try:
                if self.path.endswith("save"):
                    msg = winmgr.save_workspace(str(data.get("name", "")))
                else:
                    msg = winmgr.delete_workspace(int(data.get("id", -1)))
            except (ValueError, RuntimeError) as e:
                return self._json({"error": str(e)}, 400)
            HUB.emit("tool", keep=True, name="workspace", id=HUB._next_id(), args=msg[:120])
            HUB.emit("workspaces_changed")
            return self._json({"ok": True, "message": msg})
        elif self.path == "/api/workspaces/open":     # opening apps can take a few seconds
            def _open(wid=int(data.get("id", -1))):
                try:
                    msg = winmgr.restore_workspace(wid)
                except Exception as e:
                    msg = f"Couldn't open the workspace: {e}"
                HUB.emit("tool", keep=True, name="workspace", id=HUB._next_id(), args=msg[:160])
                HUB.emit("workspaces_changed")
            threading.Thread(target=_open, daemon=True).start()
        elif self.path.startswith("/api/auto/"):       # Automations page
            return self._automations(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/docs/"):       # Tools & Skills page: Documents
            return self._docs(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/planner/"):    # Planner page
            return self._planner(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/life/"):       # Planner page: Goals, Journal, Money
            return self._life(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/clock/"):      # Daily page: Clock; Stop and Snooze
            return self._clock(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/news/"):       # Daily page: News
            return self._news(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/mail/"):       # Planner page: Email
            return self._mail(self.path.rsplit("/", 1)[1], data)
        elif self.path.startswith("/api/agents/"):     # Agents page
            return self._agents(self.path.rsplit("/", 1)[1], data)
        elif self.path == "/api/plan/dismiss":
            plans.dismiss()
        elif self.path == "/api/software/updates":    # PC Care card: list (slow: winget asks the internet)
            try:
                return self._json({"updates": software.upgrades()})
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                return self._json({"error": str(e) or "winget took too long."}, 503)
        elif self.path == "/api/software/update":     # PC Care card: Update / Update all -> the usual approval box
            args = {"action": "update_all"} if data.get("all") else {"action": "update", "id": str(data.get("id", ""))}

            def _update(args=args):
                out = re.sub(r"</?untrusted[^>]*>", "", str(tools.execute("software", args, HUB.ctx)[0])).strip()
                HUB.emit("tool", keep=True, name="software", id=HUB._next_id(), args=out[:200])
                HUB.emit("software_status", id=args.get("id", "*"), running=out.startswith("Updating"), text=out[:200])
            threading.Thread(target=_update, daemon=True).start()
        elif self.path == "/api/network/check":
            try:
                r = netcheck.speed() if data.get("speed") else netcheck.check()
            except Exception as e:
                return self._json({"error": f"The check failed: {e}"}, 503)
            if not data.get("speed"):
                r["text"] = netcheck.describe(r)
            return self._json(r)
        elif self.path == "/api/skills/enable":
            skills.set_enabled(int(data.get("id", -1)), bool(data.get("on")))
            HUB.skills_changed()
        elif self.path == "/api/skills/delete":
            s = skills.get(int(data.get("id", -1)))
            if s and skills.delete(s["id"]):
                audit.record("skill_deleted", name=s["name"])
                HUB.skills_changed()
        elif self.path == "/api/skills/run":            # the Run button = you typed "run my skill …"
            s = skills.get(int(data.get("id", -1)))
            if not s:
                return self._json({"error": "That skill is gone."}, 404)
            skills.used(s["id"])
            threading.Thread(target=HUB.submit, args=(skills.run_message(s), "skill"), daemon=True).start()
        elif self.path == "/api/memory/merge":
            return self._json({"message": memory.merge([int(i) for i in data.get("ids") or []] or None)})
        elif self.path == "/api/reset":
            HUB.live_stop()
            HUB.brain.reset()
            HUB.history.clear()
            agents.clear_board()
            mail.clear_seen()
            HUB.emit("reset")
        else:
            return self._json({"error": "not found"}, 404)
        self._json({"ok": True})

    def _tts_stream(self, query: str) -> None:
        """Stream Jarvis's voice as MP3 while it is being generated, so playback starts within ~1 s."""
        q = parse_qs(query)
        text = (q.get("text") or [""])[0][:1200]
        voice = (q.get("voice") or [None])[0]
        t0 = time.time()
        local = tts.local_voice(text, HUB.language)
        if local:                              # Settings › Voices: this PC (or offline in Auto)
            return self._send_local_voice(text, local)
        try:
            gen = tts.stream(text, voice, HUB.language)
            first = next(gen)                  # fail before sending headers if the service is down
        except Exception as e:
            print(f"[speech] stream failed for {text[:50]!r} ({voice}): {type(e).__name__}: {e}")
            local = tts.local_voice(text, HUB.language, after_failure=True)
            if local:
                print(f"[speech] using the voice on this PC ({local}) instead")
                return self._send_local_voice(text, local)
            return self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        print(f"[speech] streaming, first audio after {time.time() - t0:.2f}s: {text[:50]!r}")
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(first)
            self.wfile.flush()
            for chunk in gen:
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass                               # the page stopped playback (e.g. you interrupted)
        except Exception as e:                 # the voice service dropped mid-sentence
            print(f"[speech] stream broke off: {type(e).__name__}: {e}")
        self.close_connection = True

    def _send_local_voice(self, text: str, voice: str) -> None:
        t0 = time.time()
        try:
            audio = tts.speak_local(text, voice)
        except Exception as e:                 # page falls back to the browser's own voice
            print(f"[speech] voice on this PC failed ({voice}): {type(e).__name__}: {e}")
            return self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        print(f"[speech] this PC ({voice}), {time.time() - t0:.2f}s: {text[:50]!r}")
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(audio)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _tts(self) -> None:
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            text = str(data.get("text", ""))[:3000]
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad json"}, 400)
        local = tts.local_voice(text, HUB.language)
        if local:
            return self._send_local_voice(text, local)
        try:
            audio = tts.synthesize(text, data.get("voice"), HUB.language)
        except Exception as e:  # page falls back to the browser's own voice
            local = tts.local_voice(text, HUB.language, after_failure=True)
            if local:
                return self._send_local_voice(text, local)
            return self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(audio)

    def _transcribe(self) -> None:
        """Browser-recorded audio (only used when the native microphone isn't available)."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 15_000_000:
            return self._json({"error": "bad audio size"}, 400)
        wav = self.rfile.read(length)
        try:
            text, engine = stt.transcribe(wav, HUB.language)
        except Exception as e:
            HUB.emit("error", keep=True, text=f"I couldn't transcribe that: {e}")
            return self._json({"text": "", "error": str(e)})
        if text:
            HUB.heard(text)
        self._json({"text": text, "engine": engine})


class QuietServer(ThreadingHTTPServer):
    """Don't print a traceback when the HUD page simply drops a connection (reload, cancelled audio)."""
    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _open_window(url: str) -> None:
    """Open the HUD as a standalone app window (Edge/Chrome app mode), else a browser tab."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidates:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--start-maximized",
                              "--autoplay-policy=no-user-gesture-required"])
            return
    webbrowser.open(url)


def _watchdog() -> None:
    """Shut down a little while after the HUD window is closed."""
    while True:
        time.sleep(5)
        with HUB.sub_lock:
            has_clients = bool(HUB.subscribers)
        if not has_clients and time.time() - HUB.last_client_seen > 20:
            print("HUD window closed. Jarvis shutting down.")
            os._exit(0)


def port_in_use() -> bool:
    import socket
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def main(open_window: bool = True, watchdog: bool = True, ready: threading.Event | None = None,
         boot: bool = False) -> None:
    global HUB
    try:
        server = QuietServer(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(f"Port {PORT} is busy - is Jarvis already running? (Set JARVIS_HUD_PORT in .env to change it.)")
    HUB = Hub()
    threading.Thread(target=HUB.brain_worker, daemon=True).start()
    threading.Thread(target=HUB.cpu_sampler, daemon=True).start()
    gpu.monitor()                                   # GPU usage, sampled every 2 s
    threading.Thread(target=HUB.weather_loop, daemon=True).start()
    threading.Thread(target=HUB.mic_watch, daemon=True).start()
    auto_call = HUB.standby_wanted() and HUB.live_on_open() and live_mod.available()
    if HUB.standby_wanted():
        if auto_call:
            # Live from the start; after a Windows sign-in, give the network a moment first
            t = threading.Timer(25 if boot else 6, HUB.auto_live)
            t.daemon = True
            t.start()
        else:
            HUB.standby_start(6)                    # hands-free from the start (after the window has opened)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Jarvis HUD running at {url}  (close the HUD window or press Ctrl+C to stop)")
    hour = datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    HUB.history.append({"type": "jarvis", "time": datetime.now().strftime("%H:%M:%S"),
                        "text": f"Good {part}, {memory.call_name()}. All systems online. How can I help?",
                        "quiet": auto_call, "greeting": True})   # the Live call greets you out loud instead
    if open_window:
        _open_window(url)
    if watchdog:
        # Shut down once no HUD window is connected (give a new or reloading window time to arrive first).
        HUB.last_client_seen = time.time() + (40 if open_window else 120)
        threading.Thread(target=_watchdog, daemon=True).start()
    if ready:
        ready.set()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
