"""Start Jarvis.
    pythonw run.py --app     desktop app: its own window, no console (what the Jarvis shortcut runs)
    python run.py            HUD in an Edge app window, with a console
    python run.py --console  terminal mode   (add --voice to talk)
    python run.py --install  create the Jarvis icon + Desktop and Start Menu shortcuts
"""
import argparse
import sys

if __name__ == "__main__":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. personal assistant")
    parser.add_argument("--app", action="store_true", help="run as a desktop app (own window, no console)")
    parser.add_argument("--install", action="store_true", help="create the Desktop / Start Menu shortcuts")
    parser.add_argument("--console", action="store_true", help="use the terminal instead of the HUD")
    parser.add_argument("--voice", action="store_true", help="(console) start in voice mode")
    parser.add_argument("--no-window", action="store_true", help="(HUD) don't open a window; browse to the URL yourself")
    args = parser.parse_args()

    if args.install:
        from jarvis.install import create_shortcuts
        for p in create_shortcuts():
            print("Created", p)
    elif args.app:
        from jarvis.desktop import main
        main()
    elif args.console:
        from jarvis.app import main
        main(start_in_voice=args.voice)
    else:
        import os
        from jarvis.app import BANNER, ensure_api_key
        os.system("")
        print(BANNER)
        ensure_api_key()
        from jarvis.hud import main
        main(open_window=not args.no_window)
