# Next steps

Exact order. Each step ends with tests, docs (FEATURE_STATUS, TESTING_REPORT, DEVELOPMENT_LOG) and a tagged release.

1. **Owner installs 1.18.0** — Setup built and exe checked (38/38); Setup opened for the owner on 23 Nov (1.17.1 is installed).
2. **Push** — 1.17.1 and 1.18.0 are committed and tagged locally; pushes now happen every 2-3 releases.
3. **Phase 6, part 2** — agent profiles sharing context [39, 101].
4. **Universal command bar** [107] — the top box also searches settings, memories and saved history.
5. **Real Ollama check** — with the owner's OK: install Ollama (free, ollama.com) and `qwen2.5:3b`; run a
   typed conversation with tools through Local AI in the packaged exe; record speed on this PC.

Waiting on the owner (not blocking):
- Permission to install Ollama for the real local-AI check.
- Publishing the latest Setup.exe as a GitHub release (`gh release create` works now; publishing needs an OK).
