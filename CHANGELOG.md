# Changelog

All notable changes to this assistant. Versions follow [semantic versioning](https://semver.org): MAJOR.MINOR.PATCH.

## 1.3.3 (2026-11-16)

### Fixed
- The clock covered the search bar in smaller windows (moving it had pulled the toolbar into the middle). The
  toolbar now always stays on the right; the clock is centred in the window only when there is room.
- Languages typed under "Other" (e.g. Sindhi) now tell speech recognition which language it is (about 70 more
  Whisper languages), so the wake word and Classic mode no longer guess; Sindhi letters are understood in names.

## 1.3.2 (2026-11-16)

### Fixed
- **Wake word didn't react to "Max":** the mute check paused the microphone for ~1.7 s every 3 s (so words were
  lost); it now runs on its own thread. Name checks now tell Whisper your language (its own guess on a 1-second
  clip was often wrong), and short names written in Urdu script ("میکس" for Max) are recognised.
- A muted microphone now shows a simple "Your mic is muted · Unmute mic" instead of "Something went wrong",
  also while waiting for the name.

### Changed
- The app keeps one fixed name, **Personal Assistant** (window title, Desktop / Start Menu shortcut, sidebar);
  renaming the assistant only changes the assistant. Older shortcuts named after the assistant are renamed.
- The clock sits in the middle of the window.
- The "First-time setup" row is hidden once setup is done.
- Shorter, simpler wording in the voice panel and Talking settings.

## 1.3.1 (2026-11-16)

### Fixed
- Wake word: short sounds (clicks, coughs, a door) are no longer sent for a name check; only bits with at least
  0.3 s of real voice are. Saves free quota in noisy rooms.
- Whisper's made-up "Thank you." / "Bye." on noise are recognised as noise in name checks.

## 1.3.0 (2026-11-16)

### Added
- **Wake word:** with hands-free on, the assistant only responds after you call its name ("Maya", "مایا").
  Just the name gets a short "Haan ji, main sun rahi hoon" / "Yes, I'm listening", then it listens; "Maya, what's
  the time?" is answered straight away. After answering it keeps listening ~15 s for a follow-up, then waits for
  its name again, so people talking nearby are ignored. Works in Live and Classic style; Settings → Wake word.
  Names are recognised in English letters, Urdu script and Hindi letters; short names must match exactly so
  everyday words ("maa", "main") never wake it. At most 12 name checks a minute (free-quota guard).
- **Noise reduction:** background noise (fans, AC, a busy room) is turned down before the assistant listens, on
  live calls and in Classic mode. Settings → Microphone → Noise reduction (Off / Normal / Strong). Live calls
  in wake-word mode are also less eager to treat background talk as speech.

## 1.2.0 (2026-11-16)

### Added
- **Welcome setup on first start:** name the assistant, what it calls you, language, call and reading voices,
  look, hands-free, conversation style and free AI keys (saved only in .env on your PC). Settings → Run setup
  brings it back.
- **Any language:** 19 languages with matching voices (English, Urdu, Hindi, Arabic, Pashto, Persian, Bengali,
  Punjabi, Turkish, French, Spanish, German, Portuguese, Italian, Russian, Chinese, Japanese, Indonesian, Malay),
  or type any other language.
- **Activity details:** click any Activity item to see what was asked and its full result (memories, searches,
  files...), with a Copy button.
- **write_file / make_folder tools:** files and folders in Desktop, Documents or Downloads are created without
  PowerShell, so no approval is needed (replacing an existing file still asks).
- Female reading voices (Sonia, Libby, Ava).

### Changed
- **Approvals remember your yes:** after you allow PowerShell commands (or locking the PC / Wi-Fi off) once, they
  aren't asked again until the app restarts. "Only this time" keeps asking; shutdown, restart and deleting files
  are always asked. Settings → Permissions → "Ask every time again".
- Live calls show Urdu in Urdu script (Gemini writes it in Hindi letters; it is converted), unless Hindi is chosen.
- Renaming the assistant renames the Desktop / Start Menu shortcut too.
- Smoother UI: page transitions, button feedback, dialogs fade in and out, fewer redraws.

### Fixed
- The theme sometimes switched by itself: tests were writing to the real settings file. Tests now use a
  separate data folder (JARVIS_DATA_DIR).

## 1.1.0 (2026-11-16)

### Added
- **Hands-free from the moment the app opens.** In Live style the assistant waits on your PC (no internet, no quota)
  and starts the call as soon as you speak, passing on your first words.
- **Choose which AI answers:** Settings → AI model, the Use buttons on the AI Models page, or by voice
  ("Groq pe chalo", "use OpenRouter", "automatic"). The Brain row in Core status shows who is answering.
- **New microphone prompt:** plugging in earbuds or a headset asks which mic to use (works mid-call too).
- **Memory editing:** edit (✎) or forget (×) any memory, or combine them all into one (button or voice).
- **Alert sounds:** Chime (new default), Classic beeps, Siren, Digital pulse, with a Play button.
- **Voice approvals:** answer the Authorization box with "yes / haan" or "no / nahi"; redesigned box with
  details, queue count and an auto-deny countdown.
- Version number shown in Settings.

### Changed
- Settings reorganised into sections (Assistant, Talking, Voices, AI model, Microphone, Language, Alerts, Chat)
  with clearer wording; the two voices are now clearly "Call voice (Live)" and "Reading voice (Classic & typed)".
- Theme picker is now Dark / Light / Auto preview cards; the theme button left the top bar.
- Profile trimmed to 7 fields; older detailed fields are folded into "About me".
- The globe shows only the sphere; conversation captions float above the footer and fade away.

### Removed
- Live reply speed, Location and Speech recognition rows from Settings (handled automatically).

## 1.0.0 (2026-11-16)

First public version: desktop Command Center, Gemini → Groq → OpenRouter with fallback, Gemini Live voice calls,
Classic Whisper + neural voice mode, PC skills, alarms and prayer times, loud alerts, profile, custom assistant
name, light/dark themes, GPU monitor.
