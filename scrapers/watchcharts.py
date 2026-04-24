import json
import logging
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_TERMS = ["fuori verso", "B15427", "B15428", "orient asymmetric"]


class WatchChartsScraper(BaseScraper):
    name = "watchcharts"
    tier = 1

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            url = "https://marketplace.watchcharts.com/search?" + urllib.parse.urlencode({"q": term})
            try:
                html = self._http_get(url).decode("utf-8", errors="replace")
                listings = self._extract_next_data(html, term) or self._extract_html(html, term)
                for listing in listings:
                    if listing.url not in seen_urls:
                        seen_urls.add(listing.url)
                        results.append(listing)
            except Exception as e:
                logger.warning("watchcharts %r failed: %s", term, e)
            self._polite_delay()

        logger.info("watchcharts: fetched %d listings", len(results))
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
        # Try common Next.js page props paths
        page_props = (
            data.get("props", {}).get("pageProps", {})
        )
        raw_listings = (
            page_props.get("listings")
            or page_props.get("results")
            or page_props.get("items")
            or []
        )
        # Also try searching nested dicts for arrays that look like listings
        if not raw_listings:
            raw_listings = _deep_find_listings(data)

        for item in raw_listings:
            if not isinstance(item, dict):
                continue
            title = (
                item.get("title") or item.get("name") or
                item.get("watchName") or item.get("watch_name") or ""
            )
            price_raw = item.get("price") or item.get("askingPrice") or item.get("asking_price")
            price = f"${price_raw}" if isinstance(price_raw, (int, float)) else str(price_raw or "")
            listing_id = item.get("id") or item.get("listingId") or item.get("listing_id")
            url = (
                item.get("url") or item.get("link") or
                (f"https://marketplace.watchcharts.com/listings/{listing_id}" if listing_id else None)
            )
            if title and url:
                listings.append(Listing(
                    source="watchcharts",
                    title=title,
                    url=url,
                    price=price or None,
                    search_term=term,
                ))
        return listings

    def _extract_html(self, html: str, term: str) -> List[Listing]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        # WatchCharts listing cards typically have an anchor with /listings/ in href
        for a in soup.find_all("a", href=re.compile(r"/listings/\d+")):
            href = a.get("href", "")
            url = href if href.startswith("http") else "https://marketplace.watchcharts.com" + href
            # Title: look for a heading or the link's text
            title = a.get_text(strip=True) or ""
            if len(title) < 3:
                parent = a.find_parent()
                if parent:
                    title = parent.get_text(" ", strip=True)[:150]
            price_el = a.find_parent() and a.find_parent().find(
                string=re.compile(r"[\$€£¥]\s*[\d,]+")
            )
            price = str(price_el).strip() if price_el else None
            if title:
                listings.append(Listing(
                    source="watchcharts",
                    title=title,
                    url=url,
                    price=price,
                    search_term=term,
                ))
        return listings


def _deep_find_listings(obj, depth=0):
    if depth > 6:
        return []
    if isinstance(obj, list) and len(obj) > 0 and isinstance(obj[0], dict):
        if any(k in obj[0] for k in ("title", "name", "watchName", "price", "listingId")):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            result = _deep_find_listings(v, depth + 1)
            if result:
                return result
    return []
