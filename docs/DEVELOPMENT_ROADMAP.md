# Development roadmap

Phases run in order, but a later item moves earlier when something depends on it. Each deliverable is small
enough to finish, test and release on its own. Numbers in brackets are decisions from FEATURE_STATUS.md.

## Phase 1 — Audit and foundation
- [x] Repository audit, version check, 110-decision matrix, docs (2026-11-21)
- [x] `tests/` with pytest, isolated data folder, no real keys (2026-11-21, v1.8.0)
- [x] API keys encrypted with Windows DPAPI, migrated out of `.env` safely [26] (v1.8.0)
- [x] Audit log of actions (tool, summary, approval, result) [26, 109] (v1.9.0)
- [x] Prompt-injection guard for web pages / files given to the AI [26, 31] (v1.9.0)
- [x] PowerShell deny-list for destructive commands [26, 44] (v1.9.0)
- [x] Emergency stop: cancel the running task and the Live call [20, 26] (v1.9.0)
- [x] SQLite storage layer with versioned migrations; history and activity kept across restarts [109] (v1.9.0)

## Phase 2 — AI brain and models
- [x] Ollama backend (native /api/chat so the context size can be set) [2, 5] (v1.9.0)
- [x] Model discovery, "is Ollama running", pull a recommended model with consent [90] (v1.9.0)
- [x] Routing: local first (setting), cloud fallback (v1.9.0); screen/picture → an AI that can see, offline → local only (v1.9.1); long-context routing waits for document reading [14, 12]
- [ ] API keys fully optional; first-run works with local AI only [3, 15]
- [ ] Model diagnostics on the AI Models page [99]

## Phase 3 — Voice, HUD, avatar
- [x] Local speech-to-text (whisper.cpp via pywhispercpp — faster-whisper's onnxruntime has no Python 3.15 build; optional model download) [12, 23] (v1.10.0)
- [ ] Local voice (Piper, optional download); speed and pitch in Settings [37]
- [x] Local wake-word check (uses the local speech model when selected / offline) [23] (v1.10.0)
- [ ] Universal command bar: search settings, memories, history, run commands [107]
- [ ] HUD customization (colours, panels) and avatar reactions [41, 97]

## Phase 4 — Memory and personal intelligence
- [x] Personal Intelligence Engine on SQLite: profile, memories with categories/importance, search [9, 100, 104]
- [x] Memory dashboard with search and a simple knowledge graph view [40]
- [x] User-controlled learning (suggested memories you approve) [29]
- [x] Skills / custom instructions [103] (Rules + Routines)

## Phase 5 — Windows computer agent
- [x] Window management and desktop layouts [102, 71]
- [x] OCR on screenshots (Windows built-in OCR) [17]
- [x] Software manager via winget (with approval) [43]
- [x] Network diagnostics [78]; developer tools [50] (read-only helpers)

## Phase 6 — Multi-agent and automation
- [x] Visible multi-step plans with step approval [20]
- [x] Workflow engine + templates; Automation Studio UI [35, 108] (no online marketplace)
- [x] Agent profiles sharing context [39, 101] (one at a time)

## Phase 7 — Productivity and knowledge
- [ ] Read/create DOCX, XLSX, PPTX, PDF [32, 25, 87]
- [ ] Local document index (RAG) [25]
- [x] Tasks/projects, calendar/planner, notes manager [85, 45, 53]
- [ ] Email (IMAP/SMTP, user's own account) [46]; finance, journal, goals [51, 86, 84]

## Phase 8 — Personal, creative, entertainment
- [ ] Stopwatch and time tools [83]; media, news, learning, fitness, travel, meetings, companion [48, 65, 61, 62, 63, 68, 60]
- [ ] Screen recording (never silent) [54]; local image generation if hardware allows [55]

## Phase 9 — Privacy, integrations, system tools
- [ ] Privacy & permission dashboard [98, 6]; encrypted vault (outside AI reach) [77, 81]
- [ ] Backup and restore [57]; self-diagnostics page [99]; activity timeline [109]
- [ ] Multi-PC pairing and optional remote access (TLS + pairing codes) [21, 28, 74]

## Phase 10 — Expansion and release
- [ ] Update check with consent from GitHub Releases [13]
- [ ] Modular feature install and version checks [110]; rollback
- [ ] Final security audit and regression run; documentation
