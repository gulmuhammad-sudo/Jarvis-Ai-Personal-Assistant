"""Live conversation: Jarvis listens and talks at the same time, like a phone call (Gemini Live).

The microphone streams to Gemini continuously and Jarvis's voice streams back as it is generated,
so there is no "record, then transcribe, then answer" wait, and you can interrupt him mid-sentence.
All of Jarvis's tools work here too (apps, YouTube, alarms, PC control...).

Echo guard: with laptop speakers the mic hears Jarvis himself. While he talks, the mic is only
passed on when it is clearly louder than his own echo (you talking over him); a headset needs no guard.
"""
from __future__ import annotations

import asyncio
import base64
import os
import threading
import time
from collections import deque
from typing import Callable

import numpy as np

from . import memory, schedule, tools
from .brain import system_prompt

try:
    import sounddevice as sd
    from google import genai
    from google.genai import types
    from scipy import signal

    from . import recorder
except Exception:            # a package is missing: Live mode is simply not offered
    genai = types = None

# Tried in order: if one hits the free tier's limit, the call continues on the next one.
# 3.1 Flash Live first: in tests it starts answering ~0.2 s sooner than 3.8.
MODELS = [m.strip() for m in os.environ.get(
    "JARVIS_LIVE_MODEL", "gemini-3.1-flash-live-preview,gemini-3.8-live,gemini-2.5-flash-native-audio-latest").split(",") if m.strip()]
MODEL = MODELS[0]
# model -> when it hit its free limit; skipped for a while (kept across restarts)
_resting: dict[str, float] = dict(schedule.get_setting("live_resting") or {})
REST_FOR = 15 * 60
DEFAULT_VOICE = os.environ.get("JARVIS_LIVE_VOICE", "Charon")
VOICES = {   # Gemini's voices (male-sounding ones first; Charon is the closest to the films' Jarvis)
    "Charon": "deep, informative", "Iapetus": "clear", "Orus": "firm", "Sadaltager": "knowledgeable",
    "Rasalgethi": "informative", "Algenib": "gravelly", "Fenrir": "lively", "Puck": "upbeat",
    "Umbriel": "easy-going", "Schedar": "even", "Kore": "firm (female)", "Aoede": "breezy (female)",
}
IN_RATE, OUT_RATE = 16000, 24000      # what Gemini Live takes in / sends back (16-bit mono PCM)
BLOCK = 0.04                          # seconds of mic audio per message
IDLE_STOP = 180                       # end the call after 3 minutes with nobody talking
# How long you have to be quiet before Jarvis answers (Settings: Fast / Normal / Patient).
# Google's default is ~0.6 s; shorter answers sooner, but may cut in when you pause mid-sentence.
PAUSES = {"fast": 400, "normal": 650, "patient": 1000}


def pause_ms() -> int:
    return PAUSES.get(schedule.get_setting("live_pause") or "fast", PAUSES["fast"])

LIVE_NOTE = """
LIVE VOICE CONVERSATION: you are talking with {user} out loud, in real time, like a phone call.
- Speak with a calm, refined British accent, like a loyal butler-engineer.
- Keep each reply short and natural (one to three sentences) unless asked for detail. Never read out lists,
  markdown, URLs or file paths in full.
- Language: if {user} speaks Urdu (or Hindi/Roman Urdu), reply in natural spoken Urdu. English gets English.
- {user} may interrupt you; if so, stop and listen.
- For anything slow (web search, files), say a few words first ("One moment, Sir") and then use the tool.
- If {user} says goodbye or asks you to stop listening ("bye", "that's all", "bas", "band karo"), say a very
  short goodbye and call end_conversation.
"""

END_TOOL = {"name": "end_conversation",
            "description": "End this live voice conversation (the user said goodbye or asked you to stop listening).",
            "input_schema": {"type": "object", "properties": {}}}


def available() -> bool:
    return genai is not None and bool(os.environ.get("GEMINI_API_KEY"))


def voice() -> str:
    v = schedule.get_setting("live_voice") or DEFAULT_VOICE
    return v if v in VOICES else DEFAULT_VOICE


class _Resampler:
    """Streaming resampler (device rate -> 16 kHz) that keeps its filter state between blocks."""

    def __init__(self, rate: int, out_rate: int = IN_RATE):
        self.step = rate / out_rate
        self.pos = 0.0                                   # next output position, in input samples
        self.prev = np.zeros(1, np.float32)              # last input sample of the previous block
        self.sos = signal.butter(8, 0.45 * out_rate, fs=rate, output="sos") if rate > out_rate else None
        self.zi = signal.sosfilt_zi(self.sos) * 0 if self.sos is not None else None

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.step == 1:
            return x
        if self.sos is not None:                         # anti-alias first
            x, self.zi = signal.sosfilt(self.sos, x, zi=self.zi)
        buf = np.concatenate([self.prev, x])             # index 0 = previous block's last sample
        n = int(np.floor((buf.size - 1 - self.pos) / self.step)) + 1
        idx = self.pos + np.arange(max(n, 0)) * self.step
        out = np.interp(idx, np.arange(buf.size), buf)
        self.pos = idx[-1] + self.step - (buf.size - 1) if n > 0 else self.pos - x.size
        self.prev = buf[-1:]
        return out.astype(np.float32)


class LiveSession:
    """One live conversation. start() returns at once; everything runs on its own thread."""

    def __init__(self, ctx: tools.ToolContext, *, on_phase: Callable[[str], None],
                 on_level: Callable[[float], None], on_partial: Callable[[str, str], None],
                 on_user: Callable[[str], None], on_reply: Callable[[str, bool], None],
                 on_tool: Callable[[str, dict], None], on_error: Callable[[str], None],
                 on_end: Callable[[str], None], history: list[tuple[str, str]] | None = None):
        self.ctx = ctx
        self.on_phase, self.on_level, self.on_partial = on_phase, on_level, on_partial
        self.on_user, self.on_reply, self.on_tool = on_user, on_reply, on_tool
        self.on_error, self.on_end = on_error, on_end
        self.history = list(history or [])[-8:]
        self.active = False
        self.phase = ""
        self.mic = ""
        self.voice = voice()
        self.model = MODEL
        self.end_reason = "stopped"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._mic_q: asyncio.Queue | None = None
        self._out = bytearray()                     # Jarvis's voice waiting to be played (int16, 24 kHz)
        self._out_lock = threading.Lock()
        self._out_rate = OUT_RATE
        self._last_play = 0.0                       # when the speaker last played Jarvis's voice
        self._drop_turn = False                     # Esc pressed: ignore the rest of this answer
        self._end_after_speech = False
        self._user_buf, self._reply_buf = "", ""
        self._last_activity = time.time()
        self._last_level = 0.0
        # mic processing state
        self._floor = 0.002
        self._speech = 0.03                         # typical loudness of your voice (raw)
        self._coupling = 0.5                        # how much of Jarvis's voice leaks back into the mic
        self._play_hist: deque[tuple[float, float]] = deque()   # (time, loudness) of what was played
        self._gate_until = 0.0
        self._held: deque[bytes] = deque(maxlen=int(0.3 / BLOCK))   # mic audio held back during his speech
        self._in_turn = False                       # Jarvis is in the middle of an answer
        self._mute_checked, self._muted = time.time(), False
        self._pending_text: list[str] = []
        self._last_voice = 0.0                      # when you last made a sound (for the reply-delay log)
        self.delays: list[float] = []
        self._tasks: set = set()                    # tools running in the background
        self._hold_until = 0.0                      # an alert beep is playing: don't send the mic
        self.barge_ins = 0                          # times you talked over him (for the log)
        self.debug: tuple = ()
        self._hp = signal.butter(2, 100, "hp", fs=IN_RATE, output="sos")
        self._hp_zi = signal.sosfilt_zi(self._hp) * 0
        self._resample: _Resampler | None = None
        self._streams: list = []
        self.thread: threading.Thread | None = None

    # ---------------- control (called from other threads) ----------------
    def start(self) -> None:
        self.active = True
        self.thread = threading.Thread(target=self._thread, name="jarvis-live", daemon=True)
        self.thread.start()

    def stop(self, reason: str = "stopped") -> None:
        if not self.active:
            return
        self.end_reason = reason
        self.active = False
        if self._loop and self._mic_q:
            self._loop.call_soon_threadsafe(self._mic_q.put_nowait, None)   # wake the sender

    def interrupt(self) -> None:
        """Stop Jarvis talking now (Esc). He keeps listening."""
        with self._out_lock:
            self._out.clear()
        self._drop_turn = self._in_turn          # only skip the answer that is still arriving

    def hold_mic(self, seconds: float) -> None:
        """Send nothing for a moment (an alert beep is playing through the speakers)."""
        self._hold_until = time.time() + seconds

    def send_text(self, text: str) -> None:
        """A typed message during the call: Jarvis answers it out loud."""
        self._last_activity = time.time()
        if self._loop and self._session:
            asyncio.run_coroutine_threadsafe(self._session.send_realtime_input(text=text), self._loop)
        else:
            self._pending_text.append(text)      # still connecting: sent as soon as the call is up

    # ---------------- audio ----------------
    def _open_audio(self) -> None:
        dev = recorder.choose_mic()
        if not dev:
            raise RuntimeError("No microphone found.")
        if recorder.is_muted(dev["name"]):
            raise RuntimeError(f"Your microphone ({dev['name']}) is muted in Windows. Press Unmute and try again.")
        self.mic = dev["name"]
        self._resample = _Resampler(dev["rate"])
        recorder._recording.set()               # stop device rescans from killing these streams
        inp = sd.InputStream(device=dev["index"], channels=1, samplerate=dev["rate"], dtype="float32",
                             blocksize=int(dev["rate"] * BLOCK), callback=self._mic_callback, latency="low")
        try:                                     # low latency: his voice starts ~0.1 s sooner
            out = sd.OutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=480,
                                  callback=self._speaker_callback, latency="low")
        except Exception:                        # speaker doesn't take 24 kHz: use its own rate
            self._out_rate = int(sd.query_devices(kind="output")["default_samplerate"])
            out = sd.OutputStream(samplerate=self._out_rate, channels=1, dtype="int16",
                                  blocksize=int(self._out_rate * 0.02), callback=self._speaker_callback, latency="low")
        self._streams = [inp, out]
        inp.start()
        out.start()
        print(f"[live] mic: {self.mic} @ {dev['rate']} Hz, speaker @ {self._out_rate} Hz, voice {self.voice}")

    def _close_audio(self) -> None:
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams = []
        recorder._recording.clear()

    def _speaker_callback(self, outdata, frames, _time, _status) -> None:
        need = frames * 2
        with self._out_lock:
            chunk = bytes(self._out[:need])
            del self._out[:need]
        a = np.frombuffer(chunk.ljust(need, b"\0"), "<i2")
        now = time.time()
        if chunk:
            self._last_play = now
        level = float(np.sqrt(np.mean((a / 32768.0) ** 2)))
        with self._out_lock:                                    # recent loudness, for the echo guard
            self._play_hist.append((now, level))
            while self._play_hist and now - self._play_hist[0][0] > 0.6:
                self._play_hist.popleft()
        outdata[:] = a.reshape(-1, 1)

    def playing(self) -> bool:
        with self._out_lock:
            return bool(self._out) or time.time() - self._last_play < 0.25

    def _mic_callback(self, indata, frames, _time, _status) -> None:
        x = self._resample(indata[:, 0].astype(np.float32))
        if x.size == 0:
            return
        x, self._hp_zi = signal.sosfilt(self._hp, x, zi=self._hp_zi)      # drop fan/AC rumble
        rms = float(np.sqrt(np.mean(x * x)))
        now = time.time()
        talking_back = self.playing()
        if talking_back:
            # His echo reaches the mic up to ~0.3 s after it is played, so compare with the loudest
            # thing he played in the last half second, times how strongly the speaker leaks into the mic.
            with self._out_lock:
                ref = max((lvl for t, lvl in self._play_hist if now - t < 0.5), default=0.0)
            expected = self._coupling * ref
            self.debug = (round(rms, 4), round(expected, 4), round(self._coupling, 3), round(self._speech, 4))
            if rms > expected * 2.5 + self._floor * 3 and rms > self._speech * 0.5:
                if now >= self._gate_until:
                    self.barge_ins += 1
                self._gate_until = now + 1.2              # you are talking over him: let it through
                self._last_activity = now
            elif now >= self._gate_until and ref > 0.003:
                # just his echo: learn the leak quickly when it is stronger than thought, forget it slowly
                ratio = rms / ref
                self._coupling = (self._coupling * 0.7 + ratio * 0.3 if ratio > self._coupling
                                  else self._coupling * 0.995 + ratio * 0.005)
        else:
            self._floor = rms if rms < self._floor else self._floor * 0.995 + rms * 0.005
            if rms > max(self._floor * 3.5, 0.0015):      # you are talking
                self._speech = self._speech * 0.95 + rms * 0.05
                self._last_activity = self._last_voice = now
        gate_open = (not talking_back or now < self._gate_until) and now >= self._hold_until
        if now < self._hold_until:
            self._held.clear()
        gain = float(np.clip(0.1 / max(self._speech, 1e-4), 1.0, 8.0))     # quiet laptop mic -> louder
        real = (np.clip(x * gain, -1, 1) * 32767).astype("<i2").tobytes()
        if gate_open:
            # just opened because you started talking over him: include the 0.3 s before, so your first word isn't cut
            pcm = b"".join(self._held) + real if self._held else real
            self._held.clear()
        else:
            self._held.append(real)
            pcm = b""                       # send nothing while he talks: no echo, and it saves free quota
        if now - self._last_level > 0.08:
            self._last_level = now
            self.on_level(round(min(1.0, rms * gain * 6), 3) if gate_open else 0.0)
        if self._loop and self._mic_q:
            self._loop.call_soon_threadsafe(self._mic_q.put_nowait, pcm)

    def _play(self, pcm: bytes) -> None:
        if self._out_rate != OUT_RATE:
            a = np.frombuffer(pcm, "<i2").astype(np.float32)
            g = np.gcd(self._out_rate, OUT_RATE)
            a = signal.resample_poly(a, self._out_rate // g, OUT_RATE // g)
            pcm = np.clip(a, -32768, 32767).astype("<i2").tobytes()
        with self._out_lock:
            self._out.extend(pcm)

    # ---------------- the conversation ----------------
    def _set_phase(self, phase: str) -> None:
        if phase != self.phase:
            self.phase = phase
            self.on_phase(phase)

    def _config(self, handle: str | None):
        user, me = memory.call_name(), schedule.agent_name()
        system = system_prompt() + LIVE_NOTE.format(user=user)
        if self.history:
            system += "\nEarlier in this conversation (typed or spoken before the call):\n" + "\n".join(
                f"{user}: {u[:300]}\n{me}: {r[:300]}" for u, r in self.history)
        decls = [types.FunctionDeclaration(name=d["name"], description=d["description"],
                                           parameters_json_schema=d["input_schema"])
                 for d in tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS + [END_TOOL]]
        extra = {}
        if "2.5" in self.model:          # no "thinking" before speaking: answers ~0.6 s sooner
            extra["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        return types.LiveConnectConfig(
            **extra,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=pause_ms())),
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice))),
            system_instruction=system,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[types.Tool(function_declarations=decls)],
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
            session_resumption=types.SessionResumptionConfig(handle=handle))

    def _thread(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:
            self.on_error(f"Live conversation stopped: {type(e).__name__}: {e}")
        finally:
            self.active = False
            self._close_audio()
            self._set_phase("")
            self.on_end(self.end_reason)

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._mic_q = asyncio.Queue()
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                              http_options=types.HttpOptions(api_version="v1beta"))
        try:
            self._open_audio()
        except Exception as e:
            self.end_reason = "error"
            self.on_error(str(e))
            return
        handle, failures = None, 0
        # start with the first model that hasn't hit its limit recently (Google takes ~10 s to refuse)
        model_i = next((i for i, m in enumerate(MODELS) if time.time() - _resting.get(m, 0) > REST_FOR), 0)
        while self.active:
            try:
                self.model = MODELS[model_i]
                async with client.aio.live.connect(model=self.model, config=self._config(handle)) as session:
                    self._session, failures = session, 0
                    self._set_phase("listening")
                    while self._pending_text:                 # typed while we were still connecting
                        await session.send_realtime_input(text=self._pending_text.pop(0))
                    handle = await self._run(session) or handle
            except Exception as e:
                if not self.active:
                    break
                msg = str(e)
                print(f"[live] {self.model}: {type(e).__name__}: {msg[:200]}")
                if any(k in msg.lower() for k in ("exhausted", "quota", "429", "not found", "404")) \
                        and model_i + 1 < len(MODELS):
                    _resting[self.model] = time.time()
                    schedule.set_setting("live_resting", _resting)
                    model_i += 1                      # this model is at its limit: carry on with the next one
                    handle = None                     # a resumption handle only works on the same model
                    self.on_tool("switching_model", {"from": self.model, "to": MODELS[model_i], "reason": msg[:80]})
                    continue
                failures += 1
                if failures >= 3 or any(k in msg for k in ("1008", "API key", "PERMISSION", "exhausted", "quota")):
                    self.end_reason = "error"
                    self.on_error(f"Live conversation couldn't continue: {msg[:200]}")
                    break
                await asyncio.sleep(1.5)
            finally:
                self._session = None

    async def _run(self, session) -> str | None:
        """Talk until stopped or until Google asks us to reconnect. Returns the resumption handle."""
        state = {"handle": None}
        sender = asyncio.create_task(self._send_mic(session))
        receiver = asyncio.create_task(self._receive(session, state))
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        errors = [t.exception() for t in done if not t.cancelled() and t.exception()]   # read every one
        if errors and self.active:
            raise errors[0]
        return state["handle"]

    async def _send_mic(self, session) -> None:
        while self.active:
            try:
                pcm = await asyncio.wait_for(self._mic_q.get(), 0.5)
            except asyncio.TimeoutError:
                pcm = b""
            if pcm is None or not self.active:
                break
            if pcm:
                await session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={IN_RATE}"))
            if time.time() - self._mute_checked > 3:          # Teams or the mic key can mute it mid-call
                self._mute_checked = time.time()
                muted = await asyncio.get_running_loop().run_in_executor(None, recorder.is_muted, self.mic)
                if muted and not self._muted:
                    self.on_error(f"Your microphone ({self.mic}) just got muted in Windows, so I can't hear you. "
                                  "Press Unmute (Teams or the keyboard's mic key may have muted it).")
                elif self._muted and muted is False:
                    self.on_tool("microphone", {"state": "unmuted, I can hear you again"})
                self._muted = bool(muted)
            playing = self.playing()
            if self.phase in ("listening", "speaking"):
                self._set_phase("speaking" if playing else "listening")
            if self._end_after_speech and not playing:
                self.stop("goodbye")
            elif not playing and self.phase == "listening" and time.time() - self._last_activity > IDLE_STOP:
                self.stop("idle")

    async def _receive(self, session, state: dict) -> None:
        while self.active:
            got = False
            async for msg in session.receive():
                got = True
                if msg.session_resumption_update and msg.session_resumption_update.new_handle:
                    state["handle"] = msg.session_resumption_update.new_handle
                if msg.go_away:
                    print("[live] server asked to reconnect")
                    return
                if msg.tool_call:            # own task: the call keeps listening while a tool runs or waits for approval
                    task = asyncio.create_task(self._tools(session, msg.tool_call.function_calls or []))
                    self._tasks.add(task)
                    task.add_done_callback(self._tool_done)
                sc = msg.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text:
                    self._user_buf += sc.input_transcription.text
                    self._last_activity = time.time()
                    self.on_partial("user", self._user_buf.strip())
                if sc.output_transcription and sc.output_transcription.text:
                    self._reply_buf += sc.output_transcription.text
                    self.on_partial("jarvis", self._reply_buf.strip())
                if sc.model_turn and not self._in_turn and self._last_voice:
                    d = time.time() - self._last_voice
                    if d < 10:
                        self.delays.append(round(d, 2))
                        print(f"[live] reply started {d:.2f}s after you stopped ({self.model})")
                if sc.model_turn:
                    self._in_turn = True
                if sc.model_turn and not self._drop_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            self._play(part.inline_data.data)
                            self._last_activity = time.time()
                            if self.phase == "listening":
                                self._set_phase("speaking")
                if sc.interrupted:                      # you talked over Jarvis
                    with self._out_lock:
                        self._out.clear()
                    self._flush(interrupted=True)
                if sc.turn_complete:
                    self._flush()
                    self._drop_turn = self._in_turn = False
            if not got:                                  # connection closed without saying why
                raise ConnectionError("live connection closed")

    def _tool_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            print(f"[live] tool failed: {type(task.exception()).__name__}: {task.exception()}")

    def _flush(self, interrupted: bool = False) -> None:
        user, reply = self._user_buf.strip(), self._reply_buf.strip()
        self._user_buf = self._reply_buf = ""
        if user:
            self.on_user(user)
        if reply:
            self.on_reply(reply + (" …" if interrupted else ""), interrupted)

    async def _tools(self, session, calls) -> None:
        if self._user_buf.strip():                       # show what was asked before what was done
            self.on_user(self._user_buf.strip())
            self._user_buf = ""
        responses = []
        for fc in calls:
            name, args = fc.name, dict(fc.args or {})
            if name == "end_conversation":
                self._end_after_speech = True
                responses.append(types.FunctionResponse(id=fc.id, name=name, response={"result": "ok, say goodbye"}))
                continue
            self._set_phase("thinking")
            self.on_tool(name, args)
            out, err = await asyncio.get_running_loop().run_in_executor(None, tools.execute, name, args, self.ctx)
            if isinstance(out, list):                    # a screenshot: send the picture itself
                for block in out:
                    if block.get("type") == "image":
                        await session.send_realtime_input(video=types.Blob(
                            data=base64.b64decode(block["source"]["data"]), mime_type="image/jpeg"))
                out = "The screenshot has been sent to you as an image. Describe what you see."
            text = str(out)[:6000]
            responses.append(types.FunctionResponse(id=fc.id, name=name,
                                                    response={"error": text} if err else {"result": text}))
        try:
            await session.send_tool_response(function_responses=responses)
        except Exception as e:                           # the call ended or Google cancelled the request
            print(f"[live] couldn't send tool result: {type(e).__name__}: {e}")
        self._last_activity = time.time()
        self._set_phase("listening")
