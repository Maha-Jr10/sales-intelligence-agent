"""
Post full intelligence outputs to a Slack channel via Incoming Webhook.

Modes:
    daily   — summary header + full daily report + all company briefs for that date
    weekly  — summary header + full weekly report
    brief   — single company brief  (requires --company-id)
    research — research bundle for one company (requires --company-id)

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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
CHUNK_SIZE = 2800   # Slack mrkdwn block limit is 3000; keep buffer
MAX_BLOCKS = 48     # Slack limit is 50; keep buffer for header/divider


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _extract_score(entry: dict) -> float:
    s = entry.get("score")
    if isinstance(s, dict):
        return float(s.get("total", 0))
    return float(entry.get("total_score", entry.get("score", 0)) or 0)


def top_scores(scores_path: Path, n: int = 10) -> list[dict]:
    data = load_json(scores_path, [])
    if isinstance(data, dict):
        data = data.get("scores", [])
    if not isinstance(data, list):
        return []
    return sorted(data, key=_extract_score, reverse=True)[:n]


def signal_counts(signals_path: Path) -> dict:
    data = load_json(signals_path, [])
    if isinstance(data, dict):
        data = data.get("signals", [])
    if not isinstance(data, list):
        return {}
    counts: dict = {}
    for s in data:
        t = s.get("signal_type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


# ── Markdown → Slack mrkdwn ───────────────────────────────────────────────────

def md_to_mrkdwn(text: str) -> str:
    lines = text.splitlines()
    out = []
    for line in lines:
        # ATX headings → bold
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            out.append(f"*{m.group(2).strip()}*")
            continue
        # Bold **text** or __text__
        line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
        line = re.sub(r"__(.+?)__", r"*\1*", line)
        # Italic *text* or _text_ (avoid double-processing)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", line)
        line = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"_\1_", line)
        # Unordered list bullets
        line = re.sub(r"^[\*\-]\s+", "• ", line)
        # Horizontal rule → nothing (we'll add a divider block separately)
        if re.match(r"^---+$", line.strip()):
            out.append("---")
            continue
        out.append(line)
    return "\n".join(out)


# ── Block builders ────────────────────────────────────────────────────────────

def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks of ≤ size chars, breaking on newlines."""
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > size and current:
            chunks.append("".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current).strip())
    return [c for c in chunks if c]


def text_to_section_blocks(text: str) -> list[dict]:
    """Convert plain/mrkdwn text to a list of section blocks."""
    blocks = []
    for chunk in chunk_text(md_to_mrkdwn(text)):
        if chunk == "---":
            blocks.append({"type": "divider"})
        else:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    return blocks


def scores_block(top: list[dict]) -> dict:
    lines = []
    for i, s in enumerate(top, 1):
        name = s.get("company_name") or s.get("company_id", "?")
        score = _extract_score(s)
        score_obj = s.get("score", {})
        tier = (score_obj.get("tier") if isinstance(score_obj, dict) else None) or s.get("tier", "")
        urgency = s.get("urgency", "")
        tier_tag = f" `{tier}`" if tier else ""
        urgency_tag = f" _{urgency}_" if urgency else ""
        lines.append(f"{i}. *{name}*{tier_tag}{urgency_tag} — {score:.0f} pts")
    return {"type": "section", "text": {"type": "mrkdwn", "text": "*Opportunity Rankings:*\n" + "\n".join(lines)}}


# ── Post ──────────────────────────────────────────────────────────────────────

def post_blocks(blocks: list) -> bool:
    """Post blocks to Slack, splitting into multiple messages if needed."""
    if not WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return False
    ok = True
    for i in range(0, max(len(blocks), 1), MAX_BLOCKS):
        chunk = blocks[i:i + MAX_BLOCKS]
        resp = requests.post(WEBHOOK_URL, json={"blocks": chunk}, timeout=10)
        if resp.status_code != 200:
            print(f"ERROR: Slack returned {resp.status_code}: {resp.text}", file=sys.stderr)
            ok = False
    return ok


def post_text(text: str) -> bool:
    """Post plain text to Slack (fallback for very large content)."""
    if not WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return False
    ok = True
    for chunk in chunk_text(text):
        resp = requests.post(WEBHOOK_URL, json={"text": chunk}, timeout=10)
        if resp.status_code != 200:
            print(f"ERROR: Slack returned {resp.status_code}: {resp.text}", file=sys.stderr)
            ok = False
    return ok


# ── Daily ─────────────────────────────────────────────────────────────────────

def post_daily(date: str, signals_dir: Path, reports_dir: Path, briefs_dir: Path) -> bool:
    signals_file = signals_dir / f"{date}.json"
    scores_file = signals_dir / f"scores-{date}.json"
    report_file = reports_dir / f"daily_{date}.md"

    counts = signal_counts(signals_file) if signals_file.exists() else {}
    top = top_scores(scores_file) if scores_file.exists() else []
    total_signals = sum(counts.values())

    # ── Message 1: Summary header + scores ───────────────────────────────────
    blocks: list = [
        {"type": "header", "text": {"type": "plain_text", "text": f":bar_chart: Daily Intelligence Scan — {date}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{total_signals} signals* collected across {len(counts)} signal types."}},
    ]
    if counts:
        breakdown = "  ".join(f"`{t}` ×{n}" for t, n in sorted(counts.items(), key=lambda x: -x[1])[:8])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Signal breakdown:*\n{breakdown}"}})
    if top:
        blocks.append(scores_block(top))
    blocks.append({"type": "divider"})

    ok = post_blocks(blocks)

    # ── Message 2: Full daily report ──────────────────────────────────────────
    if report_file.exists():
        report_text = read_text(report_file)
        report_blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f":memo: Full Daily Report — {date}"}},
        ] + text_to_section_blocks(report_text)
        ok = post_blocks(report_blocks) and ok

    # ── Messages 3+: Company briefs updated today ─────────────────────────────
    for company_dir in sorted(briefs_dir.iterdir()) if briefs_dir.exists() else []:
        if not company_dir.is_dir():
            continue
        brief_file = company_dir / f"{date}.md"
        if not brief_file.exists():
            continue
        company_name = company_dir.name.replace("-", " ").replace("_", " ").title()
        brief_text = read_text(brief_file)
        if not brief_text:
            continue
        brief_blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f":office: Brief — {company_name}"}},
        ] + text_to_section_blocks(brief_text)
        ok = post_blocks(brief_blocks) and ok

    return ok


# ── Weekly ────────────────────────────────────────────────────────────────────

def post_weekly(week: str, signals_dir: Path, reports_dir: Path) -> bool:
    report_file = reports_dir / f"weekly_{week}.md"
    scores_files = sorted(signals_dir.glob("scores-*.json"))

    all_scores: dict = {}
    for f in scores_files:
        data = load_json(f, [])
        if isinstance(data, dict):
            data = data.get("scores", [])
        if not isinstance(data, list):
            continue
        for s in data:
            cid = s.get("company_id", "")
            score = _extract_score(s)
            score_obj = s.get("score", {})
            tier = (score_obj.get("tier") if isinstance(score_obj, dict) else None) or s.get("tier", "")
            if cid not in all_scores or score > all_scores[cid]["score"]:
                all_scores[cid] = {
                    "company_id": cid,
                    "company_name": s.get("company_name", cid),
                    "score": score,
                    "tier": tier,
                    "urgency": s.get("urgency", ""),
                }

    top = sorted(all_scores.values(), key=lambda x: -x["score"])[:10]

    # ── Message 1: Summary header + scores ───────────────────────────────────
    blocks: list = [
        {"type": "header", "text": {"type": "plain_text", "text": f":calendar: Weekly Intelligence Report — {week}"}},
    ]
    if top:
        blocks.append(scores_block(top))
    blocks.append({"type": "divider"})
    ok = post_blocks(blocks)

    # ── Message 2: Full weekly report ─────────────────────────────────────────
    if report_file.exists():
        report_text = read_text(report_file)
        report_blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f":spiral_note_pad: Full Weekly Report — {week}"}},
        ] + text_to_section_blocks(report_text)
        ok = post_blocks(report_blocks) and ok

    return ok


# ── Brief ─────────────────────────────────────────────────────────────────────

def post_brief(company_id: str, date: str, briefs_dir: Path) -> bool:
    brief_file = briefs_dir / company_id / f"{date}.md"
    if not brief_file.exists():
        # Try most recent brief
        company_dir = briefs_dir / company_id
        if company_dir.exists():
            briefs = sorted(company_dir.glob("*.md"), reverse=True)
            if briefs:
                brief_file = briefs[0]
    if not brief_file.exists():
        print(f"ERROR: No brief found for {company_id}", file=sys.stderr)
        return False

    company_name = company_id.replace("-", " ").replace("_", " ").title()
    brief_text = read_text(brief_file)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f":office: Intelligence Brief — {company_name}"}},
    ] + text_to_section_blocks(brief_text)
    return post_blocks(blocks)


# ── Research ──────────────────────────────────────────────────────────────────

def post_research(company_id: str, research_file: Path) -> bool:
    if not research_file.exists():
        print(f"ERROR: Research file not found: {research_file}", file=sys.stderr)
        return False
    data = load_json(research_file, {})
    company_name = data.get("company_name", company_id.title())
    summary = data.get("summary", "")
    signals = data.get("signals", [])
    tech_stack = data.get("tech_stack", [])

    blocks: list = [
        {"type": "header", "text": {"type": "plain_text", "text": f":mag: Research — {company_name}"}},
    ]
    if summary:
        blocks += text_to_section_blocks(summary)
    if signals:
        sig_lines = "\n".join(f"• {s.get('title', s.get('type', '?'))}" for s in signals[:10])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Top signals:*\n{sig_lines}"}})
    if tech_stack:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Tech stack:* {', '.join(str(t) for t in tech_stack[:15])}"}})
    return post_blocks(blocks)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly", "brief", "research"], required=True)
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--week", default=datetime.now(timezone.utc).strftime("%Y-W%V"))
    parser.add_argument("--company-id")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--reports-dir", default="outputs/reports")
    parser.add_argument("--briefs-dir", default="outputs/briefs")
    parser.add_argument("--research-file")
    args = parser.parse_args()

    signals_dir = Path(args.signals_dir)
    reports_dir = Path(args.reports_dir)
    briefs_dir = Path(args.briefs_dir)

    if args.type == "daily":
        ok = post_daily(args.date, signals_dir, reports_dir, briefs_dir)
    elif args.type == "weekly":
        ok = post_weekly(args.week, signals_dir, reports_dir)
    elif args.type == "brief":
        if not args.company_id:
            print("ERROR: --company-id required for --type brief", file=sys.stderr)
            sys.exit(1)
        ok = post_brief(args.company_id, args.date, briefs_dir)
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
