# Next steps

Exact order. Each step ends with tests, docs (FEATURE_STATUS, TESTING_REPORT, DEVELOPMENT_LOG) and a tagged release.

1. **Real Ollama check** — with the owner's OK: install Ollama (free, ollama.com) and `qwen2.5:3b`; run a
   typed conversation with tools through Local AI in the packaged exe; record speed on this PC (12 GB RAM,
   AMD integrated GPU).
2. **Task routing** [14] — screenshots/images go to a model that can see (local vision model or Gemini);
   very long inputs to a large-context model; offline → local only. Tests with fakes.
3. **Saved permissions** [6, 98] — per-kind permission settings (always ask / allow / never) in Settings ›
   Privacy, stored in settings; `TRUSTABLE` stays the list of kinds that may ever be "allow".
4. **Local speech-to-text** [12, 23] — faster-whisper as an optional download (model files ~150 MB); used
   when offline or when chosen; wake-word name check can then run locally.
5. **Local voice** [12, 37] — Piper voices as an optional download; speech speed and pitch in Settings.
6. **Universal command bar** [107] — the top box also searches settings, memories and saved history.
7. **Personal Intelligence Engine** [9, 40, 100] — memories into SQLite with categories and search; memory page search.

Waiting on the owner (not blocking):
- Upload `dist\Personal Assistant Setup.exe` of the latest version to a GitHub release (no GitHub CLI here;
  the browser can't attach local files).
- Permission to install Ollama for the real local-AI check.
