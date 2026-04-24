import json
import logging
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_TERMS = [
    "B15427",
    "B15428",
    "オリエント B15427",
    "オリエント 左右非対称",
    "orient fuori verso",
    "フォーリヴェルソ",
]

EXTRA_HEADERS = {
    "Accept-Language": "ja,en-US;q=0.8",
    "Referer": "https://jp.mercari.com/",
}


class MercariScraper(BaseScraper):
    name = "mercari"
    tier = 2

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            qs = urllib.parse.urlencode({"keyword": term, "status": "on_sale"})
            url = f"https://jp.mercari.com/search?{qs}"
            try:
                html = self._http_get(url, extra_headers=EXTRA_HEADERS).decode("utf-8", errors="replace")
                items = (
                    self._extract_next_data(html, term)
                    or self._extract_html(html, term)
                )
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        results.append(item)
            except Exception as e:
                logger.warning("mercari %r failed: %s", term, e)
            self._polite_delay(5.0, 12.0)

        logger.info("mercari: fetched %d listings", len(results))
        return results

    def _extract_next_data(self, html: str, term: str) -> List[Listing]:
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        listings = []
        # Traverse: props.pageProps.items or similar
        items = _deep_find_items(data)
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("itemName") or item.get("title") or ""
            item_id = item.get("id") or item.get("itemId") or ""
            url = item.get("url") or (f"https://jp.mercari.com/item/{item_id}" if item_id else "")
            price = item.get("price")
            price_str = f"¥{price:,}" if isinstance(price, int) else str(price or "")
            if name and url:
                listings.append(Listing(
                    source="mercari", title=name, url=url,
                    price=price_str or None, search_term=term,
                ))
        return listings

    def _extract_html(self, html: str, term: str) -> List[Listing]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        for a in soup.find_all("a", href=re.compile(r"/item/m\w+")):
            href = a["href"]
            url = href if href.startswith("http") else "https://jp.mercari.com" + href
            title = a.get_text(strip=True)
            if not title:
                img = a.find("img")
                title = img.get("alt", "") if img else ""
            if title:
                listings.append(Listing(
                    source="mercari", title=title, url=url,
                    search_term=term,
                ))
        return listings


def _deep_find_items(obj, depth=0):
    if depth > 8:
        return []
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        keys = obj[0].keys()
        if any(k in keys for k in ("id", "itemId", "name", "itemName", "price")):
            return obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("items", "itemsList", "searchResult", "data") and isinstance(v, list):
                return v
            result = _deep_find_items(v, depth + 1)
            if result:
                return result
    return []
