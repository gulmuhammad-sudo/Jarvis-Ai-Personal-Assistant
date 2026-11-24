# Security review

## 2026-11-24 — v1.31.2 (vault, privacy lock)

| Area | How | Where |
|---|---|---|
| Encryption | a random 256-bit key, AES-256-GCM with a fresh nonce each time; the key itself sealed with keys from the master password and the recovery code (160 bits), both through scrypt (2^17, 8, 1: 128 MB); every sealed part bound to this vault, its numbers and its use; files with a key each, in pieces bound to their place and count | `vault._seal`, `_stretch`, `_about`, `file_add` |
| Windows Hello | a key in the PC's security chip signs one fixed random question, only after the gesture; the vault's key is sealed with that signature, which is kept nowhere. Using the recovery code turns it off | `hello.sign`, `vault.hello_on` |
| Guessing | 10 letters or more and not too easy; after five wrong tries 30 s, doubling to an hour, kept over a restart; scrypt makes each try half a second | `vault._wrong`, `_may_try` |
| Who may ask | every request needs the page's token and a secret given out at unlocking; a new unlocking ends the old one; lists and entries have no secrets, each is shown (20 s) or copied on its own | `vault.need`, `reveal` |
| The AI | no tool, agent, automation or plan; no screen looks while it is open; clipboard refused while it holds something from here; nothing of it in events, history, record, database or log (the record says that something was shown, not what) | `tools._execute`, `hud._vault` |
| The clipboard | out of Windows' history and cloud, cleared after 30 s only if it is still ours | `vault._put`, `clear_clipboard` |
| Locking | by time, with Windows' lock, with sleep, with the privacy lock, when the app closes | `lock.look`, `vault.check_idle` |
| Damage | written whole, the version before kept; a full disk changes nothing | `vault._write`, `save` |
| Known outside | the days documents run out (for the reminder; can be off), that a vault exists, its size | `vault._due_days` |
| What it can't do | protect from a program that already runs as you while the vault is open | — |
| The privacy lock | the server refuses all but ten requests; a locked window gets no events, no names, no history; PIN as scrypt hash inside DPAPI, waiting after wrong tries; never by voice; can't be turned on without a way to open it | `hud.WHILE_LOCKED`, `lock` |
| What the lock isn't | encryption: the app's files can be read by whoever uses this Windows account (the vault can't) | stated on the page |
| Test copies | Windows Hello is never asked; the pretend answer works only with a data folder of their own | `hello._pretend` |

## 2026-11-24 — v1.31.0 (privacy, Local only, timeline)

| Area | How | Where |
|---|---|---|
| Local only | refuses at Python's own audit events for lookups and connections, so no part of the app can forget it; messages over a connection that is open already are refused in `httpx2`, `httpx` and `requests`; only this PC itself (loopback, its own name) is let through, the home network isn't; tools that work through another program (browser, winget, ping, Ollama downloads) are refused; a Live call and the mail connection are ended | `netlog._hook`, `_note`, `tools._execute`, `hud.set_local_only` |
| Not held back | your browser, Windows, other programs, a PowerShell command you approve (the question says so), WebView2's own traffic with Microsoft | stated on the page |
| The window | in Local only: no Google Fonts, and a Content-Security-Policy for this PC only (also from the moment it is turned on) | `hud.LOCAL_CSP`, `pvLocalSet` |
| The list of what goes out | day, address, numbers; no paths, no words; 30 days; off and clear; no AI tool reads it | `netlog` |
| Who can turn things | the page's own requests with its token; no tool, agent or automation can change Local only, permissions, what is kept or who may read what | `hud._privacy` |
| An hour's permission | only the kinds that may be allowed at all; ends with Stop, with any other rule, and with a restart | `hud.allow_hour` |
| The record of actions | can't be changed line by line; clearing leaves a line; clearing by age only with a time the owner chose | `audit.clear`, `drop_before` |
| Earlier conversations for the AI | asks each time (or the owner's rule), only what was said and answered, marked untrusted, then the same hold as after an email; its words and finds aren't kept; no agent or automation has it | `tools.history_tool`, `guard` |
| Voice recordings | off unless turned on (before: the last five always) | `recorder._save_debug` |
| Test copies | Windows' recogniser obeys JARVIS_NO_MIC too | `hud.listen_once` |
| Database upgrades | one transaction each, locked; a fault leaves the old state | `storage.migrate` |

## 2026-11-24 — v1.30.0 (media, screen recording, pictures)

| Area | How | Where |
|---|---|---|
| Starting a recording | the browser's own getDisplayMedia: it can't start without a click and Windows' box, each time; `/api/rec/start` needs the page's token and `agree: true`; no tool, agent, automation or plan | `hud.html rcStart`, `hud._rec` |
| Never silent | red bar on every page, REC window above all others (also when the app is hidden), a sound and an activity entry at the start, start and end in the audit log, Emergency Stop | `desktop.rec_pill`, `screenrec.Recording` |
| The file | pieces only in order and only with the recording's own secret number; 4 hours, 8 GB, always 1 GB left; ends by itself when the page is gone; new names only; deleting means the Recycle Bin | `screenrec` |
| Files for the player | only what is in the library, resolved and still inside its folder, media types only; recordings and pictures only by plain name from their own folder; token; `nosniff`; parts checked | `media.path_of`, `screenrec.path_of`, `images.path_of`, `hud._send_file` |
| Now playing | one fixed helper script; only seven fixed words ever reach it; what apps say is untrusted for the AI | `media.NowPlaying`, `guard.READ_BACK` |
| Radio | the search words go to radio-browser.info (after an email it asks first); a station must be a public address (odd ports allowed, home network and this PC not) | `media._station_url` |
| Pictures | read by Pillow with limits and only as known kinds, written again without metadata, new files only; the AI only in your own folders, the original stays | `images._open`, `keep`, `picture_path` |
| Making online | your button says where the words go; the AI asks each time (or your rule in Permissions), after an email always; the service's filter is on; nothing about you is sent but the words | `images.generate`, `tools.images_tool` |
| JSON posts | a body that isn't an object is refused (before: an error) | `hud.do_POST` |

## 2026-11-24 — v1.29.0 (travel, meetings, people)

| Area | How | Where |
|---|---|---|
| Starting to write down | only `/api/meet/start` with the page's token and `agree: true`; no tool, agent, automation or plan can; the microphone must be free; refused while a Live call runs; a Live call is refused meanwhile | `hud.meeting_start`, `live_start` |
| Never silent | a red bar on every page (also after a reload), a sound at the start, an entry in the activity list, start and end in the audit log; Pause really drops the sound; Emergency Stop and four hours end it | `hud.html`, `meet.Scribe` |
| Sound | only in memory, piece by piece; only to the engine chosen (a failure never goes to the other one); pieces without speech aren't sent | `meet._write_down`, `Scribe` |
| What was said | other people's words: untrusted for the AI, a question for each meeting (one yes for its parts, until a new conversation or half an hour), then the same hold as after an email; not in the activity list or audit log | `tools.meetings_tool`, `meet.allow`, `guard` |
| People | the AI never gets phone numbers; names in its instructions only with a tick; no agent or automation has people or meetings | `people.prompt`, `agents` |
| Travel | the weather sends the place's name, only when asked (after an email it asks first); nothing can be booked; a hint not to keep passport numbers | `travel.weather`, `guard.AFTER_EMAIL` |

## 2026-11-24 — v1.28.0 (learning and fitness)

| Area | How | Where |
|---|---|---|
| Health notes | the AI may write; reading needs the owner's tick (only a real `true`); arguments and answers stay out of the activity list and audit log; not in agents or automations | `tools.fitness`, `guard.PRIVATE_TEXT`, `agents` |
| Cards | may hold text from documents or the web: wrapped as untrusted when read back; an agent may add and search, not answer; private, so never with the web in one agent | `guard.READ_BACK`, `agents.LIMITS` |
| Import | 2 MB at most, markup removed, every card checked before any is kept | `learn.read_cards`, `add_cards` |
| Export | never over a file, no cell a spreadsheet would run | `learn.export`, `fit.export` |
| Numbers | finite, in range, and a day's water or steps can't go past what is possible | `fit.amount`, `fit.add` |

## 2026-11-24 — v1.27.0 (clock and news)

| Area | How | Where |
|---|---|---|
| Feed addresses | http(s) on ports 80 / 443 only, no sign-in in the address; every address the name resolves to must be public, also after a redirect. Left: a name that changes between the check and the download (the answer must still parse as a feed, and nothing of it is sent anywhere) | `news._public`, `_Redirect` |
| What feeds say | 3 MB at most; entity declarations refused; markup, control and direction characters removed; links only http(s); for the AI always untrusted | `news.parse`, `guard.UNTRUSTED_TOOLS` |
| Asking the AI about a story | the message has the story's number, never its text (a title can't speak as you) | `hud.html` |
| After an email | news search and topics ask first, like the web; the top list, saved and story don't (they carry nothing out) | `guard.AFTER_EMAIL` |
| Agents | news counts as going out, clock (reading only) as private: never in one agent | `agents.OUTBOUND`, `LIMITS` |
| Opening a story | only one that is in the list, in your own browser | `hud._news` |
| Demo copies | JARVIS_NO_MIC refuses Live calls in the code, JARVIS_NO_SPEAK also alarms and spoken reminders | `hud.live_start`, `hud.alert` |

## 2026-11-23 — v1.26.0 (email)

| Area | How | Where |
|---|---|---|
| Sign-in | an app password only (16 letters; anything else is refused before it goes anywhere), DPAPI in `mail.dat`, never in the environment, logs or the page; TLS with certificate check to imap.gmail.com only | `mail.connect`, `_login` |
| Look only | mailboxes opened with EXAMINE, BODY.PEEK; the connection refuses every command but looking, and APPEND to Drafts while a draft is saved; no SMTP in the app (tested) | `mail._Guarded` |
| What emails say | untrusted; plain text only, nothing loads; hidden and invisible text removed; size limits; warnings | `mail.read`, `warnings` |
| Commands through a search | sent as a counted literal, one line | `mail.listing` |
| The AI | asks before it sees email; drafts always shown and asked; no agent or automation has email | `tools.email` |
| Carrying things out | after an email, web, opening, agents, automations, PowerShell, software and new skills ask, showing what would go out, for 30 minutes or until a new conversation. Not covered: weather and prayer city names, and things kept on this PC | `guard.AFTER_EMAIL` |
| Logs | addresses, subjects, searches, text and results left out (1.26.1; before, a draft's address could be there); approvals keep only their first line. What the assistant answers about an email is in the conversation, as always | `guard.PRIVATE_TEXT`, `PRIVATE_KINDS` |
| Test switch | `JARVIS_MAIL_TEST` works only with `JARVIS_DATA_DIR` set and only for 127.0.0.1 | `mail._test_server` |

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
