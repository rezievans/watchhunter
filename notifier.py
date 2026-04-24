import json
import logging
import queue
import threading
import time
import urllib.request
import urllib.parse
from scrapers.base import Listing

logger = logging.getLogger(__name__)

SOURCE_FLAGS = {
    "ebay.com": "🇺🇸", "ebay.it": "🇮🇹", "ebay.de": "🇩🇪",
    "ebay.co.uk": "🇬🇧", "ebay.co.jp": "🇯🇵", "ebay.fr": "🇫🇷",
    "ebay.es": "🇪🇸", "reddit": "👾", "watchcharts": "📊",
    "yahoojp": "🇯🇵", "chrono24": "🕐", "mercari": "🛒",
    "catawiki": "🏷️", "subito": "🇮🇹", "kleinanzeigen": "🇩🇪",
}


class Notifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self._queue = queue.Queue()
        self._base_url = f"https://api.telegram.org/bot{token}"

    def start_consumer_thread(self, stop_event: threading.Event):
        t = threading.Thread(
            target=self._consume,
            args=(stop_event,),
            name="notifier",
            daemon=True,
        )
        t.start()
        return t

    def enqueue(self, listing: Listing):
        self._queue.put(listing)

    def _consume(self, stop_event: threading.Event):
        while not stop_event.is_set():
            try:
                listing = self._queue.get(timeout=1.0)
                self._send(listing)
                time.sleep(1.1)  # stay within Telegram's 1 msg/sec limit
            except queue.Empty:
                continue
            except Exception as e:
                logger.error("Notifier consume error: %s", e)

    def _build_message(self, listing: Listing) -> str:
        flag = SOURCE_FLAGS.get(listing.source, "🔔")
        price_line = f"Price: {listing.price}\n" if listing.price else ""
        term_line = f"Term: <code>{listing.search_term}</code>\n" if listing.search_term else ""
        title_escaped = listing.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f"{flag} <b>NEW LISTING — {listing.source.upper()}</b>\n"
            f"{term_line}"
            f"Title: {title_escaped}\n"
            f"{price_line}"
            f'<a href="{listing.url}">View Listing →</a>\n'
            f"Found: {listing.found_at}"
        )

    def _send(self, listing: Listing):
        text = self._build_message(listing)
        ok = self._telegram_post("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })
        if ok:
            logger.info("Notified: %s — %s", listing.source, listing.title[:60])
        else:
            logger.error("FAILED to send Telegram notification for: %s — %s", listing.source, listing.title[:60])

    def send_text(self, text: str):
        self._telegram_post("sendMessage", {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        })

    def send_startup_message(self):
        self.send_text(
            "🟢 <b>WatchHunter started</b>\n"
            "Monitoring for Orient Fuori Verso (B15427 / B15428) across eBay, Reddit, "
            "WatchCharts, Yahoo Japan, Chrono24, Mercari and more.\n"
            "Dashboard: <code>http://localhost:5000</code>"
        )

    def send_shutdown_message(self):
        self.send_text("🔴 <b>WatchHunter stopped.</b>")

    def _telegram_post(self, method: str, payload: dict) -> bool:
        url = f"{self._base_url}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read())
                    if result.get("ok"):
                        return True
                    logger.error("Telegram API error: %s", result)
                    return False
            except Exception as e:
                logger.warning("Telegram POST attempt %d failed: %s", attempt + 1, e)
                time.sleep(2 ** attempt)
        return False
