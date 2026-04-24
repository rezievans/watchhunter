import logging
import random
import re
import urllib.parse
from typing import List
from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

# TLD → (sacat for named terms, sacat for ref-number terms)
TLDS = ["com", "it", "de", "co.uk", "co.jp", "fr", "es"]

# Name-based terms use sacat=0 (all categories) — the listing might be in Collectibles
NAME_TERMS = [
    "orient fuori verso",
    "orient fouri verso",
    "orient fuori verse",
    "orient fuori versa",
    "fuoriverso orient",
    "orient dent watch",
    "orient bent watch",
    "orient crash watch",
]

# Always pair ref numbers with "orient" so bare part-numbers don't match
REF_TERMS = [
    "orient B15427",
    "orient B15428",
    "orient B15427-10",
    "orient B15428-10",
]


def _rss_url(tld: str, term: str, sacat: int) -> str:
    encoded = urllib.parse.quote_plus(term)
    return f"https://www.ebay.{tld}/sch/i.html?_nkw={encoded}&_rss=1&_sacat={sacat}&_sop=10"


def _extract_price(description: str) -> str:
    m = re.search(r"([\$€£¥￥]\s*[\d,]+\.?\d*)", description)
    return m.group(1).strip() if m else None


class EbayScraper(BaseScraper):
    name = "ebay"
    tier = 1

    def fetch(self) -> List[Listing]:
        results = []
        seen_urls = set()

        # Build work list: (tld, term, sacat)
        work = []
        for tld in TLDS:
            for term in NAME_TERMS:
                work.append((tld, term, 0))
            for term in REF_TERMS:
                work.append((tld, term, 281))

        random.shuffle(work)

        for tld, term, sacat in work:
            source = f"ebay.{tld}"
            url = _rss_url(tld, term, sacat)
            try:
                xml = self._http_get(url)
                items = self._parse_rss(xml)
                for item in items:
                    link = item["link"]
                    title = item["title"]
                    if not link or not title:
                        continue
                    if link in seen_urls:
                        continue
                    seen_urls.add(link)
                    price = _extract_price(item.get("description", ""))
                    results.append(Listing(
                        source=source,
                        title=title,
                        url=link,
                        price=price,
                        search_term=term,
                    ))
            except Exception as e:
                logger.warning("ebay.%s %r failed: %s", tld, term, e)

            self._polite_delay()

        logger.info("ebay: fetched %d listings across %d TLDs", len(results), len(TLDS))
        return results
