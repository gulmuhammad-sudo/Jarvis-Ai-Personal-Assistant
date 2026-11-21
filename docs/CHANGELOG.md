# Changelog

Each version is also a git tag (`git tag -n20 vX.Y.Z` shows its notes). Newest first.

## 1.9.2 — 2026-11-21
- Settings › Privacy › Permissions: for each kind of action (PowerShell, locking, Wi-Fi off, shutdown/restart,
  cleaning folders, replacing files, closing apps with unsaved work, closing system programs) choose Ask,
  Allow or Never. Kept after a restart. "Allow" exists only for PowerShell, locking and Wi-Fi off; the rest
  always ask (or are never done). Changes are recorded in the audit log.

## 1.9.1 — 2026-11-21
- Smarter choice of AI for each message: questions about the screen, a picture or a photo go to an AI that can
  see images (e.g. Gemini) even when another one is first; with no internet, only the AI on this PC is asked
  (no waiting for cloud AIs that can't answer), or you're told plainly that there's no AI to use offline.
  Activity shows which AI was asked and why.

## 1.9.0 — 2026-11-21
- Local AI: works with Ollama (free) on this PC — offline, private, no limits. AI Models page: Get Ollama,
  Check again / Start, download a recommended model (with your OK and progress), choose the model,
  "Prefer local AI" (on: local first, cloud as backup).
- Emergency Stop: a Stop button, Esc twice, or "Stop everything" in the tray menu stops the running task,
  waiting approvals, the Live call and speech.
- Audit log: every action and approval is recorded (never keys, passwords or file contents); Settings › Privacy › Show.
- Prompt-injection guard: text from web pages, files and the clipboard is marked as untrusted for the AI.
- Dangerous PowerShell commands (formatting disks, deleting Windows, switching off Defender/firewall, user
  accounts, download-and-run…) are refused outright, even with approval.
- Conversation and Activity are kept across restarts (local SQLite database); Settings › Privacy can switch
  this off or clear it.

## 1.8.0 — 2026-11-21
- API keys are stored encrypted for your Windows account (DPAPI, `keys.dat`) instead of plain text in `.env`;
  existing keys move over automatically on first start (removed from `.env` only after they read back correctly).
  The installer saves keys encrypted too.
- Automated tests in `tests/` (pytest, 27 tests; temporary data folder, fake keys only).
- Project documentation in `docs/`: master plan + audit report, 110-feature status, architecture, security
  review, roadmap, testing report, next steps, development log, how to continue.

## 1.7.2 — 2026-11-18
- README: Download link to `Personal Assistant Setup.exe` on GitHub Releases.

## 1.7.1 — 2026-11-18 (installer published on GitHub Releases)
- No error when Google closes a quiet call: keep-alive silence, or it reconnects.
- Internet drops retried ~30 s, then a plain message instead of "APIError 1006".
- Fixed "Event loop is closed" at call end and a 5-minute hang when closing.
- Echo canceller never makes the sound worse; relearns if it goes wrong.
- Multilingual voice fallback; saving settings retries when Windows locks a file.

## 1.7.0 — 2026-11-18
- A real Windows app (`Personal Assistant.exe`) and installer (`Personal Assistant Setup.exe`) with a setup wizard.
- Brings over the run.py version's data; updates keep data; Uninstall in Windows Settings > Apps.

## 1.6.0 — 2026-11-18
- Close hides to the tray; start with Windows; Live call on open; chat in English letters by default.

## 1.5.1 — 2026-11-18
- Code clean-up; wake word reads Urdu ک correctly; tools start with a language set.

## 1.5.0 — 2026-11-18
- Fixed the assistant cutting itself off on Live calls; Urdu-script replies; Photo face; date in Live calls.

## 1.4.0 — 2026-11-18
- Interrupt any time (echo cancellation); focus mode; Globe/Mask/Rings faces; fewer files.

## 1.3.0 – 1.3.3 — 2026-11-16
- Wake word and background-noise reduction; fewer wasted wake-word checks; fixed app name; clock layout.

## 1.2.0 — 2026-11-16
- Welcome setup, any language, approvals remember "yes", activity details.

## 1.1.0 — 2026-11-16
- Hands-free start, AI switching, mic prompt, memory editing, clearer settings.

## 1.0.0 — 2026-11-16
- First public version.
