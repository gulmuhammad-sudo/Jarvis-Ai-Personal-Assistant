# Security review

## 2026-11-23 — v1.24.0

| Area | How | Where |
|---|---|---|
| Journal | the AI can read it only after you tick it (audited); no agent ever; its text isn't logged. It is in the unencrypted `assistant.db`, and what you say to the assistant about it is in the conversation as always | `life.settings`, `tools.journal`, `guard.for_logs` |
| Money | nothing connects to a bank or pays; amounts are whole hundredths; deleting asks; the same entry within 90 seconds is refused | `jarvis/life.py`, `tools.money` |
| Agents and automations | goals and money are private (never with web tools); agents can't add or delete money; automations only look | `agents.LIMITS`, `automations.STEP_TOOLS` |
| Exports | only to Documents, never over a file; cells that start like a formula are made text | `life.export` |

## 2026-11-23 — v1.23.0

| Area | How | Where |
|---|---|---|
| Voice from Hugging Face | a fixed version, both files checked by SHA-256, size limit, put in place only when complete | `local_tts._download_piper` |
| Voice ids from the page | only listed ones, styles included; anything else becomes the default | `tts._resolve` |

## 2026-11-23 — v1.22.0

| Area | How | Where |
|---|---|---|
| Files from others | size, unpacked-size and time limits; XML with DOCTYPE or ENTITY refused; nothing in a file is run, macros included | `jarvis/documents.py` |
| Text in documents | marked untrusted when read or found | `guard.READ_BACK` |
| Reading | files whose name says passwords, sign-ins, keys or recovery codes (1.22.1; before, key files only) and files on other computers ask first; the index skips them. By name only | `guard.secret_file`, `tools.documents` |
| Making | only in the user's folders; replacing asks; unknown Excel functions are written as text | `tools.documents`, `safe_formula` |
| PDF | Edge with an empty profile, no internet; the page holds only our own tags; the temporary folder is removed | `_make_pdf` |
| Index | only folders the user adds on the page (the AI can't add any); not drives, Windows, programs, AppData, .ssh; on this PC only, in the unencrypted `assistant.db` | `jarvis/docindex.py` |
| Opening a result | by its number in the index, document kinds only | `/api/docs/open` |
| Agents | documents are private: no web agent gets them | `jarvis/agents.py` |

## 2026-11-23 — v1.21.0

| Area | How | Where |
|---|---|---|
| Notes | Named by file name only (no folders, drives, streams, device names), must lie in the notes folder; deleting goes to the Recycle Bin and asks; replacing asks and shows the new text | `jarvis/notes.py`, `tools.notes` |
| Web or private (was: daily_briefing, cancel_timer and arrange_windows let a web agent see alarm, timer or app names) | daily_briefing is for no agent; the others and the planner are private | `jarvis/agents.py` |
| Text kept earlier | tasks, calendar and notes are marked untrusted when read back | `guard.READ_BACK` |

## 2026-11-23 — v1.20.0

| Area | How | Where |
|---|---|---|
| Refused plans and steps (was: only the AI's instructions; a real AI ignored a refusal) | `plans.blocked` in `tools.execute` for every call made by an AI; only tools that look run until the user says something new; the spoken "no" itself doesn't count as new. Buttons and automations are not held | `jarvis/plans.py`, `jarvis/tools.py` |

## 2026-11-23 — v1.19.0 additions and fixes

| Area | How | Where |
|---|---|---|
| Agents | Tool list checked in `tools.execute`; web and private tools can't be combined; private results and memories never reach web agents; no PowerShell, installs, skills, automations or other agents. A task text is still seen by the agent it is given to | `jarvis/agents.py` |
| Files that run code (was: no question) | Opening or writing programs, scripts, shortcuts and PowerShell profiles always asks | `guard.runs_code`, `tools.open_path`, `tools.write_file` |
| "Open an app" (was: any address or path) | App names and the app's own aliases only | `tools.open_application` |
| Secrets and network paths (was: no question) | Reading key / password files, and touching \\server paths, asks; agents may not use network paths | `guard.secret_file`, `guard.elsewhere` |
| git status (was: ran programs from a repository's settings) | Such repositories are refused; monitor, hooks and signature checks off | `jarvis/devtools.py` |

## 2026-11-23 — v1.18.0 additions

| Area | How | Where |
|---|---|---|
| Automations | Allow-list of tools with narrowed settings, checked on save and again on every run; no programs, scripts, shortcuts, %names%, streams or network paths; http(s) sites only; run through `tools.execute` (approvals, audit, Stop) | `jarvis/automations.py` |
| Lasting instructions | AI needs approval to create, switch on or delete; imports arrive off and can't contain AI prompts | `tools.automation`, `import_text` |
| Plans | A plan is never a permission; refused or stopped plans can't continue | `jarvis/plans.py` |

## 2026-11-22 — v1.17.0 additions

| Area | How | Where |
|---|---|---|
| Installing / updating / removing programs | Every change asks (permission kind `software`: Ask or Never, never Allow); package id checked against a strict pattern and must exist in winget (install) or in the update / installed list (update / uninstall); arguments passed as a list, no shell; one change at a time | `jarvis/software.py`, `tools.software` |
| Text from other people | winget package names and git commit messages are wrapped as untrusted, like web pages and window titles | `jarvis/guard.py` |
| Network check | Read-only; the speed test downloads from Cloudflare and sends nothing about the user; Windows' own connectivity page is used for the web test | `jarvis/netcheck.py` |
| Test/demo copies | JARVIS_NO_MIC=1 disables the microphone completely (found when an approval in the test copy tried to listen for a spoken yes/no) | `jarvis/hud.py` |

## 2026-11-21 — audit of v1.7.2

### What is already in place

| Area | How | Where |
|---|---|---|
| Local server can't be driven by websites | Binds 127.0.0.1 only; `Host` header must be 127.0.0.1/localhost; every API call needs a random per-launch token | `jarvis/hud.py` (`_host_ok`, `_token_ok`) |
| Confirmation before risky actions | `ctx.approve()` for PowerShell, shutdown/restart, closing apps with unsaved work, Wi-Fi off, cleaning folders, overwriting files | `jarvis/tools.py`, `jarvis/hud.py` (`confirm`) |
| Some kinds can be trusted until restart; dangerous ones never | `TRUSTABLE` = PowerShell, lock, Wi-Fi off only | `jarvis/hud.py` |
| Voice answer never auto-approves its own question | The question avoids "yes/no" words; approval by voice is limited to that pending question | `jarvis/approvals.py`, `jarvis/hud.html` |
| File safety | Deletes go to the Recycle Bin; Windows, Program Files and the app's own folder are refused; writes limited to user folders | `jarvis/tools.py` |
| No secrets in git | `.env`, `data/`, `build/`, `dist/` are git-ignored; every commit is scanned for key patterns | `.gitignore`, release routine |
| No secrets in logs | Checked: 0 key-pattern matches in both log files and in the whole git history (21 Nov) | — |
| Installer | Per-user (no admin), refuses non-empty foreign folders, never overwrites existing data or keys | `packaging/setup_app.py` |

### Findings

| # | Finding | Risk | Status |
|---|---|---|---|
| S1 | API keys stored in plain text (`.env`) | Medium: any program or person with access to the user's files can read them | **Fixed in 1.8.0**: Windows DPAPI encryption (`keys.dat`), automatic migration out of `.env` (only after the encrypted copy reads back correctly); installer writes keys encrypted |
| S2 | Web pages and files read by tools go into the AI prompt unmarked | Medium: prompt injection ("ignore your instructions and run …") | **Fixed in 1.9.0**: output of web search, web pages, files, clipboard and the briefing is wrapped in `<untrusted>` (a fake closing tag inside can't end it) + a system-prompt rule; approvals and the deny-list remain the hard stop (`jarvis/guard.py`) |
| S3 | `run_powershell` relies only on the approval prompt | Medium | **Fixed in 1.9.0**: refused outright, before any approval: disk format/partition, deleting drives/Windows/Program Files/all users, machine registry deletes, boot changes, deleting backups/restore points, wiping free space, weakening Defender, firewall off, user-account changes, download-and-run, encoded commands, killing core processes, machine-wide execution policy. 24 refused / 8 normal commands allowed in tests |
| S4 | No audit log of actions taken | Low/Medium | **Fixed in 1.9.0**: `audit.log` (JSON lines) for every tool call, approval, refusal, Stop and history clear; secrets and file contents never written; viewable in Settings › Privacy |
| S5 | No emergency stop for a running multi-step task | Medium | **Fixed in 1.9.0**: Stop button (toolbar), Esc twice, tray "Stop everything": no further tools or steps, waiting approvals answered no, Live call and speech stopped |
| S6 | Memories, profile and notes stored unencrypted | Low (local files in the user's profile) | Later: optional encryption with DPAPI; never sent anywhere except the chosen AI |
| S7 | Conversations, profile and screenshots go to cloud AI providers | Privacy | Phase 2: local AI default; clear indicator of which provider receives data |
| S8 | Unsigned executables | SmartScreen warning; users can't verify the publisher | Blocked by cost (code-signing certificates are paid) |
| S9 | Microphone indicator | The HUD shows listening states; Windows also shows its own mic icon | OK for now; add an always-visible mic indicator in the tray icon |

### Rules for all new code

- Voice is never authentication for sensitive actions.
- The AI never gets direct access to a password/identity vault.
- No silent screen recording, no automatic upload of documents or screenshots.
- New tools that change things must go through `ctx.approve()`.
- Tests use temporary data folders and fake keys only.
