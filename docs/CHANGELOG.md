# Changelog

Each version is also a git tag (`git tag -n20 vX.Y.Z` shows its notes). Newest first.

## 1.31.1 — 2026-11-24 (not pushed yet)
Every option stays where you put it.
- Fixed: after changing an option (theme, voice, model, any switch) it jumped back to the old value and forth again, once or twice.
  The page asks for the status every second and a half; answers asked for before the click came in after it and were painted. Now an
  answer older than your last choice is dropped, only one question is out at a time, and options show at once.
- Fixed: every status answer took 1.5 seconds, waiting for Ollama that isn't there, and longer with a microphone; both are asked in the
  background now (45 ms).
- Fixed: "Prefer local AI" and "Use" on AI Models showed the wrong state after a click; the Test button of a voice on this PC switched
  the voice setting there and back; the microphone list showed the old one after a change; "Keep conversation history" showed late.

## 1.31.0 — 2026-11-24 (not pushed yet)
Privacy and the timeline: a new Privacy page (Phase 9 part 1).
- Going out: which services the app talked to, how often, what goes there and how to stop it. Only the day, the address and the number
  are kept, on this PC, 30 days; it can be off.
- Local only: one switch, and nothing the app does leaves the PC: AI, speech and voices only from this PC, no Live call, no web. Held
  back at the bottom (every connection of the program), and in the window too (its letters, radio).
- Microphone & screen: each use with its reason and length, a sign at the top while the microphone is in use, and Windows' own list of
  which programs used the microphone, camera, location and screen.
- Permissions: how often each kind was asked, allowed, refused; allow for one hour (ends with Stop); ask everything again.
- Who may read what: everything the AI can be given, with switches; and what it never gets.
- Kept here: every kind of thing the app keeps, how much, clear, and for how long (nothing goes by itself unless you choose it).
- Timeline: everything, day by day: what you said, answers, actions, approvals, changes; search, take out one thing or a day, CSV, ask
  again, your most used requests. The AI can look in earlier conversations, only after it asks ("what did I ask you yesterday").
- Changed: recordings of your voice (the last five, for microphone problems) are kept only if you turn it on.
- Fixed: Windows' own recogniser could open the microphone in a test copy; a database upgrade cut short could never be finished.

## 1.30.0 — 2026-11-24
Media, screen recording and pictures: a new Studio page (Phase 8 part 4; Phase 8 is complete).
- Media: what is playing on this PC, in any app, with its controls and the volume; your own music and videos from folders you choose
  (search, playlists, mixed order, repeat), free internet radio with your own stations. It gets quieter by itself while someone
  speaks, in a Live call or when something rings. "Play …", "volume 40", "next song" by voice.
- Recorder: the screen, a window or a tab, with the computer's sound and your microphone if you tick them. Never silent: only its
  button starts it, Windows' own box asks each time what to share, a red bar stays on every page, and a small REC window stays above
  all others (also while a meeting is written down, also when the app is hidden). Pause, Stop, Emergency Stop; a recording cut short
  by a crash or a full drive keeps what there is. The assistant can't start one.
- Images: crop, turn, flip, size, light and colour, looks, text (Urdu too), see-through background, PNG / JPG / WebP, all on this PC;
  new files only, without the place and camera that photos carry. Make a picture online for free (Pollinations.ai): it says so, and
  the assistant asks each time.

## 1.29.0 — 2026-11-24
Travel, meetings and people: three new tabs on the Daily page (Phase 8 part 3).
- Travel: trips with a day-by-day plan, packing lists (basic, summer, winter, business, umrah, family), papers, a budget that follows
  Planner › Money, the time there, the weather when you press the button, add to calendar, a reminder the day before. Nothing is
  booked or paid.
- Meetings: agenda, people, notes, decisions, actions that become tasks, search, summary by the AI. The app can write down what is
  said: only your button starts it, each time with a tick that everyone knows and agrees; a red bar on every page with Pause and Stop;
  Emergency Stop ends it; sound is never saved. You choose where it is written down: on this PC (offline) or by Groq. No Live call
  can start meanwhile. The AI asks before it reads what was said, and afterwards asks before going online, as after an email.
- People: names, relations, birthdays (with reminders), notes; an optional daily check-in; how the assistant talks with you (butler,
  warm, cheerful, calm, professional; humour; length). It never sees phone numbers; names only with your tick.
- If you seem very low or in danger, the assistant is told to be kind, take it seriously and point to people and emergency help.

## 1.28.0 — 2026-11-24
Learning and fitness: two new tabs on the Daily page (Phase 8 part 2).
- Learn: decks of flashcards that come back just before you would forget them (spaced repetition). Study with the mouse, the keyboard
  (Space, 1 to 4) or by voice ("quiz me"); undo; only some new cards a day; streak and chart; a daily reminder; import from pasted text,
  CSV or Anki, export to CSV. The assistant can make cards, for example from a document you ask about.
- Fitness: water, steps, sleep, weight and workouts, daily targets, 30-day charts, BMI as a number, water and move reminders, CSV export.
  "I drank two glasses", "I slept 7 and a half hours", "I walked 30 minutes". No advice: numbers only.
- Health is private: the assistant writes what you tell it, but reads nothing back until you allow it; what was noted stays out of the
  activity list and the audit log; no agent or automation has it.
- The page of a demo copy can't open the microphone either.

## 1.27.1 — 2026-11-24
Downloading and installing, for new users.
- Setup is a file in the project folder itself (not in `dist` any more), next to READ ME FIRST.txt (English and Roman Urdu). Folders that
  only the tools need are hidden there.
- For GitHub releases: `Personal-Assistant-Setup.exe` (a download link that always gives the newest), a ZIP that shows the Setup and the
  instructions as soon as it is extracted, and checksums. `packaging/release.py` checks everything and publishes.
- An update unpacks next to the old version and swaps at the end: a full drive, a damaged file or the PC switching off never leaves you
  without a working app. Before, the old program files were deleted first.
- Setup shows a picture while it unpacks itself (before: nothing for five seconds, so people clicked again); a second double-click does
  nothing; closing the window in the middle of copying isn't possible; folders are checked before you go on.
- Plain messages when something is missing: WebView2 (with Microsoft's page), free space, an older Windows, an older Setup than what is installed.
- Uninstalling with "delete my data" also removes the offline models (before, hundreds of MB stayed). Old leftovers of Setup are cleaned.
- `--silent` and `--check` for people who install on several PCs. New: docs/INSTALL.md.

## 1.27.0 — 2026-11-24
Clock and news: a new Daily page (Phase 8 part 1).
- Timers survive a restart (one that ended while the app or the PC was off is told, not rung), can be paused, made longer and
  named. Stopwatch with laps. Focus rounds with breaks; the minutes you did are kept.
- Alarms and timers ring until you press Stop or Snooze (5 or 10 minutes; once, or up to 1, 2 or 5 minutes: you choose). In a
  Live call they ring once. Alarms can be edited and switched off and on. An alarm missed because the app or the PC was off is
  told when you are back. "Stop the alarm" and "snooze ten minutes" work by voice.
- World clock for about 75 cities with Windows' own summer-time rules (nothing is downloaded). "What time is it in London?"
- News: nine topics, seven ready sources (Dawn, Express Tribune, Geo, BBC اردو, BBC World, Ars Technica, ESPNcricinfo), your own
  RSS / Atom sources, search, words to follow (they join the daily briefing), stories kept for later, read aloud, summary by
  the AI. Nothing is fetched until you open the tab, ask, or the briefing runs. Addresses on this PC or the home network are
  refused; stories are untrusted text.
- A switched-off one-time alarm is no longer thrown away when another alarm rings.
- Demo copies (JARVIS_NO_MIC, JARVIS_NO_SPEAK) really stay off the microphone and quiet, also when a button is pressed.

## 1.26.1 — 2026-11-23
- Whom a draft is for, and the tool's answers about email, stay out of the activity list and the audit log too. Before, an
  address could get into them. (Found by the packaged-exe test.)

## 1.26.0 — 2026-11-23
Email (Gmail), look only: Planner page › Email.
- Connect with an app password that you make at Google; kept encrypted for your Windows account. Inbox, unread, search in
  Gmail's own words, reading as plain text (no pictures load, nothing is marked as read), drafts and draft replies.
- The app can't send, delete, move or mark anything: every other mail command is refused in its code, and there is no
  sending in the app at all.
- Warnings: Google couldn't confirm the sender, a name that shows another address, answers that go elsewhere, links that
  show one site and go to another, attached programs. Hidden text is left out.
- By voice or chat: "summarise my unread emails", "find the email from Ali about the meeting", "draft a reply: yes, ten is
  fine". It asks before the AI sees email (Settings › Permissions can allow or forbid it) and always shows a draft first.
- After the AI has seen an email it asks before it goes online, runs something or makes automations, for 30 minutes or until
  a new conversation, so an email can't talk it into carrying things out. Email stays out of the activity list and audit log.
- When a service finds a request too large (413), the smaller one brings documents, goals, journal, money and email only if
  you spoke of them; with the new tools it had grown too big again.

## 1.25.0 — 2026-11-23
- The glass look of Settings everywhere: see-through panels over soft light, the same rows, tabs, buttons, fields and
  headings with icons on every page, frosted popups; dark and light theme; the Setup window too. Profile sits in the middle
  like Settings.
- It costs no more than before. Blurring the panels as well looked the same and doubled the CPU use, so only popups are
  blurred. With Windows' Transparency effects off, everything is solid.

## 1.24.1 — 2026-11-23
- The local AI (offline) can write in the journal too. Before, only the online ones could. (Found by the packaged-exe test.)

## 1.24.0 — 2026-11-23
Planner page, three new tabs, all on this PC:
- Goals: goals with a target or steps, a day and a progress bar; habits (every day or some days a week) to tick, streaks,
  a reminder at your time.
- Journal: a few lines and a mood, the mood of the last 30 days, search, a reminder, a copy in Documents. Closed to the
  AI until you allow it; until then it can only write what you tell it to. Its text stays out of the activity list, the
  saved history's tool entries and the audit log.
- Money: what you spend and get, by category, with budgets, bills (reminder before their day), six months side by side,
  a CSV copy. Your own record: no bank, nothing is paid. "1.5k", "2 lakh" and Urdu digits are understood.
- By voice or chat: "I spent 1500 on groceries", "how much did I spend this month?", "mark walk as done", "write in my
  journal…". Deleting asks first; the same entry twice in a row is noticed.
- Automations can tell you your goals and habits, this month's money, or your bills.

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
