"""
Fetch one or more RSS/Atom feeds and return normalized items.

Usage:
    python tools/fetch_rss_feeds.py --feeds "https://example.com/rss,https://other.com/feed"
    python tools/fetch_rss_feeds.py --company-id stripe
    python tools/fetch_rss_feeds.py --companies-file data/companies.json --output-dir .tmp/raw_signals/

Exit codes: 0 success, 1 partial errors, 2 fatal
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(entry) -> str | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                import calendar
                ts = calendar.timegm(val)
                return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def fetch_feed(feed_url: str, company_id: str = None, max_age_days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    items = []
    errors = []

    try:
        headers = {"User-Agent": "Sales-Intelligence-Agent/1.0 (RSS Reader; +https://github.com)"}
        resp = requests.get(feed_url, headers=headers, timeout=10)
        d = feedparser.parse(resp.text)
    except Exception as e:
        return {"feed_url": feed_url, "items": [], "errors": [str(e)]}

    if d.bozo and d.bozo_exception:
        errors.append(f"bozo: {type(d.bozo_exception).__name__}")

    for entry in d.entries:
        pub_str = _parse_date(entry)
        if pub_str:
            pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if pub_dt < cutoff:
                continue

        link = getattr(entry, "link", None) or getattr(entry, "id", None) or ""
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        summary = summary[:500].strip()

        tags = [t.get("term", "") for t in getattr(entry, "tags", [])]

        items.append({
            "feed_url": feed_url,
            "company_id": company_id,
            "title": getattr(entry, "title", "").strip(),
            "link": link,
            "published": pub_str,
            "summary": summary,
            "tags": tags,
        })

    seen = set()
    unique_items = []
    for item in items:
        key = item["link"] or item["title"]
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    return {"feed_url": feed_url, "items": unique_items, "errors": errors}


def load_companies(companies_file: str) -> list:
    with open(companies_file, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("companies", [])


def main():
    parser = argparse.ArgumentParser(description="Fetch RSS/Atom feeds and return normalized items")
    parser.add_argument("--feeds", help="Comma-separated list of feed URLs")
    parser.add_argument("--company-id", help="Single company ID (reads blog_rss from companies.json)")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", help="Write output file per company to this directory")
    parser.add_argument("--max-age-days", type=int, default=30)
    args = parser.parse_args()

    all_items = []
    all_errors = []
    feeds_checked = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.feeds:
        feed_urls = [(url.strip(), None) for url in args.feeds.split(",") if url.strip()]
    elif args.company_id:
        companies = load_companies(args.companies_file)
        company = next((c for c in companies if c["id"] == args.company_id), None)
        if not company:
            print(json.dumps({"error": f"company_id '{args.company_id}' not found", "fetched_at": _now()}))
            sys.exit(2)
        feed_urls = [(company["blog_rss"], args.company_id)] if company.get("blog_rss") else []
    else:
        companies = load_companies(args.companies_file)
        feed_urls = [
            (c["blog_rss"], c["id"])
            for c in companies
            if c.get("blog_rss") and c.get("monitoring_config", {}).get("check_blog", True)
        ]

    for feed_url, company_id in feed_urls:
        feeds_checked += 1
        result = fetch_feed(feed_url, company_id=company_id, max_age_days=args.max_age_days)
        all_items.extend(result["items"])
        all_errors.extend(result["errors"])

        if args.output_dir and company_id:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            out_path = Path(args.output_dir) / f"rss_{company_id}_{today}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({"company_id": company_id, "feed_url": feed_url,
                           "items": result["items"], "errors": result["errors"],
                           "fetched_at": _now()}, f, indent=2)

    output = {
        "fetched_at": _now(),
        "feeds_checked": feeds_checked,
        "items": all_items,
        "errors": all_errors,
        "total_items": len(all_items),
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
