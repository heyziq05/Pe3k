"""Pe3k entry point.

Author: heyziq05 (https://github.com/heyziq05)

    python app.py                 # start the web app + background monitoring
    python app.py init-db         # create the database and default settings
    python app.py seed-demo       # load sample devices and a week of demo history
    python app.py reset-db --yes  # delete ALL Pe3k data and start fresh
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys

from config import Config


def serve() -> None:
    from engine import create_app
    from engine.monitoring.scheduler import get_scheduler

    app = create_app(Config, with_scheduler=True)
    log = logging.getLogger("pe3k.server")

    def stop(signum, _frame):
        log.info("shutting down", extra={"event": "shutdown", "signal": signum})
        sched = get_scheduler()
        if sched:
            sched.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    host, port = Config.HOST, Config.PORT
    print(f"\n  Pe3k is running at http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}\n")
    if Config.DEBUG:
        # The reloader would start a second scheduler, so it is always off.
        app.run(host=host, port=port, debug=True, use_reloader=False, threaded=True)
        return
    try:
        from waitress import serve as waitress_serve

        waitress_serve(app, host=host, port=port, threads=8, ident="Pe3k")
    except ImportError:
        app.run(host=host, port=port, threaded=True, use_reloader=False)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pe3k", description="Pe3k network monitor")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the web app (default)")
    sub.add_parser("init-db", help="create tables and default settings")
    seed = sub.add_parser("seed-demo", help="add sample devices and synthetic history")
    seed.add_argument("--force", action="store_true", help="seed even if devices already exist")
    reset = sub.add_parser("reset-db", help="delete all data")
    reset.add_argument("--yes", action="store_true", help="confirm deletion")
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        serve()
        return

    from engine import build_container
    from engine.logging_setup import configure_logging

    configure_logging(Config.LOG_DIR, Config.LOG_LEVEL)
    if args.command == "reset-db":
        if not args.yes:
            parser.error("reset-db deletes every device, log and alert. Re-run with --yes to confirm.")
        from engine.db import Database

        Database(Config.DATABASE_PATH).reset()
        print("Database reset.")
    container = build_container(Config)
    if args.command == "init-db":
        print(f"Database ready at {Config.DATABASE_PATH}")
    elif args.command == "seed-demo":
        from engine.demo import seed_demo, seed_if_empty

        if args.force:
            print(seed_demo(container))
        elif seed_if_empty(container):
            print("Demo data added.")
        else:
            print("Devices already exist — nothing seeded (use --force to add demo data anyway).")


if __name__ == "__main__":
    main()
