# Download, install, update, remove

## What to download

Everything is on the **[latest release](https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant/releases/latest)**.

| File | For whom |
|---|---|
| **`Personal-Assistant-Setup.exe`** | everyone: the one file you need ([direct download](https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant/releases/latest/download/Personal-Assistant-Setup.exe)) |
| `Personal-Assistant-….zip` | the same Setup in a folder with the instructions (when your browser blocks `.exe` files, or to give to someone) |
| `SHA256.txt` | to check that the download is whole (optional) |
| `Source code (zip / tar.gz)` | developers only; GitHub adds these by itself. **There is no app inside.** The same goes for the green **Code › Download ZIP** button |

You need Windows 10 (version 1809 or newer) or Windows 11, 64-bit, about 1 GB of free space, and the internet for the free AIs.

## Install

1. Open `Personal-Assistant-Setup.exe` (from the ZIP: extract it first, then open `Personal Assistant Setup.exe`).
   A small picture shows while it unpacks itself (a few seconds).
2. **"Windows protected your PC"** → **More info** → **Run anyway**. Windows says that about every app that isn't code-signed.
   A browser may say "not commonly downloaded": choose **Keep**.
3. Press **Next** through the steps. Every step already has a good answer.
4. **Install**, then **Finish**. No admin password is needed; it installs only for you.

| What | Where |
|---|---|
| The program | `%LOCALAPPDATA%\Programs\Personal Assistant` (`Personal Assistant.exe` and `_internal`) |
| Your settings, memories, notes, history | `%APPDATA%\Personal Assistant` (AI keys encrypted in `keys.dat`) |
| Offline models and voices (only if you download them) | `%LOCALAPPDATA%\Personal Assistant\models` |
| Shortcuts | Desktop, Start Menu, and Startup (only if you want it to start with Windows) |

## The free AI keys

You can skip them and add them later in **Settings › AI**. Without a key the app opens but can't answer, unless you set up
Local AI. One key is enough to start; **Gemini** is the best first one (it is also what Live calls need).

## Update

Run the newer Setup. It closes the app, swaps the program files and keeps your settings, memories and keys. If something goes
wrong on the way (no space, the PC switched off), the version you had still works.

## Remove

Windows **Settings › Apps › Installed apps › Personal Assistant › Uninstall**. It asks whether to delete your settings,
memories, keys and offline models too.

## When something doesn't work

| What you see | What to do |
|---|---|
| "This PC doesn't have Microsoft Edge WebView2" | It is a free part of Windows from Microsoft. Press Yes, run the file it downloads, then open Setup again |
| "There isn't enough free space" | Free some space, or press Browse and choose another drive |
| "already has other files in it" | Choose an empty folder; the suggested one is fine |
| "Windows didn't allow writing there" | Choose a folder inside your user folder (the suggested one), or wait a minute for the antivirus and try again |
| "This Setup file is damaged" | The download was cut short: download it again |
| An antivirus removes the file | Apps that aren't code-signed are sometimes suspected. Compare the checksum below, then restore / allow it |
| Nothing happens after a double-click | Wait half a minute (a slow disk unpacks slowly), look in the taskbar |
| The app opens but doesn't answer | Add a free AI key in Settings › AI |
| It doesn't hear you | Windows Settings › Privacy › Microphone: allow desktop apps; then Settings › Voice & Mic in the app |

**Checking the download** (PowerShell, in the folder with the file): `Get-FileHash .\Personal-Assistant-Setup.exe` must show the
number in `SHA256.txt`.

**Without questions** (for several PCs): `Personal-Assistant-Setup.exe --silent` installs into the usual folder and keeps settings;
`--dir "D:\Apps\Personal Assistant"` chooses another one.
