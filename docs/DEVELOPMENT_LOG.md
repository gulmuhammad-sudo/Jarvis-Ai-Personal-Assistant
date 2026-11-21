# Development log

Newest first. Each entry: what was done, how it was tested, what is open, the next task.

## 2026-11-21 — Session 2: voices on this PC (v1.11.0)

**Done** — `jarvis/local_tts.py` (sherpa-onnx 2.x runs Piper voices; its built-in phonemizer is gone, so
espeak-ng from `espeakng-loader` is called through ctypes to make the IPA), voice source Auto/Online/This PC,
speed/pitch sliders, voice downloads in Settings › Voices. GitHub: pushes now via the zuha-aziz account.

**Tested** — pytest 116 passed + real voice; round trip local voice → local speech-to-text gave back the English
sentence and nearly the Urdu one; running app returned audio/wav for English and Urdu (1.09 s / 4.56 s).
Not done: packaged exe build with the new native libraries (sherpa_onnx, espeakng_loader, pywhispercpp).

**Next** — build and smoke-test the exe; then NEXT_STEPS.md (universal command bar, Personal Intelligence Engine).

## 2026-11-21 — Session 2, part 2: UI polish (v1.13.0)

**Done** — icon tiles + per-icon hover motion across the app, settings alignment/switches/section icons/row
animation, reduced-motion support, Photo face removed (UI, upload API, drawing code, installer choice), duplicate
`check` icon removed. Packaged-exe check of 1.12.0 found a frozen-only bug (local STT with no console) — fixed.

**Next** — build 1.13.0, re-run the exe check, update the owner's installed app (1.7.1) with Setup, then ask
before starting the next roadmap phase.

## 2026-11-21 — Session 2: settings tabs, favicon, tidy folder, short README (v1.12.0)

**Done** — Settings regrouped into 6 tabs (script kept every id); Permissions separate from Privacy; favicon;
build output moved to %TEMP%\PersonalAssistant-build (old build/ and dist app folder deleted, ~570 MB);
.venv/.claude/.env hidden in Explorer; README shortened, full text in docs/USER_GUIDE.md. The owner chose to
keep the per-user install location (AppData\Local\Programs) — uninstall from Settings › Apps / Control Panel
already works.

**Tested** — pytest 116 + 2 skipped; running-app check (TESTING_REPORT.md).

**Next** — build 1.12.0 (first build with the new Temp location), update the owner's installed app (still
1.7.1), publish a GitHub release with `gh` (ask first).

## 2026-11-21 — Session 1, part 5: speech to text on this PC (v1.10.0, committed locally)

**Done** — `jarvis/local_stt.py` (whisper.cpp via pywhispercpp: faster-whisper isn't installable on Python 3.15
because onnxruntime has no build), Auto / Online / This PC in `stt.py`, local wake-word name check, Settings ›
Microphone row with model downloads. At the owner's request: removed the saved GitHub login (Windows Credential
Manager `git:https://github.com`), installed GitHub CLI (their command); pushing paused until they say.

**Tested** — pytest 108 + 1 real transcription; running app (see TESTING_REPORT.md). A bug found in the app check
(forced Urdu garbling English) was fixed.

**Next** — owner's go-ahead for: local voice (Piper) or the next item in NEXT_STEPS.md; a new exe build.

## 2026-11-21 — Session 1, part 4: saved permissions (v1.9.2)

**Done** — Ask/Allow/Never per action kind in Settings › Privacy (hud.py `PERMISSION_KINDS`, `permission`,
`set_permissions`; checked first in `confirm`). Tests no longer touch the microphone (`JARVIS_NO_MIC`).

**Tested** — pytest 101/101; running app check (TESTING_REPORT.md).

**Next** — NEXT_STEPS.md: local speech-to-text (after the owner's go-ahead).

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
