"""
Deduplicate, merge, and classify raw signal records from multiple sources.

Usage:
    python tools/normalize_signals.py --input-dir .tmp/raw_signals/ --company-id stripe
    python tools/normalize_signals.py --input-dir .tmp/raw_signals/ \
                                       --output-file outputs/signals/2025-01-15.json
    cat signals.json | python tools/normalize_signals.py --stdin

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_signal_weights(path: str = "data/signal_weights.json") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_date(date_str) -> datetime | None:
    if not date_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(date_str.replace("+00:00", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


def classify_signal(item: dict, weights: dict) -> tuple[str, str]:
    # Accept both normalized field names (signal_type) and raw tool output names (type)
    existing_type = item.get("signal_type") or item.get("type")
    existing_subtype = item.get("signal_subtype") or item.get("subtype")
    if existing_type and existing_subtype:
        return existing_type, existing_subtype
    if existing_type:
        return existing_type, "generic"

    text = " ".join([
        item.get("title", ""),
        item.get("raw_text", ""),
        item.get("summary", ""),
        item.get("description_snippet", ""),
    ]).lower()

    keyword_map = weights.get("signal_type_keywords", {})
    scores = {}
    for signal_type, keywords in keyword_map.items():
        for kw in keywords:
            if kw.lower() in text:
                scores[signal_type] = scores.get(signal_type, 0) + 1

    if scores:
        best_type = max(scores, key=scores.get)
    else:
        best_type = "news_mention"

    title = item.get("title", "")
    title_lower = title.lower()

    subtype_map = {
        "hiring_spike": {
            "engineering_leadership": ["cto", "vp engineering", "vp eng", "head of engineering", "chief technolog"],
            "sales_leadership": ["vp sales", "head of sales", "chief revenue", "cro"],
            "data_ai": ["data engineer", "ml engineer", "ai engineer", "machine learning", "data scientist"],
            "bulk_engineering": ["engineer", "developer", "sre", "devops", "platform"],
            "product": ["product manager", "pm ", "product designer"],
        },
        "leadership_change": {
            "new_cto": ["cto", "chief technology officer"],
            "new_cpo": ["cpo", "chief product officer"],
            "new_ceo": ["ceo", "chief executive"],
            "new_vp_eng": ["vp engineering", "vp of engineering"],
            "new_vp_sales": ["vp sales", "vp of sales"],
        },
        "funding_event": {
            "series_a": ["series a"],
            "series_b": ["series b"],
            "series_c_plus": ["series c", "series d", "series e"],
            "seed": ["seed round", "pre-seed", "seed funding"],
            "ipo": ["ipo", "initial public offering", "went public"],
        },
        "product_launch": {
            "new_product": ["new product", "launches", "introducing"],
            "major_release": ["major release", "v2", "version 2", "2.0"],
            "beta_announcement": ["beta", "early access", "preview"],
        },
        "product_hunt_launch": {
            "featured": ["#1", "featured", "product of the day"],
            "mentioned": ["product hunt"],
        },
        "github_signal": {
            "new_public_repo": ["open-source", "open source", "new repo", "sdk"],
            "sudden_star_spike": ["trending", "stars"],
        },
        "content_signal": {
            "case_study": ["case study", "customer story"],
            "whitepaper": ["whitepaper", "white paper", "report"],
            "blog_post_published": ["blog", "post", "article"],
        },
        "news_mention": {
            "press_release": ["press release", "announces", "announced"],
            "award": ["award", "recognized", "named"],
            "media_coverage": ["coverage", "featured in", "reported"],
        },
    }

    subtype = "generic"
    if best_type in subtype_map:
        for sub, patterns in subtype_map[best_type].items():
            if any(p in title_lower or p in text for p in patterns):
                subtype = sub
                break

    return best_type, subtype


def signal_fingerprint(signal: dict) -> str:
    parts = [
        signal.get("company_id", ""),
        signal.get("signal_type", ""),
        (signal.get("source_url") or signal.get("url") or "")[:80],
        (signal.get("detected_at") or signal.get("published") or "")[:10],
        (signal.get("title") or "")[:60].lower().strip(),
    ]
    key = "|".join(parts)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def make_signal_id(company_id: str, signal_type: str, seq: str) -> str:
    today = _today()
    return f"{company_id}-{signal_type}-{today}-{seq}"


def get_importance_score(signal_type: str, signal_subtype: str, weights: dict) -> float:
    w = weights.get("weights", {})
    type_weights = w.get(signal_type, {})
    return type_weights.get(signal_subtype, type_weights.get("generic", 3.0))


def apply_recency_decay(score: float, detected_at: str, weights: dict) -> float:
    if not detected_at:
        return score * weights.get("recency_decay", {}).get("last_30_days", 0.8)
    dt = parse_date(detected_at)
    if not dt:
        return score * 0.8
    now = datetime.now(timezone.utc)
    days_old = (now - dt).days
    decay = weights.get("recency_decay", {})
    if days_old <= 7:
        factor = decay.get("last_7_days", 1.0)
    elif days_old <= 30:
        factor = decay.get("last_30_days", 0.8)
    elif days_old <= 90:
        factor = decay.get("last_90_days", 0.5)
    else:
        factor = decay.get("older", 0.2)
    return round(score * factor, 2)


def normalize_one(raw: dict, weights: dict, company_id_filter: str = None) -> dict | None:
    company_id = raw.get("company_id") or company_id_filter or "unknown"

    if company_id_filter and company_id != company_id_filter:
        return None

    detected_at = (
        raw.get("detected_at")
        or raw.get("published")
        or raw.get("fetched_at")
        or _now()
    )

    dt = parse_date(detected_at)
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    if dt and dt < cutoff:
        return None

    signal_type, signal_subtype = classify_signal(raw, weights)
    base_score = get_importance_score(signal_type, signal_subtype, weights)
    score = apply_recency_decay(base_score, detected_at, weights)

    fp = signal_fingerprint({**raw, "signal_type": signal_type})
    signal_id = make_signal_id(company_id, signal_type, fp)

    return {
        "signal_id": signal_id,
        "company_id": company_id,
        "detected_at": detected_at,
        "signal_type": signal_type,
        "signal_subtype": signal_subtype,
        "source": raw.get("source") or raw.get("news_source") or "unknown",
        "source_url": raw.get("source_url") or raw.get("url") or raw.get("link") or "",
        "title": (raw.get("title") or "")[:200].strip(),
        "raw_text": (
            raw.get("raw_text")
            or raw.get("summary")
            or raw.get("snippet")
            or raw.get("description_snippet")
            or ""
        )[:1000],
        "structured_data": {
            k: v for k, v in raw.items()
            if k not in ("signal_id", "signal_type", "signal_subtype", "importance_score", "processed")
        },
        "importance_score": score,
        "processed": False,
        "included_in_brief": False,
    }


def collect_raw_from_dir(input_dir: str, company_id: str = None) -> list:
    raw_items = []
    path = Path(input_dir)
    if not path.exists():
        return []

    for json_file in path.glob("*.json"):
        if company_id and company_id not in json_file.name:
            continue
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if isinstance(data, list):
            raw_items.extend(data)
        elif isinstance(data, dict):
            for field in ("items", "listings", "launches", "new_jobs", "signals", "signals_detected", "results"):
                sub = data.get(field, [])
                if isinstance(sub, list):
                    cid = data.get("company_id", company_id)
                    for item in sub:
                        if isinstance(item, dict):
                            if not item.get("company_id") and cid:
                                item["company_id"] = cid
                            raw_items.append(item)

    return raw_items


def main():
    parser = argparse.ArgumentParser(description="Normalize and deduplicate raw signals")
    parser.add_argument("--input-dir", help="Directory of raw signal JSON files")
    parser.add_argument("--company-id", help="Filter to specific company ID")
    parser.add_argument("--output-file", help="Write normalized signals to this JSON file")
    parser.add_argument("--signals-dir", default="outputs/signals",
                        help="Append to daily signals file in this directory")
    parser.add_argument("--stdin", action="store_true", help="Read JSON array from stdin")
    parser.add_argument("--signals", help="JSON array of raw signals as string")
    args = parser.parse_args()

    weights = load_signal_weights()

    raw_items = []
    if args.stdin:
        raw_items = json.load(sys.stdin)
    elif args.signals:
        raw_items = json.loads(args.signals)
    elif args.input_dir:
        raw_items = collect_raw_from_dir(args.input_dir, args.company_id)
    else:
        print(json.dumps({"error": "provide --input-dir, --signals, or --stdin"}))
        sys.exit(2)

    normalized = []
    fingerprints_seen = set()
    for raw in raw_items:
        try:
            signal = normalize_one(raw, weights, args.company_id)
        except Exception as e:
            print(f"[normalize] skip malformed item: {e}", file=sys.stderr)
            continue
        if signal is None:
            continue
        fp = signal["signal_id"]
        if fp in fingerprints_seen:
            continue
        fingerprints_seen.add(fp)
        normalized.append(signal)

    normalized.sort(key=lambda s: s.get("importance_score", 0), reverse=True)

    if args.output_file:
        Path(args.output_file).parent.mkdir(parents=True, exist_ok=True)
        existing = []
        out_path = Path(args.output_file)
        if out_path.exists():
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
        existing_ids = {s["signal_id"] for s in existing}
        new_signals = [s for s in normalized if s["signal_id"] not in existing_ids]
        existing.extend(new_signals)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        print(f"[normalize] wrote {len(new_signals)} new signals to {args.output_file}", file=sys.stderr)

    result = {
        "company_id": args.company_id,
        "normalized_at": _now(),
        "input_count": len(raw_items),
        "output_count": len(normalized),
        "duplicates_removed": len(raw_items) - len(normalized),
        "signals": normalized,
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
