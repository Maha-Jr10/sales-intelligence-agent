"""
Generate a weekly executive intelligence digest.

Sections:
  1. Pipeline snapshot (total accounts, P1 count, sequences active, meetings booked)
  2. Priority ranking table (by composite_score)
  3. Week-over-week delta (vs prior week history snapshot)
  4. KPI summary
  5. Top 3 recommended actions ([AGENT: insert recommendation] placeholder)

After generating, writes a history snapshot to outputs/reports/history/{YYYY_WXX}.json.

Usage:
    python tools/generate_executive_report.py --week 2026-W23
    python tools/generate_executive_report.py --week 2026-W23 \
        --output-dir outputs/reports/

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


SCHEMA_VERSION = "2.0"


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


def week_to_date_range(week_str: str) -> tuple[datetime, datetime]:
    try:
        year, wnum = week_str.split("-W")
        start = datetime.strptime(f"{year}-W{int(wnum)}-1", "%Y-W%W-%w").replace(tzinfo=timezone.utc)
        return start, start + timedelta(days=6)
    except Exception:
        now = datetime.now(timezone.utc)
        return now - timedelta(days=7), now


def load_scores(signals_dir: str, date_str: str) -> list:
    mf_path = Path(signals_dir) / f"multi_factor_scores-{date_str}.json"
    if mf_path.exists():
        data = load_json(str(mf_path), {})
        return data.get("scores", []) if isinstance(data, dict) else []

    v1_path = Path(signals_dir) / f"scores-{date_str}.json"
    if v1_path.exists():
        data = load_json(str(v1_path), [])
        if isinstance(data, list):
            return [{"company_id": s["company_id"], "company_name": s.get("company_name", ""),
                     "composite_score": s.get("score", {}).get("total", 0),
                     "composite_tier": s.get("score", {}).get("tier", "D"),
                     "v1_score": s.get("score", {}).get("total", 0),
                     "v1_tier": s.get("score", {}).get("tier", "D")} for s in data]
    return []


def load_memory_all(memory_dir: str = "outputs/memory") -> dict[str, dict]:
    memories = {}
    for mem_file in Path(memory_dir).glob("*.json"):
        company_id = mem_file.stem
        data = load_json(str(mem_file), {})
        if data:
            memories[company_id] = data
    return memories


def load_week_signals(signals_dir: str, start: datetime, end: datetime) -> list:
    all_signals = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        path = Path(signals_dir) / f"{date_str}.json"
        if path.exists():
            day_signals = load_json(str(path), [])
            all_signals.extend(day_signals)
        current += timedelta(days=1)
    return all_signals


def load_prior_history(history_dir: str, current_week: str) -> dict | None:
    try:
        year, wnum = current_week.split("-W")
        prior_week_num = int(wnum) - 1
        if prior_week_num <= 0:
            prior_year = int(year) - 1
            prior_week_str = f"{prior_year}-W52"
        else:
            prior_week_str = f"{year}-W{prior_week_num:02d}"
        prior_path = Path(history_dir) / f"{prior_week_str}.json"
        return load_json(str(prior_path))
    except Exception:
        return None


def count_metric_from_memory(memories: dict, field_path: str, value=None) -> int:
    count = 0
    keys = field_path.split(".")
    for mem in memories.values():
        obj = mem
        try:
            for k in keys:
                obj = obj[k]
            if value is None:
                if obj:
                    count += 1
            elif obj == value:
                count += 1
        except (KeyError, TypeError):
            pass
    return count


def tier_label(tier: str) -> str:
    return {"P1": "🔴 P1", "P2": "🟡 P2", "P3": "🟢 P3", "P4": "⬜ P4",
            "A": "🔴 A", "B": "🟡 B", "C": "🟢 C", "D": "⬜ D"}.get(tier, tier)


def build_report(week_str: str, signals_dir: str, briefs_dir: str,
                 memory_dir: str, companies_file: str, history_dir: str) -> tuple[str, dict]:
    start, end = week_to_date_range(week_str)
    today_scores = load_scores(signals_dir, end.strftime("%Y-%m-%d"))
    if not today_scores:
        today_scores = load_scores(signals_dir, _today())

    memories = load_memory_all(memory_dir)
    week_signals = load_week_signals(signals_dir, start, end)
    prior_history = load_prior_history(history_dir, week_str)
    companies_data = load_json(companies_file, {"companies": []})
    companies = {c["id"]: c for c in companies_data.get("companies", [])}

    scores_by_company = {s["company_id"]: s for s in today_scores}
    p1_companies = [s for s in today_scores if s.get("composite_tier") in ("P1", "A")]
    p2_companies = [s for s in today_scores if s.get("composite_tier") in ("P2", "B")]

    sequences_active = count_metric_from_memory(memories, "relationship_context.engagement_status", "in_sequence")
    meetings_booked = count_metric_from_memory(memories, "relationship_context.engagement_status", "meeting_booked")

    signals_this_week = len(week_signals)
    companies_with_signals = len(set(s.get("company_id", "") for s in week_signals if s.get("company_id")))

    briefs_this_week = 0
    for cid in companies:
        brief_dir = Path(briefs_dir) / cid
        if brief_dir.exists():
            for brief_file in brief_dir.glob("*.json"):
                try:
                    file_date = datetime.strptime(brief_file.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if start <= file_date <= end:
                        briefs_this_week += 1
                except ValueError:
                    pass

    signal_type_counts: dict[str, int] = {}
    for sig in week_signals:
        st = sig.get("signal_type", "unknown")
        signal_type_counts[st] = signal_type_counts.get(st, 0) + 1
    top_signal_type = max(signal_type_counts, key=signal_type_counts.get) if signal_type_counts else "none"

    avg_score = round(sum(s.get("composite_score", s.get("v1_score", 0)) for s in today_scores) / max(len(today_scores), 1), 1)

    prior_scores = {}
    if prior_history:
        pass

    lines = []
    lines.append(f"# Executive Intelligence Report — {week_str}")
    lines.append(f"\n_Generated: {_now()}_\n")
    lines.append("---\n")

    lines.append("## Pipeline Snapshot\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total monitored accounts | {len(companies)} |")
    lines.append(f"| P1 accounts (immediate action) | {len(p1_companies)} |")
    lines.append(f"| P2 accounts (prepare outreach) | {len(p2_companies)} |")
    lines.append(f"| Sequences active | {sequences_active} |")
    lines.append(f"| Meetings booked | {meetings_booked} |")
    lines.append(f"| Signals detected this week | {signals_this_week} |")
    lines.append(f"| Accounts with signals | {companies_with_signals} |")
    lines.append("")

    if prior_history:
        delta_p1 = len(p1_companies) - prior_history.get("p1_accounts", len(p1_companies))
        delta_signals = signals_this_week - prior_history.get("accounts_with_signals", companies_with_signals)
        lines.append(f"**Week-over-week:** P1 accounts {'+' if delta_p1 >= 0 else ''}{delta_p1} | "
                     f"Signals {'+' if delta_signals >= 0 else ''}{delta_signals}\n")

    lines.append("---\n")
    lines.append("## Priority Account Ranking\n")
    lines.append("| Rank | Company | Score | Tier | Status | Top Signal | Action Window |")
    lines.append("|------|---------|-------|------|--------|-----------|---------------|")

    sorted_scores = sorted(today_scores, key=lambda s: s.get("composite_score", s.get("v1_score", 0)), reverse=True)
    for i, score_obj in enumerate(sorted_scores, 1):
        cid = score_obj["company_id"]
        name = score_obj.get("company_name") or companies.get(cid, {}).get("name", cid)
        comp_score = score_obj.get("composite_score", score_obj.get("v1_score", 0))
        tier = score_obj.get("composite_tier") or score_obj.get("v1_tier", "?")
        top_signals = score_obj.get("top_signals", [])
        top_sig = top_signals[0].replace(":", " / ") if top_signals else "—"
        mem = memories.get(cid, {})
        status = mem.get("relationship_context", {}).get("engagement_status", "not_contacted")
        action_window = score_obj.get("action_window_days", "—")
        lines.append(f"| {i} | {name} | {comp_score:.0f} | {tier_label(tier)} | {status} | {top_sig} | {action_window}d |")

    lines.append("")
    lines.append("---\n")
    lines.append("## KPI Summary\n")
    lines.append(f"- **Signals detected this week:** {signals_this_week} across {companies_with_signals} accounts")
    lines.append(f"- **Top signal type:** {top_signal_type.replace('_', ' ').title()}")
    lines.append(f"- **Briefs generated this week:** {briefs_this_week}")
    lines.append(f"- **Sequences active:** {sequences_active}")
    lines.append(f"- **Average composite score:** {avg_score}/100")
    lines.append("")

    lines.append("---\n")
    lines.append("## Top 3 Recommended Actions\n")
    lines.append("_[AGENT: Fill in specific, named account actions before distributing]_\n")
    lines.append("1. [AGENT: Highest-priority account action — who to contact, what angle, what CTA]")
    lines.append("2. [AGENT: Second-priority account action]")
    lines.append("3. [AGENT: Third-priority action — may be a monitoring alert or brief generation]")
    lines.append("")
    lines.append("---\n")
    lines.append("_Revenue Intelligence OS v2 | Review and fill in agent placeholders before distributing._")

    history_snapshot = {
        "schema_version": SCHEMA_VERSION,
        "week": week_str,
        "captured_at": _now(),
        "active_accounts": len(companies),
        "p1_accounts": len(p1_companies),
        "p2_accounts": len(p2_companies),
        "accounts_with_signals": companies_with_signals,
        "signals_detected": signals_this_week,
        "briefs_generated_this_week": briefs_this_week,
        "sequences_active": sequences_active,
        "meetings_booked": meetings_booked,
        "top_signal_type": top_signal_type,
        "avg_composite_score": avg_score,
    }

    return "\n".join(lines), history_snapshot


def main():
    parser = argparse.ArgumentParser(description="Generate weekly executive intelligence report")
    parser.add_argument("--week", help="Week identifier YYYY-WXX (default: current week)")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--briefs-dir", default="outputs/briefs")
    parser.add_argument("--memory-dir", default="outputs/memory")
    parser.add_argument("--history-dir", default="outputs/reports/history")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", default="outputs/reports")
    args = parser.parse_args()

    week_str = args.week
    if not week_str:
        week_str = datetime.now(timezone.utc).strftime("%Y-W%V")

    Path(args.history_dir).mkdir(parents=True, exist_ok=True)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    report_md, history = build_report(
        week_str, args.signals_dir, args.briefs_dir,
        args.memory_dir, args.companies_file, args.history_dir
    )

    report_path = Path(args.output_dir) / f"executive_{week_str}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    history_path = Path(args.history_dir) / f"{week_str}.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    result = {
        "type": "executive",
        "week": week_str,
        "generated_at": _now(),
        "report_path": str(report_path),
        "history_snapshot_path": str(history_path),
        "word_count": len(report_md.split()),
        "history": history,
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
