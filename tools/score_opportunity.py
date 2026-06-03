"""
Apply ICP criteria and signal weights to compute a numeric opportunity score.

Usage:
    python tools/score_opportunity.py --company-id stripe
    python tools/score_opportunity.py --company-id stripe \
                                       --signals-file outputs/signals/2025-01-15.json
    python tools/score_opportunity.py --signals-file outputs/signals/2025-01-15.json \
                                       --all-companies

Exit codes: 0 success, 2 fatal
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
        print(f"[score] cannot load {path}: {e}", file=sys.stderr)
        return default


def parse_employee_count(estimate: str) -> tuple[int, int]:
    if not estimate:
        return (0, 0)
    numbers = []
    for part in estimate.replace(",", "").split("-"):
        part = part.strip().rstrip("+").strip()
        try:
            numbers.append(int(part))
        except ValueError:
            pass
    if len(numbers) >= 2:
        return (numbers[0], numbers[1])
    if len(numbers) == 1:
        return (numbers[0], numbers[0])
    return (0, 0)


def score_icp_fit(company: dict, icp: dict) -> dict:
    breakdown = {}
    total = 0.0

    firmographics = icp.get("firmographics", {})

    emp_low, emp_high = parse_employee_count(company.get("employee_count_estimate", ""))
    emp_config = firmographics.get("employee_count", {})
    emp_weight = emp_config.get("score_weight", 0.10)
    ideal_low, ideal_high = emp_config.get("ideal_range", [50, 500])
    accept_low, accept_high = emp_config.get("acceptable_range", [20, 2000])
    emp_mid = (emp_low + emp_high) / 2 if emp_high else emp_low

    if ideal_low <= emp_mid <= ideal_high:
        emp_score = 1.0
    elif accept_low <= emp_mid <= accept_high:
        emp_score = 0.5
    else:
        emp_score = 0.0
    emp_points = round(emp_score * emp_weight * 100, 1)
    breakdown["employee_count"] = emp_points
    total += emp_points

    funding_config = firmographics.get("funding_stages", {})
    funding_weight = funding_config.get("score_weight", 0.10)
    company_funding = (company.get("funding_stage") or "").strip()
    ideal_fundings = [f.lower() for f in funding_config.get("ideal", [])]
    acceptable_fundings = [f.lower() for f in funding_config.get("acceptable", [])]

    if company_funding.lower() in ideal_fundings:
        funding_score = 1.0
    elif company_funding.lower() in acceptable_fundings:
        funding_score = 0.5
    else:
        funding_score = 0.0
    funding_points = round(funding_score * funding_weight * 100, 1)
    breakdown["funding_stage"] = funding_points
    total += funding_points

    industry_config = firmographics.get("industries", {})
    industry_weight = industry_config.get("score_weight", 0.20)
    company_industry = (company.get("industry") or "").lower()
    ideal_industries = [i.lower() for i in industry_config.get("ideal", [])]
    acceptable_industries = [i.lower() for i in industry_config.get("acceptable", [])]
    excluded_industries = [i.lower() for i in industry_config.get("excluded", [])]

    if any(ei in company_industry for ei in excluded_industries):
        industry_score = 0.0
    elif any(ii in company_industry for ii in ideal_industries):
        industry_score = 1.0
    elif any(ai in company_industry for ai in acceptable_industries):
        industry_score = 0.5
    else:
        industry_score = 0.2
    industry_points = round(industry_score * industry_weight * 100, 1)
    breakdown["industry"] = industry_points
    total += industry_points

    geo_config = firmographics.get("geographies", {})
    geo_weight = geo_config.get("score_weight", 0.05)
    company_hq = (company.get("headquarters") or "").lower()
    ideal_geos = [g.lower() for g in geo_config.get("ideal", [])]
    acceptable_geos = [g.lower() for g in geo_config.get("acceptable", [])]

    geo_score = 0.0
    for geo in ideal_geos:
        if geo.lower() in company_hq or any(geo.lower() in hq for hq in [company_hq]):
            geo_score = 1.0
            break
    if geo_score == 0.0:
        for geo in acceptable_geos:
            if geo.lower() in company_hq:
                geo_score = 0.5
                break
    if not company_hq:
        geo_score = 0.3
    geo_points = round(geo_score * geo_weight * 100, 1)
    breakdown["geography"] = geo_points
    total += geo_points

    return {"score": round(total, 1), "breakdown": breakdown}


def score_signals(signals: list, weights: dict, icp: dict) -> dict:
    if not signals:
        return {"score": 0.0, "breakdown": {}, "top_signals": []}

    signal_weights = weights.get("weights", {})
    recency_decay = weights.get("recency_decay", {})
    breakdown = {}
    total = 0.0
    signal_scores = []

    now = datetime.now(timezone.utc)

    for sig in signals:
        sig_type = sig.get("signal_type", "news_mention")
        sig_subtype = sig.get("signal_subtype", "generic")
        type_weights = signal_weights.get(sig_type, {})
        base_score = type_weights.get(sig_subtype, type_weights.get("generic", 3.0))

        detected_str = sig.get("detected_at") or sig.get("published") or ""
        decay_factor = 1.0
        if detected_str:
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                try:
                    dt_str = detected_str.replace("+00:00", "+0000")
                    dt = datetime.strptime(dt_str, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    days_old = (now - dt).days
                    if days_old <= 7:
                        decay_factor = recency_decay.get("last_7_days", 1.0)
                    elif days_old <= 30:
                        decay_factor = recency_decay.get("last_30_days", 0.8)
                    elif days_old <= 90:
                        decay_factor = recency_decay.get("last_90_days", 0.5)
                    else:
                        decay_factor = recency_decay.get("older", 0.2)
                    break
                except Exception:
                    pass

        final_score = round(base_score * decay_factor, 2)
        key = f"{sig_type}:{sig_subtype}"
        breakdown[key] = breakdown.get(key, 0) + final_score
        signal_scores.append((sig["signal_id"] if "signal_id" in sig else key, final_score, sig))

    signal_scores.sort(key=lambda x: x[1], reverse=True)
    top_signals = [f"{x[2].get('signal_type')}:{x[2].get('signal_subtype')}" for x in signal_scores[:5]]
    total = sum(breakdown.values())

    signal_weight_total = 0.35
    icp_behavioral_config = icp.get("behavioral_signals", {})
    signal_score_normalized = min(total * signal_weight_total, 35.0)

    return {
        "score": round(signal_score_normalized, 1),
        "breakdown": {k: round(v, 2) for k, v in breakdown.items()},
        "top_signals": top_signals,
        "raw_signal_total": round(total, 2),
    }


def compute_timing_bonus(signals: list) -> float:
    now = datetime.now(timezone.utc)
    bonus = 0.0
    for sig in signals:
        detected_str = sig.get("detected_at") or ""
        if not detected_str:
            continue
        try:
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                dt_str = detected_str.replace("+00:00", "+0000")
                dt = datetime.strptime(dt_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_old = (now - dt).days
                if days_old <= 3:
                    bonus += 5.0
                elif days_old <= 7:
                    bonus += 3.0
                elif days_old <= 14:
                    bonus += 1.0
                break
        except Exception:
            pass
    return min(bonus, 15.0)


def score_company(company: dict, signals: list, weights: dict, icp: dict) -> dict:
    icp_result = score_icp_fit(company, icp)
    signal_result = score_signals(signals, weights, icp)
    timing_bonus = compute_timing_bonus(signals)

    total = icp_result["score"] + signal_result["score"] + timing_bonus
    total = min(round(total, 1), 100.0)

    thresholds = weights.get("scoring_thresholds") or icp.get("scoring", {})
    tier_a = thresholds.get("tier_a_threshold", 75)
    tier_b = thresholds.get("tier_b_threshold", 50)
    tier_c = thresholds.get("tier_c_threshold", 25)

    if total >= tier_a:
        tier = "A"
        urgency = "high"
    elif total >= tier_b:
        tier = "B"
        urgency = "medium"
    elif total >= tier_c:
        tier = "C"
        urgency = "low"
    else:
        tier = "D"
        urgency = "monitor"

    action_window = 30 if tier == "A" else (60 if tier == "B" else 90)

    return {
        "company_id": company["id"],
        "company_name": company["name"],
        "scored_at": _now(),
        "score": {
            "total": total,
            "max": 100,
            "tier": tier,
            "breakdown": {
                "icp_fit": icp_result["score"],
                "icp_detail": icp_result["breakdown"],
                "signal_strength": signal_result["score"],
                "signal_detail": signal_result["breakdown"],
                "timing_bonus": round(timing_bonus, 1),
            },
        },
        "top_signals": signal_result["top_signals"],
        "urgency": urgency,
        "action_window_days": action_window,
        "signals_count": len(signals),
    }


def main():
    parser = argparse.ArgumentParser(description="Score opportunity for one or all companies")
    parser.add_argument("--company-id", help="Score a specific company")
    parser.add_argument("--all-companies", action="store_true")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--signals-file", help="JSON file of signals (defaults to today's)")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--output-file", help="Write scores to this JSON file")
    parser.add_argument("--weights-file", default="data/signal_weights.json")
    parser.add_argument("--icp-file", default="data/icp_criteria.json")
    args = parser.parse_args()

    weights = load_json(args.weights_file, {})
    icp = load_json(args.icp_file, {})
    companies_data = load_json(args.companies_file, {"companies": []})

    if not weights:
        print(json.dumps({"error": "cannot load signal_weights.json"}))
        sys.exit(2)

    signals_file = args.signals_file
    if not signals_file:
        today = _today()
        signals_file = str(Path(args.signals_dir) / f"{today}.json")

    all_signals = []
    if Path(signals_file).exists():
        all_signals = load_json(signals_file, [])

    if args.company_id:
        companies = [c for c in companies_data["companies"] if c["id"] == args.company_id]
        if not companies:
            print(json.dumps({"error": f"company_id '{args.company_id}' not found"}))
            sys.exit(2)
    else:
        companies = companies_data["companies"]

    results = []
    for company in companies:
        company_signals = [s for s in all_signals if s.get("company_id") == company["id"]]
        result = score_company(company, company_signals, weights, icp)
        results.append(result)

    results.sort(key=lambda r: r["score"]["total"], reverse=True)

    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    if len(results) == 1:
        print(json.dumps(results[0], ensure_ascii=False))
    else:
        print(json.dumps({
            "scored_at": _now(),
            "companies_scored": len(results),
            "scores": results,
        }, ensure_ascii=False))

    sys.exit(0)


if __name__ == "__main__":
    main()
