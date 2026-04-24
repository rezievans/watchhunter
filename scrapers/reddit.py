import logging
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

QUERY_BATCHES = [
    '"fuori verso" OR "fouri verso" OR "fuori verse" OR "B15427" OR "B15428"',
    '"fuoriverso" OR "orient dent" OR "orient bent" OR "orient crash" OR "B15427-10"',
    '"fuori versa" OR "B15428-10" OR "orient asymmetric" OR "orient b15427" OR "orient b15428"',
]

SUBREDDITS = [
    "r/Watchexchange",
    "r/WatchExchangeEurope",
    "r/WatchExchangeAsia",
    "r/OrientWatches",
    "r/Watches",
    "r/JapaneseWatches",
    "r/AffordableWatches",
]


class RedditScraper(BaseScraper):
    name = "reddit"
    tier = 1

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        # Global search RSS
        for query in QUERY_BATCHES:
            url = "https://www.reddit.com/search.rss?" + urllib.parse.urlencode({
                "q": query,
                "sort": "new",
                "t": "month",
                "limit": "25",
            })
            try:
                xml = self._http_get(url, extra_headers={
                    "User-Agent": "WatchHunterBot/1.0 (personal use; orient fuori verso search)",
                })
                items = self._parse_rss(xml)
                for item in items:
                    link = item["link"]
                    title = item["title"]
                    if not link or link in seen_urls:
                        continue
                    seen_urls.add(link)
                    results.append(Listing(
                        source="reddit",
                        title=title,
                        url=link,
                        search_term=query[:40],
                    ))
            except Exception as e:
                logger.warning("reddit global search failed: %s", e)
            self._polite_delay(2.0, 5.0)

        # Subreddit-specific RSS for highest-value subs
        for sub in SUBREDDITS[:3]:
            url = f"https://www.reddit.com/{sub}/new.rss?limit=25"
            try:
                xml = self._http_get(url, extra_headers={
                    "User-Agent": "WatchHunterBot/1.0 (personal use)",
                })
                items = self._parse_rss(xml)
                keywords = ["fuori verso", "fouri verso", "b15427", "b15428",
                            "orient dent", "orient bent", "orient crash", "fuoriverso"]
                for item in items:
                    title_lower = item["title"].lower()
                    desc_lower = item.get("description", "").lower()
                    if any(kw in title_lower or kw in desc_lower for kw in keywords):
                        link = item["link"]
                        if link and link not in seen_urls:
                            seen_urls.add(link)
                            results.append(Listing(
                                source="reddit",
                                title=item["title"],
                                url=link,
                                search_term=sub,
                            ))
            except Exception as e:
                logger.warning("reddit %s RSS failed: %s", sub, e)
            self._polite_delay(2.0, 5.0)

        logger.info("reddit: fetched %d listings", len(results))
        return results
