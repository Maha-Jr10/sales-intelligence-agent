"""
Search Google News RSS and Yahoo News RSS for company mentions.

Usage:
    python tools/search_news.py --query "Stripe" --company-id stripe
    python tools/search_news.py --company-id stripe --max-age-days 7
    python tools/search_news.py --companies-file data/companies.json --output-dir .tmp/raw_signals/

Exit codes: 0 success, 1 partial errors, 2 fatal
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_feed_date(entry) -> str | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            import calendar
            ts = calendar.timegm(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return None


def search_google_news(query: str, max_age_days: int = 7) -> list:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; RSS Reader)"}
    items = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        d = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        for entry in d.entries:
            pub_str = _parse_feed_date(entry)
            if pub_str:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt < cutoff:
                    continue
            summary = getattr(entry, "summary", "")
            source_tag = getattr(entry, "source", {})
            source_name = source_tag.get("title", "") if isinstance(source_tag, dict) else ""
            items.append({
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", "").strip(),
                "published": pub_str,
                "snippet": re.sub(r"<[^>]+>", "", summary)[:300],
                "source_name": source_name,
                "news_source": "google_news_rss",
            })
    except Exception as e:
        print(f"[search_news] google_news error: {e}", file=sys.stderr)
    return items


def search_yahoo_news(query: str, max_age_days: int = 7) -> list:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://news.search.yahoo.com/news/rss?p={encoded}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; RSS Reader)"}
    items = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        d = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        for entry in d.entries:
            pub_str = _parse_feed_date(entry)
            if pub_str:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt < cutoff:
                    continue
            summary = getattr(entry, "summary", "")
            items.append({
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", "").strip(),
                "published": pub_str,
                "snippet": re.sub(r"<[^>]+>", "", summary)[:300],
                "source_name": "",
                "news_source": "yahoo_news_rss",
            })
    except Exception as e:
        print(f"[search_news] yahoo_news error: {e}", file=sys.stderr)
    return items


def deduplicate(items: list) -> list:
    seen_urls = set()
    seen_titles = set()
    unique = []
    for item in items:
        url_key = item.get("url", "").split("?")[0].rstrip("/")
        title_key = re.sub(r"\W+", "", item.get("title", "").lower())[:40]
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(item)
    return unique


def extract_signal_keywords(item: dict, signal_weights_path: str = "data/signal_weights.json") -> list:
    try:
        with open(signal_weights_path, encoding="utf-8") as f:
            weights = json.load(f)
        keywords = []
        text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
        for signal_type, kw_list in weights.get("signal_type_keywords", {}).items():
            for kw in kw_list:
                if kw.lower() in text:
                    keywords.append(kw)
        return list(set(keywords))
    except Exception:
        return []


def search_company(company_id: str, company_name: str, max_age_days: int,
                   output_dir: str = None) -> dict:
    print(f"[search_news] searching news for: {company_name}", file=sys.stderr)

    google_items = search_google_news(company_name, max_age_days)
    time.sleep(1)
    yahoo_items = search_yahoo_news(company_name, max_age_days)

    raw = google_items + yahoo_items
    items = deduplicate(raw)

    for item in items:
        item["company_id"] = company_id
        item["relevance_keywords"] = extract_signal_keywords(item)

    result = {
        "company_id": company_id,
        "query": company_name,
        "fetched_at": _now(),
        "total_found": len(items),
        "items": items,
    }

    if output_dir and company_id:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"news_{company_id}_{today}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="Search news for company mentions via free RSS sources")
    parser.add_argument("--query", help="Search query (company name)")
    parser.add_argument("--company-id", help="Company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", help="Directory to write per-company output files")
    parser.add_argument("--max-age-days", type=int, default=7)
    args = parser.parse_args()

    all_results = []

    if args.query:
        company_id = args.company_id or "unknown"
        result = search_company(company_id, args.query, args.max_age_days, args.output_dir)
        all_results.append(result)
    elif args.company_id:
        with open(args.companies_file, encoding="utf-8") as f:
            companies_data = json.load(f)
        company = next((c for c in companies_data["companies"] if c["id"] == args.company_id), None)
        if not company:
            print(json.dumps({"error": f"company_id '{args.company_id}' not found", "fetched_at": _now()}))
            sys.exit(2)
        result = search_company(args.company_id, company["name"], args.max_age_days, args.output_dir)
        all_results.append(result)
    else:
        with open(args.companies_file, encoding="utf-8") as f:
            companies_data = json.load(f)
        for company in companies_data["companies"]:
            if not company.get("monitoring_config", {}).get("check_news", True):
                continue
            result = search_company(company["id"], company["name"], args.max_age_days, args.output_dir)
            all_results.append(result)
            time.sleep(2)

    if len(all_results) == 1:
        print(json.dumps(all_results[0], ensure_ascii=False))
    else:
        combined_items = [item for r in all_results for item in r.get("items", [])]
        print(json.dumps({
            "fetched_at": _now(),
            "companies_searched": len(all_results),
            "total_items": len(combined_items),
            "results": all_results,
        }, ensure_ascii=False))

    sys.exit(0)


if __name__ == "__main__":
    main()
