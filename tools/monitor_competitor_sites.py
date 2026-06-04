"""
Monitor competitor websites for changes: new blog posts, case studies,
team additions, homepage repositioning, and hiring activity.

Snapshots each competitor's key pages and diffs against the previous run.
LinkedIn is excluded (auth/bot-detection); website pages are more actionable.

Usage:
    python tools/monitor_competitor_sites.py
    python tools/monitor_competitor_sites.py --competitor-id primeforge
    python tools/monitor_competitor_sites.py --snapshot-dir .tmp/competitor_snapshots \
        --output-dir outputs/competitive

Exit codes: 0 no changes, 1 changes detected, 2 fatal error
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_VERSION = "1.0"

# Candidate paths to try per page category. First successful fetch wins.
PAGE_CANDIDATES = {
    "homepage":     ["/"],
    "blog":         ["/blog", "/blog/", "/insights", "/news", "/articles", "/resources"],
    "team":         ["/team", "/about", "/about-us", "/who-we-are", "/company"],
    "case_studies": ["/case-studies", "/work", "/portfolio", "/projects", "/clients", "/success-stories"],
    "careers":      ["/careers", "/jobs", "/join-us", "/join", "/hiring"],
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

STRIP_TAGS = ["script", "style", "nav", "footer", "head", "iframe", "noscript", "svg"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ua(domain: str) -> str:
    idx = int(hashlib.md5(domain.encode()).hexdigest(), 16) % len(USER_AGENTS)
    return USER_AGENTS[idx]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── fetching ─────────────────────────────────────────────────────────────────

def fetch_page(url: str, timeout: int = 10) -> dict | None:
    """Fetch a URL and return structured content. Returns None on hard failure."""
    headers = {
        "User-Agent": _ua(url),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception:
        try:
            time.sleep(2)
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        except Exception:
            return None

    if resp.status_code in (404, 410):
        return None
    if resp.status_code in (403, 429):
        return {"error": "blocked", "status_code": resp.status_code}
    if resp.status_code >= 400:
        return {"error": "http_error", "status_code": resp.status_code}
    if "text/html" not in resp.headers.get("Content-Type", ""):
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""

    for tag in soup(STRIP_TAGS):
        tag.decompose()

    text = " ".join(soup.get_text(separator=" ").split())

    # Extract internal links (relative + same-domain)
    base = f"{urllib.parse.urlparse(url).scheme}://{urllib.parse.urlparse(url).netloc}"
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/"):
            links.append(base + href)
        elif href.startswith(base):
            links.append(href)
    links = list(dict.fromkeys(links))[:200]

    return {
        "url": resp.url,
        "status_code": resp.status_code,
        "title": title,
        "text_hash": _hash(text),
        "word_count": len(text.split()),
        "text_preview": text[:500],
        "internal_links": links,
        "fetched_at": _now(),
    }


def probe_category(base_url: str, candidates: list[str], timeout: int = 10) -> dict | None:
    """Try candidate paths until one returns content."""
    for path in candidates:
        url = base_url.rstrip("/") + path
        result = fetch_page(url, timeout)
        if result and "error" not in result:
            result["path_used"] = path
            return result
        time.sleep(0.3)
    return None


# ── content-aware link filtering ─────────────────────────────────────────────

def _content_links(page: dict, base_url: str, category: str) -> list[str]:
    """
    Extract links that look like content items (blog posts, case studies, etc.)
    rather than navigation links. Filters by URL path patterns.
    """
    if not page:
        return []
    all_links = page.get("internal_links", [])
    base_netloc = urllib.parse.urlparse(base_url).netloc

    # Path segments that indicate content pages vs nav
    content_patterns = {
        "blog":         [r"/blog/\w", r"/insights/\w", r"/news/\w", r"/articles/\w"],
        "case_studies": [r"/case-stud", r"/work/\w", r"/portfolio/\w", r"/project/\w", r"/client/\w"],
        "careers":      [r"/job", r"/position", r"/role", r"/opening", r"/careers/\w"],
        "team":         [r"/team/\w", r"/people/\w"],
    }
    patterns = content_patterns.get(category, [])
    if not patterns:
        return all_links

    result = []
    for link in all_links:
        parsed = urllib.parse.urlparse(link)
        if parsed.netloc and parsed.netloc != base_netloc:
            continue
        path = parsed.path.lower()
        if any(re.search(p, path) for p in patterns):
            result.append(link)
    return result


# ── snapshotting ─────────────────────────────────────────────────────────────

def snapshot_competitor(competitor: dict, timeout: int = 10) -> dict:
    """Fetch all monitored page categories for one competitor."""
    domain = competitor.get("domain", "")
    if not domain:
        return {}

    base_url = f"https://{domain}"
    pages = {}

    for category, candidates in PAGE_CANDIDATES.items():
        result = probe_category(base_url, candidates, timeout)
        if result:
            result["content_links"] = _content_links(result, base_url, category)
            pages[category] = result
            print(f"  [{competitor['id']}] {category}: {result['path_used']} — {result['word_count']} words", file=sys.stderr)
        else:
            pages[category] = None
        time.sleep(0.5)

    return {
        "competitor_id": competitor["id"],
        "competitor_name": competitor["name"],
        "domain": domain,
        "snapshotted_at": _now(),
        "pages": pages,
    }


# ── diffing ───────────────────────────────────────────────────────────────────

def diff_snapshots(current: dict, previous: dict | None) -> list[dict]:
    """Compare current vs previous snapshot and return change records."""
    changes = []
    comp_id = current["competitor_id"]
    comp_name = current["competitor_name"]
    current_pages = current.get("pages", {})
    previous_pages = (previous or {}).get("pages", {}) if previous else {}

    for category, cur_page in current_pages.items():
        if not cur_page or "error" in cur_page:
            continue
        prev_page = previous_pages.get(category)

        # — First run: just record baseline, no diff —
        if previous is None or prev_page is None:
            if previous is None:
                continue  # brand-new baseline, nothing to diff

            # Page newly appeared (previously absent)
            changes.append({
                "competitor_id": comp_id,
                "competitor_name": comp_name,
                "category": category,
                "change_type": "page_appeared",
                "title": f"{comp_name}: {category.replace('_', ' ')} page is now live",
                "significance": "medium",
                "detail": {"url": cur_page.get("url", ""), "word_count": cur_page.get("word_count", 0)},
            })
            continue

        cur_links = set(cur_page.get("content_links", []))
        prev_links = set(prev_page.get("content_links", []))
        new_links = cur_links - prev_links

        # ── blog: new posts ──
        if category == "blog" and new_links:
            for link in sorted(new_links)[:10]:
                changes.append({
                    "competitor_id": comp_id,
                    "competitor_name": comp_name,
                    "category": "blog",
                    "change_type": "new_blog_post",
                    "title": f"{comp_name}: new blog post published",
                    "significance": "low",
                    "detail": {"url": link},
                })

        # ── case studies: new client ──
        elif category == "case_studies" and new_links:
            for link in sorted(new_links)[:5]:
                changes.append({
                    "competitor_id": comp_id,
                    "competitor_name": comp_name,
                    "category": "case_studies",
                    "change_type": "new_case_study",
                    "title": f"{comp_name}: new case study — potential new client",
                    "significance": "high",
                    "detail": {"url": link},
                })

        # ── careers: new job openings ──
        elif category == "careers" and new_links:
            for link in sorted(new_links)[:5]:
                changes.append({
                    "competitor_id": comp_id,
                    "competitor_name": comp_name,
                    "category": "careers",
                    "change_type": "new_job_opening",
                    "title": f"{comp_name}: new job posting detected",
                    "significance": "low",
                    "detail": {"url": link},
                })

        # ── team: link count change (proxy for headcount) ──
        elif category == "team":
            cur_hash = cur_page.get("text_hash", "")
            prev_hash = prev_page.get("text_hash", "")
            if cur_hash != prev_hash:
                cur_wc = cur_page.get("word_count", 0)
                prev_wc = prev_page.get("word_count", 0)
                delta = cur_wc - prev_wc
                if abs(delta) > 30:
                    changes.append({
                        "competitor_id": comp_id,
                        "competitor_name": comp_name,
                        "category": "team",
                        "change_type": "team_page_changed",
                        "title": f"{comp_name}: team page updated ({delta:+d} words)",
                        "significance": "medium" if delta > 0 else "low",
                        "detail": {"word_count_delta": delta, "url": cur_page.get("url", "")},
                    })

        # ── homepage: positioning / content change ──
        elif category == "homepage":
            cur_hash = cur_page.get("text_hash", "")
            prev_hash = prev_page.get("text_hash", "")
            if cur_hash != prev_hash:
                cur_wc = cur_page.get("word_count", 0)
                prev_wc = prev_page.get("word_count", 0)
                delta = cur_wc - prev_wc
                changes.append({
                    "competitor_id": comp_id,
                    "competitor_name": comp_name,
                    "category": "homepage",
                    "change_type": "homepage_changed",
                    "title": f"{comp_name}: homepage content changed",
                    "significance": "medium" if abs(delta) > 50 else "low",
                    "detail": {
                        "word_count_delta": delta,
                        "url": cur_page.get("url", ""),
                        "preview": cur_page.get("text_preview", "")[:200],
                    },
                })

    return changes


# ── main ──────────────────────────────────────────────────────────────────────

def load_previous_snapshot(competitor_id: str, snapshot_dir: Path) -> dict | None:
    candidates = sorted(snapshot_dir.glob(f"{competitor_id}_*.json"), reverse=True)
    today_name = f"{competitor_id}_{_today()}.json"
    for c in candidates:
        if c.name != today_name:
            return load_json(c)
    return None


def run(competitors: list, snapshot_dir: Path, output_dir: Path, timeout: int) -> dict:
    today = _today()
    all_changes = []
    competitor_summaries = []

    for comp in competitors:
        comp_id = comp["id"]
        print(f"[competitor_sites] scanning {comp['name']} ({comp['domain']}) ...", file=sys.stderr)

        current = snapshot_competitor(comp, timeout)
        if not current.get("pages"):
            print(f"  [{comp_id}] no pages fetched — skipping", file=sys.stderr)
            competitor_summaries.append({"competitor_id": comp_id, "status": "no_pages", "changes": []})
            continue

        # Save snapshot
        snap_path = snapshot_dir / f"{comp_id}_{today}.json"
        save_json(snap_path, current)

        previous = load_previous_snapshot(comp_id, snapshot_dir)
        changes = diff_snapshots(current, previous)
        all_changes.extend(changes)

        high = [c for c in changes if c.get("significance") == "high"]
        status = "baseline" if previous is None else ("changes" if changes else "no_changes")

        competitor_summaries.append({
            "competitor_id": comp_id,
            "competitor_name": comp["name"],
            "domain": comp["domain"],
            "status": status,
            "pages_fetched": sum(1 for p in current["pages"].values() if p and "error" not in p),
            "changes_count": len(changes),
            "high_significance_count": len(high),
            "changes": changes,
        })

        print(f"  [{comp_id}] {status} — {len(changes)} change(s), {len(high)} high", file=sys.stderr)

    digest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "date": today,
        "competitors_scanned": len(competitors),
        "total_changes": len(all_changes),
        "high_significance_changes": [c for c in all_changes if c.get("significance") == "high"],
        "competitor_summaries": competitor_summaries,
    }

    out_path = output_dir / f"_competitor_sites_{today}.json"
    save_json(out_path, digest)
    print(f"[competitor_sites] written to {out_path}", file=sys.stderr)

    return digest


def main():
    parser = argparse.ArgumentParser(description="Monitor competitor websites for changes")
    parser.add_argument("--competitor-id", help="Run for a single competitor ID")
    parser.add_argument("--competitors-file", default="data/competitors.json")
    parser.add_argument("--snapshot-dir", default=".tmp/competitor_snapshots")
    parser.add_argument("--output-dir", default="outputs/competitive")
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    competitors_data = load_json(Path(args.competitors_file), {})
    competitors = competitors_data.get("your_competitors", [])

    if not competitors:
        print(json.dumps({"error": "no competitors in config"}))
        sys.exit(2)

    if args.competitor_id:
        competitors = [c for c in competitors if c["id"] == args.competitor_id]
        if not competitors:
            print(json.dumps({"error": f"competitor_id '{args.competitor_id}' not found"}))
            sys.exit(2)

    # Skip competitors without a domain
    competitors = [c for c in competitors if c.get("domain")]

    snapshot_dir = Path(args.snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run(competitors, snapshot_dir, output_dir, args.timeout)

    print(json.dumps(result, ensure_ascii=False))
    has_changes = result["total_changes"] > 0
    sys.exit(1 if has_changes else 0)


if __name__ == "__main__":
    main()
