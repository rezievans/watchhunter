import json
import logging
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_TERMS = ["orient fuori verso", "B15427", "B15428", "orient asymmetric gold"]


class Chrono24Scraper(BaseScraper):
    name = "chrono24"
    tier = 1

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            qs = urllib.parse.urlencode({"query": term, "sortorder": "5"})
            url = f"https://www.chrono24.com/search/index.htm?{qs}"
            try:
                html = self._http_get(url, extra_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                }).decode("utf-8", errors="replace")
                items = (
                    self._extract_json_ld(html, term)
                    or self._extract_next_data(html, term)
                    or self._extract_html(html, term)
                )
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        results.append(item)
            except Exception as e:
                logger.warning("chrono24 %r failed: %s", term, e)
            self._polite_delay(4.0, 9.0)

        logger.info("chrono24: fetched %d listings", len(results))
        return results

    def _extract_json_ld(self, html: str, term: str) -> List[Listing]:
        blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        listings = []
        for block in blocks:
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            items = []
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                items = data.get("itemListElement", [])
            elif isinstance(data, list):
                items = data
            for item in items:
                if isinstance(item, dict):
                    offer = item.get("item") or item
                    name = offer.get("name") or offer.get("title") or ""
                    url = offer.get("url") or offer.get("@id") or ""
                    price_info = offer.get("offers") or {}
                    price = str(price_info.get("price", "")) if isinstance(price_info, dict) else ""
                    currency = price_info.get("priceCurrency", "") if isinstance(price_info, dict) else ""
                    if name and url:
                        listings.append(Listing(
                            source="chrono24",
                            title=name,
                            url=url,
                            price=f"{currency} {price}".strip() or None,
                            search_term=term,
                        ))
        return listings

    def _extract_next_data(self, html: str, term: str) -> List[Listing]:
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        listings = []
        articles = _deep_find_list(data, ("articles", "listings", "results", "items"))
        for a in articles:
            if not isinstance(a, dict):
                continue
            name = a.get("name") or a.get("title") or ""
            url = a.get("url") or a.get("detailUrl") or ""
            if not url.startswith("http"):
                url = "https://www.chrono24.com" + url
            price = str(a.get("price") or a.get("priceFormatted") or "")
            if name and url:
                listings.append(Listing(
                    source="chrono24", title=name, url=url,
                    price=price or None, search_term=term,
                ))
        return listings

    def _extract_html(self, html: str, term: str) -> List[Listing]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        for article in soup.find_all("article", class_=re.compile(r"article-item|wsp-", re.I)):
            a = article.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            url = href if href.startswith("http") else "https://www.chrono24.com" + href
            title_el = article.find(class_=re.compile(r"text-bold|article-title|name", re.I))
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
            price_el = article.find(class_=re.compile(r"price|Price"))
            price = price_el.get_text(strip=True) if price_el else None
            if title:
                listings.append(Listing(
                    source="chrono24", title=title, url=url,
                    price=price, search_term=term,
                ))
        return listings


def _deep_find_list(obj, keys, depth=0):
    if depth > 7:
        return []
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and isinstance(obj[k], list):
                return obj[k]
        for v in obj.values():
            result = _deep_find_list(v, keys, depth + 1)
            if result:
                return result
    return []
