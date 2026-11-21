# Next steps

Exact order. Each step ends with tests, docs (FEATURE_STATUS, TESTING_REPORT, DEVELOPMENT_LOG) and a tagged release.

1. **Owner installs 1.16.1** — Setup built and exe checked (23/23); Setup opened for the owner on 21 Nov (1.15.0 is installed).
2. **Build 1.17.0** — packaged-exe check (winget, network, dev tools inside the exe), then update the installed app.
3. **Phase 6 — multi-agent and automation** — visible multi-step plans with step approval [20], workflow engine [35, 108].
4. **Universal command bar** [107] — the top box also searches settings, memories and saved history.
5. **Real Ollama check** — with the owner's OK: install Ollama (free, ollama.com) and `qwen2.5:3b`; run a
   typed conversation with tools through Local AI in the packaged exe; record speed on this PC.

Waiting on the owner (not blocking):
- Permission to install Ollama for the real local-AI check.
- Publishing the latest Setup.exe as a GitHub release (`gh release create` works now; publishing needs an OK).
