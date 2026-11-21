# Development log

Newest first. Each entry: what was done, how it was tested, what is open, the next task.

## 2026-11-21 — Session 1, part 3: task routing (v1.9.1)

**Done** — `providers.route()`: seeing questions → an AI that can see; offline → local only (or a plain
message); a routing note in Activity (not counted as an action). The owner now approves each next step.

**Tested** — pytest 94/94; running app check (see TESTING_REPORT.md).

**Next** — NEXT_STEPS.md: saved permissions (after the owner's go-ahead).

## 2026-11-21 — Session 1, part 2: rest of Phase 1 + local AI (v1.9.0)

**Done**
- `jarvis/audit.py` (audit log), `jarvis/guard.py` (untrusted-text marking, PowerShell deny-list),
  Emergency Stop (`tools.STOP`, loops in providers/brain/Ollama, `/api/stop`, Stop button, Esc twice, tray),
  `jarvis/storage.py` (SQLite + migrations; history restored at start; Settings › Privacy: keep / clear / audit view),
  `jarvis/local_ai.py` + `OllamaBrain` + AI Models "Local AI" card (detect, start, download with progress,
  choose model, prefer local).
- Ran the app (isolated test copy) in the browser pane after each feature, as the owner asked.

**Tested** — pytest 80/80; running-app checks listed in TESTING_REPORT.md. A page-script break (literal line
break inside a JS string) was found by running the app and is now caught by tests/test_pages.py.

**Open** — real Ollama not installed (needs the owner's OK); 1.8.0/1.9.0 installers not on GitHub Releases yet.

**Next** — NEXT_STEPS.md step 1–2.

## 2026-11-21 — Session 1: repository audit, Phase 1 foundation (v1.8.0)

**Done**
- Audit: one branch (`main`), tags v1.0.0–v1.7.2, all versions consistent (repo 1.7.2 = README only; release,
  installer and installed app = 1.7.1). No API keys in logs or git history.
- Wrote `docs/`: master plan with audit report, 110-decision status matrix, architecture, security review,
  roadmap, changelog (reconstructed from tags), testing report, next steps, how to continue.
- `tests/` (pytest): 27 tests, temporary data folder, fake keys; the real `.env` is protected by a fixture.
- `jarvis/keystore.py`: API keys encrypted with Windows DPAPI in `keys.dat`; `.env` keys migrate automatically,
  removed from `.env` only after the encrypted copy reads back; never in test runs (`JARVIS_DATA_DIR` set).
  `config.save_env_keys` and the installer store keys encrypted.

**Tested**
- pytest 27/27; older end-to-end scripts all pass (regression 42, round3 24, round4 33, round5 22, rename 11,
  approvals 12) — round4's key check updated to the new encrypted storage.
- Packaged exe 1.8.0 with a fake `%APPDATA%`: keys migrated, settings kept, providers connected, Live available.

**Open**
- 1.8.0 Setup.exe not yet uploaded to GitHub Releases (needs the owner: no GitHub CLI here, the browser can't
  attach local files).
- The owner's real keys move to `keys.dat` the first time the 1.8.0 app (or `python -m jarvis` from the
  checkout) starts.

**Next** — continuing in the same session: audit log, prompt-injection guard, PowerShell deny-list, emergency
stop, SQLite history, Ollama (see NEXT_STEPS.md).
