# Next steps

Exact order. Each step ends with tests, docs (FEATURE_STATUS, TESTING_REPORT, DEVELOPMENT_LOG) and a tagged release.

1. **Build 1.14.0** — packaged-exe check (memories, suggestions, voices offline), then update the owner's
   installed app with `dist\Personal Assistant Setup.exe`.
2. **Phase 4, rest** — knowledge graph view on the Memory page [40]; skills / custom instructions [103].
3. **Universal command bar** [107] — the top box also searches settings, memories and saved history.
4. **Real Ollama check** — with the owner's OK: install Ollama (free, ollama.com) and `qwen2.5:3b`; run a
   typed conversation with tools through Local AI in the packaged exe; record speed on this PC.

Waiting on the owner (not blocking):
- Permission to install Ollama for the real local-AI check.
- Publishing the latest Setup.exe as a GitHub release (`gh release create` works now; publishing needs an OK).
