import logging
import random
import threading
import time
from typing import List

from database import Database
from notifier import Notifier
from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Specific phrases that alone confirm it's the watch
_SPECIFIC = [
    "fuori verso", "fouri verso", "fuori verse", "fuori versa", "fuoriverso",
    "orient crash", "orient dent", "orient bent", "orient asymmetric",
    "orient b15427", "orient b15428",
    "オリエント b15427", "オリエント b15428",
    "orient 左右非対称", "オリエント 左右非対称",
]

# Must have a brand/watch word AND (reference OR watch category word)
_BRAND = ["orient", "オリエント"]
_REF   = ["b15427", "b15428", "15427-10", "15428-10"]
_WATCH = ["時計", "腕時計", "watch", "wristwatch", "orologio", "montre", "uhr", "reloj", "horology"]


def _is_relevant(title: str) -> bool:
    t = title.lower()
    if any(s in t for s in _SPECIFIC):
        return True
    has_brand = any(b in t for b in _BRAND)
    has_ref   = any(r in t for r in _REF)
    has_watch = any(w in t for w in _WATCH)
    return has_brand and (has_ref or has_watch)


class Monitor:
    def __init__(self, db: Database, notifier: Notifier):
        self.db = db
        self.notifier = notifier
        self._threads = []

    def start(self, scrapers: List[BaseScraper], stop_event: threading.Event):
        for scraper in scrapers:
            if not scraper.enabled:
                logger.info("Scraper %s is disabled, skipping", scraper.name)
                continue
            t = threading.Thread(
                target=self._run_loop,
                args=(scraper, stop_event),
                name=f"scraper-{scraper.name}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
            logger.info("Started scraper: %s (interval=%ds)", scraper.name, scraper.interval)

    def _run_loop(self, scraper: BaseScraper, stop_event: threading.Event):
        # Stagger startup so all scrapers don't hammer servers simultaneously
        jitter = random.uniform(0, 60)
        logger.debug("%s: startup jitter %.1fs", scraper.name, jitter)
        if stop_event.wait(jitter):
            return

        while True:
            self._poll_once(scraper)
            if stop_event.wait(scraper.interval):
                break

    def _poll_once(self, scraper: BaseScraper):
        t_start = time.time()
        try:
            listings = scraper.fetch()
        except Exception as e:
            logger.error("Scraper %s raised unexpectedly: %s", scraper.name, e)
            self.db.update_source_status(scraper.name, success=False, error=str(e))
            return

        relevant = [l for l in listings if _is_relevant(l.title)]
        dropped = len(listings) - len(relevant)
        if dropped:
            logger.debug("%s: dropped %d irrelevant results", scraper.name, dropped)

        new_count = 0
        for listing in relevant:
            try:
                is_new = self.db.insert_listing(listing)
                if is_new:
                    self.notifier.enqueue(listing)
                    new_count += 1
            except Exception as e:
                logger.error("DB insert error for %s: %s", scraper.name, e)

        duration = time.time() - t_start
        self.db.update_source_status(
            scraper.name,
            success=True,
            new_count=new_count,
        )
        if new_count:
            logger.info(
                "%s: %d listings checked, %d NEW (%.1fs)",
                scraper.name, len(listings), new_count, duration,
            )
        else:
            logger.debug(
                "%s: %d listings, 0 new (%.1fs)",
                scraper.name, len(listings), duration,
            )
