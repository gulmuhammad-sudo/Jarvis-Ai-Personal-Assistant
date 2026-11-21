# Development roadmap

Phases run in order, but a later item moves earlier when something depends on it. Each deliverable is small
enough to finish, test and release on its own. Numbers in brackets are decisions from FEATURE_STATUS.md.

## Phase 1 — Audit and foundation
- [x] Repository audit, version check, 110-decision matrix, docs (2026-11-21)
- [x] `tests/` with pytest, isolated data folder, no real keys (2026-11-21, v1.8.0)
- [x] API keys encrypted with Windows DPAPI, migrated out of `.env` safely [26] (v1.8.0)
- [ ] Audit log of actions (tool, summary, approval, result) [26, 109]
- [ ] Prompt-injection guard for web pages / files given to the AI [26, 31]
- [ ] PowerShell deny-list for destructive commands [26, 44]
- [ ] Emergency stop: cancel the running task and the Live call [20, 26]
- [ ] SQLite storage layer with versioned migrations; history and activity kept across restarts [109]

## Phase 2 — AI brain and models
- [ ] Ollama backend (OpenAI-compatible endpoint on localhost) [2, 5]
- [ ] Model discovery, "is Ollama running", pull a recommended model with consent [90]
- [ ] Routing: local first, cloud for vision/long context when allowed, offline fallback [14, 12]
- [ ] API keys fully optional; first-run works with local AI only [3, 15]
- [ ] Model diagnostics on the AI Models page [99]

## Phase 3 — Voice, HUD, avatar
- [ ] Local speech-to-text (faster-whisper, optional download) [12, 23]
- [ ] Local voice (Piper, optional download); speed and pitch in Settings [37]
- [ ] Local wake-word check [23]
- [ ] Universal command bar: search settings, memories, history, run commands [107]
- [ ] HUD customization (colours, panels) and avatar reactions [41, 97]

## Phase 4 — Memory and personal intelligence
- [ ] Personal Intelligence Engine on SQLite: profile, memories with categories/importance, search [9, 100, 104]
- [ ] Memory dashboard with search and a simple knowledge graph view [40]
- [ ] User-controlled learning (suggested memories you approve) [29]
- [ ] Skills / custom instructions [103]

## Phase 5 — Windows computer agent
- [ ] Window management and desktop layouts [102, 71]
- [ ] OCR on screenshots (Windows built-in OCR) [17]
- [ ] Software manager via winget (with approval) [43]
- [ ] Network diagnostics [78]; developer tools [50]

## Phase 6 — Multi-agent and automation
- [ ] Visible multi-step plans with step approval [20]
- [ ] Workflow engine + templates; Automation Studio UI [35, 108]
- [ ] Agent profiles sharing context [39, 101]

## Phase 7 — Productivity and knowledge
- [ ] Read/create DOCX, XLSX, PPTX, PDF [32, 25, 87]
- [ ] Local document index (RAG) [25]
- [ ] Tasks/projects, calendar/planner, notes manager [85, 45, 53]
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
