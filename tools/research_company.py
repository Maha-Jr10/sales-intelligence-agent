"""
Orchestrate multi-source research for a single company and produce a raw research bundle.

This is a pure orchestrator — it calls other tools via subprocess and aggregates output.
No reasoning happens here. The agent reads the bundle and synthesizes the brief.

Usage:
    python tools/research_company.py --company-id stripe
    python tools/research_company.py --company-id stripe --depth deep
    python tools/research_company.py --company-id stripe --depth quick --output-file .tmp/stripe.json

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run_tool(tool_args: list, timeout: int = 30) -> tuple[dict | list | None, str]:
    try:
        result = subprocess.run(
            [sys.executable] + tool_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=timeout,
        )
        stderr = result.stderr.strip()
        if stderr:
            print(f"[research] tool stderr: {stderr}", file=sys.stderr)

        if result.stdout.strip():
            try:
                return json.loads(result.stdout), None
            except json.JSONDecodeError:
                return None, f"non_json_output: {result.stdout[:200]}"
        return None, "empty_output"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


def fetch_wikipedia(company_name: str) -> str | None:
    import urllib.parse
    import urllib.request
    try:
        encoded = urllib.parse.quote(company_name)
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(url, headers={"User-Agent": "SalesBot/1.0"})
        with urllib.request.urlopen(req, timeout=5, encoding="utf-8") as resp:
            data = json.loads(resp.read().decode())
            return data.get("extract") or None
    except Exception:
        return None


def fetch_wayback(domain: str) -> dict:
    import urllib.request
    try:
        url = f"http://web.archive.org/cdx/search/cdx?url={domain}&output=json&limit=5&fl=timestamp,statuscode&collapse=timestamp:6"
        req = urllib.request.Request(url, headers={"User-Agent": "SalesBot/1.0"})
        with urllib.request.urlopen(req, timeout=10, encoding="utf-8") as resp:
            rows = json.loads(resp.read().decode())
            if len(rows) > 1:
                first = rows[1]
                first_ts = first[0] if first else ""
                first_archived = f"{first_ts[:4]}-{first_ts[4:6]}-{first_ts[6:8]}" if len(first_ts) >= 8 else ""
                return {
                    "first_archived": first_archived,
                    "snapshot_count": len(rows) - 1,
                }
    except Exception:
        pass
    return {}


def research_company(company: dict, depth: str = "standard", raw_signals_dir: str = ".tmp/raw_signals") -> dict:
    company_id = company["id"]
    company_name = company["name"]
    domain = company.get("domain", "")
    monitoring = company.get("monitoring_config", {})
    collection_errors = []
    data = {}

    Path(raw_signals_dir).mkdir(parents=True, exist_ok=True)
    Path(".tmp/research_cache").mkdir(parents=True, exist_ok=True)

    print(f"[research] Starting {depth} research for {company_name}", file=sys.stderr)

    # Scrape about/main page
    website = company.get("website", f"https://{domain}")
    scrape_result, err = run_tool(["tools/scrape_website.py", "--url", website, "--skip-robots"])
    if scrape_result and not scrape_result.get("error"):
        data["company_profile"] = {
            "source": "website_scrape",
            "url": website,
            "title": scrape_result.get("title", ""),
            "about_text": scrape_result.get("text_content", "")[:3000],
            "links": scrape_result.get("links", [])[:20],
        }
    else:
        collection_errors.append({"source": "website_scrape", "error": err or "failed"})

    # News search
    if monitoring.get("check_news", True):
        news_result, err = run_tool([
            "tools/search_news.py", "--query", company_name,
            "--company-id", company_id, "--max-age-days", "30"
        ], timeout=30)
        if news_result and not news_result.get("error"):
            data["recent_news"] = news_result.get("items", [])[:15]
        else:
            collection_errors.append({"source": "search_news", "error": err or "failed"})

    # Careers
    if monitoring.get("check_careers", True):
        careers_result, err = run_tool([
            "tools/monitor_careers_page.py", "--company-id", company_id,
            "--companies-file", "data/companies.json"
        ], timeout=40)
        if careers_result and not careers_result.get("error"):
            data["job_listings"] = careers_result.get("new_jobs", [])
            data["total_jobs_count"] = careers_result.get("total_jobs_current", 0)
            data["careers_change_detected"] = careers_result.get("change_detected", False)
        else:
            collection_errors.append({"source": "monitor_careers", "error": err or "failed"})

    # RSS feeds
    if monitoring.get("check_blog", True) and company.get("blog_rss"):
        rss_result, err = run_tool([
            "tools/fetch_rss_feeds.py", "--company-id", company_id,
            "--companies-file", "data/companies.json", "--max-age-days", "30"
        ], timeout=20)
        if rss_result and not rss_result.get("error"):
            data["rss_items"] = rss_result.get("items", [])[:10]
        else:
            collection_errors.append({"source": "fetch_rss_feeds", "error": err or "failed"})

    # GitHub
    if monitoring.get("check_github", True) and company.get("github_org"):
        gh_result, err = run_tool([
            "tools/search_github_activity.py", "--company-id", company_id,
            "--companies-file", "data/companies.json"
        ], timeout=20)
        if gh_result and not gh_result.get("error"):
            data["github_signals"] = {
                "org": company.get("github_org"),
                "recent_repos": gh_result.get("recent_repos", [])[:5],
                "signals_detected": gh_result.get("signals_detected", []),
                "tech_stack_hints": gh_result.get("tech_stack_hints", []),
            }
        else:
            collection_errors.append({"source": "github_activity", "error": err or "failed"})

    # Tech stack
    if domain:
        tech_result, err = run_tool([
            "tools/fetch_tech_signals.py", "--domain", domain, "--company-id", company_id
        ], timeout=20)
        if tech_result and not tech_result.get("error"):
            data["tech_stack"] = {
                "source": "website_scan",
                "detected": [t["name"] for t in tech_result.get("tech_stack", [])],
                "cdn": tech_result.get("cdn"),
                "signals_for_outreach": tech_result.get("signals_for_outreach", []),
            }
        else:
            collection_errors.append({"source": "fetch_tech_signals", "error": err or "failed"})

    # Product Hunt
    if monitoring.get("check_product_hunt", False):
        ph_result, err = run_tool([
            "tools/check_product_hunt.py", "--company", company_name, "--company-id", company_id
        ], timeout=20)
        if ph_result:
            data["product_hunt"] = ph_result.get("launches", [])

    # Deep research extras
    if depth in ("standard", "deep"):
        wiki = fetch_wikipedia(company_name)
        data["wikipedia_summary"] = wiki

        wayback = fetch_wayback(domain) if domain else {}
        data["wayback_signals"] = wayback

    if depth == "deep":
        for page_slug in ("about", "product", "pricing", "blog"):
            page_url = f"https://{domain}/{page_slug}"
            page_result, err = run_tool([
                "tools/scrape_website.py", "--url", page_url, "--skip-robots"
            ], timeout=15)
            if page_result and not page_result.get("error"):
                data[f"page_{page_slug}"] = {
                    "url": page_url,
                    "text": page_result.get("text_content", "")[:2000],
                }

    bundle = {
        "company_id": company_id,
        "company_name": company_name,
        "researched_at": _now(),
        "depth": depth,
        "company_meta": {
            "domain": domain,
            "industry": company.get("industry"),
            "employee_count_estimate": company.get("employee_count_estimate"),
            "headquarters": company.get("headquarters"),
            "funding_stage": company.get("funding_stage"),
            "website": company.get("website"),
            "github_org": company.get("github_org"),
            "linkedin_url": company.get("linkedin_url"),
            "tier": company.get("tier"),
            "notes": company.get("notes"),
        },
        "data": data,
        "collection_errors": collection_errors,
        "ready_for_brief": len(data) > 0,
    }

    cache_path = Path(".tmp/research_cache") / f"{company_id}_{_today()}.json"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    print(f"[research] bundle saved to {cache_path}", file=sys.stderr)

    return bundle


def main():
    parser = argparse.ArgumentParser(description="Orchestrate multi-source company research")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--depth", choices=["quick", "standard", "deep"], default="standard")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-file", help="Write bundle to this path (default: .tmp/research_cache/)")
    args = parser.parse_args()

    try:
        with open(args.companies_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(json.dumps({"error": f"cannot load companies.json: {e}"}))
        sys.exit(2)

    company = next((c for c in data["companies"] if c["id"] == args.company_id), None)
    if not company:
        print(json.dumps({"error": f"company_id '{args.company_id}' not found"}))
        sys.exit(2)

    bundle = research_company(company, depth=args.depth)

    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)

    print(json.dumps(bundle, ensure_ascii=False))
    sys.exit(1 if bundle["collection_errors"] else 0)


if __name__ == "__main__":
    main()
