# Testing report

Only real results are recorded here. "Session scripts" are older end-to-end checks that still live outside the
repository (they need real AI keys and devices); they are being turned into `tests/` cases marked `network`.

## How to run

```
.venv\Scripts\python -m pytest tests                 # fast, offline, temporary data folder, fake keys only
set PA_TEST_NETWORK=1 && .venv\Scripts\python -m pytest tests   # also the online tests (none yet)
.venv\Scripts\python packaging\build.py              # then smoke-test the packaged exe (see below)
```

## 2026-11-21 — Windows, workspaces, OCR (v1.16.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 177 passed, 2 skipped | new tests/test_desktop.py (29): snap/arrange maths for 1-6 windows (no overlap, fills the screen), fraction round trip, finding windows by app/alias/title/number, list text, tools with fake windows, window titles untrusted, workspace save/update/restore/reopen a closed app/Store apps not launched, delete needs OK, real Windows OCR on a generated picture |
| Real windows (2 windows the check opened itself, never the owner's apps) | 9/9 | list, find, snap left lands exactly on the left half (1920x1020 real pixels at 125% scaling), minimise, maximise, side by side, save workspace → scramble → restore puts both back, focus |
| Windows OCR | pass | generated picture "Invoice number 4821 / Total due: 3,500 rupees" read exactly in 0.8 s, offline |
| Running app (test copy) | pass | 4 new tools listed, Workspaces card (empty state, "Type a name first", 2 sample workspaces with app chips, Open/Delete), save API refuses an empty name. Save/Open not pressed there: they would read and move the owner's real windows |

## 2026-11-21 — Skills and memory graph (v1.15.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 148 passed, 2 skipped | new tests/test_skills_graph.py (11): save/edit/find/limits, rules first, only enabled skills reach the AI (and `brain.system_prompt`), prompt budget lists the rest by name, `use_skill`, `save_skill` refused without approval and while Stop is on, name extraction, graph links only names in 2+ memories |
| Running app (test copy) | pass after 3 fixes | graph: 19 nodes, names Ali/Hina/Lahore; hover tooltip + neighbours lit; click name → list filtered, click category → chip, click memory → scrolled + highlighted. Skills: examples, save, duplicate name error, On/Off, two-click Delete, audit `skill_saved`/`skill_deleted`. Fixed: list stayed visible in Graph mode (CSS beat `hidden`), graph bunched in the middle (layout spread + pre-settled), "On" text inside skill switches; also a console error when the form closed before Save answered |
| Run button with a real AI | not run | would spend the owner's AI quota from the test copy; `run_message` is unit-tested |
| Packaged exe 1.15.0 (isolated data, real local voice + speech model, fake Ollama) | 19/19 | the 14 checks of 1.14.0 plus: memory graph, skills saved (rules first), **Run** sends the routine and the (fake local) AI answers, skills in the audit log, skills kept after restart |
| Setup.exe size | 142 MB | |

## 2026-11-21 — Personal Intelligence Engine (v1.14.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 137 passed, 2 skipped | new tests/test_memory_engine.py (20): one-time import of memory.json with ids/dates kept and a backup, duplicate check, category/importance updates and bad values, search ranking and filters, top-60 limit for the AI, merge, 6 sentences that should be suggested and 6 questions/commands that shouldn't, tool schemas |
| Running app (test copy) | pass | old test memories imported with categories; "Remember this?" card shows editable text, Save stores it with source "suggested", "No thanks" hides it; card disappears when the AI saves the fact itself; search "cat mano" → 1 hit; stars and category select saved (checked via /api/info); no console errors |
| Packaged exe 1.14.0 (isolated data, real local voice + speech model, fake Ollama) | 14/14 | version, favicon, offline speech + voice engines, voice on this PC (3.0 s), local speech-to-text round trip, local AI, old memory.json imported with categories + backup kept, saved suggestion + stars, Stop in audit, memories and conversation kept after restart |
| Setup.exe size | 142 MB | |

## 2026-11-21 — UI polish, Photo face removed (v1.13.0)

| Suite | Result | Notes |
|---|---|---|
| Packaged exe 1.12.0 (isolated data, real local voice + speech model, fake Ollama) | 9/10 → fixed | version, favicon, offline engines inside the exe, voice on this PC (3.0 s WAV), local AI, Stop, history after restart passed; **speech-to-text on this PC failed in the exe** (`'NoneType' object has no attribute 'flush'`: no console) → fixed in local_stt.py + tests/test_frozen_quirks.py; recheck in the 1.13.0 exe |
| `pytest tests` | 117 passed, 2 skipped | |
| Running app (test copy) | pass | 8 switches (click flips, aria-checked follows), 29 rows aligned label/controls, 11 section + 6 tab icons, Photo face gone, rows animate in, no console errors |
| Setup.exe size | 141 MB | up from 104 MB: offline speech + voice engines |

## 2026-11-21 — Settings tabs, favicon, tidy folder (v1.12.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 116 passed, 2 skipped | page scripts parse; all 184 element ids kept after regrouping Settings |
| Running app (test copy) | pass | 6 tabs, each shows the right rows; Permissions tab has the 8 kinds + "Allowed until restart"; Privacy has history + audit only; /favicon.ico 200 image/x-icon; no console errors |
| Build into %TEMP% | not run yet | build.py changed; next build checks it |

## 2026-11-21 — Speech to text on this PC (v1.10.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | **108 passed, 1 skipped** | + test_local_stt (8): WAV → 16 kHz mono, download with progress (fake server), cut-off download leaves nothing, only known models, engine order by setting / offline, "This PC" without a model keeps cloud, cloud failure → this PC. The skipped one runs a real transcription when PA_TEST_STT_DIR points at a model: **passed** when run that way |
| Real model (base-q5_1, 60 MB, this PC) | pass | Windows-voice sentence "Please set a timer for ten minutes and open the calculator." → exact text; 4 s of audio in 1.3 s (2.7 s with model loading) |
| Running app (test copy) | pass after a fix | Settings › Microphone shows Auto / Online / This PC and the models; WAV sent to /api/transcribe → engine "local". First try with the language set to Urdu gave garbled Urdu for English speech (Urdu was forced) → now English/Urdu are auto-detected on this PC; retried: exact text |
| Real voice / Urdu speech | not tested | needs the owner speaking on the laptop |
| Packaged exe | not built | `--collect-all=pywhispercpp` added to build.py; next build must check the native library is included |

## 2026-11-21 — Saved permissions (v1.9.2)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | **101 passed** | + test_permissions (7): default ask, Never refuses without a question, Allow only for safe kinds (even if written by hand), rules survive a restart, Never/Ask ends a session "yes", unknown kinds ignored, tools obey it and it's audited |
| Running app (test copy) | pass | Settings › Privacy lists 8 kinds; Allow disabled (faded) for 5; PowerShell = Never → "run Get-Date" refused with no question, note in Activity |
| Fixed during this step | — | tests opened the microphone for 0.8 s (engine start-up mic check, and a voice approval prompt): now `JARVIS_NO_MIC=1` in tests and the test hub asks on screen only |

## 2026-11-21 — Task routing (v1.9.1)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | **94 passed** | + test_routing (14): seeing questions in English / Roman Urdu / Urdu go to the AI that can see, other questions keep the order ("pick a song" isn't a picture), offline → local only, offline without local → plain message, fallback inside the routed order, online check cached |
| Running app (test copy) | pass | Groq chosen, asked "what is a photo album?": Activity showed "Asked Gemini — needs to see", Gemini answered. Not tried: a real screen question (would send a real screenshot of the owner's screen to the cloud) |

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
