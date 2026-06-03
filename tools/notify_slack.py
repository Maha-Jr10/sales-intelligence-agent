"""
Post a report summary to a Slack channel via Incoming Webhook.

Usage:
    python tools/notify_slack.py --type daily --date 2026-06-03
    python tools/notify_slack.py --type weekly --week 2026-W23

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


def top_scores(scores_path: Path, n: int = 5) -> list[dict]:
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


def build_daily_blocks(date: str, signals_dir: Path) -> list:
    signals_file = signals_dir / f"{date}.json"
    scores_file = signals_dir / f"scores-{date}.json"

    counts = signal_counts(signals_file) if signals_file.exists() else {}
    top = top_scores(scores_file) if scores_file.exists() else []

    total_signals = sum(counts.values())

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":bar_chart: Daily Intelligence Scan — {date}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{total_signals} signals* collected across {len(counts)} signal types.",
            },
        },
    ]

    if counts:
        breakdown = "  ".join(f"`{t}` ×{n}" for t, n in sorted(counts.items(), key=lambda x: -x[1])[:6])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Signal breakdown:*\n{breakdown}"}})

    if top:
        lines = []
        for i, s in enumerate(top, 1):
            name = s.get("company_name") or s.get("company_id", "?")
            score = _extract_score(s)
            score_obj = s.get("score", {})
            tier = (score_obj.get("tier") if isinstance(score_obj, dict) else None) or s.get("tier", "")
            tier_tag = f" `{tier}`" if tier else ""
            lines.append(f"{i}. *{name}*{tier_tag} — score {score:.1f}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Top opportunities:*\n" + "\n".join(lines)},
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Sales Intelligence Agent · outputs/reports/daily_{}.md".format(date)}],
        }
    )
    return blocks


def build_weekly_blocks(week: str, signals_dir: Path) -> list:
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
                all_scores[cid] = {"name": s.get("company_name", cid), "score": score, "tier": tier}

    top = sorted(all_scores.values(), key=lambda x: -x["score"])[:5]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":calendar: Weekly Intelligence Report — {week}"},
        },
    ]

    if top:
        lines = []
        for i, s in enumerate(top, 1):
            tier_tag = f" `{s['tier']}`" if s["tier"] else ""
            lines.append(f"{i}. *{s['name']}*{tier_tag} — peak score {s['score']:.1f}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Top accounts this week:*\n" + "\n".join(lines)},
            }
        )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Sales Intelligence Agent · outputs/reports/weekly_{}.md".format(week)}],
        }
    )
    return blocks


def post(blocks: list) -> bool:
    if not WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return False
    resp = requests.post(WEBHOOK_URL, json={"blocks": blocks}, timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: Slack returned {resp.status_code}: {resp.text}", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["daily", "weekly"], required=True)
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--week", default=datetime.now(timezone.utc).strftime("%Y-W%V"))
    parser.add_argument("--signals-dir", default="outputs/signals")
    args = parser.parse_args()

    signals_dir = Path(args.signals_dir)

    if args.type == "daily":
        blocks = build_daily_blocks(args.date, signals_dir)
    else:
        blocks = build_weekly_blocks(args.week, signals_dir)

    ok = post(blocks)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
