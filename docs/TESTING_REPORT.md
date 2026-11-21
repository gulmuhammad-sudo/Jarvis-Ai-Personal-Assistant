# Testing report

Only real results are recorded here. "Session scripts" are older end-to-end checks that still live outside the
repository (they need real AI keys and devices); they are being turned into `tests/` cases marked `network`.

## How to run

```
.venv\Scripts\python -m pytest tests                 # fast, offline, temporary data folder, fake keys only
set PA_TEST_NETWORK=1 && .venv\Scripts\python -m pytest tests   # also the online tests (none yet)
.venv\Scripts\python packaging\build.py              # then smoke-test the packaged exe (see below)
```

## 2026-11-21 — Phase 1 rest + local AI (v1.9.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | **80 passed** | + guard/audit (38: 24 dangerous commands refused, 8 normal allowed, untrusted marking, audit redaction, approvals logged, Stop), storage (4), local AI against a fake Ollama (7), page scripts parse with Node + every wired button exists (3) |
| Running app (test copy, isolated data, browser pane) | pass | audit log records tool calls; Settings › Privacy shows them; Stop button stops and is logged; conversation came back after restarting the app; AI Models shows the Local AI card |
| Bug caught while running it | fixed | a `\n` written into hud.html as a real line break stopped the whole page script; now caught by tests/test_pages.py |
| Real Ollama | not tested | Ollama isn't installed on this PC |
| Packaged exe 1.9.0 (isolated data, fake Ollama, spare port) | 7/7 | version; local AI found and first in the chain; answered with a tool; audit has the tool + Stop; conversation back after restart; `assistant.db` created |

## 2026-11-21 — Phase 1 (v1.8.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` (new) | **27 passed** | keystore (8), core (8), safety (6), installer (5). Real `.env` checksum identical before/after |
| Session: regression | 42/42 | dev build |
| Session: round3 (mics, alerts) | 24/24 | |
| Session: round4 (setup wizard, settings) | 33/33 | key test updated: keys now go to encrypted `keys.dat`, not `.env` |
| Session: round5 (wake word, Live ack) | 22/22 | needs network |
| Session: rename | 11/11 | |
| Session: approvals (incl. a real Live call) | 12/12 | needs network |
| Packaged exe 1.8.0 (fake %APPDATA% with a plain .env) | pass | keys moved to `keys.dat` (0 key lines left in `.env`), other settings kept, no key text in `keys.dat`, Gemini/Groq/OpenRouter connected, Live available |

Bug found by the new tests: none in product code. One test itself was wrong (compared misaligned audio blocks)
and was fixed.

## 2026-11-18 — v1.7.1 (recorded during development)

| Check | Result |
|---|---|
| Live call with simulated laptop audio (quiet mic, echo, barge-in) | 11/11, echo canceller removed 23 dB |
| Echo canceller benchmark | ~29 dB removed after 4–7 s |
| Installer backend (prefill, copy, settings, migration, update) | 9/9 |
| Uninstaller on a fake install | shortcuts, Apps entry, data and folder removed |
| Packaged exe headless | all providers, Whisper, voice, microphone listing OK |

## Not yet tested

- Interrupting by voice and the echo canceller on the real laptop speakers/mic (only simulated audio so far).
- A Live call inside the installed exe.
- UI (hud.html) automatically — only manual browser checks so far.
