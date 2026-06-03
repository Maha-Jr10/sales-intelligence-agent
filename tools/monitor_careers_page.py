"""
Scrape a company's careers page, extract job listings, and compare against the previous snapshot.

Supports:
  - Greenhouse ATS boards (boards.greenhouse.io/{slug})
  - Lever ATS boards (jobs.lever.co/{slug})
  - Ashby ATS boards (jobs.ashbyhq.com/{slug})
  - Generic HTML scraping fallback

Usage:
    python tools/monitor_careers_page.py --company-id stripe
    python tools/monitor_careers_page.py --companies-file data/companies.json --output-dir .tmp/raw_signals/

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


SENIORITY_PATTERNS = {
    "executive": ["CEO", "CTO", "CPO", "CFO", "COO", "CISO", "Chief "],
    "vp": ["VP ", "Vice President", "Head of "],
    "director": ["Director", "Sr. Director", "Senior Director"],
    "manager": [" Manager", " Lead", "Principal "],
    "senior": ["Senior ", "Sr. ", "Staff "],
}

DEPT_PATTERNS = {
    "Engineering": ["Engineer", "Developer", "SRE", "DevOps", "Platform", "Backend", "Frontend", "Full Stack", "Data Engineer", "ML", "AI", "Security", "QA", "Infrastructure"],
    "Product": ["Product Manager", "PM ", "Product Designer", "UX", "Design"],
    "Sales": ["Sales", "Account Executive", "AE ", "SDR", "BDR", "Business Development"],
    "Marketing": ["Marketing", "Growth", "Content", "SEO", "Demand Gen"],
    "Finance": ["Finance", "Accounting", "Controller", "CFO"],
    "Operations": ["Operations", "Ops", "Chief of Staff"],
    "Customer Success": ["Customer Success", "CSM", "Account Manager", "Support"],
    "Data": ["Data Scientist", "Data Analyst", "Analytics", "Business Intelligence", "BI "],
    "HR": ["Recruiter", "HR", "People Ops", "Talent"],
    "Legal": ["Legal", "Counsel", "Compliance"],
}


def detect_seniority(title: str) -> str:
    for level, patterns in SENIORITY_PATTERNS.items():
        for p in patterns:
            if p.lower() in title.lower():
                return level
    return "ic"


def detect_department(title: str) -> str:
    for dept, patterns in DEPT_PATTERNS.items():
        for p in patterns:
            if p.lower() in title.lower():
                return dept
    return "Other"


def is_leadership(title: str) -> bool:
    seniority = detect_seniority(title)
    return seniority in ("executive", "vp", "director")


def job_fingerprint(job: dict) -> str:
    parts = [
        (job.get("title") or "").lower().strip(),
        (job.get("location") or "").lower().strip(),
        (job.get("department") or "").lower().strip(),
    ]
    return "|".join(parts)


def fetch_greenhouse(domain_or_slug: str) -> list:
    slug = domain_or_slug.split("/")[-1].split(".")[0]
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for j in data.get("jobs", []):
            jobs.append({
                "title": j.get("title", ""),
                "location": j.get("location", {}).get("name", ""),
                "department": j.get("departments", [{}])[0].get("name", "") if j.get("departments") else "",
                "url": j.get("absolute_url", ""),
                "source": "greenhouse_api",
            })
        return jobs
    except Exception as e:
        print(f"[monitor_careers] greenhouse error: {e}", file=sys.stderr)
        return []


def fetch_lever(company_slug: str) -> list:
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for j in data:
            jobs.append({
                "title": j.get("text", ""),
                "location": j.get("categories", {}).get("location", ""),
                "department": j.get("categories", {}).get("department", ""),
                "url": j.get("hostedUrl", ""),
                "source": "lever_api",
            })
        return jobs
    except Exception as e:
        print(f"[monitor_careers] lever error: {e}", file=sys.stderr)
        return []


def fetch_ashby(company_slug: str) -> list:
    url = f"https://jobs.ashbyhq.com/api/non-user-graphql"
    payload = {
        "operationName": "ApiJobBoardWithTeams",
        "variables": {"organizationHostedJobsPageName": company_slug},
        "query": "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) { jobBoard: jobBoardByRetoolId(organizationHostedJobsPageName: $organizationHostedJobsPageName) { jobPostings { id title locationName teamName jobPostingState } } }"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        postings = data.get("data", {}).get("jobBoard", {}).get("jobPostings", [])
        jobs = []
        for j in postings:
            if j.get("jobPostingState") != "published":
                continue
            jobs.append({
                "title": j.get("title", ""),
                "location": j.get("locationName", ""),
                "department": j.get("teamName", ""),
                "url": f"https://jobs.ashbyhq.com/{company_slug}/{j.get('id', '')}",
                "source": "ashby_api",
            })
        return jobs
    except Exception as e:
        print(f"[monitor_careers] ashby error: {e}", file=sys.stderr)
        return []


def fetch_generic_html(url: str) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Sales-Intelligence-Bot/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")

        job_schema = soup.find_all("script", type="application/ld+json")
        jobs = []
        for tag in job_schema:
            try:
                data = json.loads(tag.string)
                if isinstance(data, list):
                    items = data
                else:
                    items = [data]
                for item in items:
                    if item.get("@type") == "JobPosting":
                        jobs.append({
                            "title": item.get("title", ""),
                            "location": item.get("jobLocation", {}).get("address", {}).get("addressLocality", ""),
                            "department": item.get("occupationalCategory", ""),
                            "url": item.get("url", url),
                            "source": "schema_org",
                        })
            except Exception:
                pass

        if jobs:
            return jobs

        title_patterns = re.compile(
            r"(engineer|developer|manager|director|VP|head of|designer|analyst|scientist|"
            r"recruiter|executive|product|marketing|sales|ops|sre|devops|platform|data|"
            r"backend|frontend|fullstack|full-stack)", re.IGNORECASE
        )
        for el in soup.find_all(["li", "div", "article", "tr"], limit=500):
            text = el.get_text(separator=" ").strip()
            if 5 < len(text) < 150 and title_patterns.search(text):
                link = el.find("a", href=True)
                href = link["href"] if link else url
                if href.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    href = f"{parsed.scheme}://{parsed.netloc}{href}"
                jobs.append({
                    "title": text[:150],
                    "location": "",
                    "department": "",
                    "url": href,
                    "source": "html_heuristic",
                })

        seen = set()
        unique = []
        for j in jobs:
            key = j["title"].lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                unique.append(j)

        return unique[:200]
    except Exception as e:
        print(f"[monitor_careers] html scrape error: {e}", file=sys.stderr)
        return []


def detect_ats(careers_url: str) -> tuple[str, str]:
    url_lower = careers_url.lower()
    if "greenhouse.io" in url_lower:
        slug = careers_url.split("greenhouse.io/")[-1].split("/")[0].split("?")[0]
        return "greenhouse", slug
    if "lever.co" in url_lower:
        slug = careers_url.split("lever.co/")[-1].split("/")[0].split("?")[0]
        return "lever", slug
    if "ashbyhq.com" in url_lower:
        slug = careers_url.split("ashbyhq.com/")[-1].split("/")[0].split("?")[0]
        return "ashby", slug
    return "generic", careers_url


def load_previous_snapshot(company_id: str, snapshots_dir: str) -> dict | None:
    path = Path(snapshots_dir)
    if not path.exists():
        return None
    candidates = sorted(path.glob(f"{company_id}_careers_*.json"), reverse=True)
    today_str = _today()
    for c in candidates:
        if today_str not in c.name:
            try:
                with open(c, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def save_snapshot(company_id: str, jobs: list, snapshots_dir: str) -> str:
    Path(snapshots_dir).mkdir(parents=True, exist_ok=True)
    snapshot_id = f"{company_id}_careers_{_today()}"
    path = Path(snapshots_dir) / f"{snapshot_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"snapshot_id": snapshot_id, "company_id": company_id,
                   "captured_at": _now(), "jobs": jobs}, f, indent=2)
    return snapshot_id


def compare_snapshots(current: list, previous: list) -> dict:
    current_fps = {job_fingerprint(j): j for j in current}
    previous_fps = {job_fingerprint(j): j for j in previous}

    new_jobs = [j for fp, j in current_fps.items() if fp not in previous_fps]
    removed_jobs = [j for fp, j in previous_fps.items() if fp not in current_fps]

    for j in new_jobs:
        j["seniority"] = detect_seniority(j["title"])
        j["department_detected"] = detect_department(j["title"])
        j["is_leadership"] = is_leadership(j["title"])

    return {
        "new_jobs": new_jobs,
        "removed_jobs": removed_jobs,
        "net_change": len(new_jobs) - len(removed_jobs),
        "change_detected": bool(new_jobs or removed_jobs),
    }


def process_company(company: dict, snapshots_dir: str, output_dir: str = None) -> dict:
    company_id = company["id"]
    careers_url = company.get("careers_url") or company.get("website", "")

    if not careers_url:
        return {"company_id": company_id, "error": "no_careers_url", "fetched_at": _now()}

    ats_type, slug = detect_ats(careers_url)
    print(f"[monitor_careers] {company_id} — ATS: {ats_type}", file=sys.stderr)

    if ats_type == "greenhouse":
        jobs = fetch_greenhouse(slug)
    elif ats_type == "lever":
        jobs = fetch_lever(slug)
    elif ats_type == "ashby":
        jobs = fetch_ashby(slug)
    else:
        jobs = fetch_generic_html(careers_url)

    if not jobs and ats_type == "generic":
        for pattern in [f"boards.greenhouse.io/{company_id}", f"jobs.lever.co/{company_id}", f"jobs.ashbyhq.com/{company_id}"]:
            test_ats, test_slug = detect_ats(f"https://{pattern}")
            if test_ats == "greenhouse":
                jobs = fetch_greenhouse(test_slug)
            elif test_ats == "lever":
                jobs = fetch_lever(test_slug)
            elif test_ats == "ashby":
                jobs = fetch_ashby(test_slug)
            if jobs:
                break

    previous_snapshot = load_previous_snapshot(company_id, snapshots_dir)
    current_snapshot_id = save_snapshot(company_id, jobs, snapshots_dir)

    if previous_snapshot:
        diff = compare_snapshots(jobs, previous_snapshot.get("jobs", []))
        previous_snapshot_id = previous_snapshot.get("snapshot_id")
    else:
        diff = {"new_jobs": jobs, "removed_jobs": [], "net_change": len(jobs), "change_detected": False}
        previous_snapshot_id = None
        for j in diff["new_jobs"]:
            j["seniority"] = detect_seniority(j["title"])
            j["department_detected"] = detect_department(j["title"])
            j["is_leadership"] = is_leadership(j["title"])

    result = {
        "company_id": company_id,
        "scraped_at": _now(),
        "careers_url": careers_url,
        "ats_type": ats_type,
        "snapshot_id": current_snapshot_id,
        "previous_snapshot_id": previous_snapshot_id,
        "total_jobs_current": len(jobs),
        "total_jobs_previous": len(previous_snapshot.get("jobs", [])) if previous_snapshot else 0,
        "new_jobs": diff["new_jobs"],
        "removed_jobs": diff["removed_jobs"],
        "net_change": diff["net_change"],
        "change_detected": diff["change_detected"],
        "first_run": previous_snapshot is None,
    }

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"careers_{company_id}_{_today()}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="Monitor company careers pages for job changes")
    parser.add_argument("--company-id", help="Single company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--snapshots-dir", default="outputs/snapshots")
    parser.add_argument("--output-dir", help="Directory to write per-company output files")
    args = parser.parse_args()

    with open(args.companies_file, encoding="utf-8") as f:
        companies_data = json.load(f)

    if args.company_id:
        companies = [c for c in companies_data["companies"] if c["id"] == args.company_id]
        if not companies:
            print(json.dumps({"error": f"company_id '{args.company_id}' not found"}))
            sys.exit(2)
    else:
        companies = [
            c for c in companies_data["companies"]
            if c.get("monitoring_config", {}).get("check_careers", True)
        ]

    results = []
    errors = []
    for company in companies:
        try:
            result = process_company(company, args.snapshots_dir, args.output_dir)
            results.append(result)
        except Exception as e:
            print(f"[monitor_careers] error for {company['id']}: {e}", file=sys.stderr)
            errors.append({"company_id": company["id"], "error": str(e)})

    if len(results) == 1 and not errors:
        print(json.dumps(results[0], ensure_ascii=False))
    else:
        print(json.dumps({
            "processed": len(results),
            "errors": errors,
            "results": results,
            "fetched_at": _now(),
        }, ensure_ascii=False))

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
