# Changelog

Each version is also a git tag (`git tag -n20 vX.Y.Z` shows its notes). Newest first.

## 1.23.0 — 2026-11-23
Pakistani women's voices:
- Reading voice: Uzma (Microsoft's Pakistani voice) can be chosen now, in four ways of speaking: normal, soft, lively,
  deeper. She reads Urdu, Roman Urdu and English. Asad can be chosen too. Before, they only read text in Urdu letters.
- On this PC, offline: Aegis, a Pakistani Urdu woman's voice (64 MB, one click in Settings › Voice & Mic, MIT licence).
  With a woman's reading voice, the offline voice is a woman's too.
- Live calls: Aoede, Leda, Zephyr, Kore, Sulafat and Achernar "(Pakistani)": Google's women's voices told to speak the
  Pakistani way. Google has no voice from Pakistan.
- With a woman's voice the assistant speaks of itself in the feminine in Urdu (kar rahi hun).

## 1.22.1 — 2026-11-23
- Documents whose name says they hold passwords, sign-ins, keys or recovery codes ("My Passwords.xlsx", Windows' BitLocker
  recovery key file) now ask before they are read and stay out of the document search. Before, only key files like `.env`
  and `id_rsa` did. It goes by the name: a password inside "notes.docx" isn't recognised.

## 1.22.0 — 2026-11-23
- Documents: reads PDF, Word, Excel, PowerPoint and text files ("summarise Desktop/report.pdf", "what's on sheet Budget?")
  and makes Word, Excel, PowerPoint and PDF files ("make a PowerPoint about… on my Desktop"). Replacing a file asks first.
- PDFs are made with Windows' own Edge, hidden, with an empty profile and no internet; its temporary folder is removed.
- Tools & Skills › Documents: choose folders, search inside every document in them, click a result to open it. The index
  stays on this PC; password and key files are skipped. What you ask about goes to the AI with your message.
- The Writer agent can use documents; web agents can't.
- Four free packages came in: pypdf, python-docx, openpyxl, python-pptx.

## 1.21.0 — 2026-11-23
- Planner page. Calendar: month and week with events, tasks, alarms and prayers; repeating events, reminders, a warning
  when two overlap. Tasks: due day or time, importance, projects. Notes: search, read, change, rename, delete (Recycle Bin).
  All on this PC.
- By voice or chat: "send the report tomorrow at 5, project Work", "what's planned on Friday?", "read my shopping note".
  Deleting, and replacing a note's text, asks first.
- The daily briefing, the Timeline and automations ("What's planned", "Open tasks") know about it.
- Agents: plans, tasks and notes are on the private side. Corrected: a web agent could have been given the daily briefing
  (alarm and timer names), timers or the names of open apps since 1.19; none of the ready-made ones was.
- The clock is no longer partly covered by the search box on pages other than the Command Center.

## 1.20.0 — 2026-11-23
Found by the first test with real AIs (Gemini, Groq):
- Your "no" to a plan or a step now holds in code: tools that change something don't run until you say something new, a
  refused step can't be marked done, and with "Ask before every step" nothing changes outside an approved step.
- Automations tell you what they found (weather, prayer times, internet…) when they end, or that a timed one stopped
  early. Before, the result was only on the Automations page.
- Notes like these obey Spoken replies; alarms and reminders still speak.
- A request too large for a service's free limit (413) is tried again with fewer tools instead of dropping the task.

## 1.19.2 — 2026-11-23
- Spoken replies stay off (or on) after a restart, and with them off the greeting at start-up is silent too. Turning
  Hands-free on still turns them on. Alarms and Live calls speak as before.

## 1.19.1 — 2026-11-23
- The Voice panel on the left: with two more menu items since 1.18 it was squeezed, so its text lay over the mic and its
  heading broke in two. The menu is more compact on lower windows and the panel rearranges itself to the room it has.
- Setup: the Look page was taller than the window, so Back / Next were cut off and it couldn't scroll. It now fits,
  longer pages scroll inside, the buttons always stay visible, the window is never bigger than the screen and can be
  resized. The line about a Photo face (removed in 1.13) is gone.

## 1.19.0 — 2026-11-23
- Agents page: specialists with their own tools — Researcher, Organiser, PC Helper, Writer, and your own. Give one a
  task there, or ask the assistant ("ask the Researcher to…"). Results go on a shared board the agents read.
- An agent gets the web or your private things, never both; its tool list is enforced in code, not just in its
  instructions. One agent works at a time; risky actions still ask; Stop stops it.
- Safety fixes, also for the assistant itself: opening or writing a file that can run (program, script, shortcut)
  always asks; "open an app" takes app names only, not links or paths; reading files that usually hold passwords or
  keys asks; paths on other computers ask; git status no longer starts programs set in a repository's own settings
  (it refuses such repositories).

## 1.18.0 — 2026-11-23
- Automations page: several steps under one name, run by hand, at a time on chosen days, or when the app opens.
  Steps come from a safe list (no PowerShell, power actions, deleting, uninstalling, Wi-Fi off, nothing that runs a
  script or program file). Steps that need permission still ask; Stop stops them; one runs at a time.
- Templates (Morning start, Focus time, Evening wind-down, PC check-up), Export and Import as text. Imports are
  checked, can't contain a prompt for the AI and arrive switched off.
- By voice or chat: "run my Focus time automation"; creating, switching on or deleting one always asks you.
- Plans for longer tasks: the assistant shows its steps and ticks them off. Settings › Permissions › Plans: show and
  ask first (default), ask before every step, or only show.
- After Emergency Stop no automation starts by itself until you give a new instruction.

## 1.17.1 — 2026-11-23
- Network check: one lost web request no longer leads to "a firewall, proxy or VPN may be blocking them". It
  tries twice, then a second site, and only then says web pages don't load (and suggests running it again).

## 1.17.0 — 2026-11-22
- Software manager (winget, built into Windows): "find VLC", "what's installed", "which apps have updates",
  "install / update / uninstall …", "update everything". Changes always ask first (Settings › Permissions ›
  Software: Ask or Never), run in the background and tell you when they finish. Tools & Skills › PC Care ›
  Software updates lists waiting updates with Update / Update all buttons.
- Network center: "why is the internet not working?" checks Wi-Fi signal, the router, the internet, DNS and a
  real web page, and answers in plain words (also spots "sign in to this Wi-Fi" pages); "speed test"; "flush DNS".
  Also on Tools & Skills › PC Care › Network.
- Developer helpers (read-only): installed dev tools and versions, a project's git status, "what's using port 3000?".
- Safety: package names and git commit messages are marked untrusted; a demo/test copy with JARVIS_NO_MIC=1 never
  opens the microphone, not even for a spoken yes/no.

## 1.16.1 — 2026-11-21
- Hide details now really shows just the face: the side menu, Voice status, top bar and footer go away and the
  globe / rings / mask fills the window. A light dock at the bottom keeps Hands-free, the Mic, Spoken replies,
  Stop and Show details; it stays faint until you point at it and the mic glows green while listening.
  Approval boxes, alerts and the short captions still appear. Ctrl+K shows the details and the typing box.

## 1.16.0 — 2026-11-21
- Windows on command: "show my open windows", "bring Chrome to the front", "put VS Code on the right",
  "maximise Word", "minimise everything", "put Chrome and VS Code side by side" (2-6 windows: halves, one big +
  two stacked, quarters, grid). Works on every monitor and on scaled (125%/150%) displays.
- Workspaces: "save this as my Study workspace" remembers which apps are open and where; "open Study workspace"
  reopens the closed ones and puts every window back. Also on the Tools & Skills page (Save / Open / Delete).
- Read text on the screen, in one window or in a picture with Windows' own OCR — offline, nothing uploaded.
- Window titles and text read off the screen are marked as untrusted, like web pages.

## 1.15.0 — 2026-11-21
- Skills (Tools & Skills page): write your own instructions once.
  - **Rules** are followed in every reply ("Keep answers short", "Use metric units").
  - **Routines** run when you ask by name ("run my morning briefing") or press **Run**.
  - Each has On/Off, Edit and Delete; three examples to start from.
  - The assistant can save a skill for you, but only after you press Authorize, so a web page can't plant
    lasting instructions.
- Memory › **Graph**: a map of what the assistant knows — you in the middle, your categories around you, each
  memory (bigger = more stars), and the people/places that appear in several memories linking them. Hover to
  read, click to open it in the list.
- Saving, changing and deleting skills is written to the audit log.

## 1.14.0 — 2026-11-21
- Personal Intelligence Engine: memories now live in the app database with a category (personal, family,
  people, work, study, health, likes, routine, other) and an importance (1-3 stars). Your old memories are
  moved over automatically; the old file is kept as `memory.json.imported`.
- Memory page: search box, category chips with counts, change a memory's category or stars in place.
- "Remember this?": when you tell the assistant something lasting about yourself (name, job, likes, family,
  allergies — English or Roman Urdu), a card offers to save it. Nothing is saved unless you press Save.
  Turn it off in Settings › Privacy › Suggest memories.
- The AI gets the most important 60 memories in every chat and can search the rest (`recall_memories` with
  words or a category).

## 1.13.1 — 2026-11-21
- Settings are centred in one column (tabs and rows), instead of hugging the left side.

## 1.13.0 — 2026-11-21
- New look for icons everywhere: menu icons sit in small tiles (the open page glows), every icon has its own
  hover animation (gear turns, mic pulses, bell rings, refresh spins…), buttons give a press effect.
- Settings: icons on tabs and sections, every row has its label on the left and controls on the right, On/Off
  settings are real switches, rows slide in when you open a tab. Windows' "reduce animations" is respected.
- Removed the Photo face (Globe, Mask and Rings remain; a saved Photo choice shows the Globe).
- Fixed: speech-to-text on this PC failed inside the installed app (no console to write logs to) — found by
  testing the packaged exe.

## 1.12.0 — 2026-11-21
- Settings in tabs: General · Voice & Mic · AI · Privacy · Permissions · Alerts. Permissions (Ask / Allow /
  Never per action, and "Allowed until restart") are now in one place, separate from Privacy.
- App icon (favicon) in the window/browser tab.
- Tidy project folder: builds happen in %TEMP%\PersonalAssistant-build; the project only gets
  dist\Personal Assistant Setup.exe.
- Short README; the full guide moved to docs/USER_GUIDE.md.

## 1.11.0 — 2026-11-21
- Voices that speak on this PC (Settings › Voices › Voice source: Auto / Online / This PC): Alan and Jenny
  (British), Fasih (Urdu), Rohan and Priyamvada (Hindi), ~20 MB each, downloaded when you press Download.
  Offline and private; Auto uses them when there's no internet or the online voices fail.
- Speaking speed and pitch sliders (pitch applies to the online voices).
- Tests: 116 + a real voice and a real transcription (local voice -> local speech-to-text round trip).

## 1.10.0 — 2026-11-21 (not pushed: GitHub login removed by the owner)
- Speech to text on this PC (Settings › Microphone): Auto (online when there's internet, this PC when not),
  Online, or This PC. Download a speech model once: Base (60 MB, fast) or Small (190 MB, better for Urdu).
  Works offline; nothing you say leaves the computer. If the online service fails, this PC takes over.
- The wake-word name check also runs on this PC when "This PC" is chosen or there's no internet.

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
