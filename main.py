#!/usr/bin/env python3
"""
WatchHunter — Orient Fuori Verso monitor.
Polls marketplaces 24/7, sends Telegram alerts, serves dashboard at localhost:5000.
"""

import argparse
import json
import logging
import logging.handlers
import os
import signal
import sys
import threading

# Allow importing sibling modules when run directly
sys.path.insert(0, os.path.dirname(__file__))

from database import Database
from notifier import Notifier
from monitor import Monitor


def load_config(path: str) -> dict:
    # Environment variables override config file (used in cloud/Railway deployment)
    config = {}
    try:
        with open(path) as f:
            config = json.load(f)
    except FileNotFoundError:
        pass  # OK in cloud — rely entirely on env vars
    except json.JSONDecodeError as e:
        sys.exit(f"Config JSON error: {e}")
    # Env vars override (cloud deployment)
    if os.environ.get("TELEGRAM_TOKEN"):
        config["telegram_token"] = os.environ["TELEGRAM_TOKEN"]
    if os.environ.get("TELEGRAM_CHAT_ID"):
        config["telegram_chat_id"] = os.environ["TELEGRAM_CHAT_ID"]
    return config


def setup_logging(log_path: str):
    fmt = logging.Formatter("%(asctime)s [%(threadName)s] %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(fmt)
    root.addHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)


def ensure_caffeinate():
    """Re-exec under caffeinate -i to prevent idle sleep, unless already running under it."""
    if os.environ.get("CAFFEINATE_CHILD"):
        return
    if sys.platform != "darwin":
        return
    caffeinate = "/usr/bin/caffeinate"
    if not os.path.exists(caffeinate):
        return
    env = os.environ.copy()
    env["CAFFEINATE_CHILD"] = "1"
    os.execve(caffeinate, [caffeinate, "-i", sys.executable] + sys.argv, env)


def build_scrapers(config: dict):
    from scrapers.ebay import EbayScraper
    from scrapers.reddit import RedditScraper
    from scrapers.watchcharts import WatchChartsScraper
    from scrapers.yahoojp import YahooJpScraper
    from scrapers.chrono24 import Chrono24Scraper
    from scrapers.mercari import MercariScraper
    from scrapers.catawiki import CatawikiScraper
    from scrapers.subito import SubitoScraper
    from scrapers.kleinanzeigen import KleinanzeigenScraper
    from scrapers.instagram import InstagramScraper

    return [
        EbayScraper(config),
        RedditScraper(config),
        WatchChartsScraper(config),
        YahooJpScraper(config),
        Chrono24Scraper(config),
        MercariScraper(config),
        CatawikiScraper(config),
        SubitoScraper(config),
        KleinanzeigenScraper(config),
        InstagramScraper(config),
    ]


def run_check_now(config: dict, db: Database):
    """Run one poll cycle on all scrapers synchronously. Sends Telegram for new finds."""
    from notifier import Notifier
    from monitor import _is_relevant
    token = config.get("telegram_token", "")
    chat_id = config.get("telegram_chat_id", "")
    notifier = Notifier(token, chat_id) if (token and not token.startswith("YOUR")) else None

    scrapers = build_scrapers(config)
    print(f"\nRunning one-shot check across {len(scrapers)} scrapers...\n")
    total_new = 0
    for scraper in scrapers:
        if not scraper.enabled:
            print(f"  [{scraper.name}] DISABLED")
            continue
        print(f"  [{scraper.name}] checking...", end=" ", flush=True)
        try:
            listings = scraper.fetch()
            relevant = [l for l in listings if _is_relevant(l.title)]
            new = 0
            for l in relevant:
                if db.insert_listing(l):
                    new += 1
                    print(f"\n    NEW: {l.source} | {l.title[:70]} | {l.price} | {l.url}")
                    if notifier:
                        notifier._send(l)
            print(f"{len(listings)} found ({len(relevant)} relevant), {new} new")
            total_new += new
            db.update_source_status(scraper.name, success=True, new_count=new)
        except Exception as e:
            print(f"ERROR: {e}")
            db.update_source_status(scraper.name, success=False, error=str(e))

    stats = db.get_stats()
    print(f"\nDone. {total_new} new listings this run. Total in DB: {stats['total']}")


def main():
    ensure_caffeinate()

    parser = argparse.ArgumentParser(description="WatchHunter — Orient Fuori Verso monitor")
    parser.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config.json"))
    parser.add_argument("--check-now", action="store_true", help="Run one poll cycle and exit")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable web dashboard")
    args = parser.parse_args()

    config = load_config(args.config)

    base_dir = os.path.dirname(os.path.abspath(args.config))
    log_path = os.path.join(base_dir, config.get("log_path", "watchhunter.log"))
    db_path = os.path.join(base_dir, config.get("db_path", "watchhunter.db"))

    setup_logging(log_path)
    logger = logging.getLogger(__name__)
    logger.info("WatchHunter starting up. DB: %s", db_path)

    db = Database(db_path)

    if args.check_now:
        run_check_now(config, db)
        return

    token = config.get("telegram_token", "")
    chat_id = config.get("telegram_chat_id", "")
    if not token or token.startswith("YOUR"):
        sys.exit("ERROR: Set telegram_token in config.json (see README for setup instructions)")
    if not chat_id or str(chat_id).startswith("YOUR"):
        sys.exit("ERROR: Set telegram_chat_id in config.json")

    notifier = Notifier(token, chat_id)
    stop_event = threading.Event()

    def _shutdown(signum, frame):
        logger.info("Shutdown signal received (%s)", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Start Telegram notification consumer
    notifier.start_consumer_thread(stop_event)

    # Start web dashboard
    if not args.no_dashboard:
        import dashboard.app as dash_app
        dash_app.db = db
        port = config.get("dashboard_port", 5000)
        dash_thread = threading.Thread(
            target=lambda: dash_app.app.run(
                host="127.0.0.1",
                port=port,
                use_reloader=False,
                threaded=True,
                debug=False,
            ),
            name="flask-dashboard",
            daemon=True,
        )
        dash_thread.start()
        logger.info("Dashboard running at http://127.0.0.1:%d", port)

    # Start scrapers
    scrapers = build_scrapers(config)
    monitor = Monitor(db, notifier)
    monitor.start(scrapers, stop_event)

    # Notify Telegram that we started
    notifier.send_startup_message()
    logger.info("WatchHunter is running. Monitoring %d sources.", len(scrapers))

    # Block main thread until shutdown
    stop_event.wait()

    logger.info("Shutting down...")
    notifier.send_shutdown_message()
    logger.info("WatchHunter stopped.")


if __name__ == "__main__":
    main()
