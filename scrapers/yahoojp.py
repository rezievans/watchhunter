import logging
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_TERMS = [
    "オリエント B15427",
    "オリエント B15428",
    "ORIENT B15427",
    "ORIENT B15428",
    "オリエント 左右非対称 時計",
    "オリエント クラッシュ 時計",
    "オリエント フォーリヴェルソ",
    "orient fuori verso",
]

EXTRA_HEADERS = {
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    "Referer": "https://auctions.yahoo.co.jp/",
}


class YahooJpScraper(BaseScraper):
    name = "yahoojp"
    tier = 1

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            qs = urllib.parse.urlencode({
                "p": term,
                "va": term,
                "exflg": "1",
                "b": "1",
                "n": "20",
                "mode": "1",
            })
            url = f"https://auctions.yahoo.co.jp/search/search?{qs}"
            try:
                html = self._http_get(url, extra_headers=EXTRA_HEADERS).decode("utf-8", errors="replace")
                items = self._parse_html(html, term)
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        results.append(item)
            except Exception as e:
                logger.warning("yahoojp %r failed: %s", term, e)
            self._polite_delay(2.0, 6.0)

        logger.info("yahoojp: fetched %d listings", len(results))
        return results

    def _parse_html(self, html: str, term: str) -> List[Listing]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # Yahoo JP search results use various class patterns
        # Try the main Product list items
        items = (
            soup.find_all("li", class_=re.compile(r"Product", re.I))
            or soup.find_all("div", class_=re.compile(r"Product", re.I))
            or soup.find_all("article")
        )

        for el in items:
            # Find title link
            a = (
                el.find("a", class_=re.compile(r"title|name", re.I))
                or el.find("a", href=re.compile(r"page\.auctions\.yahoo\.co\.jp|aucview"))
            )
            if not a:
                a = el.find("a")
            if not a:
                continue

            title = a.get_text(strip=True) or el.get_text(" ", strip=True)[:120]
            href = a.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else "https://auctions.yahoo.co.jp" + href

            # Find price
            price_el = el.find(class_=re.compile(r"price|Price"))
            price = price_el.get_text(strip=True) if price_el else None

            if title and len(title) > 3:
                listings.append(Listing(
                    source="yahoojp",
                    title=title,
                    url=url,
                    price=price,
                    search_term=term,
                ))

        return listings
