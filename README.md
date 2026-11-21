# Personal Assistant

A Jarvis-style AI assistant for Windows. It **talks, listens and does things on your PC** — in English, Urdu
or almost any language. You choose its name, voice and look. Free to use: it runs on free AI services, or
completely on your own PC.

## Download and install

1. Go to **[Releases](https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant/releases)** and download
   `Personal.Assistant.Setup.exe` (Windows 10/11, about 100 MB).
2. Run it. If Windows says *"Windows protected your PC"*, press **More info → Run anyway** (the app isn't
   code-signed).
3. Follow the steps: name, language, voice, look, your free AI keys (optional) and startup options.
   No admin password needed.

Open **Personal Assistant** from the Start Menu or the Desktop.

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

- Live voice conversations you can interrupt, in English, Urdu (Roman or Urdu script) and more
- Open apps, files and websites; search the web; play YouTube; weather, news, prayer times
- Timers, alarms, notes and long-term memory you can search, edit and see as a graph
- Your own skills: rules it always follows and routines you run by name
- Windows on command (snap, side by side, minimise all) and saved workspaces; reads text on screen (offline OCR)
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
.venv\Scripts\python packaging\build.py  # makes dist\Personal Assistant Setup.exe
```

| Folder | What's in it |
|---|---|
| `jarvis/` | the app (engine, voice, tools, UI page) |
| `packaging/` | build script and the install wizard |
| `tests/` | automated tests |
| `docs/` | [user guide](docs/USER_GUIDE.md), [feature status](docs/FEATURE_STATUS.md), [architecture](docs/ARCHITECTURE.md), [changelog](docs/CHANGELOG.md), roadmap |
| `assets/` | the icon |
