# Continue development (for a new session)

1. Read, in order: `docs/NEXT_STEPS.md`, the last entry of `docs/DEVELOPMENT_LOG.md`, `docs/FEATURE_STATUS.md`.
2. Check the real state — don't trust the docs blindly:
   ```
   git status
   git log --oneline -5
   git tag --sort=-creatordate | head -3
   .venv\Scripts\python -m pytest tests -q
   ```
   `jarvis/__init__.py` holds the version; the newest tag must match it.
3. Before touching voice or Live code, the app may be running a call: check
   `http://127.0.0.1:8765/api/stats` (token from the page) → `live.active`, and ask before restarting it.
4. Work on the first unchecked item in NEXT_STEPS.md. For each change:
   - read the code it touches first;
   - add/adjust tests in `tests/` (temporary data folder only; fake keys only; never the real `.env`/`keys.dat`);
   - run `pytest tests`; for packaging changes also `python packaging\build.py` and smoke-test
     `%TEMP%\PersonalAssistant-build\app\Personal Assistant\Personal Assistant.exe --no-window` with `JARVIS_DATA_DIR` and `JARVIS_HUD_PORT`
     set to a temporary folder / spare port;
   - update FEATURE_STATUS.md, TESTING_REPORT.md, DEVELOPMENT_LOG.md, NEXT_STEPS.md, CHANGELOG.md;
   - bump `__version__`, commit, annotated tag `vX.Y.Z` with the change list, push `main --follow-tags`.
5. Never commit `.env`, `data/`, `keys.dat`, `build/`, the Setup (`*.exe`), personal paths or e-mail addresses; scan the
   staged diff for key patterns (`AIza…`, `gsk_…`, `sk-or-…`, `sk-ant-…`) before every commit.
6. Talk to the owner in Roman Urdu or English (never Hindi script).
