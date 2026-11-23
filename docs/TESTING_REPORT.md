# Testing report

Only real results are recorded here. "Session scripts" are older end-to-end checks that still live outside the
repository (they need real AI keys and devices); they are being turned into `tests/` cases marked `network`.

## How to run

```
.venv\Scripts\python -m pytest tests                 # fast, offline, temporary data folder, fake keys only
set PA_TEST_NETWORK=1 && .venv\Scripts\python -m pytest tests   # also the online tests (none yet)
.venv\Scripts\python packaging\build.py              # then smoke-test the packaged exe (see below)
```

## 2026-11-23 — Agents and safety fixes (v1.19.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 360 passed, 3 skipped | new tests/test_agents.py (57 cases incl. every web × private pair, tools an agent asks for but doesn't have, a changed database row, board and memories kept from web agents, the real local tool loop, approvals, Stop, one at a time) and a page test that nothing is defined twice |
| Holes probed before the fix | 3 of 3 real | a repository's core.fsmonitor program ran during git status (marker file); write_file accepted a PowerShell profile and a .bat without asking; open_application accepted a web address, a network path and any .exe path. All three were in released versions. Same probe after the fix: refused / asks. Reading secret files was found by reading the code |
| Running app (test copy, no mic) | pass after 1 fix | agent editor, web + memories refused, HTML shown as text, live state, 9 pages and the form without sideways scroll at 375 px, no script errors. Fixed: a second renderAgents() stopped the whole page at start-up; 358 tests had passed because they only check syntax |
| Emergency Stops | 0 in this session | with a hook on the button and Esc; the earlier 16 remain unexplained |
| Packaged exe 1.19.0 (isolated data, no mic, fake Ollama, a page kept open) | 51/51 in 3 runs, 50/51 in one | the 38 checks of 1.18.0 plus: an agent really ran, only its own tools were sent to the AI, no memories sent for a web agent, a tricked AI got refusals for 3 tools, private results kept off the web agent's board, nothing written, audit log, own agent kept after restart. The one failure: the PC went to standby during that run (Windows log 12:09:29 to 13:03:33) and the network check reported the disconnected Wi-Fi |
| Page of the packaged exe in a browser | pass | version 1.19.0, all 9 pages open, no script errors |
| Setup.exe size | 142 MB | |
| Not tested | — | agents, plans and automations by voice with a real AI |

## 2026-11-23 — Automations and plans (v1.18.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 301 passed, 3 skipped | new tests/test_automations.py (79): refused steps, paths, apps and sites; triggers; once a day, missed times skipped, both start-up runs when busy; stop between steps and while waiting; a changed database row; one at a time (20 repeats); approvals inside a run; import/export; the AI's tool; plans in all three modes; no tool schema with an empty object |
| Running app (test copy, no mic) | pass after 1 fix | make / run / import / switch on / delete, template editor, unsafe imports refused, HTML in a name shown as text, plan card (hidden in focus mode), plan setting (bad value ignored), phone width. Fixed: the On checkbox was invisible |
| Found while building | fixed | `open_path` with %COMSPEC% passed the first file check; a second start-up automation was dropped when the first was busy; an imported AI prompt would have reached the AI as the user's words; an object without properties in a tool schema (some AI services refuse the whole request) |
| Unexplained | open | 16 Emergency Stops in the test copy at 10:16:19-24 (also 8 on 21 Nov 14:25-14:26 and 1 at 20:54). The code only stops on the button, Esc twice or the tray. Two instrumented repeats (desktop and phone size): none. Cause not established |
| Packaged exe 1.18.0 (isolated data, no mic, fake Ollama, a page kept open) | 38/38 in 3 of 3 runs | the 27 checks of 1.17.1 plus: automation and plan tools, 21 safe step kinds, an automation ran all its steps, unsafe step and imported AI prompt refused, import arrives off, the start-up automation ran by itself once after a restart and not before, plans ask first, no Emergency Stop by itself |
| Setup.exe size | 142 MB | |
| Not tested | — | with a real AI (plans, creating by voice); a real timed run (tick is unit-tested with a fake clock) |

## 2026-11-23 — Packaged exe 1.17.0 and 1.17.1

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 222 passed, 3 skipped | 5 new cases: the web page test retries and uses a second site before reporting a failure |
| Packaged exe 1.17.0 | 27/27, not released | the network check in that run wrongly said web pages don't load (one lost request; cause not known); the exe check only looked for *a* verdict, so it passed. 5 of 5 repeats in the exe were right. Fixed in 1.17.1 (retry + second site) |
| Packaged exe 1.17.1 (isolated data, no mic, fake Ollama) | first run broke off (connection reset), then 27/27 in 8 runs | the network check must now say "Internet is working" 3 times in a row. The reset matches a test mistake, reproduced separately: started with --no-window and no open page, the engine stops itself (exit code 0, after 55 s in the probe); with a page open it keeps running. The last 3 runs keep a page open. The installed app runs without that watchdog |
| Setup.exe size | 142 MB | |

## 2026-11-22 — Software manager, network center, developer tools (v1.17.0)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 217 passed, 3 skipped | new tests/test_pccare.py (40): winget tables (search, updates, list, truncation note), good/bad package ids, looking needs no OK, install/update/uninstall/update-all ask first (kind `software`) and do nothing on No, unknown ids refused, one change at a time, report when done, 10 network verdicts, netsh parsing, git status of a temporary repo, ports, untrusted marking, JARVIS_NO_MIC keeps the mic closed |
| Real, read-only (PA_TEST_NETWORK=1) | pass | winget search "vlc", 17 waiting updates listed, installed list; network check "Internet is working (45 ms)" in 8.6 s; speed test 57 Mbps (5 MB); dev tool versions in 1.8 s |
| Running app (test copy) | pass after 3 fixes | PC Care cards: 17 updates with Update buttons, network verdict + details; Update → approval box "Update Bonjour from 3.0.0.10 to 3.1.0.1 with winget?" → Deny → nothing changed (audit: granted false ×4; a fifth approval got no answer because the server was stopped; Bonjour still 3.0.0.10). Fixed: raw `<untrusted>` tags in the Activity feed, the button stuck on "Asking…" after Deny, software approvals now use the warning style |
| Found | fixed | with an approval waiting in the test copy, the app opened the mic to hear a spoken yes/no (log: no mic heard anything; no words were logged). Whether a silent clip reached the online speech service isn't known: the test copy uses the project's keys. JARVIS_NO_MIC=1 now turns the microphone off completely |
| Not tested | — | a real install/update/uninstall (would change the owner's PC) |

## 2026-11-21 — Focus mode: just the face (v1.16.1)

| Suite | Result | Notes |
|---|---|---|
| `pytest tests` | 178 passed, 2 skipped | new page test: focus mode hides menu/top bar/footer, dock has its 5 buttons wired |
| Running app (test copy) | pass after 1 fix | side/top/foot hidden, face 1008x756 in a 1024x768 window, dock visible; globe, rings (green pulsing mic while listening), mask, light theme, phone width 375 px (no sideways scroll); Show details brings everything back, Ctrl+K shows the typing box, dock mic starts listening, dock buttons follow Hands-free and Spoken replies. Fixed: the assistant's name under the mask sat behind the dock |
| Packaged exe 1.16.1 (isolated data, real local voice + speech model, fake Ollama) | 23/23 | the 19 checks of 1.15.0 plus: window/workspace/OCR tools inside the exe, empty workspaces list, workspace needs a name, focus-mode dock in the page (the owner's windows were not read or moved) |
| Setup.exe size | 142 MB | |
| Note (corrected 23 Nov) | — | one check turned Hands-free on in the test copy. That could not open the microphone: JARVIS_HANDSFREE=off blocks standby. What did open it briefly was the start-up level check of every test copy run until then. JARVIS_NO_MIC=1 was added to the test copy here, but it only skipped that start-up check; spoken answers to approvals were still possible until 1.17.0 |

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
