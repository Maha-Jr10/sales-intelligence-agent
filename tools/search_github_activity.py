"""
Query GitHub API for an organization's public activity and detect signals.

Usage:
    python tools/search_github_activity.py --org stripe --company-id stripe
    python tools/search_github_activity.py --company-id stripe  # reads github_org from companies.json
    python tools/search_github_activity.py --companies-file data/companies.json --output-dir .tmp/raw_signals/

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PERSONAL_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_get(url: str, headers: dict) -> tuple[dict | list | None, int]:
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        print(f"[github] GET {url} → {resp.status_code} (rate_limit_remaining={remaining})", file=sys.stderr)

        if resp.status_code == 404:
            return None, 404
        if resp.status_code == 403:
            return {"error": "rate_limited_or_forbidden"}, 403
        if resp.status_code != 200:
            return None, resp.status_code
        return resp.json(), 200
    except Exception as e:
        print(f"[github] error: {e}", file=sys.stderr)
        return None, 0


NEW_REPO_SIGNAL_KEYWORDS = ["sdk", "platform", "api", "cli", "open", "public", "docs", "agent", "ai", "ml"]


def detect_repo_signals(repo: dict) -> list:
    signals = []
    name = repo.get("name", "").lower()
    desc = (repo.get("description") or "").lower()
    now = datetime.now(timezone.utc)

    created_str = repo.get("created_at", "")
    if created_str:
        try:
            created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if (now - created).days <= 14:
                signal_hint = "new_public_repo"
                if any(kw in name or kw in desc for kw in NEW_REPO_SIGNAL_KEYWORDS):
                    signal_hint = "new_public_repo"
                signals.append({
                    "type": "github_signal",
                    "subtype": signal_hint,
                    "detail": f"New repo '{repo['name']}' created {(now - created).days} days ago",
                    "repo": repo["name"],
                    "description": repo.get("description", ""),
                    "url": repo.get("html_url", ""),
                })
        except Exception:
            pass

    stars_today = repo.get("stargazers_count", 0)
    if stars_today > 100:
        signals.append({
            "type": "github_signal",
            "subtype": "sudden_star_spike",
            "detail": f"Repo '{repo['name']}' has {stars_today} stars",
            "repo": repo["name"],
            "stars": stars_today,
        })

    return signals


def fetch_org_activity(org: str, company_id: str, days_lookback: int = 14) -> dict:
    headers = get_headers()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_lookback)

    org_data, status = github_get(f"https://api.github.com/orgs/{org}", headers)
    if org_data is None or status == 404:
        return {
            "company_id": company_id,
            "github_org": org,
            "error": "org_not_found",
            "fetched_at": _now(),
        }

    repos_data, _ = github_get(
        f"https://api.github.com/orgs/{org}/repos?type=public&sort=created&direction=desc&per_page=50",
        headers
    )
    repos_data = repos_data or []

    recent_repos = []
    all_signals = []
    tech_languages = {}

    for repo in (repos_data if isinstance(repos_data, list) else []):
        lang = repo.get("language")
        if lang:
            tech_languages[lang] = tech_languages.get(lang, 0) + 1

        created_str = repo.get("created_at", "")
        if created_str:
            try:
                created = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                is_new = (datetime.now(timezone.utc) - created).days <= days_lookback
            except Exception:
                is_new = False
        else:
            is_new = False

        repo_summary = {
            "name": repo.get("name", ""),
            "description": repo.get("description", ""),
            "created_at": repo.get("created_at", ""),
            "stars": repo.get("stargazers_count", 0),
            "language": repo.get("language", ""),
            "html_url": repo.get("html_url", ""),
            "is_new": is_new,
        }
        recent_repos.append(repo_summary)
        repo_signals = detect_repo_signals(repo)
        all_signals.extend(repo_signals)

    tech_sorted = sorted(tech_languages, key=tech_languages.get, reverse=True)

    rate_remaining = "unknown"
    try:
        rate_resp = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=5)
        if rate_resp.status_code == 200:
            rate_remaining = rate_resp.json().get("rate", {}).get("remaining", "unknown")
    except Exception:
        pass

    for sig in all_signals:
        sig["company_id"] = company_id
        sig["source"] = "github_api"
        sig["source_url"] = f"https://github.com/{org}"
        sig["detected_at"] = _now()
        sig["title"] = sig.get("detail", "")

    return {
        "company_id": company_id,
        "github_org": org,
        "fetched_at": _now(),
        "org_data": {
            "public_repos": org_data.get("public_repos") if isinstance(org_data, dict) else None,
            "members_public": org_data.get("public_members_url") if isinstance(org_data, dict) else None,
            "created_at": org_data.get("created_at") if isinstance(org_data, dict) else None,
            "description": org_data.get("description") if isinstance(org_data, dict) else None,
        },
        "recent_repos": recent_repos[:20],
        "signals_detected": all_signals,
        "tech_stack_hints": tech_sorted[:10],
        "api_rate_limit_remaining": rate_remaining,
    }


def main():
    parser = argparse.ArgumentParser(description="Query GitHub org activity for sales signals")
    parser.add_argument("--org", help="GitHub organization slug")
    parser.add_argument("--company-id", help="Company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", help="Write output files to this directory")
    parser.add_argument("--days-lookback", type=int, default=14)
    args = parser.parse_args()

    if args.company_id and not args.org:
        with open(args.companies_file, encoding="utf-8") as f:
            data = json.load(f)
        company = next((c for c in data["companies"] if c["id"] == args.company_id), None)
        if not company:
            print(json.dumps({"error": f"company_id not found"}))
            sys.exit(2)
        github_org = company.get("github_org")
        if not github_org:
            print(json.dumps({"company_id": args.company_id, "skipped": True, "reason": "no_github_org_configured"}))
            sys.exit(0)
        args.org = github_org

    if args.org and args.company_id:
        result = fetch_org_activity(args.org, args.company_id, args.days_lookback)
        if args.output_dir:
            Path(args.output_dir).mkdir(parents=True, exist_ok=True)
            out_path = Path(args.output_dir) / f"github_{args.company_id}_{_today()}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)

    with open(args.companies_file, encoding="utf-8") as f:
        data = json.load(f)

    all_results = []
    errors = []
    for company in data["companies"]:
        if not company.get("monitoring_config", {}).get("check_github", True):
            continue
        github_org = company.get("github_org")
        if not github_org:
            continue
        try:
            result = fetch_org_activity(github_org, company["id"], args.days_lookback)
            all_results.append(result)
            if args.output_dir:
                Path(args.output_dir).mkdir(parents=True, exist_ok=True)
                out_path = Path(args.output_dir) / f"github_{company['id']}_{_today()}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2)
        except Exception as e:
            errors.append({"company_id": company["id"], "error": str(e)})
        time.sleep(1)

    print(json.dumps({
        "fetched_at": _now(),
        "companies_checked": len(all_results),
        "errors": errors,
        "results": all_results,
    }, ensure_ascii=False))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
