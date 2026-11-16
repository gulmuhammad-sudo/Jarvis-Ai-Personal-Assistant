# J.A.R.V.I.S. — your personal AI assistant

A Jarvis-style desktop assistant for Windows. It **talks, listens and acts on your PC**, in English or Urdu.

**Free to run.** Jarvis uses free AI keys (Gemini → Groq → OpenRouter) and switches automatically if one is busy or down.

## Start it

1. Double-click **`Jarvis.bat`**. The first run installs everything and adds a **Jarvis** shortcut (arc-reactor icon) to your Desktop and Start Menu.
2. After that, open Jarvis from the shortcut. It opens as its own app window; closing the window stops Jarvis.
3. Click the mic (or press **Ctrl+Space**) and talk, or type in the box at the top (**Ctrl+K**).

Prefer the terminal? **`Jarvis Console.bat`** (add `--voice` to talk to it).
If something goes wrong, `data\jarvis.log` says what happened.

## Make it yours

- **Wake word (busy rooms):** with hands-free on, say its name first ("Maya…" or "Maya, mausam batao"). It answers
  "Haan ji, main sun rahi hoon", listens for ~15 s of follow-ups, then waits for its name again. Settings → Wake word.
- **Noise reduction:** Settings → Microphone → Noise reduction turns fans, AC and room chatter down. A headset helps most.
- **First start:** a short welcome setup asks for the assistant's name, what it calls you, your language (19 built
  in, or type any other), voices, look, hands-free and your free AI keys. Settings → Assistant → Run setup repeats it.
- **Approvals:** say "haan" / "yes" once and that kind of action (e.g. PowerShell) isn't asked again until the app
  restarts. Files in Desktop/Documents/Downloads are created without asking at all.
- **Activity:** click an item to see exactly what was done and its result.

- **Name:** Settings → **Assistant's name** (or just say "your name is Maya now" / "tumhara naam Friday rakh do").
  The new name is used everywhere: how it introduces itself, Live calls, approvals, the window title and every
  label on screen. Nothing else changes; every skill keeps working. For a female voice pick Kore or Aoede in
  Settings → Live voice (and Sonia/Libby for Classic).
- **Appearance:** Settings → Assistant → **Appearance** (Dark, Light, or Auto to follow Windows), or say "light mode".

- **Hands-free (on by default):** as soon as the app opens Jarvis is listening, so just start talking. In Live
  style it waits on your PC (no internet, no quota) and starts the call the moment you speak, passing on your first
  words. Turn it off with the button under the mic or Settings → Talking → Hands-free.
- **Which AI answers:** Settings → AI model, the **Use** buttons on the AI Models page, or say "Groq pe chalo" /
  "use OpenRouter" / "automatic". The one you pick answers first, the others stay as backup, and "Brain" in Core
  status shows who is answering. Live calls always use Gemini Live (choose Classic style to talk to another AI by voice).
- **New microphone:** plug in earbuds or a headset and Jarvis asks which mic to use (even mid-call).
- **Memory:** edit any memory (✎), forget it (×), or "Combine all into one" (also by voice: "put all my memories into one").
- **Alert sound:** Settings → Alerts → Alert sound (Chime, Classic beeps, Siren, Digital pulse) with a Play button.

## The Command Center

- **Left menu:** Command Center, Conversations (full chat), Memory (what Jarvis remembers + your notes), Profile, Tools & Skills, AI Models, Settings.
- **Profile** (left menu, or click your name at the top right): your name, what Jarvis should call you, birthday, city, languages, one "About me" box (family, study/work, interests, routine, goals) and how you like replies. Jarvis uses it in every conversation, typed or Live. It is saved in `data/profile.json` and sent to the AI with your messages, so leave out anything private.
- **Alerts:** warnings (alarms, timers, low battery, errors, mic muted, PC overloaded for 30 s) pop up at the top of the screen and **beep at full volume**: Windows volume goes to 100% just for the beep, then back to yours. Esc or × dismisses one. Turn it off in Settings → **Loud alerts** (then it beeps at your normal volume).
- **Centre globe:** Jarvis's AI core. Drag to rotate, scroll to zoom, hover to probe, click to talk. Cyan = standing by, green = listening, amber = thinking, pulsing = speaking. The latest exchange shows under it.
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

- **Reply speed:** Settings → **Live reply speed**. *Fast* (default) answers after 0.4 s of quiet; if Jarvis
  jumps in while you pause to think, choose *Normal* (0.65 s) or *Patient* (1 s). `data/jarvis.log` notes how
  quickly each reply started.

- **Interrupt him:** tap the mic or press **Esc** while he talks. On a headset (or with the speakers turned
  down) you can also just start talking over him. On loud laptop speakers his own voice leaks back into the
  mic, so Jarvis ignores sound that is quieter than his echo. That stops him interrupting himself.
- **End the call:** say "bye" / "bas, shukriya", tap the mic while he's listening, or press **End live conversation**.
  It also ends by itself after 3 quiet minutes.
- **Voice:** Settings → **Live voice** (Charon by default; he speaks with a British accent). The Ryan voice is
  only in Classic mode.
- **Free limits:** if one live model hits its free limit, Jarvis carries on with the next one
  (3.1 Flash Live, the quickest → 3.8 Live → 2.5 Flash Native Audio) and rests the busy one for 15 minutes.
- Prefer the old way? Settings → **How you talk to Jarvis → Classic** (you speak, then Jarvis answers in Ryan's voice).

## Voice (Classic mode)

- **Listening:** Jarvis records from your microphone itself and picks one that actually works. If the laptop mic goes silent (for example while a Bluetooth headset is connected), it switches mic on its own. If Windows has the mic **muted**, an **Unmute** button appears; **Settings → Microphone** lets you pick a mic or **Boost** a low input level.
- **Understanding:** Whisper (free Groq key) works out whether you spoke English or Urdu. Fan noise is filtered out first. Unclear audio, and Whisper's made-up "sentences" from noise, get "Sorry, I didn't catch that" instead of a wrong answer.
- **Weak laptop mic?** Press **Settings → Microphone → Boost level**, or use a headset. If Microsoft Teams or the keyboard's mic key mutes the mic, Jarvis tells you and shows **Unmute**.
- **Speaking:** Microsoft's natural voice **Ryan (British)** by default; Urdu replies use **Asad**. Speech starts streaming about a second after the reply.
- **Conversation mode:** after answering something you *said*, Jarvis listens again for a follow-up, so you don't need to press the mic each time. Click the mic or press **Esc** to interrupt Jarvis. You can turn it off in Settings.
- The last 5 recordings are kept in `data/voice_debug` to diagnose voice problems.

## Settings (`.env`)

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
- **Claude (optional):** put `claude` first in `JARVIS_PROVIDERS` and either sign in with `claude auth login` (Claude account with Pro) or add `ANTHROPIC_API_KEY`.

## How it works

| File | Job |
|---|---|
| `run.py` | Starts Jarvis: `--app` desktop app (what the shortcut runs), `--console` terminal, `--install` shortcuts |
| `jarvis/desktop.py` | The native app window (WebView2), taskbar icon, log file |
| `jarvis/hud.py` + `hud.html` | The engine and the Command Center page. It only listens on `127.0.0.1`, with a secret token per launch, so websites can't control Jarvis. |
| `jarvis/providers.py` | Gemini / Groq / OpenRouter / DeepSeek with fallback (`brain.py`, `brain_cc.py`: optional Claude) |
| `jarvis/tools.py` | Every action Jarvis can take. Add a skill: write a function and add its definition to one of the tool lists. |
| `jarvis/schedule.py` | Alarms, prayer times, weather, news, battery warnings, morning briefing |
| `jarvis/live.py` | Live conversation (Gemini Live): mic and speaker streaming, echo guard, tools, model fallback |
| `jarvis/recorder.py`, `stt.py`, `tts.py` | Classic mode: microphone, speech-to-text (Whisper), voice (Ryan / Asad) |
| `jarvis/memory.py`, `config.py` | Your profile, long-term memory, settings and safe saving of the `data/` files |
| `jarvis/alerts.py` | The loud alert beep (raises the volume for the beep, then puts it back) |
| `jarvis/wake.py`, `denoise.py` | Wake word (is the name in what was said?) and background-noise reduction |
| `jarvis/languages.py`, `urdu.py` | Languages and voices; Urdu shown in Urdu script on Live calls |
| `jarvis/gpu.py` | GPU usage and GPU memory for the System gauges (Windows performance counters) |
| `jarvis/app.py`, `voice.py` | The console version and its Windows voice |
