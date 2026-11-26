# Development log

Newest first. Each entry: what was done, how it was tested, what is open, the next task.

## 2026-11-26 — Session 2, part 28: Phase 10 part 2 — final audit, regression run, documentation (v1.31.11)

**Done** — went through every security requirement of the master plan (SECURITY_REVIEW.md): requests and tokens, commands, paths,
secrets in logs (also counted in the owner's real log and database, nothing read out: none), injected text, the page's HTML. Two
findings fixed (framing; vault links), the audit kept as tests. Full regression: 1545 passed, 4 skipped; exe 80 / 80 and 227 / 227; new user 15 / 15.
README, master plan, roadmap and next steps brought up to date.

**The roadmap of the master plan is complete.** What is left: the decisions marked NOT IMPLEMENTED or PARTIALLY IMPLEMENTED in
FEATURE_STATUS.md, and the owner's own checks.

## 2026-11-26 — Session 2, part 27: Phase 10 part 1 — updates and parts (v1.31.10)

**Done** — `updates.py` (GitHub Releases, double checksum, file version, restore point, going back through `backup.prepare`), `parts.py`
(features off: `parts.offered` for every AI, `_execute` refuses, pages hidden by `body[data-off]`), Settings › Updates, doctor row
"Version", `self_check` action `updates`.

**Found** — a stale status answer drew over a parts switch (now in `CHANGES`, and an older parts answer never draws); the first page
after a start didn't know which parts were off (now in the replay); eleven tabs wrapped one alone onto a second line (now two even rows).

**Next** — Phase 10 part 2: final security audit and regression run, documentation.

## 2026-11-25 — Session 2, part 26: asked languages, top bar, menu (v1.31.8)

**Asked by the owner** — what is asked for in Urdu must not be turned into Roman; fewer icons at the top right (a drop-down); the left menu
was too long.

**Done** — `languages.asked_for`, `Hub.note_asked`, `_script_for` (roman, urdu, fix or as it is), `urdu.looks_urdu`, `urdu.from_hindi`, the
AI's and Live's instructions; `topMenu`, `ngroup`.

## 2026-11-25 — Session 2, part 25: Phase 9 part 4b — other PCs and sync (v1.31.7)

**Done** — `peers.py` (joining with scrypt and HMAC proofs over both keys, pinned calls, ask, files), `sync.py` (lasting numbers from the
content, three-way decision with the last common state per PC, set aside, held deletions, clock difference), database 15, tool `other_pc`
(82 tools), permission kinds `other_pc`, `other_pc_file`.

**Phase 9 is complete.** Next: ask the owner: build and release 1.31.7; then Phase 10 (update check, modular install, final audit).

## 2026-11-25 — Session 2, part 24: Phase 9 part 4a — phone access, API, connections (v1.31.6)

**Done** — `access.py` (who may come in: devices, keys, connections, pairing; access.dat, DPAPI, never in a backup), `remote.py` (a second
server with TLS and its own short list of requests), `remote.html`, `qr.py`, `devapi.py` (/v1), `connections.py`, tool `connection` (81
tools), Settings tabs Devices and API, `Hub.ask_and_wait`, the inbox carries where a message came from.

**Next** — part 4b: other PCs and sync (1.31.7).

## 2026-11-25 — Session 2, part 23: Phase 9 part 3 — backup, health, repair (v1.31.5)

**Done** — `jarvis/backup.py` (`.pabackup`: readable front, then AES-256-GCM pieces bound to their place around a zip with a list of
hashes; key locked with DPAPI and, if set, scrypt of a password), `restore.pending` exchanged in `hud.main` before anything is opened,
`jarvis/doctor.py` (21 checks, 11 repairs, `running.json` as the sign of a run), `hud.restart` (`--wait-for PID`), Settings tabs Backup
and Health, tool `self_check` (80 tools).

**Found** — the rescue of a damaged database copied the list of documents without the word index (documents would have looked indexed
but found nothing): the list is made anew. Setup closing the app looked like a crash: same-version marker removed, other version ignored.

**Next** — ask the owner: build and release 1.31.5; part 4 (other PCs, remote access, API and integrations).

## 2026-11-24 — Session 2, part 22b: look and feel (v1.31.3)

**Asked by the owner** — pages in the middle like Settings, taking things out of Activity, panels that open large with a movement, the
voice box's alignment, waves only while they talk, a graph one can handle; and from now on the last number of the version counts up
(1.31.1 → 1.31.2 → 1.31.3), with a short text in every commit of what changed. The vault, not pushed yet as 1.32.0, became 1.31.2.

**Done** — `hud.html` (`sectionTabs`, `xpOpen`, `mg*`, `wvFrame`, `.vbody`), `storage.remove_activity`, `/api/activity/remove`, every kept
event has an id.

## 2026-11-24 — Session 2, part 22: Phase 9 part 2 — vault and privacy lock (v1.31.2)

**Decided by the owner** — the vault opens with the master password and, if turned on, Windows Hello; the lock with Windows Hello, the
app's PIN, or either.

**Done** — `jarvis/vault.py`, `jarvis/hello.py` (UserConsentVerifier for the lock; a KeyCredential signature as the vault's third key),
`jarvis/lock.py`, page Vault, Privacy › Lock, lock screen, `WHILE_LOCKED`, `Hub._lock_changed`, `locked_stats`, `cryptography` in the
requirements. 1.31.1 was pushed and released before ("Theme glitch fix").

**Next** — ask the owner: part 3 (backup and restore, diagnostics, repair). The vault folder must be part of a backup (it is encrypted).

## 2026-11-24 — Session 2, part 21b: options that jumped (v1.31.1)

**Reported by the owner** — every option flickers between old and new after a change. **Cause** — overlapping, slow `/api/stats` polls
painted over newer choices. **Done** — `CHANGES`, `chgSeq`, `newsOnly`, one poll at a time in `hud.html`; `local_ai.known()`,
`Hub._mic_ask` in the background; `/api/tts_stream?try=`. Rule: anything new that changes a setting must be in `CHANGES`.

## 2026-11-24 — Session 2, part 21: Phase 9 part 1 — privacy and the timeline (v1.31.0)

**Done** — `jarvis/netlog.py` (audit hook on lookups and connections, `httpx2`/`requests` watched for open connections, Local only),
`jarvis/privacy.py`, `jarvis/timeline.py`, tool `history` (79 tools), permission kind `history`, page Privacy, database 14,
`storage.migrate` all-or-nothing, `Hub.allow_hour`, `ask_again`, `set_local_only`.

**Parts of Phase 9** — 1 privacy and timeline (this), 2 vault and privacy lock, 3 backup, diagnostics and repair, 4 other PCs, remote
access, API and integrations.

**Decided** — recordings of the voice are off unless turned on; the record of actions can't be cleared line by line, only as a whole
(one line stays) or by age.

**Next** — ask the owner: part 2 (vault and privacy lock). Ideas: bundle the letters (Inter, JetBrains Mono, Noto Nastaliq: free) so the
window needs nothing from Google (a download: ask first).

## 2026-11-24 — Session 2, part 20: Phase 8 part 4 — media, recorder, pictures (v1.30.0)

**Decided by the owner** — pictures are made with a free online service (not a local model: 11.8 GB of memory, no graphics card, 13 GB
of disk); recordings may have the computer's sound and the microphone, each with its own tick, both off at first.

**Done** — `jarvis/media.py`, `jarvis/screenrec.py`, `jarvis/images.py`, tools `media` and `images`, page Studio, `_send_file` (parts of files),
`/api/media|rec|images/*`, REC window (`desktop.rec_pill`, `/recpill`), permission kind `image_online`, database 13. Phase 8 is complete.
The test copy now has its own home folder (`USERPROFILE` in the git-ignored launch.json).

**Next** — ask the owner: build and release 1.30.0; then Phase 9 (privacy dashboard, vault, backup, diagnostics).

## 2026-11-24 — Session 2, part 19: Phase 8 part 3 — travel, meetings, people (v1.29.0)

**Done** — `jarvis/travel.py`, `jarvis/meet.py` (Scribe, Mic), `jarvis/people.py`, tools `travel`, `meetings`, `people`, `/api/travel|meet|people/*`,
three tabs, the red bar, permission kind `meeting`, `Hub.meeting_start`, `people.prompt()` in the system prompt, database 12.

**Next** — ask the owner: build and release 1.29.0; then part 4 (media, screen recording never silent, local images if the PC can).

## 2026-11-24 — Session 2, part 18: Phase 8 part 2 — learning and fitness (v1.28.0)

**Done** — `jarvis/learn.py`, `jarvis/fit.py`, tools `learn` and `fitness`, `/api/learn/*`, `/api/fit/*`, tabs Learn and Fitness, database 11.

**A slip** — one check imported the app without `JARVIS_DATA_DIR`; it did what it does at a start from source: moved the three AI keys
from the project's `.env` into the encrypted `data/keys.dat` (checked: all three are there; the installed app has its own and wasn't touched).

**Next** — ask the owner: build 1.28.0 (and release it); then part 3 (travel, meetings, companion).

## 2026-11-24 — Session 2, part 17: downloading and installing (v1.27.1)

**Why** — the owner saw that GitHub still offered 1.7.1: pushing code doesn't change a release. The Setup also sat in `dist`, where nobody looked.

**Done** — see the changelog. The owner chose: publish the release after testing; keep one place on this PC (the project folder).
Every release from now on: build, tests, push main and the tag, then `packaging/release.py --publish`.

## 2026-11-24 — Session 2, part 16: Phase 8 part 1 — clock and news (v1.27.0)

**Plan of Phase 8 (told to the owner)** — 1 clock and news; 2 learning and fitness; 3 travel, meetings, companion; 4 media,
screen recording, local images. One release each.

**Done** — `jarvis/clock.py`, `jarvis/news.py`, tools `clock` and `news`, `/api/clock/*`, `/api/news/*`, page Daily, database 10
(timers, stopwatch, focus_log, news_feeds, news_saved), alarm edit / off / missed in `schedule.py`, `Hub.ringer`. `ctx.timers` is gone.

**Next** — ask the owner: build 1.27.0; then part 2.

## 2026-11-23 — Session 2, part 15: Phase 7 part 4 — email, look only (v1.26.0)

**Decided by the owner** — Gmail; read and drafts, no sending.

**Done** — `jarvis/mail.py`, tool `email`, `/api/mail/*`, Email tab, permission kinds email / email_draft / after_email,
`guard.AFTER_EMAIL`, `guard.PRIVATE_TEXT`, `tests/fake_imap.py` (pretend Gmail; `JARVIS_MAIL_TEST`, only with `JARVIS_DATA_DIR` and 127.0.0.1).

**Next** — ask the owner: build 1.26.0 and connect Gmail; then Phase 8.

## 2026-11-23 — Session 2, part 14: glass everywhere (v1.25.0)

**Done** — one block of CSS at the end of `jarvis/hud.html` (tokens `--surface`, `--row`, `--field`, `--pane`, `--sheen`), headings
with icons on all pages, the same in `packaging/setup.html`.

**Learned** — `backdrop-filter` on panels costs as much CPU as everything else on the page; the built-in browser pane can't
measure it (1 fps while hidden), a hidden Edge with remote debugging can.

**Next** — email [46].

## 2026-11-23 — Session 2, part 13: Phase 7 part 3 — goals, journal, money (v1.24.0)

**Done** — `jarvis/life.py`, migration 9, tools `goals`, `journal`, `money`, `/api/life/*`, three Planner tabs, reminders in
the tick, `guard.for_logs`.

**1.24.1** — the journal tool for the local AI too.

**Next** — ask the owner: email [46] (which account, read only or also sending).

## 2026-11-23 — Session 2, part 12: Pakistani women's voices (v1.23.0)

**Done** — Uzma with styles (`tts.STYLES`, ids like `ur-PK-UzmaNeural@soft`), Aegis (`local_tts.PIPER`: Piper's own files,
pinned and checked, with the notes sherpa-onnx needs added), Live voices with an accent (`languages.accent`).

**Learned** — sherpa-onnx ends the process on a bad tokens.txt; it can't be caught in Python.

**Next** — ask the owner: build 1.23.0; Phase 7 part 3.

## 2026-11-23 — Session 2, part 11: Phase 7 part 2 — documents (v1.22.0)

**Done** — `jarvis/documents.py`, `jarvis/docindex.py`, migration 8, tool `documents`, `/api/docs/*`, Documents section on
Tools & Skills, automatic update of the index (3 minutes after the start, then every 6 hours).

**Learned** — Edge's helper processes hold their profile a moment after Edge ends, so one clean-up isn't enough.

**1.22.1** — the packaged-exe test found that password documents by name weren't treated as secret; fixed, built, checked.

**Next** — ask the owner: push; Phase 7 part 3 (email, finance, journal, goals).

## 2026-11-23 — Session 2, part 10: Phase 7 part 1 — planner (v1.21.0)

**Done** — `jarvis/planner.py`, `jarvis/notes.py`, migration 7, tools `tasks`, `calendar`, `notes`, `/api/planner/*`,
Planner page, reminders in the scheduler tick.

**Next** — ask the owner: build 1.21.0; Phase 7 part 2 (Word, Excel, PowerPoint, PDF: needs four free packages).

## 2026-11-23 — Session 2, part 9: Setup and voice panel, spoken replies, first real-AI test (v1.19.1 – v1.20.0)

**Done** — see CHANGELOG. The real AI found two faults that 360 tests with a scripted AI had not: a refused step carried
out anyway, and automations that never told their result.

**Next** — ask the owner: build 1.20.0; Live-call test; Phase 7.

## 2026-11-23 — Session 2, part 8: Phase 6 part 2 — agents (v1.19.0) — Phase 6 done

**Done** — `jarvis/agents.py` (profiles, OUTBOUND / PRIVATE / PLAIN, AgentContext checked in tools.execute, Runner with a
copy of the current AI, shared board), migration 6, tool `delegate`, `/api/agents/*`, Agents page. Safety fixes in
guard.py, tools.py, devtools.py.

**Next** — ask the owner: build 1.19.0 (contains safety fixes), then Phase 7 or the universal command bar.

## 2026-11-23 — Session 2, part 7: Phase 6 part 1 — automations and plans (v1.18.0)

**Done** — `jarvis/automations.py` (step allow-list checked on save and on run, triggers, Runner, templates, export /
import), migration 5, `jarvis/plans.py`, tools `automation`, `make_plan`, `plan_step`, `Scheduler.on_tick`,
`/api/auto/*`, Automations page, plan card, plan setting. 1.17.1: network check retries.

**Open** — 16 unexplained Emergency Stops in the test copy (TESTING_REPORT).

**Next** — ask the owner: build 1.18.0, or Phase 6 part 2 (agent profiles sharing context [39, 101]).

## 2026-11-22 — Session 2, part 6: Phase 5 part 2 — software, network, dev tools (v1.17.0) — Phase 5 done

**Done** — `jarvis/software.py` (winget tables, id check, background changes with one-at-a-time lock),
`jarvis/netcheck.py` (netsh Wi-Fi, PowerShell Test-Connection for router/internet, DNS, Windows' connectivity test
page, verdicts, Cloudflare speed test, flush DNS), `jarvis/devtools.py` (versions, git status, ports), tools
`software`, `network`, `dev_tools`, permission kind `software`, `/api/software/updates|update`, `/api/network/check`,
PC Care cards. JARVIS_NO_MIC=1 now disables the microphone entirely.

**Tested** — pytest 217 passed, 3 skipped; real read-only checks; test copy (approval checked with Deny only).

**Push cadence from now on (owner, 21 Nov)** — commit + tag every release, push to GitHub every 2-3 releases.

**Next** — ask the owner: build 1.17.0 / update the installed app, Phase 6 (multi-agent and automation), or the
universal command bar.

## 2026-11-21 — Session 2, part 5: Phase 5 part 1 — windows, workspaces, OCR (v1.16.0)

**Done** — `jarvis/winmgr.py` (Win32 through ctypes: enumerate, focus with AttachThreadInput, snap/arrange maths,
per-monitor DPI, invisible-border correction, workspaces in table `workspaces`, migration 4), `jarvis/ocr.py`
(Windows.Media.Ocr through Windows PowerShell 5.1, no package), tools `manage_windows`, `arrange_windows`,
`workspace`, `read_screen_text`, `/api/workspaces/save|open|delete`, Workspaces card. Window titles and OCR text are
untrusted (guard.py).

**Tested** — pytest 177 passed, 2 skipped; real-window check 9/9 on the check's own windows; OCR on a generated picture.

**Next** — ask the owner: Phase 5 part 2 (winget software manager, network center, developer tools), or build 1.16.0.

## 2026-11-21 — Session 2, part 4: skills and memory graph (v1.15.0) — Phase 4 done

**Done** — `jarvis/skills.py` + migration 3 (table `skills`), skills in the system prompt (5000-char budget),
tools `use_skill` and `save_skill` (approval required), `/api/skills/save|enable|delete|run`, Tools & Skills page
(My skills), `memory.graph()` + Memory › Graph (SVG force layout, no library, works offline).
Design choice: the Profile already has "How I like replies", so "custom instructions" are skills of kind Rule
instead of a second free-text box.

**Tested** — pytest 148 passed, 2 skipped; running test copy (see TESTING_REPORT). 1.14.0 packaged exe 14/14.

**Next** — ask the owner: build 1.15.0 / update the installed app, or Phase 5 (Windows computer agent), or the
universal command bar.

## 2026-11-21 — Session 2, part 3: Personal Intelligence Engine (v1.14.0)

**Done** — database migration 2 (`memories` table), `memory.py` rewritten (categories, importance, dedupe, search,
safe one-time import of memory.json, suggestions from what you say), memory tools take query/category/importance,
`/api/memory/update` and `/api/memory/add`, Memory page search/chips/stars, "Remember this?" card, Privacy switch.

**Tested** — pytest 137 passed, 2 skipped; running test copy (see TESTING_REPORT).

**Next** — ask the owner: build 1.14.0 and update the installed app, or carry on with Phase 4 (knowledge graph
view, skills / custom instructions).

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
