"""
Query Product Hunt for company launches and mentions.

Uses Product Hunt RSS feed and DuckDuckGo fallback.

Usage:
    python tools/check_product_hunt.py --company "Linear" --company-id linear
    python tools/check_product_hunt.py --companies-file data/companies.json --output-dir .tmp/raw_signals/

Exit codes: 0 success, 1 partial, 2 fatal
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
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_feed_date(entry) -> str | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            import calendar
            ts = calendar.timegm(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return None


def search_ph_rss(company_name: str, max_age_days: int = 30) -> list:
    url = "https://www.producthunt.com/feed"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Sales-Bot/1.0)"}
    launches = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        d = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        company_lower = company_name.lower()

        for entry in d.entries:
            title = getattr(entry, "title", "")
            desc = getattr(entry, "summary", "") or getattr(entry, "description", "")
            text = (title + " " + desc).lower()
            if company_lower not in text:
                continue

            pub_str = _parse_feed_date(entry)
            if pub_str:
                dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if dt < cutoff:
                    continue

            upvotes = 0
            upvote_match = re.search(r"(\d+)\s*upvotes?", desc, re.IGNORECASE)
            if upvote_match:
                upvotes = int(upvote_match.group(1))

            is_featured = "#1" in title or "product of the day" in text.lower()

            launches.append({
                "name": title,
                "tagline": re.sub(r"<[^>]+>", "", desc)[:200],
                "url": getattr(entry, "link", ""),
                "published": pub_str,
                "upvotes": upvotes,
                "is_featured": is_featured,
                "source": "product_hunt_rss",
            })
    except Exception as e:
        print(f"[ph] rss error: {e}", file=sys.stderr)
    return launches


def search_ph_ddg(company_name: str, max_age_days: int = 30) -> list:
    query = urllib.parse.quote_plus(f"site:producthunt.com \"{company_name}\"")
    url = f"https://html.duckduckgo.com/html/?q={query}"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"}
    launches = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "lxml")
        company_lower = company_name.lower()

        for result in soup.find_all("div", class_="result__body", limit=10):
            title_el = result.find("a", class_="result__a")
            snippet_el = result.find("a", class_="result__snippet")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            text = (title + " " + snippet).lower()

            if company_lower not in text:
                continue
            if "producthunt.com" not in href:
                continue

            launches.append({
                "name": title,
                "tagline": snippet[:200],
                "url": href,
                "published": None,
                "upvotes": 0,
                "is_featured": "#1" in title or "product of the day" in text,
                "source": "product_hunt_ddg",
            })
    except Exception as e:
        print(f"[ph] ddg error: {e}", file=sys.stderr)
    return launches


def fetch_company_ph(company_name: str, company_id: str, max_age_days: int = 30) -> dict:
    launches = search_ph_rss(company_name, max_age_days)
    if not launches:
        time.sleep(1)
        launches = search_ph_ddg(company_name, max_age_days)

    for l in launches:
        l["company_id"] = company_id
        l["signal_type"] = "product_hunt_launch"
        l["signal_subtype"] = "featured" if l.get("is_featured") else "mentioned"
        l["detected_at"] = _now()
        l["title"] = l["name"]
        l["source_url"] = l["url"]

    return {
        "company_id": company_id,
        "query": company_name,
        "fetched_at": _now(),
        "total_found": len(launches),
        "launches": launches,
    }


def main():
    parser = argparse.ArgumentParser(description="Search Product Hunt for company launches")
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--company-id", help="Company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", help="Directory to write output files")
    parser.add_argument("--max-age-days", type=int, default=30)
    args = parser.parse_args()

    if args.company and args.company_id:
        result = fetch_company_ph(args.company, args.company_id, args.max_age_days)
        if args.output_dir:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            out_path = Path(args.output_dir) / f"ph_{args.company_id}_{_today()}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    with open(args.companies_file, encoding="utf-8") as f:
        data = json.load(f)

    all_results = []
    errors = []
    for company in data["companies"]:
        if not company.get("monitoring_config", {}).get("check_product_hunt", False):
            continue
        try:
            result = fetch_company_ph(company["name"], company["id"], args.max_age_days)
            all_results.append(result)
            if args.output_dir and result["launches"]:
                Path(args.output_dir).mkdir(parents=True, exist_ok=True)
                out_path = Path(args.output_dir) / f"ph_{company['id']}_{_today()}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2)
        except Exception as e:
            errors.append({"company_id": company["id"], "error": str(e)})
        time.sleep(2)

    print(json.dumps({
        "fetched_at": _now(),
        "companies_checked": len(all_results),
        "errors": errors,
        "results": all_results,
    }, ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
