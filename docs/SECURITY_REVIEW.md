# Security review

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
| S2 | Web pages and files read by tools go into the AI prompt unmarked | Medium: prompt injection ("ignore your instructions and run …") | Next: wrap fetched/untrusted text in a clearly marked block + rule in the system prompt; approvals remain the hard stop |
| S3 | `run_powershell` relies only on the approval prompt | Medium | Next: deny-list of destructive patterns (format, diskpart, `Remove-Item -Recurse` on system paths, registry deletes, disabling Defender) that are refused outright |
| S4 | No audit log of actions taken | Low/Medium | Next: append-only `audit.log` (tool, arguments summary, approved by, result) |
| S5 | No emergency stop for a running multi-step task | Medium | Next: one Stop control that cancels the brain's tool loop and the Live call |
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
