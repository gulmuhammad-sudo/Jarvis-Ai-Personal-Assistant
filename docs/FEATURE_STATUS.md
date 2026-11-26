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
| 13 | Automatic updates with consent | IMPLEMENTED BUT NEEDS TESTING | `updates.py`, Settings › Updates | GitHub Releases | test_updates_parts.py; a real look at GitHub | Downloading and installing for real in the installed app; going back |
| 14 | Multi-model support and routing | IMPLEMENTED BUT NEEDS TESTING | `jarvis/providers.py` (`MultiBrain`, `chain`, `route`, `needs_vision`, `online`), AI Models page | 5 | test_local_ai 7, test_routing 14; running app: "photo" question with Groq chosen went to Gemini | 1.9.1: screen/picture questions go to an AI that can see; offline → local only; fallback inside the routed order. Missing: long-document routing (comes with document reading, 25/32) |
| 15 | Unlimited local usage | IMPLEMENTED BUT NEEDS TESTING | `jarvis/local_ai.py` | 5 | test_local_ai | No limits on local models (only the PC's speed/memory) |

## B. Intelligence, security and system management (16–30)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 16 | Adaptive AI personality | NOT IMPLEMENTED | `jarvis/brain.py` (fixed prompt) | 100, 105 | — | Personality settings + learned style, shared with 105 |
| 17 | Visual awareness (screenshots, OCR, images, documents) | PARTIALLY IMPLEMENTED | tools `look_at_screen`, `take_screenshot`, `read_screen_text` (`jarvis/ocr.py`); vision via Gemini/OpenRouter | 5 | test_desktop (OCR on a generated picture) | 1.16.0: Windows' own OCR, offline — screen, one window or a picture file. Missing: offline image understanding, PDF reading |
| 18 | Proactive intelligence and alerts | PARTIALLY IMPLEMENTED | `jarvis/schedule.py`, `jarvis/alerts.py`, `jarvis/hud.py` | 38 | regression (alerts parts) | Battery, prayers, alarms, briefing, overload alerts. Missing: user-configurable alert rules |
| 19 | Multilingual (English, Urdu, Roman Urdu, Hindi, Arabic) | IMPLEMENTED BUT NEEDS TESTING | `jarvis/languages.py`, `jarvis/urdu.py`, `jarvis/stt.py`, `jarvis/tts.py` | — | Session checks for Urdu script / Roman Urdu rewrites | 19 languages + any typed language. Add unit tests (started in `tests/`) |
| 20 | Controlled autonomous multi-step tasks | IMPLEMENTED BUT NEEDS TESTING | `jarvis/plans.py`, tools `make_plan` / `plan_step`, plan card, Settings › Permissions › Plans; approvals, `tools.STOP` | 6, 101 | test_automations (plans), test_guard_audit (stop) | 1.18.0: the assistant shows its steps and asks first (or per step, or only shows). 1.20.0: a refusal holds in code. Tried with Gemini (plan, refusal, per step) and Groq (refusal). Whether a plan is made is up to the AI; risky tools ask on their own either way. Not tried in Live calls |
| 21 | Secure remote access / web interface | IMPLEMENTED BUT NEEDS TESTING | `remote.py`, `remote.html`, `access.py`, `qr.py`, Settings › Devices | 26, 28 | test_remote_api.py; phone page in the test copy | A real phone in the Wi-Fi; Windows' firewall question; Tailscale |
| 22 | Local-first privacy | PARTIALLY IMPLEMENTED | `jarvis/config.py`, `jarvis/keystore.py`, `jarvis/local_ai.py`, Settings › Privacy | 5, 98 | test_keystore, test_storage | Keys encrypted; local AI keeps conversations on the PC; history can be switched off/cleared. Cloud AIs still receive messages when used |
| 23 | Custom wake word, local detection | IMPLEMENTED BUT NEEDS TESTING | `jarvis/wake.py`, `jarvis/hud.py` (standby, `_check_wake`), `jarvis/local_stt.py` | — | Session wake-word test passed (cloud); local path not yet tried with a real voice | Any name works. 1.10.0: with Speech to text = This PC (or offline) the name check runs locally. Needs a real-voice run on the laptop |
| 24 | Advanced developer mode | NOT IMPLEMENTED | — | 50, 91 | — | — |
| 25 | Knowledge and document understanding | PARTIALLY IMPLEMENTED | `jarvis/documents.py`, `jarvis/docindex.py`, tables `doc_folders`, `docs`, `doc_text`, tool `documents`, Tools & Skills › Documents | — | test_documents, running app | 1.22.0: PDF, Word, Excel, PowerPoint, text; local index of chosen folders (word search). Missing: meaning search, scanned PDFs (pictures of text) |
| 26 | Application security and permissions | PARTIALLY IMPLEMENTED | `jarvis/hud.py` (token, host check), `jarvis/tools.py`, `jarvis/keystore.py`, `jarvis/audit.py`, `jarvis/guard.py` | — | test_keystore 8, test_safety 6, test_guard_audit 38 | 1.8.0: keys encrypted (DPAPI). 1.9.0: audit log, prompt-injection marking, PowerShell deny-list, Emergency Stop. Missing: saved per-kind permissions, privacy dashboard |
| 27 | System monitoring dashboard | IMPLEMENTED BUT NEEDS TESTING | `jarvis/hud.py` (stats), `jarvis/gpu.py`, `jarvis/hud.html` | — | none | CPU, RAM, GPU, disk, battery, network |
| 28 | Multiple Windows PC support | IMPLEMENTED BUT NEEDS TESTING | `peers.py`, tool `other_pc`, Settings › Devices | 21, 74 | test_peers_sync.py (two real programs) | Two real PCs |
| 29 | Adaptive personal learning | PARTIALLY IMPLEMENTED | `memory.suggest_from`, `hud.py` `_suggest_memory`, Memory page card | 100 | test_memory_engine (suggest / no-suggest cases) | 1.14.0: when you say something lasting about yourself it asks "Remember this?"; nothing is saved without your OK; switch in Settings › Privacy. Missing: learning habits/patterns |
| 30 | Hybrid background / interactive tasks | PARTIALLY IMPLEMENTED | `jarvis/live.py` (tools in a pool), `jarvis/schedule.py` scheduler | — | live test | Timers, alarms and tools run in the background. Missing: a task list you can see and cancel |

## C. Productivity, creativity and automation (31–50)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 31 | Web intelligence and browser assistance | PARTIALLY IMPLEMENTED | tools `web_search`, `fetch_webpage`, `open_website`, `search_web_in_browser`, `play_youtube`; `jarvis/guard.py` | 26 | test_guard_audit | Search with fallbacks, page reading, web text marked untrusted (1.9.0). Missing: browser automation (Playwright) |
| 32 | Word, Excel, PowerPoint, PDF suite | PARTIALLY IMPLEMENTED | `jarvis/documents.py`, tool `documents` | 25 | test_documents | 1.22.0: reads and makes .docx .xlsx .pptx .pdf (PDF through hidden Edge). Missing: changing an existing file, pictures, charts |
| 33 | No smart-home / IoT | NOT APPLICABLE | — | — | — | Excluded |
| 34 | Cybersecurity scope = privacy protection | PARTIALLY IMPLEMENTED | see 26 | 26, 98 | — | Baseline security partly there; privacy-protection tools not yet |
| 35 | Automation Studio | IMPLEMENTED BUT NEEDS TESTING | `jarvis/automations.py`, table `automations`, tool `automation`, Automations page | 20, 26 | test_automations, running app | 1.18.0: safe steps, by hand / at a time / when the app opens, results kept. No conditions or loops; only runs while the app runs |
| 36 | No native mobile app | NOT APPLICABLE | — | — | — | Excluded |
| 37 | Fully customizable voice | PARTIALLY IMPLEMENTED | `jarvis/tts.py`, `jarvis/live.py`, `jarvis/languages.py`, `jarvis/local_tts.py` | — | test_voices, test_local_tts | 18 Live, 15 reading and 6 offline voices (1.23.0: Pakistani women's voices in all three); speed and pitch in Settings. Missing: your own voice |
| 38 | Smart notification center | PARTIALLY IMPLEMENTED | `jarvis/alerts.py`, Activity feed in `jarvis/hud.html` | — | none | Pop-ups + feed (not kept after restart). Missing: history, filters, do-not-disturb |
| 39 | AI agent ecosystem | IMPLEMENTED BUT NEEDS TESTING | `jarvis/agents.py`, table `agents`, tool `delegate`, Agents page | 20 | test_agents | 1.19.0: 4 ready-made agents and your own, hard tool limits, web or private never both. Tried with Gemini (Researcher, Writer, a tricked page) |
| 40 | Knowledge graph and memory dashboard | IMPLEMENTED BUT NEEDS TESTING | Memory page in `jarvis/hud.html` (List / Graph), `memory.graph()` | 9 | test_skills_graph (graph, names), running app | 1.15.0: graph view — you in the middle, categories, memories (size = stars), names/places found in 2+ memories link them; hover shows the text, click opens it in the list. Not yet tried by the owner |
| 41 | Complete UI customization | PARTIALLY IMPLEMENTED | `jarvis/hud.html` | — | test_pages; running-app checks | Theme, face, focus mode, settings in tabs, animated icons (1.12–1.13). Missing: colours, layout, panel choice |
| 42 | Multi-user voice profiles | NOT IMPLEMENTED | — | 7 | — | — |
| 43 | Windows software manager | IMPLEMENTED BUT NEEDS TESTING | `jarvis/software.py` (winget), tool `software`, Tools & Skills › PC Care › Software updates, permission kind `software` (Ask/Never, never Allow) | 26 | test_pccare (parsing, approvals, one change at a time), real read-only search/list/updates | 1.17.0: search, installed, updates; install/update/uninstall/update all after approval, in the background, reported when done. A real install was not run in testing (approval box checked with Deny) |
| 44 | Advanced Windows administration | PARTIALLY IMPLEMENTED | tools `run_powershell`, `power_action`, `wireless`, `set_brightness`, `lock_computer`; `jarvis/guard.py` | 26 | test_guard_audit (24 refused, 8 allowed) | PowerShell asks first; destructive commands refused outright (1.9.0). Missing: services, scheduled tasks, event log tools |
| 45 | Calendar and planner | IMPLEMENTED BUT NEEDS TESTING | `jarvis/planner.py`, table `calendar`, tool `calendar`, Planner page | — | test_planner, running app | 1.21.0: events (repeat, all day, over midnight), overlap warning, reminders, month and week view with tasks, alarms, prayers. No sync with online calendars, no .ics |
| 46 | Email assistant | IMPLEMENTED BUT NEEDS TESTING | `jarvis/mail.py`, tool `email`, Planner › Email | 77 | test_mail (pretend Gmail), running app | 1.26.0: Gmail, reading, search, warnings, drafts. Never sends. Not tried with a real account; no other providers, no attachments |
| 47 | File intelligence | PARTIALLY IMPLEMENTED | tools `find_files`, `find_old_files`, `clean_folder`, `read_text_file`, `write_file`, `make_folder` | 25 | none | Search, clean-up to Recycle Bin, text files |
| 48 | Media center | IMPLEMENTED BUT NEEDS TESTING | `jarvis/media.py`, tool `media`, Studio › Media | — | test_studio, running app with real radio | 1.30.0: now playing, volume, own library, playlists, radio. Control of other apps' music only checked as far as Windows' answer |
| 49 | Gaming assistant | NOT IMPLEMENTED | — | — | — | — |
| 50 | Developer studio | PARTIALLY IMPLEMENTED | `jarvis/devtools.py`, tool `dev_tools` | 24 | test_pccare | 1.17.0: installed dev tools and versions, git status of a project, programs listening on ports (read-only). Missing: running builds/tests, editing code |

## D. Personal services and specialized tools (51–70)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 51 | Personal finance manager | IMPLEMENTED BUT NEEDS TESTING | `jarvis/life.py`, tables `money`, `budgets`, `bills`, tool `money`, Planner › Money | — | test_life, running app | 1.24.0: spending, income, budgets, bills with reminders, trend, CSV copy. One currency; no bank, no import |
| 52 | Language assistant | PARTIALLY IMPLEMENTED | `jarvis/languages.py`, `jarvis/urdu.py`, `jarvis/local_stt.py` | — | test_core (Urdu text) | Talks in many languages (speech recognised online or on this PC); no translation/learning tools |
| 53 | Personal knowledge manager and notes | PARTIALLY IMPLEMENTED | `jarvis/notes.py`, tools `notes`, `save_note`, Planner page › Notes | 25 | test_planner, running app | 1.21.0: search, read, change, rename, delete (Recycle Bin). Missing: links between notes, meaning search |
| 54 | Screen recording | IMPLEMENTED BUT NEEDS TESTING | `jarvis/screenrec.py`, Studio › Recorder, REC window in `desktop.py` | 26 (no silent recording) | test_studio, real getDisplayMedia of the test page's own tab, REC window for real | 1.30.0. Not tried with a real screen, microphone or the box in the app's window |
| 55 | AI image generation and editing | IMPLEMENTED BUT NEEDS TESTING | `jarvis/images.py`, tool `images`, Studio › Images | 5 | test_studio, running app with one real picture | 1.30.0: editing on the PC; making online (Pollinations.ai, owner's choice). No local making: this PC has no graphics card for it. The free service puts its name in a corner |
| 56 | No AI video studio | NOT APPLICABLE | — | — | — | Excluded |
| 57 | Backup and recovery | IMPLEMENTED BUT NEEDS TESTING | `backup.py`, Settings › Backup | 26 | test_backup_health.py; real restore in the test copy | Restoring on another PC, a USB stick |
| 58 | No public plugin SDK initially | NOT APPLICABLE | — | — | — | Excluded for now |
| 59 | Voice communication assistant | NOT IMPLEMENTED | — | — | — | — |
| 60 | AI personal companion | IMPLEMENTED BUT NEEDS TESTING | `jarvis/people.py`, tool `people`, Daily › People | 100, 105 | test_travel_meet_people, running app | 1.29.0: people, birthdays, check-in, manner. The manner not yet tried with a real AI |
| 61 | AI learning center | IMPLEMENTED BUT NEEDS TESTING | `jarvis/learn.py`, tool `learn`, Daily › Learn | — | test_learn_fit, running app | 1.28.0: decks, spaced repetition, quiz, import/export, reminder. Not tried with a real AI; no courses or lessons |
| 62 | Health and fitness center | IMPLEMENTED BUT NEEDS TESTING | `jarvis/fit.py`, tool `fitness`, Daily › Fitness | storage layer | test_learn_fit, running app | 1.28.0: water, steps, sleep, weight, workouts, targets, charts, reminders. Typed or spoken by the owner; no watch or phone is connected |
| 63 | Travel and trip planner | IMPLEMENTED BUT NEEDS TESTING | `jarvis/travel.py`, tool `travel`, Daily › Travel | 31 | test_travel_meet_people, running app with real weather | 1.29.0: plan, packing, papers, budget, weather, calendar. No maps, tickets or bookings |
| 64 | No shopping assistant | NOT APPLICABLE | — | — | — | Excluded |
| 65 | News and intelligence center | IMPLEMENTED BUT NEEDS TESTING | `jarvis/news.py`, tool `news`, Daily › News | 31 | test_news (made-up feeds), running app with real feeds | 1.27.0: topics, sources, search, follow, keep, briefing. Not tried with a real AI; no alerts when something new appears |
| 66 | No smart-home dashboard | NOT APPLICABLE | — | — | — | Excluded |
| 67 | Social media assistant | NOT IMPLEMENTED | — | — | — | — |
| 68 | Meeting and conference assistant | IMPLEMENTED BUT NEEDS TESTING | `jarvis/meet.py`, tool `meetings`, Daily › Meetings | stt | test_travel_meet_people, real offline speech model with a synthetic voice | 1.29.0: notes, actions, writing down with consent. Not tried with a real microphone or in an online call (hears the room, not the call's own sound) |
| 69 | Smart search and research engine | PARTIALLY IMPLEMENTED | tools `web_search`, `fetch_webpage` | 31 | none | Web search with fallbacks; no multi-source research report |
| 70 | Emergency and personal safety | NOT IMPLEMENTED | — | — | — | — |

## E. Advanced personal and system management (71–90)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 71 | Workspace manager | IMPLEMENTED BUT NEEDS TESTING | `jarvis/winmgr.py` (workspaces), table `workspaces`, tool `workspace`, Tools & Skills › Workspaces | 102 | test_desktop (fake windows), real check on test windows | 1.16.0: save the open windows under a name; Open reopens closed apps and puts every window back (per monitor). Store apps can be placed but not reopened. Not yet tried by the owner on their own apps |
| 72 | Data analytics and visualization | NOT IMPLEMENTED | — | 32 | — | — |
| 73 | Communication and messaging center | NOT IMPLEMENTED | — | 46 | — | — |
| 74 | Local-only memory sync | IMPLEMENTED BUT NEEDS TESTING | `sync.py`, tables `sync_items`, `sync_lost` | 28 | test_peers_sync.py | Two real PCs over days; goals, journal, money aren't synced |
| 75 | Performance optimization center | PARTIALLY IMPLEMENTED | tools `system_status`, `clean_folder` | 27 | none | Shows heavy apps; clean-up to Recycle Bin |
| 76 | Smart clipboard | PARTIALLY IMPLEMENTED | tool `clipboard` (read/write) | — | none | No history |
| 77 | Encrypted password and identity manager | IMPLEMENTED BUT NEEDS TESTING | `jarvis/vault.py`, page Vault | secure storage | test_vault_lock, running app | 1.31.2: outside the AI's reach. Windows Hello with a pretend answer only (its box needs the owner's finger) |
| 78 | Network and internet center | IMPLEMENTED BUT NEEDS TESTING | `jarvis/netcheck.py`, tools `network`, `wireless`, Tools & Skills › PC Care › Network | — | test_pccare (10 verdict cases), real check on this PC | 1.17.0: Wi-Fi signal, router, internet, DNS and a real web page (spots Wi-Fi sign-in pages) with a plain verdict; speed test (~10 MB, Cloudflare); flush DNS |
| 79 | No separate background scheduling engine | NOT APPLICABLE | (`jarvis/schedule.py` stays the small built-in scheduler) | — | — | Excluded |
| 80 | No separate hardware manager | NOT APPLICABLE | (hardware stats live in the dashboard, 27) | — | — | Excluded |
| 81 | Document and identity vault | IMPLEMENTED BUT NEEDS TESTING | `jarvis/vault.py`, page Vault | secure storage | test_vault_lock, running app | 1.31.2: documents with numbers, dates, reminders and encrypted files |
| 82 | Weather intelligence | IMPLEMENTED BUT NEEDS TESTING | tool `get_weather`, `jarvis/schedule.py` | — | live test used it once | Unit test with a stubbed response |
| 83 | Clock, stopwatch, countdown, alarms | IMPLEMENTED BUT NEEDS TESTING | `jarvis/clock.py`, `jarvis/schedule.py`, tool `clock`, Daily › Clock | — | test_clock, running app | 1.27.0: stopwatch, timers that survive a restart, focus rounds, ringing with snooze, world clock. The sound itself and voice commands not heard by a person yet |
| 84 | Goals and habit tracker | IMPLEMENTED BUT NEEDS TESTING | `jarvis/life.py`, tables `goals`, `habits`, `habit_log`, tool `goals`, Planner › Goals | — | test_life, running app | 1.24.0: targets, steps, streaks, reminders |
| 85 | Task and project management | IMPLEMENTED BUT NEEDS TESTING | `jarvis/planner.py`, table `tasks`, tool `tasks`, Planner page | storage layer | test_planner, running app | 1.21.0: due day or time (reminds), importance, projects, done. No sub-tasks |
| 86 | Reflection and mood journal | IMPLEMENTED BUT NEEDS TESTING | `jarvis/life.py`, table `journal`, tool `journal`, Planner › Journal | — | test_life, running app | 1.24.0: entries, mood of 30 days, search, reminder; closed to the AI until allowed. Not encrypted (see 77, 81) |
| 87 | Presentation design studio | PARTIALLY IMPLEMENTED | `jarvis/documents.py` (`_make_pptx`) | 32 | test_documents | 1.22.0: slides from text, 4 themes, speaker notes. Missing: pictures, charts, preview |
| 88 | Audio and voice studio | NOT IMPLEMENTED | — | — | — | — |
| 89 | Database and information studio | NOT IMPLEMENTED | — | storage layer | — | — |
| 90 | AI model and local AI management | PARTIALLY IMPLEMENTED | AI Models page (Local AI card), `jarvis/local_ai.py`, `jarvis/providers.py` | 5 | test_local_ai | 1.9.0: detect/start Ollama, list models with capabilities, download recommended models with progress, choose model, prefer local. Missing: delete models, disk usage |

## F. Integrations, accessibility and future intelligence (91–110)

| # | Decision | Status | Source files | Depends on | Tests | Remaining / next action |
|---|---|---|---|---|---|---|
| 91 | API and developer integration center | IMPLEMENTED BUT NEEDS TESTING | `devapi.py`, /v1, Settings › API | 26 | test_remote_api.py | Real AI with /v1/ask; plugins of others |
| 92 | Knowledge sharing and export | NOT IMPLEMENTED | — | 9 | — | — |
| 93 | Accessibility center | PARTIALLY IMPLEMENTED | voice control, RTL Urdu, light/dark | — | none | No screen-reader labels audit, no font-size setting |
| 94 | No live-streaming studio | NOT APPLICABLE | — | — | — | Excluded |
| 95 | System restore and troubleshooting | IMPLEMENTED BUT NEEDS TESTING | `doctor.py` repairs, restore points, Windows' tools | 99 | test_backup_health.py | Microphone, shortcut and DNS repairs on the owner's PC |
| 96 | No household management | NOT APPLICABLE | — | — | — | Excluded |
| 97 | AI avatar and character studio | PARTIALLY IMPLEMENTED | faces Globe/Mask/Rings in `jarvis/hud.html` (Photo removed in 1.13.0 at the owner's request) | — | manual checks | No character editor, no lip sync |
| 98 | Privacy and permission dashboard | IMPLEMENTED BUT NEEDS TESTING | `jarvis/privacy.py`, `jarvis/netlog.py`, page Privacy | 6, 26 | test_privacy, running app | 1.31.0: going out, Local only, microphone and screen uses, Windows' list, permissions with an hour, who may read what, kept and how long. Not tried with a real microphone or a real Live call |
| 99 | Self-diagnostics and health monitoring | IMPLEMENTED BUT NEEDS TESTING | `doctor.py`, Settings › Health, tool `self_check`, crash notice | — | test_backup_health.py | Real AI with `self_check`; look by itself in the background |
| 100 | Personal user understanding engine | PARTIALLY IMPLEMENTED | `jarvis/memory.py` (profile + top memories in every prompt) | 9 | test_memory_engine | Shared Personal Intelligence Engine with 9, 29, 40, 103, 104. 1.14.0: categories, importance, search. Missing: skills/custom instructions [103] |
| 101 | Multi-agent command center | PARTIALLY IMPLEMENTED | Agents page, shared board, `delegate` | 20, 39 | test_agents | 1.19.0: give tasks, live state, results, shared board. One agent at a time, no parallel teams |
| 102 | Desktop and window management | IMPLEMENTED BUT NEEDS TESTING | `jarvis/winmgr.py` (Win32 via ctypes), tools `manage_windows`, `arrange_windows` | — | test_desktop 29, real check on 2 test windows (9/9) | 1.16.0: list, focus, minimise/maximise/restore, snap to halves/quarters/centre, minimise all, 2-6 windows side by side; per-monitor DPI and Windows 11 invisible borders handled; window titles marked untrusted |
| 103 | Knowledge and skill expansion | PARTIALLY IMPLEMENTED | `jarvis/skills.py`, `storage.py` (table `skills`), tools `use_skill` / `save_skill`, Tools & Skills page | 100 | test_skills_graph 11 | 1.15.0: your own skills — Rules (every reply) and Routines (run by name or the Run button), on/off, edit, delete; the AI can save one only after you approve. Missing: importing documents as knowledge, shareable skill packs |
| 104 | User understanding for all user types | PARTIALLY IMPLEMENTED | same as 100 | 100 | none | Same engine as 100 |
| 105 | Personality and emotional intelligence | NOT IMPLEMENTED | — | 16 | — | — |
| 106 | Universal device and app integration | PARTIALLY IMPLEMENTED | `connections.py`, tool `connection` | 91 | test_remote_api.py (a pretend service) | The real services; reading from devices; more kinds |
| 107 | Universal command and search bar | PARTIALLY IMPLEMENTED | top input box (Ctrl+K) in `jarvis/hud.html` | 109 | none | Sends to the assistant; doesn't search settings, memories or history |
| 108 | Workflow marketplace and templates | PARTIALLY IMPLEMENTED | templates, export / import in `jarvis/automations.py` | 35 | test_automations | 1.18.0: 4 templates, sharing as text (imports are checked and arrive off). No online marketplace |
| 109 | Command history and activity timeline | IMPLEMENTED BUT NEEDS TESTING | `jarvis/timeline.py`, tool `history`, Privacy › Timeline | — | test_privacy, running app | 1.31.0: days, search, kinds, take out, CSV, ask again, most used. Tool not tried with a real AI |
| 110 | Modular expansion and upgrade system | IMPLEMENTED BUT NEEDS TESTING | `parts.py`: parts on/off, downloaded parts, versions; going back | 13 | test_updates_parts.py | Plugins from others (not planned: safety) |

## Totals (after v1.31.2, 24 Nov 2026)

| Status | Count |
|---|---|
| IMPLEMENTED AND VERIFIED | 1 |
| IMPLEMENTED BUT NEEDS TESTING | 39 |
| PARTIALLY IMPLEMENTED | 38 |
| NOT IMPLEMENTED | 22 |
| BLOCKED BY EXTERNAL DEPENDENCY | 0 |
| NOT APPLICABLE | 10 |
