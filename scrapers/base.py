import hashlib
import logging
import random
import time
import urllib.request
import urllib.parse
import gzip
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
]


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@dataclass
class Listing:
    source: str
    title: str
    url: str
    price: Optional[str] = None
    search_term: Optional[str] = None
    found_at: str = field(default_factory=utcnow_iso)

    @property
    def hash(self):
        raw = (self.source + ":" + self.url).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def __repr__(self):
        return f"Listing({self.source!r}, {self.title[:50]!r}, {self.price!r})"


class BaseScraper(ABC):
    name: str = ""
    tier: int = 1

    def __init__(self, config: dict):
        self.config = config
        scraper_cfg = config.get("scrapers", {}).get(self.name, {})
        self.enabled = scraper_cfg.get("enabled", True)
        self.interval = scraper_cfg.get("interval_seconds", 1800)
        self.min_delay = scraper_cfg.get("min_delay", 1.5)
        self.max_delay = scraper_cfg.get("max_delay", 4.5)
        self.timeout = scraper_cfg.get("timeout", 20)
        self.max_retries = 3

    @abstractmethod
    def fetch(self) -> List[Listing]:
        pass

    def _http_get(self, url: str, extra_headers: dict = None, timeout: int = None) -> bytes:
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if extra_headers:
            headers.update(extra_headers)

        t = timeout or self.timeout
        last_err = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=t) as resp:
                    data = resp.read()
                    if resp.info().get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    return data
            except Exception as e:
                last_err = e
                status = getattr(e, "code", None)
                if status in (429, 503):
                    wait = (2 ** attempt) * 2
                    logger.warning("%s: rate limited (%s), waiting %ds", self.name, status, wait)
                    time.sleep(wait)
                elif status and 400 <= status < 500:
                    # 4xx other than 429: don't retry
                    raise
                else:
                    time.sleep(2 ** attempt)
        raise last_err

    def _parse_rss(self, xml_bytes: bytes) -> List[dict]:
        """Parse RSS 2.0 or Atom 1.0. Returns list of {title, link, description}."""
        items = []
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            logger.warning("%s: RSS parse error: %s", self.name, e)
            return items

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # Atom
        for entry in root.findall(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            content_el = entry.find("atom:content", ns) or entry.find("atom:summary", ns)
            if link_el is not None:
                link = link_el.get("href") or link_el.text or ""
                items.append({
                    "title": (title_el.text or "") if title_el is not None else "",
                    "link": link.strip(),
                    "description": (content_el.text or "") if content_el is not None else "",
                })
        if items:
            return items

        # RSS 2.0
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            link = (link_el.text or "").strip() if link_el is not None else ""
            items.append({
                "title": (title_el.text or "").strip() if title_el is not None else "",
                "link": link,
                "description": (desc_el.text or "").strip() if desc_el is not None else "",
            })
        return items

    def _polite_delay(self, min_s: float = None, max_s: float = None):
        mn = min_s if min_s is not None else self.min_delay
        mx = max_s if max_s is not None else self.max_delay
        time.sleep(random.uniform(mn, mx))

    def _log_error(self, msg: str, exc: Exception = None):
        if exc:
            logger.error("%s: %s — %s", self.name, msg, exc)
        else:
            logger.error("%s: %s", self.name, msg)
