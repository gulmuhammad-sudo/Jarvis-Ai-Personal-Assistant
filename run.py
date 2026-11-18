"""Start the Personal Assistant.

    pythonw run.py              the app in its own window (what the Desktop shortcut runs)
    python run.py --install     create the Desktop + Start Menu shortcuts
    python run.py --no-window   only the engine; open http://127.0.0.1:8765 yourself (for testing)
"""
import argparse
import sys

if __name__ == "__main__":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Personal Assistant")
    parser.add_argument("--app", action="store_true", help="the app in its own window (default)")
    parser.add_argument("--install", action="store_true", help="create the Desktop / Start Menu shortcuts")
    parser.add_argument("--no-window", action="store_true", help="engine only, no window")
    args = parser.parse_args()

    if args.install:
        from jarvis.install import create_shortcuts
        for p in create_shortcuts():
            print("Created", p)
    elif args.no_window:
        from jarvis.hud import main
        main(open_window=False)
    else:
        from jarvis.desktop import main
        main()
