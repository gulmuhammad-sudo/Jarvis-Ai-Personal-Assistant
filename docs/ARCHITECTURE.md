# Architecture

## How it runs today (v1.7.x)

One Python process (`Personal Assistant.exe`, or `pythonw -m jarvis` from source):

```
 desktop.py  ── WebView2 window + tray icon + close-to-tray + single instance
     │ starts
 hud.py      ── local HTTP + Server-Sent-Events server on 127.0.0.1:8765 (per-launch token, Host check)
     │          "Hub": the engine. Owns state, settings, approvals, history, standby/wake word
     ├── providers.py / brain.py   AI brain: OpenAI-compatible cloud providers with fallback, tool loop
     ├── live.py + aec.py          Gemini Live calls: mic/speaker streaming, echo canceller, barge-in
     ├── recorder.py, denoise.py   microphone capture, noise reduction (Classic mode, standby)
     ├── stt.py, voice.py          speech-to-text (Whisper via Groq/Gemini; Windows recognizer as backup)
     ├── tts.py                    neural voices (edge-tts, online); page speechSynthesis as backup
     ├── wake.py, urdu.py, languages.py   name detection, Urdu/Roman/Hindi script handling, languages
     ├── tools.py                  every action on the PC (~47 tools) behind approvals
     ├── memory.py, skills.py      Personal Intelligence Engine: profile, memories, graph; your rules/routines
     ├── storage.py, schedule.py   SQLite (history, memories, skills, workspaces); alarms, weather, prayers, news, settings
     ├── winmgr.py, ocr.py         windows (Win32 via ctypes), workspaces; Windows OCR (offline)
     ├── software.py, netcheck.py, devtools.py   winget manager; network check/speed; read-only dev helpers
     ├── alerts.py, gpu.py         loud alerts; GPU counters
     └── install.py                shortcuts, start with Windows, Apps entry, uninstall
 hud.html    ── the whole Command Center UI (one page, canvas faces, settings, setup wizard)
 packaging/  ── build.py (PyInstaller app + installer), setup_app.py + setup.html (install wizard)
```

Storage: JSON files in the data folder (`%APPDATA%\Personal Assistant`, or `data\` in a checkout):
`settings.json`, `profile.json`, `memory.json`, `alarms.json`, `location.json`, `notes\`, `jarvis.log`, and
API keys (moving from plain `.env` to a DPAPI-encrypted `keys.dat`, see SECURITY_REVIEW.md).

## Strengths to keep

- The local server only listens on 127.0.0.1 and needs a random token per launch, so websites can't drive it.
- Every risky tool asks first; deleting goes to the Recycle Bin; system folders are refused.
- Installer upgrades in place and never overwrites user data; uninstaller can keep it.
- Program files and user data are separate.

## Problems found in the audit

| Problem | Why it matters | Plan |
|---|---|---|
| `hud.py` (1,365 lines) is both the web server and the whole engine | Hard to test pieces alone; every feature grows this file | Split gradually: `server` (HTTP) / `engine` (Hub) / feature services. No big-bang rewrite |
| `hud.html` is one 2,947-line file | Same | Split into modules served from `jarvis/web/` when the next big UI work starts |
| No tests in the repository (all checks lived in a temporary folder) | Nothing to rerun before a release | `tests/` with pytest (started in this audit) |
| JSON files for everything | No queries, no migrations, risk with bigger data (memories, history, tasks) | SQLite storage layer with versioned migrations, JSON kept for small settings |
| API keys in a plain-text `.env` | Anyone with file access can read them | DPAPI encryption (started in this audit) |
| History and activity live only in memory | Lost on restart; decision 109 needs a timeline | Store in SQLite |
| Cloud-only brain and speech | Breaks the zero-budget / offline / privacy goals | Phase 2: Ollama + local STT/TTS |

## Target structure (grown step by step)

Shared services first, features on top, so no two features build their own copy of memory, storage or permissions.

```
jarvis/
  core/        config, paths, secrets (DPAPI), storage (SQLite + migrations), events, logging
  security/    permissions, approvals, audit log, prompt-injection guard, command validation
  ai/          model gateway + routing; backends: ollama (local), gemini, groq, openrouter, deepseek, claude
  voice/       live calls, recorder, stt (cloud + local), tts (online + local), wake word, aec, denoise
  intelligence/  Personal Intelligence Engine: profile, memory, learning, knowledge graph, skills
  knowledge/   documents (PDF/DOCX/XLSX/PPTX), local index (RAG)
  agent/       Windows tools, tool registry, multi-step tasks, emergency stop
  automation/  workflows, templates
  features/    calendar, tasks, notes, finance, journal, ... (each a small module using the services above)
  ui/          server (HTTP/SSE) + web assets
  install/     shortcuts, updates, uninstall
```

The move is incremental: a module moves only when it is touched for a feature, keeping imports working
(old names re-export the new ones) so the installer, tests and data stay compatible.

## Interfaces between parts

- UI ↔ engine: HTTP JSON (`/api/...`, token header) + one SSE stream (`/api/events`).
- Engine ↔ AI: `providers.make_brain()` returns an object with `ask(text)`, `set_language()`,
  `set_voice_mode()`, `use(provider, model)`; tool calls go through `tools.execute(name, args, ctx)`.
- Tools ↔ person: `ToolContext.approve(question, kind)` and `notify()` — the only way a tool may act on
  something risky.
- Everything ↔ storage: `config.read_json` / `write_json` today; `core.storage` (SQLite) next.
