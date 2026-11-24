# Next steps

Exact order. Each step ends with tests, docs (FEATURE_STATUS, TESTING_REPORT, DEVELOPMENT_LOG) and a tagged release.

1. **Build and release 1.30.0** (committed and tagged locally, not pushed): exe test with Studio checks (28 automation steps now; `LOCALAPPDATA` must point into the made-up home), setup_test, push, RELEASE_NOTES, `packaging/release.py --publish`. 1.29.0 is the latest release on GitHub. The owner tries a screen recording and a meeting.
2. **Phase 9** — privacy and permission dashboard [98, 6], encrypted vault [77, 81], backup and restore [57], self-diagnostics [99], activity timeline [109], multi-PC pairing [21, 28, 74].
3. **Real AI, rest** — Live calls with plans and agents (needs the owner's microphone); fewer tools per request for Groq.
4. **Phase 7 — productivity and knowledge.** Also: find out where the unexplained Emergency Stops in the test copy came from.
5. **Universal command bar** [107] — the top box also searches settings, memories and saved history.
6. **Real Ollama check** — with the owner's OK: install Ollama (free, ollama.com) and `qwen2.5:3b`; run a
   typed conversation with tools through Local AI in the packaged exe; record speed on this PC.

Waiting on the owner (not blocking):
- Permission to install Ollama for the real local-AI check.
