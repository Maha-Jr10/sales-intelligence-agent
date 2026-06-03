"""
Pull job listings from multiple public sources (Indeed scraping, HN Who's Hiring).

Usage:
    python tools/fetch_job_listings.py --company-id stripe
    python tools/fetch_job_listings.py --company "Stripe" --company-id stripe --sources indeed,hn_hiring

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_tech_keywords(path: str = "data/tech_keywords.json") -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [t["name"] for t in data.get("technologies", [])]
    except Exception:
        return ["Python", "Go", "Rust", "TypeScript", "React", "Kubernetes", "AWS", "GCP",
                "Terraform", "Snowflake", "dbt", "Datadog", "PostgreSQL", "Redis", "Kafka"]


def extract_tech_mentions(text: str, tech_list: list) -> list:
    found = []
    for tech in tech_list:
        if re.search(rf"\b{re.escape(tech)}\b", text, re.IGNORECASE):
            found.append(tech)
    return found


def detect_seniority(title: str) -> str:
    title_lower = title.lower()
    if any(w in title_lower for w in ["cto", "ceo", "cpo", "chief", "vp ", "vice president", "head of"]):
        return "executive"
    if any(w in title_lower for w in ["director", "sr. director"]):
        return "director"
    if any(w in title_lower for w in ["staff ", "principal ", "distinguished"]):
        return "staff"
    if any(w in title_lower for w in ["senior ", "sr. ", " iii", " iv"]):
        return "senior"
    if any(w in title_lower for w in ["manager", "lead ", " lead"]):
        return "manager"
    if any(w in title_lower for w in ["junior", "jr.", "associate", "intern"]):
        return "junior"
    return "mid"


def scrape_indeed(company_name: str, max_results: int = 25) -> list:
    encoded = urllib.parse.quote_plus(company_name)
    url = f"https://www.indeed.com/jobs?q=%22{encoded}%22&sort=date"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code in (403, 429):
            print(f"[fetch_jobs] indeed blocked ({resp.status_code}), trying DuckDuckGo", file=sys.stderr)
            return scrape_indeed_via_ddg(company_name)

        soup = BeautifulSoup(resp.text, "lxml")
        jobs = []

        for card in soup.find_all("div", class_=re.compile(r"job_seen_beacon|jobsearch-SerpJobCard"), limit=max_results):
            title_el = card.find(["h2", "span"], class_=re.compile(r"jobTitle|title"))
            company_el = card.find(["span", "div"], class_=re.compile(r"companyName|company"))
            location_el = card.find(["div", "span"], class_=re.compile(r"companyLocation|location"))
            link_el = card.find("a", href=True)

            title = title_el.get_text(strip=True) if title_el else ""
            comp = company_el.get_text(strip=True) if company_el else ""
            location = location_el.get_text(strip=True) if location_el else ""
            href = link_el["href"] if link_el else ""
            if href.startswith("/"):
                href = f"https://www.indeed.com{href}"

            if title and comp and company_name.lower() in comp.lower():
                jobs.append({
                    "source": "indeed",
                    "title": title,
                    "company": comp,
                    "location": location,
                    "posted_date": _today(),
                    "url": href,
                    "description_snippet": "",
                    "tech_mentions": [],
                    "seniority": detect_seniority(title),
                })

        return jobs
    except Exception as e:
        print(f"[fetch_jobs] indeed error: {e}", file=sys.stderr)
        return []


def scrape_indeed_via_ddg(company_name: str) -> list:
    query = urllib.parse.quote_plus(f"site:indeed.com \"{company_name}\" jobs")
    url = f"https://html.duckduckgo.com/html/?q={query}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DuckDuckGoBot/1.1)"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "lxml")
        jobs = []
        for result in soup.find_all("div", class_="result__body", limit=10):
            title_el = result.find("a", class_="result__a")
            snippet_el = result.find("a", class_="result__snippet")
            if title_el:
                jobs.append({
                    "source": "indeed_ddg",
                    "title": title_el.get_text(strip=True),
                    "company": company_name,
                    "location": "",
                    "posted_date": _today(),
                    "url": title_el.get("href", ""),
                    "description_snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    "tech_mentions": [],
                    "seniority": "unknown",
                })
        return jobs
    except Exception as e:
        print(f"[fetch_jobs] ddg fallback error: {e}", file=sys.stderr)
        return []


def search_hn_hiring(company_name: str) -> list:
    from datetime import date
    today = date.today()
    month_str = today.strftime("%B %Y")
    query = urllib.parse.quote_plus(f"who is hiring {month_str}")
    url = f"http://hn.algolia.com/api/v1/search?query=Ask+HN%3A+Who+is+hiring&tags=ask_hn&hitsPerPage=3"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        hits = data.get("hits", [])
        if not hits:
            return []
        story_id = hits[0].get("objectID", "")
        if not story_id:
            return []

        comments_url = f"http://hn.algolia.com/api/v1/search?tags=comment,story_{story_id}&hitsPerPage=1000"
        resp2 = requests.get(comments_url, timeout=15)
        comments = resp2.json().get("hits", [])

        jobs = []
        company_lower = company_name.lower()
        for comment in comments:
            text = comment.get("comment_text", "") or ""
            if company_lower not in text.lower():
                continue
            first_line = text.split("\n")[0]
            title_match = re.search(r"(?:hiring|looking for|seeking)[:\s]+(.{10,80})", text, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else first_line[:100]
            location_match = re.search(r"\b(remote|onsite|hybrid|[A-Z][a-z]+,\s*[A-Z]{2})\b", text)
            location = location_match.group(0) if location_match else ""

            clean_text = re.sub(r"<[^>]+>", " ", text)
            jobs.append({
                "source": "hn_who_is_hiring",
                "title": title,
                "company": company_name,
                "location": location,
                "posted_date": _today(),
                "url": f"https://news.ycombinator.com/item?id={comment.get('objectID', '')}",
                "description_snippet": clean_text[:300],
                "tech_mentions": [],
                "seniority": detect_seniority(title),
            })

        return jobs[:10]
    except Exception as e:
        print(f"[fetch_jobs] hn_hiring error: {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(description="Fetch job listings from public sources")
    parser.add_argument("--company", help="Company name to search")
    parser.add_argument("--company-id", help="Company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--sources", default="indeed,hn_hiring",
                        help="Comma-separated sources: indeed,hn_hiring")
    parser.add_argument("--output-dir", help="Directory to write output files")
    args = parser.parse_args()

    tech_list = load_tech_keywords()

    if args.company_id and not args.company:
        with open(args.companies_file, encoding="utf-8") as f:
            data = json.load(f)
        company_obj = next((c for c in data["companies"] if c["id"] == args.company_id), None)
        if not company_obj:
            print(json.dumps({"error": f"company_id not found", "fetched_at": _now()}))
            sys.exit(2)
        args.company = company_obj["name"]

    if not args.company:
        print(json.dumps({"error": "provide --company or --company-id", "fetched_at": _now()}))
        sys.exit(2)

    sources = [s.strip() for s in args.sources.split(",")]
    all_jobs = []
    errors = []

    if "indeed" in sources:
        jobs = scrape_indeed(args.company)
        all_jobs.extend(jobs)
        time.sleep(2)

    if "hn_hiring" in sources:
        jobs = search_hn_hiring(args.company)
        all_jobs.extend(jobs)

    for job in all_jobs:
        desc = job.get("description_snippet", "")
        job["tech_mentions"] = extract_tech_mentions(desc + " " + job.get("title", ""), tech_list)

    seen = set()
    unique = []
    for j in all_jobs:
        key = (j.get("title", "").lower().strip()[:50], j.get("source", ""))
        if key not in seen:
            seen.add(key)
            unique.append(j)

    result = {
        "company_id": args.company_id,
        "company_name": args.company,
        "fetched_at": _now(),
        "sources_checked": sources,
        "total_found": len(unique),
        "listings": unique,
    }

    if args.output_dir and args.company_id:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(args.output_dir) / f"jobs_{args.company_id}_{_today()}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
