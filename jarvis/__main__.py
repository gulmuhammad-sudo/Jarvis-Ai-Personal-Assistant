"""Start the Personal Assistant.

The installed app is "Personal Assistant.exe" (made by packaging/build.py, installed by "Personal Assistant Setup.exe").
From a source checkout:

    pythonw -m jarvis              the app in its own window
    pythonw -m jarvis --tray       start hidden in the tray (what "start with Windows" runs)
    python -m jarvis --no-window   only the engine; open http://127.0.0.1:8765 yourself (for testing)
    python -m jarvis --install     Desktop + Start Menu shortcuts that run this checkout
"""
import argparse
import sys


def main() -> None:
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="Personal Assistant", description="Personal Assistant")
    parser.add_argument("--app", action="store_true", help=argparse.SUPPRESS)     # older shortcuts pass it
    parser.add_argument("--tray", action="store_true", help="start hidden in the tray (Windows sign-in)")
    parser.add_argument("--no-window", action="store_true", help="engine only, no window")
    parser.add_argument("--install", action="store_true", help="Desktop / Start Menu shortcuts for this checkout")
    parser.add_argument("--uninstall", action="store_true", help="remove the installed app")
    args, _ = parser.parse_known_args()

    if args.uninstall:
        from jarvis.install import uninstall
        uninstall()
    elif args.install:
        from jarvis.install import create_shortcuts
        for p in create_shortcuts():
            print("Created", p)
    elif args.no_window:
        from jarvis.hud import main as engine
        engine(open_window=False)
    else:
        from jarvis.desktop import main as app
        app(tray=args.tray)


if __name__ == "__main__":
    main()
