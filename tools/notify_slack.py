"""
Post concise intelligence summaries to Slack with links to the GitHub repo for full details.

Modes:
    daily   — signal counts + ranked accounts + per-company top signals
    weekly  — ranked accounts + week-over-week snapshot
    brief   — single company key facts + top signals
    research — single company research highlights

Usage:
    python tools/notify_slack.py --type daily --date 2026-06-03
    python tools/notify_slack.py --type weekly --week 2026-W23
    python tools/notify_slack.py --type brief --company-id stripe --date 2026-06-03
    python tools/notify_slack.py --type research --company-id stripe

Exit codes: 0 success, 1 error
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
REPO_URL = os.getenv("GITHUB_REPO_URL", "https://github.com/Maha-Jr10/sales-intelligence-agent").rstrip("/")

URGENCY_EMOJI = {"high": ":red_circle:", "medium": ":large_yellow_circle:", "low": ":white_circle:", "monitor": ":white_circle:"}
TIER_EMOJI = {"A": ":star:", "B": ":large_blue_circle:", "C": ":white_circle:", "D": ":white_circle:"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _extract_score(entry: dict) -> float:
    s = entry.get("score")
    if isinstance(s, dict):
        return float(s.get("total", 0))
    return float(entry.get("total_score", entry.get("score", 0)) or 0)


def _extract_tier(entry: dict) -> str:
    s = entry.get("score")
    if isinstance(s, dict):
        return s.get("tier", "")
    return entry.get("tier", "")


def load_scores(scores_path: Path) -> list[dict]:
    data = load_json(scores_path, [])
    if isinstance(data, dict):
        data = data.get("scores", [])
    return data if isinstance(data, list) else []


def find_signals_file(signals_dir: Path, date: str) -> Path | None:
    for name in [f"{date}.json", f"signals_{date}.json"]:
        p = signals_dir / name
        if p.exists():
            return p
    return None


def load_signals(signals_path: Path) -> list[dict]:
    data = load_json(signals_path, [])
    if isinstance(data, dict):
        data = data.get("signals", [])
    return data if isinstance(data, list) else []


def post(blocks: list) -> bool:
    if not WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return False
    resp = requests.post(WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: Slack returned {resp.status_code}: {resp.text}", file=sys.stderr)
        return False
    return True


def link(label: str, url: str) -> str:
    return f"<{url}|{label}>"


# ── Daily ─────────────────────────────────────────────────────────────────────

def post_daily(date: str, signals_dir: Path) -> bool:
    signals_file = find_signals_file(signals_dir, date)
    scores_file  = signals_dir / f"scores-{date}.json"

    signals = load_signals(signals_file) if signals_file else []
    scores  = sorted(load_scores(scores_file), key=_extract_score, reverse=True)

    # Signal type counts
    counts: dict = {}
    for s in signals:
        t = s.get("signal_type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    total = sum(counts.values())

    # Signal breakdown line (no table — just inline tags)
    breakdown = "  ".join(
        f"`{t}` {n}" for t, n in sorted(counts.items(), key=lambda x: -x[1])[:8]
    ) or "none"

    # Build ranked account lines
    account_lines = []
    for i, s in enumerate(scores[:10], 1):
        name    = s.get("company_name") or s.get("company_id", "?")
        score   = _extract_score(s)
        tier    = _extract_tier(s)
        urgency = s.get("urgency", "")
        top_sig = s.get("top_signals", [])
        seen = []; [seen.append(ts.split(":")[0]) for ts in top_sig if ts.split(":")[0] not in seen]
        sig_str = ", ".join(seen[:3]) if seen else "—"
        urg_dot = URGENCY_EMOJI.get(urgency, "")
        tier_str = f"`{tier}`" if tier else ""
        account_lines.append(f"{i}. *{name}* {tier_str} {urg_dot}  {score:.0f} pts  _{sig_str}_")

    reports_url = f"{REPO_URL}/tree/master/outputs/reports"
    signals_url = f"{REPO_URL}/tree/master/outputs/signals"
    briefs_url  = f"{REPO_URL}/tree/master/outputs/briefs"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":bar_chart: Daily Intelligence Scan — {date}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{total} signals* collected across {len(counts)} types\n"
                    f"{breakdown}"
                ),
            },
        },
    ]

    if account_lines:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Ranked Accounts*\n" + "\n".join(account_lines)},
        })

    blocks += [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":open_file_folder:  Full details on GitHub:\n"
                    f"• {link('Daily report', reports_url)}\n"
                    f"• {link('Signal data', signals_url)}\n"
                    f"• {link('Company briefs', briefs_url)}"
                ),
            },
        },
    ]

    return post(blocks)


# ── Weekly ────────────────────────────────────────────────────────────────────

def post_weekly(week: str, signals_dir: Path) -> bool:
    scores_files = sorted(signals_dir.glob("scores-*.json"))

    all_scores: dict = {}
    for f in scores_files:
        for s in load_scores(f):
            cid   = s.get("company_id", "")
            score = _extract_score(s)
            tier  = _extract_tier(s)
            if cid not in all_scores or score > all_scores[cid]["score"]:
                all_scores[cid] = {
                    "company_name": s.get("company_name", cid),
                    "score": score,
                    "tier": tier,
                    "urgency": s.get("urgency", ""),
                    "top_signals": s.get("top_signals", []),
                }

    top = sorted(all_scores.values(), key=lambda x: -x["score"])[:10]

    account_lines = []
    for i, s in enumerate(top, 1):
        tier    = s["tier"]
        urgency = s["urgency"]
        top_sig = s.get("top_signals", [])
        seen = []; [seen.append(ts.split(":")[0]) for ts in top_sig if ts.split(":")[0] not in seen]
        sig_str = ", ".join(seen[:3]) if seen else "—"
        urg_dot = URGENCY_EMOJI.get(urgency, "")
        tier_str = f"`{tier}`" if tier else ""
        account_lines.append(f"{i}. *{s['company_name']}* {tier_str} {urg_dot}  {s['score']:.0f} pts  _{sig_str}_")

    outputs_url = f"{REPO_URL}/tree/master/outputs"
    reports_url = f"{REPO_URL}/tree/master/outputs/reports"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":calendar: Weekly Intelligence Report — {week}"},
        },
    ]

    if account_lines:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Top Accounts This Week*\n" + "\n".join(account_lines)},
        })

    blocks += [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":open_file_folder:  Full details on GitHub:\n"
                    f"• {link('Weekly report', reports_url)}\n"
                    f"• {link('All outputs', outputs_url)}"
                ),
            },
        },
    ]

    return post(blocks)


# ── Brief ─────────────────────────────────────────────────────────────────────

def post_brief(company_id: str, date: str, briefs_dir: Path) -> bool:
    brief_file = briefs_dir / company_id / f"{date}.md"
    if not brief_file.exists():
        company_dir = briefs_dir / company_id
        if company_dir.exists():
            candidates = sorted(company_dir.glob("*.md"), reverse=True)
            if candidates:
                brief_file = candidates[0]
    if not brief_file.exists():
        print(f"ERROR: No brief found for {company_id}", file=sys.stderr)
        return False

    # Extract first ~600 chars as a plain-text preview (skip markdown syntax)
    raw = brief_file.read_text(encoding="utf-8")
    lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    preview = " ".join(lines)[:600]
    if len(preview) == 600:
        preview = preview.rsplit(" ", 1)[0] + "…"

    company_name = company_id.replace("-", " ").replace("_", " ").title()
    brief_url = f"{REPO_URL}/blob/master/outputs/briefs/{company_id}/{brief_file.name}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":office: Brief — {company_name}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": preview},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":open_file_folder:  {link('Read full brief on GitHub', brief_url)}",
            },
        },
    ]

    return post(blocks)


# ── Research ──────────────────────────────────────────────────────────────────

def post_research(company_id: str, research_file: Path) -> bool:
    data = load_json(research_file, {}) if research_file.exists() else {}
    company_name = data.get("company_name", company_id.replace("-", " ").title())

    signals = data.get("signals", [])
    tech    = data.get("tech_stack", data.get("tech_stack_hints", []))
    summary = data.get("summary", "")

    sig_lines = "\n".join(f"• {s.get('title', s.get('type', '?'))}" for s in signals[:8]) or "No signals found"
    tech_str  = ", ".join(str(t) for t in tech[:12]) if tech else "—"

    research_url = f"{REPO_URL}/tree/master/outputs"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":mag: Research Complete — {company_name}"},
        },
    ]

    if summary:
        preview = summary[:500] + ("…" if len(summary) > 500 else "")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": preview}})

    blocks += [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top signals:*\n{sig_lines}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Tech stack:* {tech_str}"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":open_file_folder:  {link('View all outputs on GitHub', research_url)}",
            },
        },
    ]

    return post(blocks)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "brief", "research"], required=True)
    parser.add_argument("--date",         default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--week",         default=datetime.now(timezone.utc).strftime("%Y-W%V"))
    parser.add_argument("--company-id")
    parser.add_argument("--signals-dir",  default="outputs/signals")
    parser.add_argument("--reports-dir",  default="outputs/reports")
    parser.add_argument("--briefs-dir",   default="outputs/briefs")
    parser.add_argument("--research-file")
    args = parser.parse_args()

    if args.type == "daily":
        ok = post_daily(args.date, Path(args.signals_dir))

    elif args.type == "weekly":
        ok = post_weekly(args.week, Path(args.signals_dir))

    elif args.type == "brief":
        if not args.company_id:
            print("ERROR: --company-id required for --type brief", file=sys.stderr)
            sys.exit(1)
        ok = post_brief(args.company_id, args.date, Path(args.briefs_dir))

    elif args.type == "research":
        if not args.company_id:
            print("ERROR: --company-id required for --type research", file=sys.stderr)
            sys.exit(1)
        research_file = Path(args.research_file) if args.research_file else Path(f".tmp/research_{args.company_id}.json")
        ok = post_research(args.company_id, research_file)

    else:
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
