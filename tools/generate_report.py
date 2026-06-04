"""
Assemble daily or weekly intelligence reports from stored signal and brief files.

Usage:
    python tools/generate_report.py --type daily --date 2025-01-15
    python tools/generate_report.py --type weekly --week 2025-W03
    python tools/generate_report.py --type daily  # defaults to today

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_signals_for_date(date_str: str, signals_dir: str = "outputs/signals") -> list:
    for candidate in [f"{date_str}.json", f"signals_{date_str}.json"]:
        path = Path(signals_dir) / candidate
        if path.exists():
            data = load_json(str(path), [])
            if isinstance(data, dict):
                return data.get("signals", [])
            return data
    return []


def load_scores_for_date(date_str: str, signals_dir: str = "outputs/signals") -> list:
    path = Path(signals_dir) / f"scores-{date_str}.json"
    if path.exists():
        data = load_json(str(path), [])
        if isinstance(data, list):
            return data
        return data.get("scores", [])
    return []


def load_brief(company_id: str, date_str: str, briefs_dir: str = "outputs/briefs") -> dict | None:
    path = Path(briefs_dir) / company_id / f"{date_str}.json"
    if path.exists():
        return load_json(str(path))
    for existing in sorted(Path(briefs_dir).glob(f"{company_id}/*.json"), reverse=True):
        data = load_json(str(existing))
        if data:
            return data
    return None


def tier_badge(tier: str) -> str:
    return {"A": "🔴 TIER A", "B": "🟡 TIER B", "C": "🟢 TIER C", "D": "⬜ TIER D"}.get(tier, tier)


def format_signal_line(signal: dict) -> str:
    title = signal.get("title", "")
    sig_type = signal.get("signal_type", "").replace("_", " ").title()
    score = signal.get("importance_score", 0)
    return f"  - [{sig_type}] {title} (score: {score})"


def build_daily_report(date_str: str, signals_dir: str, briefs_dir: str, companies_file: str) -> str:
    signals = load_signals_for_date(date_str, signals_dir)
    scores_raw = load_scores_for_date(date_str, signals_dir)

    scores_by_company = {}
    for s in scores_raw:
        cid = s.get("company_id")
        if cid:
            scores_by_company[cid] = s

    companies_data = load_json(companies_file, {"companies": []})
    companies = {c["id"]: c for c in companies_data.get("companies", [])}

    signals_by_company = {}
    for sig in signals:
        cid = sig.get("company_id", "unknown")
        if cid not in signals_by_company:
            signals_by_company[cid] = []
        signals_by_company[cid].append(sig)

    all_company_ids = set(signals_by_company.keys()) | set(scores_by_company.keys())

    scored_companies = []
    for cid in all_company_ids:
        score_data = scores_by_company.get(cid, {})
        total = score_data.get("score", {}).get("total", 0) if score_data else 0
        tier = score_data.get("score", {}).get("tier", "D") if score_data else "D"
        name = companies.get(cid, {}).get("name") or score_data.get("company_name") or cid
        company_signals = signals_by_company.get(cid, [])
        scored_companies.append((cid, name, total, tier, company_signals, score_data))

    scored_companies.sort(key=lambda x: x[2], reverse=True)

    tier_a = [c for c in scored_companies if c[3] == "A"]
    tier_b = [c for c in scored_companies if c[3] == "B"]
    tier_c_d = [c for c in scored_companies if c[3] in ("C", "D")]

    lines = []
    lines.append(f"# Daily Intelligence Report — {date_str}")
    lines.append(f"\n_Generated: {_now()}_\n")
    lines.append("---\n")

    lines.append("## Executive Summary\n")
    total_signals = len(signals)
    lines.append(f"**{total_signals} signals detected** across **{len(all_company_ids)} accounts**.")
    if tier_a:
        lines.append(f"**{len(tier_a)} Tier A accounts** require immediate attention.")
    if tier_b:
        lines.append(f"**{len(tier_b)} Tier B accounts** are worth monitoring closely.")
    if not signals:
        lines.append("No signals detected today. Check monitoring configuration.")
    lines.append("")
    lines.append("---\n")

    if tier_a:
        lines.append("## Tier A — Immediate Action\n")
        for i, (cid, name, score, tier, co_signals, score_data) in enumerate(tier_a, 1):
            brief = load_brief(cid, date_str, briefs_dir)
            lines.append(f"### {i}. {name} — {tier_badge(tier)} (Score: {score:.0f}/100)\n")
            if brief:
                lines.append(f"**Executive Summary:** {brief.get('executive_summary', 'Brief available.')}\n")
                angles = brief.get("recommended_outreach_angles", [])
                if angles:
                    lines.append(f"**Top Outreach Angle:** {angles[0]}\n")
                next_actions = brief.get("next_actions", [])
                if next_actions:
                    lines.append(f"**Recommended Action:** {next_actions[0]}\n")
            else:
                lines.append("_Brief not yet generated. Run `intelligence_brief_generation` workflow._\n")

            if co_signals:
                lines.append("**Signals detected:**")
                for sig in co_signals[:5]:
                    lines.append(format_signal_line(sig))
                lines.append("")

            lines.append("")

    if tier_b:
        lines.append("## Tier B — Monitor Closely\n")
        for cid, name, score, tier, co_signals, score_data in tier_b:
            lines.append(f"### {name} — {tier_badge(tier)} (Score: {score:.0f}/100)\n")
            if co_signals:
                for sig in co_signals[:3]:
                    lines.append(format_signal_line(sig))
                lines.append("")
            lines.append("")

    if tier_c_d:
        lines.append("## Tier C/D — Low Priority\n")
        for cid, name, score, tier, co_signals, score_data in tier_c_d:
            sig_count = len(co_signals)
            lines.append(f"- **{name}** (Score: {score:.0f}) — {sig_count} signal(s) detected")
        lines.append("")

    monitored_without_signals = [
        c["name"] for c in companies_data.get("companies", [])
        if c["id"] not in signals_by_company
    ]
    if monitored_without_signals:
        lines.append("## Accounts With No Signals Today\n")
        for name in monitored_without_signals:
            lines.append(f"- {name}")
        lines.append("")

    if scored_companies:
        lines.append("\n---\n")
        lines.append("## Signal Summary Table\n")
        lines.append("| Company | Top Signal | Score | Tier |")
        lines.append("|---------|-----------|-------|------|")
        for cid, name, score, tier, co_signals, _ in scored_companies:
            top_sig = co_signals[0].get("title", "—")[:60] if co_signals else "—"
            lines.append(f"| {name} | {top_sig} | {score:.0f} | {tier} |")
        lines.append("")

    lines.append("\n---\n")
    lines.append("_Sales Intelligence Agent | github.com/your-repo_")

    return "\n".join(lines)


def build_weekly_report(week_str: str, signals_dir: str, briefs_dir: str, companies_file: str) -> str:
    try:
        year, week_num = week_str.split("-W")
        # %G/%V/%u = ISO 8601 year/week/weekday; %W is NOT ISO and gives wrong start dates
        start_of_week = datetime.strptime(f"{year}-W{int(week_num)}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)
    except Exception:
        start_of_week = datetime.now(timezone.utc) - timedelta(days=7)

    all_signals = []
    for i in range(7):
        day = (start_of_week + timedelta(days=i)).strftime("%Y-%m-%d")
        daily = load_signals_for_date(day, signals_dir)
        all_signals.extend(daily)

    all_company_ids = list(set(s.get("company_id", "") for s in all_signals))
    companies_data = load_json(companies_file, {"companies": []})
    companies = {c["id"]: c for c in companies_data.get("companies", [])}

    lines = []
    lines.append(f"# Weekly Intelligence Report — {week_str}")
    lines.append(f"\n_Generated: {_now()}_\n")
    lines.append("---\n")
    lines.append("## Week in Review\n")
    lines.append(f"- **Total signals detected:** {len(all_signals)}")
    lines.append(f"- **Accounts with activity:** {len(all_company_ids)}")
    lines.append(f"- **Monitoring period:** {start_of_week.strftime('%Y-%m-%d')} to {(start_of_week + timedelta(days=6)).strftime('%Y-%m-%d')}")
    lines.append("")

    signals_by_company = {}
    for sig in all_signals:
        cid = sig.get("company_id", "unknown")
        if cid not in signals_by_company:
            signals_by_company[cid] = []
        signals_by_company[cid].append(sig)

    lines.append("## Accounts by Signal Volume\n")
    sorted_companies = sorted(signals_by_company.items(), key=lambda x: len(x[1]), reverse=True)
    for cid, sigs in sorted_companies:
        name = companies.get(cid, {}).get("name", cid)
        signal_types = list(set(s.get("signal_type", "") for s in sigs))
        lines.append(f"- **{name}**: {len(sigs)} signals — {', '.join(signal_types[:3])}")
    lines.append("")

    no_activity = [
        c["name"] for c in companies_data.get("companies", [])
        if c["id"] not in signals_by_company
    ]
    if no_activity:
        lines.append("## Accounts With No Activity This Week\n")
        lines.append("_Consider reviewing monitoring configuration or removing from list:_")
        for name in no_activity:
            lines.append(f"- {name}")
        lines.append("")

    lines.append("## Recommended Focus for Next Week\n")
    for i, (cid, sigs) in enumerate(sorted_companies[:3], 1):
        name = companies.get(cid, {}).get("name", cid)
        lines.append(f"{i}. **{name}** — {len(sigs)} signals detected. Generate brief if not done.")
    lines.append("")

    lines.append("\n---\n")
    lines.append("_Sales Intelligence Agent | github.com/your-repo_")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate daily or weekly intelligence reports")
    parser.add_argument("--type", choices=["daily", "weekly"], required=True)
    parser.add_argument("--date", help="Date for daily report (YYYY-MM-DD, default: today)")
    parser.add_argument("--week", help="Week for weekly report (YYYY-WXX)")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--briefs-dir", default="outputs/briefs")
    parser.add_argument("--reports-dir", default="outputs/reports")
    parser.add_argument("--companies-file", default="data/companies.json")
    args = parser.parse_args()

    Path(args.reports_dir).mkdir(parents=True, exist_ok=True)

    if args.type == "daily":
        date_str = args.date or _today()
        report_md = build_daily_report(date_str, args.signals_dir, args.briefs_dir, args.companies_file)
        out_path = Path(args.reports_dir) / f"daily_{date_str}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        result = {
            "type": "daily",
            "date": date_str,
            "generated_at": _now(),
            "report_path": str(out_path),
            "word_count": len(report_md.split()),
        }
    else:
        week_str = args.week
        if not week_str:
            now = datetime.now(timezone.utc)
            week_str = now.strftime("%Y-W%V")

        report_md = build_weekly_report(week_str, args.signals_dir, args.briefs_dir, args.companies_file)
        out_path = Path(args.reports_dir) / f"weekly_{week_str}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        result = {
            "type": "weekly",
            "week": week_str,
            "generated_at": _now(),
            "report_path": str(out_path),
            "word_count": len(report_md.split()),
        }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
