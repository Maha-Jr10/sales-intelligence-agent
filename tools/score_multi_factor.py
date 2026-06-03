"""
Multi-factor opportunity scoring: v1 score (opaque) + Intent score + Urgency score
= Composite priority score.

Reads correlation boosts from correlate_signals.py output.
Urgency bonuses are summed then capped to prevent double-counting.

Usage:
    python tools/score_multi_factor.py --all-companies \
        --signals-file outputs/signals/2026-06-03.json \
        --scores-file outputs/signals/scores-2026-06-03.json \
        --correlations-file outputs/signals/correlations-2026-06-03.json \
        --output-file outputs/signals/multi_factor_scores-2026-06-03.json
    python tools/score_multi_factor.py --company-id stripe

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
        print(f"[mf_score] cannot load {path}: {e}", file=sys.stderr)
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


def compute_intent_score(company_id: str, signals: list, config: dict,
                         research_cache_dir: str = ".tmp/research_cache") -> dict:
    intent_cfg = config.get("intent_scoring", {})
    cluster_threshold = intent_cfg.get("signal_cluster_threshold", 3)
    cluster_window = intent_cfg.get("signal_cluster_window_days", 7)
    cluster_bonus = intent_cfg.get("signal_cluster_bonus", 12.0)
    intent_keywords = intent_cfg.get("intent_keywords_in_job_descriptions", [])
    keyword_score = intent_cfg.get("keyword_match_score", 3.0)

    now = datetime.now(timezone.utc)
    cluster_cutoff = now - timedelta(days=cluster_window)

    recent_signals = [
        s for s in signals
        if (dt := parse_date(s.get("detected_at") or s.get("published") or "")) and dt >= cluster_cutoff
    ]

    cluster_count = len(recent_signals)
    cluster_bonus_applied = cluster_bonus if cluster_count >= cluster_threshold else 0.0

    keyword_matches = 0
    try:
        today = _today()
        cache_path = Path(research_cache_dir) / f"{company_id}_{today}.json"
        if not cache_path.exists():
            candidates = sorted(Path(research_cache_dir).glob(f"{company_id}_*.json"), reverse=True)
            cache_path = candidates[0] if candidates else None

        if cache_path and cache_path.exists():
            bundle = load_json(str(cache_path), {})
            job_listings = bundle.get("data", {}).get("job_listings", [])
            for job in job_listings:
                desc = (job.get("description_snippet") or "").lower()
                for kw in intent_keywords:
                    if kw.lower() in desc:
                        keyword_matches += 1
                        break
    except Exception as e:
        print(f"[mf_score] research cache scan skipped: {e}", file=sys.stderr)

    keyword_total = min(keyword_matches * keyword_score, 20.0)
    intent_raw = cluster_bonus_applied + keyword_total
    intent_score = min(round(intent_raw, 2), 100.0)

    return {
        "intent_score": intent_score,
        "intent_breakdown": {
            "signal_cluster_count": cluster_count,
            "signal_cluster_bonus": cluster_bonus_applied,
            "keyword_matches": keyword_matches,
            "keyword_total_score": keyword_total,
        },
    }


def compute_urgency_score(company_id: str, signals: list, config: dict,
                          correlation_boost: float) -> dict:
    urgency_cfg = config.get("urgency_scoring", {})
    now = datetime.now(timezone.utc)
    bonuses = {}

    new_exec_window = urgency_cfg.get("new_executive_window_days", 90)
    new_exec_bonus = urgency_cfg.get("new_executive_bonus", 15.0)
    post_funding_window = urgency_cfg.get("post_funding_window_days", 180)
    post_funding_bonus = urgency_cfg.get("post_funding_bonus", 12.0)
    comp_pressure_bonus = urgency_cfg.get("competitive_pressure_bonus", 10.0)
    same_day_bonus = urgency_cfg.get("multiple_signals_same_day_bonus", 8.0)
    corr_boost_cap = urgency_cfg.get("correlation_boost_cap", 30)
    max_total = urgency_cfg.get("max_total_urgency_bonus", 50)

    leadership_signals = [
        s for s in signals if s.get("signal_type") == "leadership_change"
    ]
    for sig in leadership_signals:
        dt = parse_date(sig.get("detected_at") or sig.get("published") or "")
        if dt and (now - dt).days <= new_exec_window:
            bonuses["new_executive"] = new_exec_bonus
            break

    funding_signals = [
        s for s in signals if s.get("signal_type") == "funding_event"
    ]
    for sig in funding_signals:
        dt = parse_date(sig.get("detected_at") or sig.get("published") or "")
        if dt and (now - dt).days <= post_funding_window:
            bonuses["post_funding"] = post_funding_bonus
            break

    competitive_signals = [
        s for s in signals if s.get("signal_type") == "competitive_pressure"
    ]
    if competitive_signals:
        bonuses["competitive_pressure"] = comp_pressure_bonus

    dates_with_signals: dict[str, int] = {}
    for sig in signals:
        dt = parse_date(sig.get("detected_at") or "")
        if dt:
            date_key = dt.strftime("%Y-%m-%d")
            dates_with_signals[date_key] = dates_with_signals.get(date_key, 0) + 1
    if any(count >= 2 for count in dates_with_signals.values()):
        bonuses["multiple_signals_same_day"] = same_day_bonus

    individual_total = sum(bonuses.values())
    corr_boost_capped = min(correlation_boost, corr_boost_cap)
    urgency_raw = individual_total + corr_boost_capped
    urgency_score = min(round(urgency_raw, 2), max_total)

    return {
        "urgency_score": urgency_score,
        "correlation_boost_applied": corr_boost_capped,
        "urgency_breakdown": {
            **{f"urgency_{k}": v for k, v in bonuses.items()},
            "urgency_correlation_boost": corr_boost_capped,
            "urgency_total_raw": round(urgency_raw, 2),
            "urgency_cap_applied": urgency_raw > max_total,
        },
    }


def composite_score(v1_score: float, intent: float, urgency: float, weights: dict) -> float:
    w_v1 = weights.get("v1_score", 0.30)
    w_intent = weights.get("intent_score", 0.40)
    w_urgency = weights.get("urgency_score", 0.30)
    raw = v1_score * w_v1 + intent * w_intent + urgency * w_urgency
    return min(round(raw, 2), 100.0)


def composite_tier(score: float, tiers: dict) -> str:
    if score >= tiers.get("p1_threshold", 80):
        return "P1"
    if score >= tiers.get("p2_threshold", 60):
        return "P2"
    if score >= tiers.get("p3_threshold", 40):
        return "P3"
    return "P4"


def score_company(company: dict, signals: list, v1_score_obj: dict,
                  correlation_data: dict, config: dict) -> dict:
    company_id = company["id"]
    v1_score = v1_score_obj.get("score", {}).get("total", 0) if v1_score_obj else 0
    v1_tier = v1_score_obj.get("score", {}).get("tier", "D") if v1_score_obj else "D"

    corr_boost = correlation_data.get("total_priority_boost", 0) if correlation_data else 0

    intent_result = compute_intent_score(company_id, signals, config)
    urgency_result = compute_urgency_score(company_id, signals, config, corr_boost)

    weights = config.get("composite_weights", {})
    tiers = config.get("priority_tiers", {})

    comp = composite_score(v1_score, intent_result["intent_score"], urgency_result["urgency_score"], weights)
    tier = composite_tier(comp, tiers)

    return {
        "company_id": company_id,
        "company_name": company.get("name", company_id),
        "v1_score": v1_score,
        "v1_tier": v1_tier,
        "intent_score": intent_result["intent_score"],
        "urgency_score": urgency_result["urgency_score"],
        "correlation_boost_applied": urgency_result["correlation_boost_applied"],
        "composite_score": comp,
        "composite_tier": tier,
        "score_breakdown": {
            "v1_score_passthrough": v1_score,
            **intent_result["intent_breakdown"],
            **urgency_result["urgency_breakdown"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-factor opportunity scoring")
    parser.add_argument("--company-id", help="Score specific company")
    parser.add_argument("--all-companies", action="store_true")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--signals-file", help="Normalized signals JSON")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--scores-file", help="v1 scores JSON (outputs/signals/scores-{date}.json)")
    parser.add_argument("--correlations-file", help="Correlations JSON from correlate_signals.py")
    parser.add_argument("--config-file", default="data/scoring_config.json")
    parser.add_argument("--output-file", help="Write output to this file")
    args = parser.parse_args()

    config = load_json(args.config_file, {})
    if not config:
        print(json.dumps({"error": "cannot load scoring_config.json"}))
        sys.exit(2)

    today = _today()
    signals_file = args.signals_file or str(Path(args.signals_dir) / f"{today}.json")
    scores_file = args.scores_file or str(Path(args.signals_dir) / f"scores-{today}.json")
    correlations_file = args.correlations_file or str(Path(args.signals_dir) / f"correlations-{today}.json")

    all_signals = load_json(signals_file, [])
    v1_scores_raw = load_json(scores_file, [])
    correlations_raw = load_json(correlations_file, {})

    v1_by_company: dict[str, dict] = {}
    v1_list = v1_scores_raw if isinstance(v1_scores_raw, list) else v1_scores_raw.get("scores", [])
    for s in v1_list:
        cid = s.get("company_id")
        if cid:
            v1_by_company[cid] = s

    corr_by_company: dict[str, dict] = {}
    for c in correlations_raw.get("companies", []):
        cid = c.get("company_id")
        if cid:
            corr_by_company[cid] = c

    companies_data = load_json(args.companies_file, {"companies": []})
    if args.company_id:
        companies = [c for c in companies_data["companies"] if c["id"] == args.company_id]
        if not companies:
            print(json.dumps({"error": f"company_id '{args.company_id}' not found"}))
            sys.exit(2)
    else:
        companies = companies_data["companies"]

    results = []
    for company in companies:
        cid = company["id"]
        company_signals = [s for s in all_signals if s.get("company_id") == cid]
        result = score_company(
            company,
            company_signals,
            v1_by_company.get(cid),
            corr_by_company.get(cid),
            config,
        )
        results.append(result)

    results.sort(key=lambda r: r["composite_score"], reverse=True)
    for i, r in enumerate(results):
        r["priority_rank"] = i + 1

    output = {
        "schema_version": "2.0",
        "generated_at": _now(),
        "date": today,
        "companies_scored": len(results),
        "scores": results,
    }

    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"[mf_score] written to {args.output_file}", file=sys.stderr)

    if len(results) == 1:
        print(json.dumps(results[0], ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
