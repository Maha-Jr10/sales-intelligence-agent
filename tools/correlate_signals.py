"""
Detect named signal combination patterns per company, compute correlation confidence,
and output explainable buying-event narratives.

Output feeds into score_multi_factor.py (priority_boost field).

Usage:
    python tools/correlate_signals.py --all-companies \
        --signals-file outputs/signals/2026-06-03.json \
        --output-file outputs/signals/correlations-2026-06-03.json
    python tools/correlate_signals.py --company-id stripe --lookback-days 7

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
    except Exception as e:
        print(f"[correlate] cannot load {path}: {e}", file=sys.stderr)
        return default


def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.replace("+00:00", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return None


def load_signals_for_company(company_id: str, signals: list) -> list:
    return [s for s in signals if s.get("company_id") == company_id]


def apply_template(template: str, signal: dict, company_name: str, all_signals: list) -> str:
    replacements = {
        "{company}": company_name,
        "{signal_count}": str(len(all_signals)),
        "{days}": "30",
        "{signal_types}": ", ".join(set(s.get("signal_type", "") for s in all_signals[:3])),
        "{funding_type}": next(
            (s.get("signal_subtype", "funding round").replace("_", " ")
             for s in all_signals if s.get("signal_type") == "funding_event"),
            "funding"
        ),
        "{executive_role}": next(
            (s.get("structured_data", {}).get("job_title", "executive")
             for s in all_signals if s.get("signal_type") == "leadership_change"),
            "executive"
        ),
        "{product_name}": next(
            (s.get("title", "new product")
             for s in all_signals if s.get("signal_type") == "product_launch"),
            "new product"
        ),
    }
    result = template
    for key, value in replacements.items():
        result = result.replace(key, str(value))
    return result


def match_pattern(pattern: dict, company_signals: list, lookback_days: int) -> dict | None:
    now = datetime.now(timezone.utc)
    window_days = pattern.get("time_window_days", lookback_days)
    cutoff = now - timedelta(days=window_days)

    recent_signals = []
    for sig in company_signals:
        dt = parse_date(sig.get("detected_at") or sig.get("published") or "")
        if dt and dt >= cutoff:
            recent_signals.append((dt, sig))

    required_types = pattern.get("required_signal_types", [])
    required_count = pattern.get("required_signal_count")

    if required_count:
        if len(recent_signals) < required_count:
            return None
        matched_signals = [s for _, s in recent_signals[:required_count]]
    else:
        matched_signals = []
        matched_types = set()
        for dt, sig in sorted(recent_signals, key=lambda x: x[0], reverse=True):
            sig_type = sig.get("signal_type", "")
            if sig_type in required_types and sig_type not in matched_types:
                matched_signals.append(sig)
                matched_types.add(sig_type)
        if matched_types < set(required_types):
            return None

    why_matched = []
    for sig in matched_signals:
        dt = parse_date(sig.get("detected_at") or sig.get("published") or "")
        date_str = dt.strftime("%Y-%m-%d") if dt else "unknown date"
        sig_type = sig.get("signal_type", "unknown")
        sig_subtype = sig.get("signal_subtype", "")
        label = f"{sig_type}" + (f":{sig_subtype}" if sig_subtype else "")

        if required_count:
            days_ago = (now - dt).days if dt else 0
            why_matched.append(f"{label} detected on {date_str} ({days_ago} days ago)")
        else:
            for req_type in required_types:
                if sig_type == req_type:
                    why_matched.append(f"{req_type} detected on {date_str} (within {window_days}-day window)")

    return {
        "pattern_id": pattern["id"],
        "pattern_name": pattern["name"],
        "confidence_score": pattern.get("confidence_score", 0.75),
        "priority_boost": pattern.get("priority_boost", 10),
        "matched_signals": [s.get("signal_id", "") for s in matched_signals],
        "why_matched": why_matched,
        "narrative": "",
        "_matched_signal_objects": matched_signals,
    }


def correlate_company(company_id: str, company_name: str, company_signals: list,
                      patterns: list, lookback_days: int) -> dict:
    if not company_signals:
        return {
            "company_id": company_id,
            "correlation_detected": False,
            "highest_confidence": 0.0,
            "patterns_matched": [],
            "composite_narrative": "",
            "total_priority_boost": 0,
        }

    matched_patterns = []
    for pattern in patterns:
        result = match_pattern(pattern, company_signals, lookback_days)
        if result:
            result["narrative"] = apply_template(
                pattern.get("narrative_template", ""),
                company_signals[0] if company_signals else {},
                company_name,
                result["_matched_signal_objects"],
            )
            del result["_matched_signal_objects"]
            matched_patterns.append(result)

    matched_patterns.sort(key=lambda p: p["confidence_score"], reverse=True)
    highest_confidence = matched_patterns[0]["confidence_score"] if matched_patterns else 0.0
    total_boost = sum(p["priority_boost"] for p in matched_patterns)

    if len(matched_patterns) == 1:
        composite_narrative = matched_patterns[0]["narrative"]
    elif len(matched_patterns) > 1:
        pattern_names = ", ".join(p["pattern_name"] for p in matched_patterns[:2])
        composite_narrative = (
            f"Multiple buying patterns detected for {company_name}: {pattern_names}. "
            + matched_patterns[0]["narrative"]
        )
    else:
        composite_narrative = ""

    return {
        "company_id": company_id,
        "correlation_detected": bool(matched_patterns),
        "highest_confidence": round(highest_confidence, 3),
        "patterns_matched": matched_patterns,
        "composite_narrative": composite_narrative,
        "total_priority_boost": total_boost,
    }


def main():
    parser = argparse.ArgumentParser(description="Detect signal combination patterns per company")
    parser.add_argument("--company-id", help="Correlate for specific company only")
    parser.add_argument("--all-companies", action="store_true")
    parser.add_argument("--signals-file", help="JSON file of normalized signals")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--combinations-file", default="data/signal_combinations.json")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-file", help="Write output to this file")
    args = parser.parse_args()

    combinations = load_json(args.combinations_file, {})
    patterns = combinations.get("patterns", [])
    if not patterns:
        print(json.dumps({"error": "no patterns in signal_combinations.json"}))
        sys.exit(2)

    signals_file = args.signals_file
    if not signals_file:
        signals_file = str(Path(args.signals_dir) / f"{_today()}.json")

    if not Path(signals_file).exists():
        result = {
            "schema_version": "2.0",
            "generated_at": _now(),
            "date": _today(),
            "companies": [],
            "note": f"signals file not found: {signals_file}",
        }
        print(json.dumps(result))
        sys.exit(0)

    all_signals = load_json(signals_file, [])

    companies_data = load_json(args.companies_file, {"companies": []})
    company_map = {c["id"]: c.get("name", c["id"]) for c in companies_data.get("companies", [])}

    if args.company_id:
        company_ids = [args.company_id]
    else:
        company_ids = list(set(s.get("company_id", "") for s in all_signals if s.get("company_id")))
        for cid in company_map:
            if cid not in company_ids:
                company_ids.append(cid)

    company_results = []
    for cid in company_ids:
        company_name = company_map.get(cid, cid)
        company_signals = load_signals_for_company(cid, all_signals)
        result = correlate_company(cid, company_name, company_signals, patterns, args.lookback_days)
        company_results.append(result)

    company_results.sort(key=lambda r: r["total_priority_boost"], reverse=True)

    output = {
        "schema_version": "2.0",
        "generated_at": _now(),
        "date": _today(),
        "lookback_days": args.lookback_days,
        "companies": company_results,
        "companies_with_correlations": sum(1 for r in company_results if r["correlation_detected"]),
    }

    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"[correlate] wrote correlations to {args.output_file}", file=sys.stderr)

    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
