# Feature status — all 110 decisions

First written in the repository audit of 2026-11-21 (code at v1.7.2, commit `6e9819a`). Update a row whenever its
status changes; never delete history (add notes instead).

**Statuses**

| Status | Meaning |
|---|---|
| IMPLEMENTED AND VERIFIED | Works, and a repeatable test (in `tests/`) or a recorded end-to-end check proves it |
| IMPLEMENTED BUT NEEDS TESTING | The code exists and is used, but no repeatable test covers it yet |
| PARTIALLY IMPLEMENTED | Some of the decision exists; the rest is listed under *Remaining* |
| NOT IMPLEMENTED | Nothing yet (a decorative button does not count) |
| BLOCKED BY EXTERNAL DEPENDENCY | Needs something we can't get for free or can't do from here |
| NOT APPLICABLE | Excluded by the decision itself ("No …") |

"Session checks" are the end-to-end scripts run during development in November 2026 (live call with simulated
audio, installer, uninstaller, packaged-exe smoke test). They are being moved into `tests/` so they can be repeated.

## A. Core platform and AI foundation (1–15)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 1 | Windows desktop app as an EXE | IMPLEMENTED AND VERIFIED | `packaging/build.py`, `packaging/setup_app.py`, `packaging/setup.html`, `jarvis/install.py`, `jarvis/desktop.py` | — | Session checks 18 Nov: packaged exe started headless, all providers/mic/TTS OK; installer backend 9/9; uninstaller 1/1; v1.7.1 installed on the dev PC | Not code-signed (signing certificates cost money: SmartScreen warning stays). Move installer tests into `tests/` |
| 2 | Hybrid local + cloud AI | IMPLEMENTED BUT NEEDS TESTING | `jarvis/local_ai.py`, `jarvis/providers.py` (`OllamaBrain`, `chain`) | Ollama installed by the user | tests/test_local_ai.py 7/7 against a fake Ollama server | 1.9.0: local (Ollama) + cloud in one chain. Not yet run against a real Ollama install on this PC |
| 3 | Zero-budget development | PARTIALLY IMPLEMENTED | `jarvis/providers.py`, `jarvis/tts.py`, `jarvis/stt.py` | 5, 12 | none | Everything used is free, but the assistant needs free-tier cloud keys to think or transcribe. Local AI removes that need |
| 4 | Live voice and normal chat | IMPLEMENTED BUT NEEDS TESTING | `jarvis/live.py`, `jarvis/hud.py`, `jarvis/providers.py`, `jarvis/hud.html` | — | Session check: live call with simulated audio 11/11 (dev build). Not yet run inside the packaged exe | Live call inside the installed exe; repeatable live test in `tests/` (needs a Gemini key: marked optional) |
| 5 | Local AI as the default | IMPLEMENTED BUT NEEDS TESTING | `jarvis/providers.py` (`prefer_local`, default on), AI Models page | Ollama | test_local_ai: local goes first / last | Default is local-first whenever Ollama has a tool-capable model. Needs a real-model run |
| 6 | Customizable PC-control permissions | IMPLEMENTED BUT NEEDS TESTING | `jarvis/hud.py` (`PERMISSION_KINDS`, `permission`, `set_permissions`, `confirm`), `jarvis/tools.py` (`ctx.approve`), Settings › Privacy › Permissions | 26, 98 | tests/test_permissions.py 7/7; running app: PowerShell = Never refused `Get-Date` with no question | 1.9.2: Ask / Allow / Never per kind (8 kinds), saved across restarts; Allow only for PowerShell, lock, Wi-Fi off. Needs a real-PC run with the installed exe |
| 7 | Google sign-in, email/password, local accounts | NOT IMPLEMENTED | — | 28, 42 | — | Single local user only. Local accounts first; Google sign-in needs an OAuth client registration (free, but the user must create it) |
| 8 | Full assistant personalization | PARTIALLY IMPLEMENTED | `jarvis/schedule.py`, `jarvis/memory.py`, `jarvis/hud.html`, `packaging/setup.html` | — | rename test 11/11 | Name, call-name, language, voices, theme, face, chat text. Missing: personality style, speech speed/pitch in the UI |
| 9 | Advanced long-term memory | PARTIALLY IMPLEMENTED | `jarvis/memory.py`, `jarvis/storage.py` (table `memories`), tools `remember_fact` / `recall_memories` / `edit_memory` / `merge_memories` / `forget_memory` | 40, 100 | test_memory_engine 20 | 1.14.0: SQLite, 9 categories, importance 1-3, word search, only the top 60 go to the AI, old memory.json imported once (kept as a backup). Missing: encryption at rest, semantic (meaning) search |
| 10 | Plugin marketplace | NOT IMPLEMENTED | — | 110, 26 | — | Needs a module system first (Phase 10) |
| 11 | Futuristic JARVIS HUD | IMPLEMENTED BUT NEEDS TESTING | `jarvis/hud.html`, `jarvis/hud.py` | — | Manual browser checks only | Automated UI smoke test (page loads, no console errors) |
| 12 | Full offline support | PARTIALLY IMPLEMENTED | `jarvis/local_ai.py`, `jarvis/local_stt.py`, `jarvis/stt.py`, page `speechSynthesis` fallback, local tools | 5 | test_local_ai, test_local_stt | Offline brain (Ollama, 1.9.0) and offline speech-to-text (whisper.cpp, 1.10.0). Still online: neural voices (offline falls back to the page's Windows voice), Live calls. Next: local TTS |
| 13 | Automatic updates with consent | NOT IMPLEMENTED | — | GitHub Releases | — | Check GitHub Releases API for a newer `Personal.Assistant.Setup.exe`, ask, download, run Setup (it already upgrades in place) |
| 14 | Multi-model support and routing | IMPLEMENTED BUT NEEDS TESTING | `jarvis/providers.py` (`MultiBrain`, `chain`, `route`, `needs_vision`, `online`), AI Models page | 5 | test_local_ai 7, test_routing 14; running app: "photo" question with Groq chosen went to Gemini | 1.9.1: screen/picture questions go to an AI that can see; offline → local only; fallback inside the routed order. Missing: long-document routing (comes with document reading, 25/32) |
| 15 | Unlimited local usage | IMPLEMENTED BUT NEEDS TESTING | `jarvis/local_ai.py` | 5 | test_local_ai | No limits on local models (only the PC's speed/memory) |

## B. Intelligence, security and system management (16–30)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 16 | Adaptive AI personality | NOT IMPLEMENTED | `jarvis/brain.py` (fixed prompt) | 100, 105 | — | Personality settings + learned style, shared with 105 |
| 17 | Visual awareness (screenshots, OCR, images, documents) | PARTIALLY IMPLEMENTED | tools `look_at_screen`, `take_screenshot`; vision via Gemini/OpenRouter | 5 | none | No OCR, no offline vision, no image/PDF file analysis |
| 18 | Proactive intelligence and alerts | PARTIALLY IMPLEMENTED | `jarvis/schedule.py`, `jarvis/alerts.py`, `jarvis/hud.py` | 38 | regression (alerts parts) | Battery, prayers, alarms, briefing, overload alerts. Missing: user-configurable alert rules |
| 19 | Multilingual (English, Urdu, Roman Urdu, Hindi, Arabic) | IMPLEMENTED BUT NEEDS TESTING | `jarvis/languages.py`, `jarvis/urdu.py`, `jarvis/stt.py`, `jarvis/tts.py` | — | Session checks for Urdu script / Roman Urdu rewrites | 19 languages + any typed language. Add unit tests (started in `tests/`) |
| 20 | Controlled autonomous multi-step tasks | PARTIALLY IMPLEMENTED | agent loops in `jarvis/providers.py` / `jarvis/brain.py`, approvals, `tools.STOP` | 6, 101 | test_guard_audit (stop) | 1.9.0: Emergency Stop (button, Esc twice, tray). Missing: visible plan and step list |
| 21 | Secure remote access / web interface | NOT IMPLEMENTED | `jarvis/hud.py` binds 127.0.0.1 only (deliberately) | 26, 28 | — | Needs device pairing + TLS before exposing anything beyond this PC |
| 22 | Local-first privacy | PARTIALLY IMPLEMENTED | `jarvis/config.py`, `jarvis/keystore.py`, `jarvis/local_ai.py`, Settings › Privacy | 5, 98 | test_keystore, test_storage | Keys encrypted; local AI keeps conversations on the PC; history can be switched off/cleared. Cloud AIs still receive messages when used |
| 23 | Custom wake word, local detection | IMPLEMENTED BUT NEEDS TESTING | `jarvis/wake.py`, `jarvis/hud.py` (standby, `_check_wake`), `jarvis/local_stt.py` | — | Session wake-word test passed (cloud); local path not yet tried with a real voice | Any name works. 1.10.0: with Speech to text = This PC (or offline) the name check runs locally. Needs a real-voice run on the laptop |
| 24 | Advanced developer mode | NOT IMPLEMENTED | — | 50, 91 | — | — |
| 25 | Knowledge and document understanding | PARTIALLY IMPLEMENTED | tools `read_text_file`, `find_files` | 5 | none | Plain text only. Missing: PDF/DOCX/XLSX reading, local index (RAG) |
| 26 | Application security and permissions | PARTIALLY IMPLEMENTED | `jarvis/hud.py` (token, host check), `jarvis/tools.py`, `jarvis/keystore.py`, `jarvis/audit.py`, `jarvis/guard.py` | — | test_keystore 8, test_safety 6, test_guard_audit 38 | 1.8.0: keys encrypted (DPAPI). 1.9.0: audit log, prompt-injection marking, PowerShell deny-list, Emergency Stop. Missing: saved per-kind permissions, privacy dashboard |
| 27 | System monitoring dashboard | IMPLEMENTED BUT NEEDS TESTING | `jarvis/hud.py` (stats), `jarvis/gpu.py`, `jarvis/hud.html` | — | none | CPU, RAM, GPU, disk, battery, network |
| 28 | Multiple Windows PC support | NOT IMPLEMENTED | — | 21, 74 | — | — |
| 29 | Adaptive personal learning | PARTIALLY IMPLEMENTED | `memory.suggest_from`, `hud.py` `_suggest_memory`, Memory page card | 100 | test_memory_engine (suggest / no-suggest cases) | 1.14.0: when you say something lasting about yourself it asks "Remember this?"; nothing is saved without your OK; switch in Settings › Privacy. Missing: learning habits/patterns |
| 30 | Hybrid background / interactive tasks | PARTIALLY IMPLEMENTED | `jarvis/live.py` (tools in a pool), `jarvis/schedule.py` scheduler | — | live test | Timers, alarms and tools run in the background. Missing: a task list you can see and cancel |

## C. Productivity, creativity and automation (31–50)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 31 | Web intelligence and browser assistance | PARTIALLY IMPLEMENTED | tools `web_search`, `fetch_webpage`, `open_website`, `search_web_in_browser`, `play_youtube`; `jarvis/guard.py` | 26 | test_guard_audit | Search with fallbacks, page reading, web text marked untrusted (1.9.0). Missing: browser automation (Playwright) |
| 32 | Word, Excel, PowerPoint, PDF suite | NOT IMPLEMENTED | — | 25 | — | python-docx / openpyxl / python-pptx / pypdf are free |
| 33 | No smart-home / IoT | NOT APPLICABLE | — | — | — | Excluded |
| 34 | Cybersecurity scope = privacy protection | PARTIALLY IMPLEMENTED | see 26 | 26, 98 | — | Baseline security partly there; privacy-protection tools not yet |
| 35 | Automation Studio | NOT IMPLEMENTED | — | 20, 26 | — | — |
| 36 | No native mobile app | NOT APPLICABLE | — | — | — | Excluded |
| 37 | Fully customizable voice | PARTIALLY IMPLEMENTED | `jarvis/tts.py`, `jarvis/live.py`, `jarvis/languages.py` | — | none | 12 Live + 10 reading voices. Speed/pitch only via `.env`; no local TTS |
| 38 | Smart notification center | PARTIALLY IMPLEMENTED | `jarvis/alerts.py`, Activity feed in `jarvis/hud.html` | — | none | Pop-ups + feed (not kept after restart). Missing: history, filters, do-not-disturb |
| 39 | AI agent ecosystem | NOT IMPLEMENTED | (the HUD "Agents" panel only lights up tool categories) | 20 | — | — |
| 40 | Knowledge graph and memory dashboard | IMPLEMENTED BUT NEEDS TESTING | Memory page in `jarvis/hud.html` (List / Graph), `memory.graph()` | 9 | test_skills_graph (graph, names), running app | 1.15.0: graph view — you in the middle, categories, memories (size = stars), names/places found in 2+ memories link them; hover shows the text, click opens it in the list. Not yet tried by the owner |
| 41 | Complete UI customization | PARTIALLY IMPLEMENTED | `jarvis/hud.html` | — | test_pages; running-app checks | Theme, face, focus mode, settings in tabs, animated icons (1.12–1.13). Missing: colours, layout, panel choice |
| 42 | Multi-user voice profiles | NOT IMPLEMENTED | — | 7 | — | — |
| 43 | Windows software manager | NOT IMPLEMENTED | — | 26 | — | `winget` is free and built in |
| 44 | Advanced Windows administration | PARTIALLY IMPLEMENTED | tools `run_powershell`, `power_action`, `wireless`, `set_brightness`, `lock_computer`; `jarvis/guard.py` | 26 | test_guard_audit (24 refused, 8 allowed) | PowerShell asks first; destructive commands refused outright (1.9.0). Missing: services, scheduled tasks, event log tools |
| 45 | Calendar and planner | PARTIALLY IMPLEMENTED | tools `set_alarm`, `set_timer`, `jarvis/schedule.py` | — | regression (alarm parts) | Alarms and timers only |
| 46 | Email assistant | NOT IMPLEMENTED | — | 77 | — | — |
| 47 | File intelligence | PARTIALLY IMPLEMENTED | tools `find_files`, `find_old_files`, `clean_folder`, `read_text_file`, `write_file`, `make_folder` | 25 | none | Search, clean-up to Recycle Bin, text files |
| 48 | Media center | PARTIALLY IMPLEMENTED | tools `media_control`, `play_youtube` | — | none | Media keys, volume, YouTube |
| 49 | Gaming assistant | NOT IMPLEMENTED | — | — | — | — |
| 50 | Developer studio | NOT IMPLEMENTED | — | 24 | — | — |

## D. Personal services and specialized tools (51–70)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 51 | Personal finance manager | NOT IMPLEMENTED | — | storage layer | — | — |
| 52 | Language assistant | PARTIALLY IMPLEMENTED | `jarvis/languages.py`, `jarvis/urdu.py`, `jarvis/local_stt.py` | — | test_core (Urdu text) | Talks in many languages (speech recognised online or on this PC); no translation/learning tools |
| 53 | Personal knowledge manager and notes | PARTIALLY IMPLEMENTED | tools `save_note`, `list_notes` (`data/notes/`) | 25 | none | Text notes only, no search UI |
| 54 | Screen recording | NOT IMPLEMENTED | — | 26 (no silent recording) | — | — |
| 55 | AI image generation and editing | NOT IMPLEMENTED | — | 5 | — | — |
| 56 | No AI video studio | NOT APPLICABLE | — | — | — | Excluded |
| 57 | Backup and recovery | PARTIALLY IMPLEMENTED | installer keeps data on update/uninstall | 26 | installer test | No backup/restore command |
| 58 | No public plugin SDK initially | NOT APPLICABLE | — | — | — | Excluded for now |
| 59 | Voice communication assistant | NOT IMPLEMENTED | — | — | — | — |
| 60 | AI personal companion | NOT IMPLEMENTED | — | 100, 105 | — | — |
| 61 | AI learning center | NOT IMPLEMENTED | — | — | — | — |
| 62 | Health and fitness center | NOT IMPLEMENTED | — | storage layer | — | — |
| 63 | Travel and trip planner | NOT IMPLEMENTED | (weather only) | 31 | — | — |
| 64 | No shopping assistant | NOT APPLICABLE | — | — | — | Excluded |
| 65 | News and intelligence center | PARTIALLY IMPLEMENTED | `jarvis/schedule.py` (`headlines`), `daily_briefing` | — | none | Headlines in the briefing only |
| 66 | No smart-home dashboard | NOT APPLICABLE | — | — | — | Excluded |
| 67 | Social media assistant | NOT IMPLEMENTED | — | — | — | — |
| 68 | Meeting and conference assistant | NOT IMPLEMENTED | — | — | — | — |
| 69 | Smart search and research engine | PARTIALLY IMPLEMENTED | tools `web_search`, `fetch_webpage` | 31 | none | Web search with fallbacks; no multi-source research report |
| 70 | Emergency and personal safety | NOT IMPLEMENTED | — | — | — | — |

## E. Advanced personal and system management (71–90)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 71 | Workspace manager | NOT IMPLEMENTED | — | 102 | — | — |
| 72 | Data analytics and visualization | NOT IMPLEMENTED | — | 32 | — | — |
| 73 | Communication and messaging center | NOT IMPLEMENTED | — | 46 | — | — |
| 74 | Local-only memory sync | NOT IMPLEMENTED | — | 28 | — | — |
| 75 | Performance optimization center | PARTIALLY IMPLEMENTED | tools `system_status`, `clean_folder` | 27 | none | Shows heavy apps; clean-up to Recycle Bin |
| 76 | Smart clipboard | PARTIALLY IMPLEMENTED | tool `clipboard` (read/write) | — | none | No history |
| 77 | Encrypted password and identity manager | NOT IMPLEMENTED | — | secure storage | — | Must stay outside the AI's reach |
| 78 | Network and internet center | PARTIALLY IMPLEMENTED | tool `wireless`, `run_powershell` | — | none | Wi-Fi/Bluetooth status and toggles |
| 79 | No separate background scheduling engine | NOT APPLICABLE | (`jarvis/schedule.py` stays the small built-in scheduler) | — | — | Excluded |
| 80 | No separate hardware manager | NOT APPLICABLE | (hardware stats live in the dashboard, 27) | — | — | Excluded |
| 81 | Document and identity vault | NOT IMPLEMENTED | — | secure storage | — | — |
| 82 | Weather intelligence | IMPLEMENTED BUT NEEDS TESTING | tool `get_weather`, `jarvis/schedule.py` | — | live test used it once | Unit test with a stubbed response |
| 83 | Clock, stopwatch, countdown, alarms | PARTIALLY IMPLEMENTED | HUD clock, `set_timer`, `set_alarm` | — | regression (alarm parts) | No stopwatch |
| 84 | Goals and habit tracker | NOT IMPLEMENTED | — | storage layer | — | — |
| 85 | Task and project management | NOT IMPLEMENTED | — | storage layer | — | — |
| 86 | Reflection and mood journal | NOT IMPLEMENTED | — | storage layer | — | — |
| 87 | Presentation design studio | NOT IMPLEMENTED | — | 32 | — | — |
| 88 | Audio and voice studio | NOT IMPLEMENTED | — | — | — | — |
| 89 | Database and information studio | NOT IMPLEMENTED | — | storage layer | — | — |
| 90 | AI model and local AI management | PARTIALLY IMPLEMENTED | AI Models page (Local AI card), `jarvis/local_ai.py`, `jarvis/providers.py` | 5 | test_local_ai | 1.9.0: detect/start Ollama, list models with capabilities, download recommended models with progress, choose model, prefer local. Missing: delete models, disk usage |

## F. Integrations, accessibility and future intelligence (91–110)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 91 | API and developer integration center | NOT IMPLEMENTED | — | 26 | — | — |
| 92 | Knowledge sharing and export | NOT IMPLEMENTED | — | 9 | — | — |
| 93 | Accessibility center | PARTIALLY IMPLEMENTED | voice control, RTL Urdu, light/dark | — | none | No screen-reader labels audit, no font-size setting |
| 94 | No live-streaming studio | NOT APPLICABLE | — | — | — | Excluded |
| 95 | System restore and troubleshooting | PARTIALLY IMPLEMENTED | `jarvis.log`, mic diagnostics, Unmute/Boost | 99 | none | No "repair" actions |
| 96 | No household management | NOT APPLICABLE | — | — | — | Excluded |
| 97 | AI avatar and character studio | PARTIALLY IMPLEMENTED | faces Globe/Mask/Rings in `jarvis/hud.html` (Photo removed in 1.13.0 at the owner's request) | — | manual checks | No character editor, no lip sync |
| 98 | Privacy and permission dashboard | PARTIALLY IMPLEMENTED | Settings › Privacy in `jarvis/hud.html` | 6, 26 | test_permissions, test_storage, test_guard_audit | Keep/clear history, audit record, per-action permissions (1.9.0–1.9.2). Missing: data-sent-to-cloud overview, mic/camera usage log |
| 99 | Self-diagnostics and health monitoring | PARTIALLY IMPLEMENTED | AI Models status, mic probing, echo-canceller log | — | none | No diagnostics page |
| 100 | Personal user understanding engine | PARTIALLY IMPLEMENTED | `jarvis/memory.py` (profile + top memories in every prompt) | 9 | test_memory_engine | Shared Personal Intelligence Engine with 9, 29, 40, 103, 104. 1.14.0: categories, importance, search. Missing: skills/custom instructions [103] |
| 101 | Multi-agent command center | NOT IMPLEMENTED | — | 20, 39 | — | — |
| 102 | Desktop and window management | NOT IMPLEMENTED | — | — | — | — |
| 103 | Knowledge and skill expansion | PARTIALLY IMPLEMENTED | `jarvis/skills.py`, `storage.py` (table `skills`), tools `use_skill` / `save_skill`, Tools & Skills page | 100 | test_skills_graph 11 | 1.15.0: your own skills — Rules (every reply) and Routines (run by name or the Run button), on/off, edit, delete; the AI can save one only after you approve. Missing: importing documents as knowledge, shareable skill packs |
| 104 | User understanding for all user types | PARTIALLY IMPLEMENTED | same as 100 | 100 | none | Same engine as 100 |
| 105 | Personality and emotional intelligence | NOT IMPLEMENTED | — | 16 | — | — |
| 106 | Universal device and app integration | NOT IMPLEMENTED | — | 91 | — | — |
| 107 | Universal command and search bar | PARTIALLY IMPLEMENTED | top input box (Ctrl+K) in `jarvis/hud.html` | 109 | none | Sends to the assistant; doesn't search settings, memories or history |
| 108 | Workflow marketplace and templates | NOT IMPLEMENTED | — | 35 | — | — |
| 109 | Command history and activity timeline | PARTIALLY IMPLEMENTED | `jarvis/storage.py` (SQLite), `jarvis/audit.py`, Conversations page, Settings › Privacy | — | test_storage 4, test_guard_audit | 1.9.0: conversation + activity survive restarts; permanent audit record viewable in Settings. Missing: timeline page with search and dates |
| 110 | Modular expansion and upgrade system | NOT IMPLEMENTED | — | 13 | — | — |

## Totals (after v1.15.0, 21 Nov 2026)

| Status | Count |
|---|---|
| IMPLEMENTED AND VERIFIED | 1 |
| IMPLEMENTED BUT NEEDS TESTING | 12 |
| PARTIALLY IMPLEMENTED | 41 |
| NOT IMPLEMENTED | 46 |
| BLOCKED BY EXTERNAL DEPENDENCY | 0 |
| NOT APPLICABLE | 10 |
