# Project master plan

## Goal

Grow Personal Assistant (JARVIS) from a voice assistant into a general-purpose, privacy-focused personal AI for
Windows that adapts to each user, works offline with local AI, and costs nothing to run. The approved
specification is the 110 decisions tracked one by one in [FEATURE_STATUS.md](FEATURE_STATUS.md).

Ground rules: zero budget (no paid APIs, hosting or subscriptions; free tiers optional), local-first data,
security in every module, no rewrite from scratch, no fake features, every change tested and recorded.

## Initial audit report — 2026-11-21

**Repository.** One branch (`main`), tags v1.0.0–v1.7.2, latest commit `6e9819a` (v1.7.2). About 10,600 lines:
Python package `jarvis/` (24 modules), a single-page UI (`jarvis/hud.html`), and `packaging/` (build + installer).

**Version check.** v1.7.1 and v1.7.2 tags point at the right commits and their `__version__` matches.
GitHub Release v1.7.1 (Latest) has `Personal.Assistant.Setup.exe` (103,512,414 bytes). The installed app on the
development PC is 1.7.1 (registry DisplayVersion and the exe's file version). v1.7.2 only changed the README,
so 1.7.1 is still the newest program; there is no discrepancy that affects users.

**What works (checked end to end during November).** Desktop app + tray, installer/upgrade/uninstall, data
migration from the run.py version, cloud AI with fallback, ~47 PC tools behind approvals, Live calls with echo
cancellation and interrupting (simulated-audio test 11/11), wake word by name, noise reduction, Urdu/Roman Urdu
handling, faces, focus mode, alarms/timers/prayers/weather/briefing.

**What is weak or missing.**
1. No tests in the repository — every check so far was a throw-away script. *(Fixing now.)*
2. API keys in plain text. *(Fixing now: DPAPI.)*
3. Cloud-only brain, speech-to-text and voices: no offline use, conversations leave the PC (decisions 2, 5, 12, 15, 22).
4. Two oversized files (`hud.py`, `hud.html`) mix many responsibilities.
5. JSON files instead of a database; history and activity are lost on restart.
6. No prompt-injection guard, PowerShell deny-list, audit log or emergency stop.
7. 51 of 110 decisions are not started; 43 are partial (see FEATURE_STATUS.md).

**Most important architectural improvements, in order.**
1. Test suite + safe secret storage (foundation for everything else). — Phase 1
2. Security core: audit log, prompt-injection guard, command validation, emergency stop. — Phase 1
3. SQLite storage layer with migrations; persist history/activity. — Phase 1→4
4. Model gateway with a local Ollama backend and routing that prefers local. — Phase 2
5. Local speech (faster-whisper) and local voice (Piper) as optional components. — Phase 2/3
6. Personal Intelligence Engine shared by memory, profile, learning, knowledge graph, skills. — Phase 4

## How work is tracked

| File | Purpose |
|---|---|
| [FEATURE_STATUS.md](FEATURE_STATUS.md) | All 110 decisions, status, files, tests, next action |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Phases and their concrete deliverables |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the code is organised now and where it is going |
| [SECURITY_REVIEW.md](SECURITY_REVIEW.md) | Security findings and their status |
| [TESTING_REPORT.md](TESTING_REPORT.md) | Real test results per session |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each version |
| [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) | Session-by-session log |
| [NEXT_STEPS.md](NEXT_STEPS.md) | The exact next tasks |
| [CONTINUE_DEVELOPMENT.md](CONTINUE_DEVELOPMENT.md) | How to resume in a new session |

(These live in `docs/` to keep the repository's top folder small.)
