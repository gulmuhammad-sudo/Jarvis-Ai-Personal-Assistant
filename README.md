# Personal Assistant

A Jarvis-style AI assistant for Windows. It **talks, listens and does things on your PC** — in English, Urdu
or almost any language. You choose its name, voice and look. Free to use: it runs on free AI services, or
completely on your own PC.

## Download and install

### **[⬇ Download Personal Assistant Setup](https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant/releases/latest/download/Personal-Assistant-Setup.exe)** (Windows 10 / 11, about 160 MB)

1. **Open the file you downloaded.** If Windows says *"Windows protected your PC"*, press **More info → Run anyway**; if the
   browser says *"not commonly downloaded"*, choose **Keep** (the app isn't code-signed).
2. **Press Next through the steps:** folder, name, language, voice, look, your free AI keys (optional), startup. Every step
   already has a good answer. No admin password needed.
3. **Press Finish.** Later, open **Personal Assistant** from the Desktop or the Start Menu.

Prefer a folder? Take `Personal-Assistant-….zip` from the [latest release](https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant/releases/latest),
extract it, and open `Personal Assistant Setup.exe` inside.

> **Don't use the green *Code › Download ZIP* button** or *Source code (zip)*: that is the program text for developers, without the app.

To update, run the newer Setup: your settings, memories and keys stay. Problems? See [Install help](docs/INSTALL.md).

| What | Where |
|---|---|
| The program | `%LOCALAPPDATA%\Programs\Personal Assistant` |
| Your settings, memories, notes, history | `%APPDATA%\Personal Assistant` (API keys encrypted in `keys.dat`) |
| Offline models and voices | `%LOCALAPPDATA%\Personal Assistant\models` |
| Uninstall | **Settings › Apps › Installed apps** or **Control Panel › Programs and Features** → *Personal Assistant* → Uninstall (it asks whether to keep your data) |

## Using it

- **Talk:** press the mic or **Ctrl+Space** — or just say its name (wake word). **Type:** **Ctrl+K**.
- **Stop everything:** the red square button, **Esc twice**, or *Stop everything* in the tray menu.
- **Closing the window** only hides it by the clock (tray). Right-click the tray icon to quit.
- **Settings** has tabs: General · Voice & Mic · AI · Privacy · Permissions · Alerts.

## What it can do

- Live voice conversations you can interrupt, in English, Urdu (Roman or Urdu script) and more; Pakistani voices, men's and women's
- Open apps, files and websites; search the web; play YouTube; weather, news, prayer times
- Timers, alarms, notes and long-term memory you can search, edit and see as a graph
- Your own skills: rules it always follows and routines you run by name
- Windows on command (snap, side by side, minimise all) and saved workspaces; reads text on screen (offline OCR)
- Clock: timers, stopwatch, focus rounds, alarms that ring until stopped, world clock
- News: topics, your own sources, search, words you follow
- Learning: flashcards that come back before you forget them; quizzes you by voice
- Fitness: water, steps, sleep, weight, workouts, with targets and charts, private on your PC
- Travel: trips, packing lists, papers and budget; weather and time there
- Meetings: notes, decisions, actions as tasks; writes down what is said (only if you start it and all agree)
- People: birthdays and notes, a daily check-in, and how the assistant talks with you
- Email: reads your Gmail, warns of tricks, saves drafts; it can't send or delete
- Goals and habits, a private journal, and your own record of money, on your PC
- Documents: reads and makes Word, Excel, PowerPoint and PDF files, and searches inside the folders you choose
- Planner: calendar, tasks and notes on your PC, with reminders
- Agents: specialists with their own tools; web or your private things, never both
- Automations (by hand, at a time, or when the app opens) and visible plans for longer tasks
- Software updates and installs through winget (always asks first), internet check and speed test, dev helpers
- PC control: volume, brightness, Wi-Fi/Bluetooth, screenshots, cleaning old files, PowerShell
- Works **offline** if you want: local AI ([Ollama](https://ollama.com), free), speech recognition and voices
  on your PC — one-time downloads from inside the app

## Privacy and safety

- Your data stays on your PC. API keys are encrypted for your Windows account.
- Risky actions ask first; you choose **Ask / Allow / Never** per kind of action (Settings › Permissions).
  Dangerous commands (formatting disks, deleting Windows, switching off Defender…) are always refused.
- Text from web pages and files is treated as information, never as instructions.
- Settings › Privacy: keep or clear the saved conversation, and see a record of everything it did.

## For developers

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller pytest
.venv\Scripts\pythonw -m jarvis          # run from source
.venv\Scripts\python -m pytest tests     # tests (temporary data, fake keys)
.venv\Scripts\python packaging\build.py  # makes Personal Assistant Setup.exe, and the release files
```

| Folder | What's in it |
|---|---|
| `jarvis/` | the app (engine, voice, tools, UI page) |
| `packaging/` | build script and the install wizard |
| `tests/` | automated tests |
| `docs/` | [install help](docs/INSTALL.md), [user guide](docs/USER_GUIDE.md), [feature status](docs/FEATURE_STATUS.md), [architecture](docs/ARCHITECTURE.md), [changelog](docs/CHANGELOG.md), roadmap |
| `assets/` | the icon |
