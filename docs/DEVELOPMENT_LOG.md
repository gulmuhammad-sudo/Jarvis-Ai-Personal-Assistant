# Development log

Newest first. Each entry: what was done, how it was tested, what is open, the next task.

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
