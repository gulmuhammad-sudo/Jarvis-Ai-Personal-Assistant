# User guide (full details)

The short version is the [README](../README.md). This page has every detail.


A Jarvis-style desktop assistant. It **talks, listens and acts on your PC**, in English, Urdu or any other language.
You choose its name and voice (it starts as "Jarvis"; this README calls it Jarvis).

**Free to run.** It uses free AI keys (Gemini → Groq → OpenRouter) and switches automatically if one is busy or down.

## Download

**[Download Personal Assistant Setup](https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant/releases/latest/download/Personal-Assistant-Setup.exe)**
(Windows 10 / 11, about 160 MB). If Windows says "Windows protected your PC", press **More info → Run anyway** (the app isn't
code-signed). Other files, checks and help: [Install help](INSTALL.md).

## Install

1. Run **`Personal Assistant Setup.exe`**. It installs for you only (no admin rights) and walks you through:
   install folder · the assistant's name and what it calls you · language, talking style and voices · theme,
   face and chat text · your free AI keys · start with Windows, Live call on open, hands-free and wake word.
   If you used the older run.py / .bat version, Setup finds it and brings over its settings, memories, notes and keys.
2. Open **Personal Assistant** from the Start Menu or the Desktop. It is a normal app (`Personal Assistant.exe`).
   - **Closing the window only hides it.** It keeps running with an icon by the clock (the **^** menu next to
     Wi-Fi and volume). Click that icon to open it again; right-click it for **Start live call**, **Start with
     Windows** and **Quit**.
   - **Starts with Windows:** when you sign in it opens by itself in the tray (Settings → Startup to turn it off).
   - **Live from the start:** as soon as it opens, a Live call starts and it greets you. After 3 quiet minutes it
     waits for you (or its name) again. Settings → Startup → *Live call when it opens*.
3. Click the mic (or press **Ctrl+Space**) and talk, or type in the box at the top (**Ctrl+K**).

- **Your data** (settings, memories, notes, the log) is in `%APPDATA%\Personal Assistant`. API keys are in
  `keys.dat` there, encrypted for your Windows account (only you, on this PC, can read them).
  If something goes wrong, `jarvis.log` there says what happened.
- **Uninstall:** Windows Settings → Apps → Installed apps → Personal Assistant → Uninstall. It asks whether to
  keep your data for next time.

### Build it yourself

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\python packaging\build.py
```

That makes `Personal Assistant Setup.exe` in the project folder; the app and the release files are in `%TEMP%\PersonalAssistant-build`.
To run straight from the code instead: `.venv\Scripts\pythonw -m jarvis` (its data then lives in `data\`
and its keys in `.env` next to the code).

## Privacy and safety

- **Stop everything:** the red square button at the top, Esc twice, or "Stop everything" in the tray menu.
- **Local AI (optional, free):** install [Ollama](https://ollama.com/download/windows), then on the AI Models page
  download a model (e.g. qwen2.5:3b, 1.9 GB). The assistant then thinks on this PC — offline, private, no limits —
  with the cloud AIs as backup ("Prefer local AI" decides which goes first).
- **Settings › Privacy:** keep or clear the saved conversation; see a record of everything it did on this PC.
- Dangerous PowerShell commands are refused even if you approve them; text from web pages and files is treated
  as information, never as instructions; API keys are stored encrypted.

## Make it yours

- **Just the face at first:** the Command Center opens with only the assistant's face; the grid button at the top
  shows or hides the details around it (remembered).
- **Face:** Globe, Mask or Rings (in the setup wizard or Settings › General › Face).
- **Talk over it any time:** start talking clearly and it stops and listens. Echo cancellation removes its own
  voice from the mic, so this works on laptop speakers too (a headset is still best).

- **Wake word (busy rooms):** with hands-free on, say its name first ("Maya…" or "Maya, mausam batao"). It answers
  "Haan ji, main sun rahi hoon", listens for ~15 s of follow-ups, then waits for its name again. Settings → Wake word.
- **Noise reduction:** Settings → Microphone → Noise reduction turns fans, AC and room chatter down. A headset helps most.
- **First start:** a short welcome setup asks for the assistant's name, what it calls you, your language (19 built
  in, or type any other), voices, look, hands-free and your free AI keys. Settings → Assistant → Run setup repeats it.
- **Approvals:** say "haan" / "yes" once and that kind of action (e.g. PowerShell) isn't asked again until the app
  restarts. Files in Desktop/Documents/Downloads are created without asking at all.
- **Activity:** click an item to see exactly what was done and its result.

- **Name:** Settings → **Assistant's name** (or just say "your name is Maya now" / "tumhara naam Friday rakh do").
  The new name is used for how it introduces itself, Live calls, approvals, the wake word and the labels on
  screen. The app itself (window title, shortcut) is always called **Personal Assistant**; every skill keeps working. For a woman's voice pick Kore or Aoede in
  Settings → Live voice (and Sonia/Libby for Classic). Pakistani: the Live voices marked "(Pakistani)", Uzma for Classic
  and typed answers, Aegis for offline (Download in Settings → Voice & Mic).
- **Appearance:** Settings → Assistant → **Appearance** (Dark, Light, or Auto to follow Windows), or say "light mode".

- **Hands-free (on by default):** as soon as the app opens Jarvis is listening, so just start talking. In Live
  style it waits on your PC (no internet, no quota) and starts the call the moment you speak, passing on your first
  words. Turn it off with the button under the mic or Settings → Talking → Hands-free.
- **Which AI answers:** Settings → AI model, the **Use** buttons on the AI Models page, or say "Groq pe chalo" /
  "use OpenRouter" / "automatic". The one you pick answers first, the others stay as backup, and "Brain" in Core
  status shows who is answering. Live calls always use Gemini Live (choose Classic style to talk to another AI by voice).
- **New microphone:** plug in earbuds or a headset and Jarvis asks which mic to use (even mid-call).
- **Memory:** search, filter by category, set stars (importance), edit (✎), forget (×), or "Combine all into one"
  (also by voice: "put all my memories into one"). **Graph** shows them as a map: you, your categories, each memory,
  and the people/places that link them. When you tell it something lasting about yourself it asks "Remember this?";
  nothing is saved unless you press Save (off switch: Settings › Privacy).
- **Skills** (Tools & Skills page): **Rules** are followed in every reply ("Keep answers short"); **Routines** run when
  you say "run my <name>" or press Run. Each has On/Off. The assistant can save one for you only after you approve.
- **Alert sound:** Settings → Alerts → Alert sound (Chime, Classic beeps, Siren, Digital pulse) with a Play button.

## The Command Center

- **Left menu:** Command Center, Conversations (full chat), Memory (what Jarvis remembers + your notes), Profile, Tools & Skills, AI Models, Settings.
- **Profile** (left menu, or click your name at the top right): your name, what Jarvis should call you, birthday, city, languages, one "About me" box (family, study/work, interests, routine, goals) and how you like replies. Jarvis uses it in every conversation, typed or Live. It is saved in `data/profile.json` and sent to the AI with your messages, so leave out anything private.
- **Alerts:** warnings (alarms, timers, low battery, errors, mic muted, PC overloaded for 30 s) pop up at the top of the screen and **beep at full volume**: Windows volume goes to 100% just for the beep, then back to yours. Esc or × dismisses one. Turn it off in Settings → **Loud alerts** (then it beeps at your normal volume).
- **Hide details** (grid button at the top): only the face fills the window, with a faint dock at the bottom: Hands-free, Mic, Spoken replies, Stop and Show details. Ctrl+K brings the details and the typing box back.
- **Centre face:** the globe (or the face you chose). Click it to talk; the globe can also be dragged and zoomed. Cyan = standing by, green = listening, amber = thinking, pulsing = speaking. The conversation itself is in the chat panel and on the Conversations page.
- **Activity:** everything Jarvis does, reminders, AI model switches and PC warnings.
- **Agents:** Jarvis's skills (Research, Browser, Memory, Task, Vision, System) light up while they work.
- **Timeline:** your timers, alarms and today's remaining prayers. **Models:** which AI providers are connected.
- **Daily Briefing** button (bottom right): weather, prayers, alarms, PC health and headlines in one go.
- When Jarvis wants to run something risky (a PowerShell command, shutdown, cleaning a folder…), an **Authorization required** box appears: **Authorize** or **Deny** (Esc).

## What it can do

| Say something like… | What Jarvis does |
|---|---|
| "What's the weather in Karachi?" / "Latest tech news" | Searches the live web (DuckDuckGo; if it blocks automated searches, Google News + Wikipedia, then Groq web search) |
| "Open Chrome" / "Launch Spotify" / "Open my Downloads" | Opens apps, folders and files |
| "Atif Aslam ka Tajdar-e-Haram lagao" | Finds the video on YouTube and plays it straight away |
| "How's my PC doing?" | CPU, RAM, battery, disk and the heaviest apps |
| "Look at my screen — what's this error?" | Takes a screenshot and reads it |
| "Read the text in this window" / "read the text in Desktop/receipt.png" | Windows' own OCR, offline |
| "Put Chrome on the left and VS Code on the right" / "minimise everything" | Moves, snaps, minimises and maximises windows |
| "Save this as my Study workspace" / "open Study workspace" | Saves the window layout; reopens the apps and puts them back |
| "Set a timer for 10 minutes" / "pause the timer" / "start the stopwatch" / "focus for 25 minutes" | Daily › Clock; timers survive a restart |
| "Snooze ten minutes" / "stop the alarm" | What is ringing now (or the Stop and Snooze buttons) |
| "What time is it in London?" | World clock |
| "What's in the news?" / "news about Karachi" / "what's new in what I follow?" | Headlines with their sources (Daily › News) |
| "Make ten flashcards about …" / "quiz me" | Daily › Learn |
| "I drank two glasses" / "I slept 7:30" / "I walked 30 minutes" | Daily › Fitness (it reads them back only if you allow it) |
| "Plan a trip to Istanbul from 5 to 9 June" / "what is left to pack?" | Daily › Travel (nothing is booked) |
| "New meeting tomorrow at 10 with Ali" / "summarise my last meeting" | Daily › Meetings; only your button starts writing down what is said |
| "My brother Ali's birthday is 14 May" / "whose birthday is next?" | Daily › People, where you also choose how it talks with you |
| "What did I ask you yesterday?" | Asks first, then looks in your saved conversations |
| (passwords, cards, CNIC, passport) | Vault page: only you; the assistant can't see it |
| (lock the whole app) | The lock at the top or Ctrl+L, after choosing how to open it (Privacy › Lock) |
| (what goes out, the microphone, what is kept) | Privacy page; "Local only" keeps everything on this PC |
| "Play <song>" / "next song" / "volume 40" / "find a Quran radio" | Studio › Media |
| "Make a picture of a red apple" / "make photo.jpg smaller" | Asks first, then Studio › Images; the original stays |
| (a screen recording) | Only by its button: Studio › Recorder |
| "Summarise my unread emails" / "draft a reply to Ali: yes, ten is fine" | Reads your Gmail and saves drafts; never sends (Planner › Email to connect) |
| "I spent 1500 on groceries" / "how much did I spend this month?" / "mark walk as done" / "write in my journal: …" | Goals, habits, journal, money (Planner page) |
| "Summarise Desktop/report.pdf" / "make a PowerPoint about solar power on my Desktop" / "find the warranty in my documents" | Reads, makes and searches documents (folders: Tools & Skills › Documents) |
| "Send the report tomorrow at 5" / "what's planned on Friday?" / "read my shopping note" | Planner: tasks, calendar, notes (Planner page) |
| "Ask the Researcher to compare these two phones" | A specialist agent does it (Agents page) |
| "Run my Focus time automation" / "make an automation that tells me the weather at 8" | Automations page; creating one asks you first |
| "Which apps have updates?" / "install VLC" / "update everything" | winget; every install, update or uninstall asks you first |
| "Why is the internet not working?" / "speed test" / "flush DNS" | Checks Wi-Fi, router, internet, DNS and a web page; plain answer |
| "Which dev tools do I have?" / "git status of Desktop/Jarvis" / "what's using port 3000?" | Read-only developer helpers |
| "Remind me in 20 minutes to drink water" | A timer that's spoken out loud when it's due |
| "Set an alarm for 7 am every day" / "Weekdays 6:30 alarm, label gym" | Saved alarms with a chime (once, daily, weekdays, weekends or chosen days). They survive restarts, and if the PC was asleep they still ring within 5 minutes. |
| "Namaz ka waqt kya hai?" | Prayer times for your city (Karachi method, Hanafi Asr) with reminders 10 minutes before and at each prayer. "Prayer reminders off" stops them. |
| "Daily briefing" | The morning summary. It also plays by itself at 08:00 while Jarvis is running. |
| "Urdu mein baat karo" / "Speak English" | Switches language (also the **EN / اردو** button at the top) |
| "My city is Lahore" | Changes the city for weather and prayers (set to Islamabad now) |
| "Turn the volume up" / "Pause the music" / "Brightness 40" | Media keys, volume, screen brightness |
| "Bluetooth on karo" / "Wi-Fi status" | Wi-Fi and Bluetooth. Turning Wi-Fi off asks first (Jarvis needs the internet). |
| "Chrome band karo" | Closes an app politely; asks first if it has unsaved work |
| "Shutdown" / "Restart" / "Sleep" | Always asks first; shutdown/restart wait 30 s ("cancel shutdown") |
| "Screenshot lo" | Saves a PNG in `Pictures\Jarvis Screenshots` |
| "Downloads mein purani files dikhao" / "Clean my Downloads" | Lists old files; cleaning asks first and only moves them to the **Recycle Bin**. System and Jarvis folders are never touched. |
| "Find my resume PDF" / "Summarise notes.txt" / "Note this down: …" | Finds and reads files; saves notes to `data/notes/` |
| "My name is Ali and I study CS" | Remembers it long-term (`data/memory.json`) |
| "What's my IP address?" | Runs PowerShell, **asking you before every command** |
| (automatic) | Battery warnings at 20%, 10% and 5% when unplugged, and "fully charged" |

## Live conversation (default)

Click the mic, **Start live conversation** or press **Ctrl+Space**, then just talk, like a phone call. Jarvis
(Gemini Live, free with your Gemini key) hears you while you speak and answers out loud straight away
(under a second after you stop). Every skill still works: apps, YouTube, alarms, PC control, approvals.

- **Interrupt:** just start talking while it answers, or tap the mic / press **Esc**. Echo cancellation takes its
  own voice out of the mic, and it only stops for clear speech that lasts a moment, so it doesn't cut itself off.
  `data/jarvis.log` says how much echo was removed on each call.
- **Chat text:** the chat is written in English letters (Urdu as Roman Urdu), even when it speaks Urdu. Say
  "Urdu mein type karke do" (or Settings → Language → Chat text) and the chat is typed in Urdu script instead;
  "English mein likho" switches back.
- It knows today's date and the time the call started.
- **End the call:** say "bye" / "bas, shukriya", tap the mic while he's listening, or press **End live conversation**.
  It also ends by itself after 3 quiet minutes.
- **Voice:** Settings → **Live voice** (Charon by default; Kore, Aoede and the Pakistani ones are women's voices). The Ryan voice is
  only in Classic mode.
- **Free limits:** if one live model hits its free limit, Jarvis carries on with the next one
  (3.1 Flash Live, the quickest → 3.8 Live → 2.5 Flash Native Audio) and rests the busy one for 15 minutes.
- Prefer the old way? Settings → **How you talk to Jarvis → Classic** (you speak, then Jarvis answers in Ryan's voice).

## Voice (Classic mode)

- **Listening:** Jarvis records from your microphone itself and picks one that actually works. If the laptop mic goes silent (for example while a Bluetooth headset is connected), it switches mic on its own. If Windows has the mic **muted**, an **Unmute** button appears; **Settings → Microphone** lets you pick a mic or **Boost** a low input level.
- **Understanding:** Whisper (free Groq key) works out whether you spoke English or Urdu. Fan noise is filtered out first. Unclear audio, and Whisper's made-up "sentences" from noise, get "Sorry, I didn't catch that" instead of a wrong answer.
- **Weak laptop mic?** Press **Settings → Microphone → Boost level**, or use a headset. If Microsoft Teams or the keyboard's mic key mutes the mic, Jarvis tells you and shows **Unmute**.
- **Speaking:** Microsoft's natural voice **Ryan (British)** by default; Replies in Urdu letters use **Asad**, or **Uzma** with a woman's voice; Uzma can also be the reading voice. Speech starts streaming about a second after the reply.
- **Conversation mode:** after answering something you *said*, Jarvis listens again for a follow-up, so you don't need to press the mic each time. Click the mic or press **Esc** to interrupt Jarvis. You can turn it off in Settings.
- The last 5 recordings are kept in `data/voice_debug` to diagnose voice problems.

## Settings (`.env` in your data folder)

```
JARVIS_USER_NAME=Sir                         # what Jarvis calls you
JARVIS_PROVIDERS=gemini,groq,openrouter,deepseek   # AI providers, in order
GEMINI_API_KEY=...       # free: https://aistudio.google.com/apikey
GROQ_API_KEY=...         # free: https://console.groq.com/keys   (also used for Whisper)
OPENROUTER_API_KEY=...   # free models: https://openrouter.ai/keys
DEEPSEEK_API_KEY=        # paid, very cheap: https://platform.deepseek.com
```

Optional: `JARVIS_NAME` (starting name, default `Jarvis`) · `JARVIS_THEME` (`dark` / `light` / `system`) · `JARVIS_LIVE_VOICE` (default `Charon`) · `JARVIS_LIVE_MODEL` (comma-separated, tried in order) · `JARVIS_VOICE` (default `en-GB-RyanNeural`) · `JARVIS_URDU_VOICE` (`ur-PK-AsadNeural` / `ur-PK-UzmaNeural`) · `JARVIS_VOICE_SPEED=+5%` · `JARVIS_VOICE_PITCH=-2Hz` · `JARVIS_BRIEFING_TIME=08:00` (or `off`) · `JARVIS_PRAYER_REMINDER_MINUTES=10` · `JARVIS_PRAYER_METHOD=1` · `JARVIS_PRAYER_SCHOOL=1` (Hanafi; 0 = Shafi'i) · `JARVIS_NEWS_REGION=PK` · `JARVIS_BATTERY_WARN=20` · `JARVIS_BATTERY_FULL_NOTICE=off` · `GEMINI_MODEL` / `GROQ_MODEL` / `OPENROUTER_MODEL` (comma-separated lists are tried in order).

### AI providers and fallback
- Providers without a key are skipped. One with a bad key is skipped until you restart Jarvis.
- Every reply is labelled with the AI that wrote it (e.g. "JARVIS · GEMINI"), and switches show in Activity.
- If a provider fails *after* it already did something on your PC, Jarvis stops and tells you instead of repeating the action on another model.
- Gemini and OpenRouter's default model can read screenshots; Groq and DeepSeek can't.
- **Claude (optional, paid):** add `ANTHROPIC_API_KEY` and put `claude` first in `JARVIS_PROVIDERS`. Without a key it is skipped.

## How it works

| File | Job |
|---|---|
| `packaging/` | `build.py` builds the .exe and the installer; `setup_app.py` + `setup.html` are the install wizard |
| `jarvis/__main__.py` | Starts the app (`--tray`: hidden in the tray; `--uninstall`: what Windows runs to remove it) |
| `jarvis/install.py` | Shortcuts, start with Windows, the Settings → Apps entry and uninstalling |
| `jarvis/desktop.py` | The native app window (WebView2), tray icon and menu, taskbar icon, log file |
| `jarvis/hud.py` + `hud.html` | The engine and the Command Center page. It only listens on `127.0.0.1`, with a secret token per launch, so websites can't control Jarvis. |
| `jarvis/providers.py` | Gemini / Groq / OpenRouter / DeepSeek with fallback (`brain.py`: the instructions, optional Claude with an API key) |
| `jarvis/tools.py` | Every action Jarvis can take. Add a skill: write a function and add its definition to one of the tool lists. |
| `jarvis/schedule.py` | Alarms, prayer times, weather, news, battery warnings, morning briefing |
| `jarvis/live.py` | Live conversation (Gemini Live): mic and speaker streaming, interrupting, tools, model fallback |
| `jarvis/recorder.py`, `stt.py`, `tts.py` | Classic mode: microphone, speech-to-text (Whisper), voice (Ryan / Asad) |
| `jarvis/memory.py`, `config.py` | Your profile, long-term memory, settings and safe saving of the `data/` files |
| `jarvis/alerts.py` | The loud alert beep (raises the volume for the beep, then puts it back) |
| `jarvis/aec.py` | Echo cancellation: removes the assistant's own voice from the mic so you can interrupt it |
| `jarvis/wake.py`, `denoise.py` | Wake word (is the name in what was said?) and background-noise reduction |
| `jarvis/languages.py`, `urdu.py` | Languages and voices; chat text in English letters or, if you ask, Urdu script |
| `jarvis/gpu.py` | GPU usage and GPU memory for the System gauges (Windows performance counters) |
| `jarvis/voice.py` | Windows' own speech recognition (backup when no Groq/Gemini key) |
