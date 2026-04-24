import json
import logging
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_TERMS = [
    "orient fuori verso",
    "B15427",
    "B15428",
    "orologio orient asimmetrico",
    "orient dent",
]


class SubitoScraper(BaseScraper):
    name = "subito"
    tier = 2

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            qs = urllib.parse.urlencode({
                "q": term,
                "sort": "datedesc",
                "shp": "true",
            })
            url = f"https://www.subito.it/annunci-italia/vendita/usato/?{qs}"
            try:
                html = self._http_get(url, extra_headers={
                    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
                    "Referer": "https://www.subito.it/",
                }).decode("utf-8", errors="replace")
                items = self._extract(html, term)
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        results.append(item)
            except Exception as e:
                logger.warning("subito %r failed: %s", term, e)
            self._polite_delay(3.0, 8.0)

        logger.info("subito: fetched %d listings", len(results))
        return results

    def _extract(self, html: str, term: str) -> List[Listing]:
        # Subito.it uses Next.js — try __NEXT_DATA__ first
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                listings = self._parse_next(data, term)
                if listings:
                    return listings
            except json.JSONDecodeError:
                pass

        # HTML fallback
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        for a in soup.find_all("a", href=re.compile(r"\.subito\.it/\w+/\w+/annunci/")):
            href = a["href"]
            url = href if href.startswith("http") else "https://www.subito.it" + href
            title = a.get_text(strip=True)
            if not title:
                img = a.find("img")
                title = img.get("alt", "") if img else ""
            if title and len(title) > 3:
                listings.append(Listing(
                    source="subito", title=title, url=url, search_term=term,
                ))
        return listings

    def _parse_next(self, data: dict, term: str) -> List[Listing]:
        listings = []
        # ads are typically in pageProps.initialState.adsList.data
        ads = _deep_find(data, ("adsList", "ads", "items", "results", "data"))
        for ad in ads:
            if not isinstance(ad, dict):
                continue
            title = ad.get("subject") or ad.get("title") or ad.get("name") or ""
            url = ad.get("urls", {}).get("default") if isinstance(ad.get("urls"), dict) else None
            url = url or ad.get("url") or ad.get("link") or ""
            if not url.startswith("http"):
                url = "https://www.subito.it" + url
            price_info = ad.get("prices") or {}
            price = None
            if isinstance(price_info, dict):
                p = price_info.get("EUR") or next(iter(price_info.values()), None)
                if isinstance(p, dict):
                    price = f"€{p.get('value', '')}"
            if title and url:
                listings.append(Listing(
                    source="subito", title=title, url=url,
                    price=price, search_term=term,
                ))
        return listings


def _deep_find(obj, keys, depth=0):
    if depth > 8:
        return []
    if isinstance(obj, dict):
        for k in keys:
            if k in obj:
                v = obj[k]
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    result = _deep_find(v, keys, depth + 1)
                    if result:
                        return result
        for v in obj.values():
            if isinstance(v, (dict, list)):
                result = _deep_find(v, keys, depth + 1)
                if result:
                    return result
    elif isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("subject", "title", "url", "urls")):
            return obj
    return []
