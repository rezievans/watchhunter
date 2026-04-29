import logging
import re
import urllib.parse
from typing import List

from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    'site:instagram.com "fuori verso"',
    'site:instagram.com "orient fuori verso"',
    'site:instagram.com "B15427" orient',
    'site:instagram.com "B15428" orient',
    'site:instagram.com "orient asymmetric" watch',
]


class InstagramScraper(BaseScraper):
    name = "instagram"
    tier = 2

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls: set = set()

        for query in SEARCH_QUERIES:
            try:
                listings = self._search_ddg(query)
                for l in listings:
                    if l.url not in seen_urls:
                        seen_urls.add(l.url)
                        results.append(l)
            except Exception as e:
                logger.warning("instagram %r failed: %s", query, e)
            self._polite_delay(5.0, 12.0)

        logger.info("instagram: fetched %d listings", len(results))
        return results

    def _search_ddg(self, query: str) -> List[Listing]:
        qs = urllib.parse.urlencode({"q": query, "kl": "wt-wt"})
        url = f"https://html.duckduckgo.com/html/?{qs}"
        html = self._http_get(url, extra_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://duckduckgo.com/",
        }).decode("utf-8", errors="replace")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        for result in soup.find_all("div", class_=re.compile(r"result")):
            a = result.find("a", class_=re.compile(r"result__a"))
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            actual_url = self._unwrap_ddg_url(href)
            if not actual_url or "instagram.com" not in actual_url:
                continue
            # Only posts/reels, not profile pages
            if not any(p in actual_url for p in ("/p/", "/reel/", "/tv/")):
                continue
            snippet_el = result.find("a", class_=re.compile(r"result__snippet")) \
                      or result.find("span", class_=re.compile(r"result__snippet"))
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            full_title = f"{title} — {snippet}" if snippet else title
            listings.append(Listing(
                source="instagram",
                title=full_title,
                url=actual_url,
                search_term=query,
            ))

        return listings

    def _unwrap_ddg_url(self, href: str) -> str:
        if not href:
            return ""
        if "uddg=" in href:
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                url = urllib.parse.unquote(m.group(1))
                return self._normalize_ig_url(url)
        if href.startswith("http"):
            return self._normalize_ig_url(href)
        return ""

    def _normalize_ig_url(self, url: str) -> str:
        # Strip query params and trailing slashes so same post always hashes the same
        parsed = urllib.parse.urlparse(url)
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        return clean
