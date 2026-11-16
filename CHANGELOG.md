# Changelog

All notable changes to this assistant. Versions follow [semantic versioning](https://semver.org): MAJOR.MINOR.PATCH.

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
