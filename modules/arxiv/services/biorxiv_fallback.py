"""Europe PMC metadata fallback for bioRxiv. It is not an official-version checkpoint."""
import re
import time
from datetime import date
from html import unescape

import httpx

from modules.arxiv.services.biorxiv_crawler import BiorxivCrawler, BiorxivAPIError

EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def plain_text(value):
    return unescape(re.sub(r"<[^>]*>", " ", value or "")).strip()


class BiorxivEuropePMCCrawler(BiorxivCrawler):
    def crawl_date_range(self, date_from: date, date_to: date, batch_delay=None):
        # Index-date overlap also catches papers deposited before their indexing date.
        interval = f"[{date_from.isoformat()} TO {date_to.isoformat()}]"
        query = f'SRC:PPR AND PUBLISHER:bioRxiv AND (FIRST_PDATE:{interval} OR FIRST_IDATE:{interval})'
        cursor, seen_cursors, seen_ids = "*", set(), set()
        result, total, received = [], None, 0
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "SportsMatter/1.0 (+https://sports-matter.com)"}) as client:
            while True:
                data = None
                for attempt in range(3):
                    try:
                        response = client.get(EUROPE_PMC_SEARCH, params={"query": query, "format": "json", "resultType": "core", "pageSize": 100, "cursorMark": cursor})
                        response.raise_for_status()
                        data = response.json()
                        if not isinstance(data, dict) or "hitCount" not in data or "resultList" not in data:
                            raise ValueError("Missing Europe PMC result metadata")
                        items = data["resultList"].get("result")
                        if not isinstance(items, list) or int(data["hitCount"]) < 0:
                            raise ValueError("Invalid Europe PMC result set")
                        break
                    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                        if attempt == 2 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429):
                            raise BiorxivAPIError(f"Europe PMC fallback unavailable: {type(exc).__name__}") from exc
                        time.sleep(2 * (attempt + 1))
                if total is None:
                    total = int(data["hitCount"])
                elif total != int(data["hitCount"]):
                    raise BiorxivAPIError("Europe PMC result total changed during pagination")
                if not items and received < total:
                    raise BiorxivAPIError("Europe PMC returned an incomplete result set")
                for item in items:
                    if item.get("id") in seen_ids or not item.get("id"):
                        raise BiorxivAPIError("Europe PMC repeated or omitted an article ID")
                    seen_ids.add(item["id"])
                    # Explicitly validate publisher; medRxiv/other PPRs must not be mislabeled.
                    publisher = item.get("bookOrReportDetails", {}).get("publisher", "")
                    if item.get("source") != "PPR" or publisher.lower() != "biorxiv":
                        raise BiorxivAPIError("Unexpected publisher in bioRxiv fallback")
                    if not item.get("doi") or not item.get("firstPublicationDate") or not item.get("abstractText"):
                        raise BiorxivAPIError("Incomplete Europe PMC metadata; do not advance checkpoint")
                    article = self._parse_record({"doi": item["doi"], "title": plain_text(item.get("title")),
                        "abstract": plain_text(item["abstractText"]), "date": item["firstPublicationDate"],
                        "authors": "; ".join(a.get("fullName", "") for a in item.get("authorList", {}).get("author", [])) or item.get("authorString", "")})
                    if article:
                        # Europe PMC does not promise the current bioRxiv version or category.
                        article["version"] = None
                        article["abs_url"] = "https://www.biorxiv.org/content/" + item["doi"]
                        article["pdf_url"] = article["abs_url"] + ".full.pdf"
                        article["_metadata_provider"] = "europe_pmc"
                        result.append(article)
                received += len(items)
                if received >= total:
                    break
                next_cursor = data.get("nextCursorMark")
                if not next_cursor or next_cursor == cursor or next_cursor in seen_cursors:
                    raise BiorxivAPIError("Europe PMC cursor did not advance")
                seen_cursors.add(cursor)
                cursor = next_cursor
                time.sleep(self.page_delay if batch_delay is None else batch_delay)
        self.raw_count = received
        return list({article["arxiv_id"]: article for article in result}.values())
