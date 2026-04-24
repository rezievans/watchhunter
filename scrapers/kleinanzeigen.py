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
    "orient asymmetrisch",
    "orient dent",
]


class KleinanzeigenScraper(BaseScraper):
    name = "kleinanzeigen"
    tier = 2

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            slug = term.lower().replace(" ", "-").replace("/", "-")
            url = f"https://www.kleinanzeigen.de/s-anzeigen/{urllib.parse.quote(slug)}/k0"
            try:
                html = self._http_get(url, extra_headers={
                    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                    "Referer": "https://www.kleinanzeigen.de/",
                }).decode("utf-8", errors="replace")
                items = self._extract(html, term)
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        results.append(item)
            except Exception as e:
                logger.warning("kleinanzeigen %r failed: %s", term, e)
            self._polite_delay(3.0, 8.0)

        logger.info("kleinanzeigen: fetched %d listings", len(results))
        return results

    def _extract(self, html: str, term: str) -> List[Listing]:
        # Try __NEXT_DATA__ / window state injection
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                listings = self._parse_next(data, term)
                if listings:
                    return listings
            except json.JSONDecodeError:
                pass

        # Try window.__SETTINGS__  or similar patterns Kleinanzeigen uses
        m = re.search(r'window\.__listings__\s*=\s*(\[.*?\])\s*;', html, re.DOTALL)
        if m:
            try:
                ads = json.loads(m.group(1))
                return self._ads_to_listings(ads, term)
            except json.JSONDecodeError:
                pass

        # HTML fallback
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        for article in soup.find_all("article", class_=re.compile(r"aditem", re.I)):
            a = article.find("a", href=re.compile(r"/s-anzeige/"))
            if not a:
                continue
            href = a["href"]
            url = href if href.startswith("http") else "https://www.kleinanzeigen.de" + href
            title_el = article.find(class_=re.compile(r"ellipsis|title|text", re.I))
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
            price_el = article.find(class_=re.compile(r"price|Price"))
            price = price_el.get_text(strip=True) if price_el else None
            if title and len(title) > 3:
                listings.append(Listing(
                    source="kleinanzeigen", title=title, url=url,
                    price=price, search_term=term,
                ))
        return listings

    def _parse_next(self, data: dict, term: str) -> List[Listing]:
        ads = _deep_find_ads(data)
        return self._ads_to_listings(ads, term)

    def _ads_to_listings(self, ads: list, term: str) -> List[Listing]:
        listings = []
        for ad in ads:
            if not isinstance(ad, dict):
                continue
            title = ad.get("title") or ad.get("name") or ad.get("subject") or ""
            ad_id = ad.get("id") or ad.get("adId") or ""
            url = ad.get("url") or ad.get("link") or (
                f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}" if ad_id else ""
            )
            price = ad.get("price") or ad.get("priceLabel") or ""
            if title and url:
                listings.append(Listing(
                    source="kleinanzeigen", title=title, url=url,
                    price=str(price) or None, search_term=term,
                ))
        return listings


def _deep_find_ads(obj, depth=0):
    if depth > 8:
        return []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("ads", "items", "results", "listings", "adsList") and isinstance(v, list):
                return v
            result = _deep_find_ads(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("title", "adId", "id", "url")):
            return obj
    return []
