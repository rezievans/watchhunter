import json
import logging
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_TERMS = ["orient fuori verso", "B15427", "orient asymmetric vintage"]


class CatawikiScraper(BaseScraper):
    name = "catawiki"
    tier = 2

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        for term in SEARCH_TERMS:
            qs = urllib.parse.urlencode({"q": term})
            url = f"https://www.catawiki.com/en/l/watches?{qs}"
            try:
                html = self._http_get(url, extra_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                }).decode("utf-8", errors="replace")
                items = self._extract_data(html, term)
                for item in items:
                    if item.url not in seen_urls:
                        seen_urls.add(item.url)
                        results.append(item)
            except Exception as e:
                logger.warning("catawiki %r failed: %s", term, e)
            self._polite_delay(3.0, 8.0)

        logger.info("catawiki: fetched %d listings", len(results))
        return results

    def _extract_data(self, html: str, term: str) -> List[Listing]:
        # Catawiki embeds state in window.__INITIAL_STATE__
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});\s*</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                return self._parse_state(data, term)
            except json.JSONDecodeError:
                pass

        # Fallback: __NEXT_DATA__
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                return self._parse_state(data, term)
            except json.JSONDecodeError:
                pass

        # HTML fallback
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []
        for a in soup.find_all("a", href=re.compile(r"/en/l/\w+-\d+|/en/a/\d+")):
            href = a["href"]
            url = href if href.startswith("http") else "https://www.catawiki.com" + href
            title = a.get_text(strip=True)
            if title and len(title) > 5:
                listings.append(Listing(
                    source="catawiki", title=title, url=url, search_term=term,
                ))
        return listings

    def _parse_state(self, data: dict, term: str) -> List[Listing]:
        listings = []
        lots = _deep_find_lots(data)
        for lot in lots:
            if not isinstance(lot, dict):
                continue
            title = lot.get("title") or lot.get("name") or lot.get("lotTitle") or ""
            lot_id = lot.get("id") or lot.get("lotId") or ""
            url = lot.get("url") or lot.get("lotUrl") or (
                f"https://www.catawiki.com/en/l/{lot_id}" if lot_id else ""
            )
            bid = lot.get("currentBid") or lot.get("startingBid") or lot.get("price")
            price = f"€{bid}" if bid else None
            if title and url:
                listings.append(Listing(
                    source="catawiki", title=title, url=url,
                    price=price, search_term=term,
                ))
        return listings


def _deep_find_lots(obj, depth=0):
    if depth > 7:
        return []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("lots", "items", "results", "lots_list") and isinstance(v, list):
                return v
            result = _deep_find_lots(v, depth + 1)
            if result:
                return result
    return []
