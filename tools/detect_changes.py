"""
Compare two snapshots and emit structured change event records.

Usage:
    python tools/detect_changes.py --current outputs/snapshots/stripe_careers_2025-01-15.json \
                                    --previous outputs/snapshots/stripe_careers_2025-01-08.json \
                                    --company-id stripe --change-type careers
    python tools/detect_changes.py --current-data '{"jobs":[...]}' --previous-data '{"jobs":[...]}' \
                                    --company-id stripe --change-type careers --write-signals

Exit codes: 0 no changes or success, 1 changes detected, 2 fatal
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _safe_json(obj) -> str:
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        return json.dumps(str(obj))


CHANGE_TO_SIGNAL = {
    "careers": {
        "added": {
            "executive": ("hiring_spike", "engineering_leadership"),
            "vp": ("hiring_spike", "engineering_leadership"),
            "director": ("hiring_spike", "engineering_leadership"),
            "Engineering": ("hiring_spike", "bulk_engineering"),
            "Data": ("hiring_spike", "data_ai"),
            "Sales": ("hiring_spike", "sales_leadership"),
            "default": ("hiring_spike", "generic"),
        }
    },
    "webpage": {
        "content_changed": ("tech_change", "generic"),
    },
    "rss": {
        "new_item": ("content_signal", "blog_post_published"),
    },
}


def significance_level(change_kind: str, field: str, value: dict, change_type: str) -> str:
    if change_type == "careers" and change_kind == "added":
        title = (value.get("title") or "").lower()
        seniority = value.get("seniority", "")
        if seniority in ("executive", "vp") or any(
            w in title for w in ["cto", "ceo", "vp ", "head of", "chief"]
        ):
            return "high"
        dept = value.get("department_detected", "")
        if dept in ("Engineering", "Data"):
            return "medium"
        return "low"
    return "low"


def fingerprint(obj: dict, fields: list) -> str:
    key = "|".join(str(obj.get(f, "")).lower().strip() for f in fields)
    return hashlib.md5(key.encode()).hexdigest()[:12]


def diff_careers(current_data: dict, previous_data: dict) -> list:
    current_jobs = current_data.get("jobs", []) or current_data.get("new_jobs", []) + current_data.get("listings", [])
    previous_jobs = previous_data.get("jobs", []) if previous_data else []

    fp_fields = ["title", "location", "department"]
    current_fps = {fingerprint(j, fp_fields): j for j in current_jobs}
    previous_fps = {fingerprint(j, fp_fields): j for j in previous_jobs}

    changes = []
    for fp, job in current_fps.items():
        if fp not in previous_fps:
            title = job.get("title", "")
            seniority = job.get("seniority", "unknown")
            dept = job.get("department_detected", job.get("department", ""))
            sig = significance_level("added", "job_listing", job, "careers")

            signal_map = CHANGE_TO_SIGNAL.get("careers", {}).get("added", {})
            signal_tuple = (
                signal_map.get(seniority)
                or signal_map.get(dept)
                or signal_map.get("default")
                or ("hiring_spike", "generic")
            )

            changes.append({
                "change_kind": "added",
                "field": "job_listing",
                "value": job,
                "significance": sig,
                "signal_type": signal_tuple[0],
                "signal_subtype": signal_tuple[1],
                "title": f"New job: {title}",
            })

    for fp, job in previous_fps.items():
        if fp not in current_fps:
            changes.append({
                "change_kind": "removed",
                "field": "job_listing",
                "value": job,
                "significance": "low",
                "signal_type": None,
                "signal_subtype": None,
                "title": f"Job removed: {job.get('title', '')}",
            })

    return changes


def diff_webpage(current_data: dict, previous_data: dict) -> list:
    current_text = current_data.get("text_content", "")
    previous_text = previous_data.get("text_content", "") if previous_data else ""

    current_hash = hashlib.sha256(current_text.encode()).hexdigest()[:16]
    previous_hash = hashlib.sha256(previous_text.encode()).hexdigest()[:16]

    if current_hash == previous_hash:
        return []

    word_count_delta = len(current_text.split()) - len(previous_text.split())
    return [{
        "change_kind": "content_changed",
        "field": "page_text",
        "value": {
            "current_hash": current_hash,
            "previous_hash": previous_hash,
            "word_count_delta": word_count_delta,
        },
        "significance": "medium" if abs(word_count_delta) > 100 else "low",
        "signal_type": "tech_change",
        "signal_subtype": "generic",
        "title": f"Page content changed ({word_count_delta:+d} words)",
    }]


def diff_rss(current_data: dict, previous_data: dict) -> list:
    current_items = current_data.get("items", [])
    previous_items = previous_data.get("items", []) if previous_data else []

    current_links = {item.get("link") or item.get("url", ""): item for item in current_items}
    previous_links = {item.get("link") or item.get("url", ""): item for item in previous_items}

    changes = []
    for link, item in current_links.items():
        if link and link not in previous_links:
            changes.append({
                "change_kind": "new_item",
                "field": "rss_item",
                "value": item,
                "significance": "low",
                "signal_type": "content_signal",
                "signal_subtype": "blog_post_published",
                "title": f"New post: {item.get('title', '')}",
            })
    return changes


DIFF_HANDLERS = {
    "careers": diff_careers,
    "webpage": diff_webpage,
    "rss": diff_rss,
}


def build_signal(company_id: str, change: dict, source_url: str = "") -> dict:
    today = _today()
    seq = hashlib.md5(json.dumps(change, sort_keys=True).encode()).hexdigest()[:6]
    signal_id = f"{company_id}-{change.get('signal_type', 'change')}-{today}-{seq}"

    return {
        "signal_id": signal_id,
        "company_id": company_id,
        "detected_at": _now(),
        "signal_type": change.get("signal_type"),
        "signal_subtype": change.get("signal_subtype"),
        "source": "detect_changes",
        "source_url": source_url,
        "title": change.get("title", ""),
        "raw_text": _safe_json(change.get("value", {}))[:500],
        "structured_data": change.get("value", {}),
        "importance_score": {"high": 8.0, "medium": 5.0, "low": 3.0}.get(change.get("significance", "low"), 3.0),
        "processed": False,
        "included_in_brief": False,
    }


def append_signals(signals: list, signals_dir: str = "outputs/signals"):
    Path(signals_dir).mkdir(parents=True, exist_ok=True)
    today = _today()
    signals_file = Path(signals_dir) / f"{today}.json"

    existing = []
    if signals_file.exists():
        with open(signals_file, encoding="utf-8") as f:
            existing = json.load(f)

    existing_ids = {s["signal_id"] for s in existing}
    new_signals = [s for s in signals if s["signal_id"] not in existing_ids]
    existing.extend(new_signals)

    with open(signals_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    return len(new_signals)


def main():
    parser = argparse.ArgumentParser(description="Diff two snapshots and emit change events")
    parser.add_argument("--current", help="Path to current snapshot JSON file")
    parser.add_argument("--previous", help="Path to previous snapshot JSON file")
    parser.add_argument("--current-data", help="Current snapshot as JSON string")
    parser.add_argument("--previous-data", help="Previous snapshot as JSON string")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--change-type", choices=["careers", "webpage", "rss"], default="careers")
    parser.add_argument("--write-signals", action="store_true", help="Append signals to outputs/signals/")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--source-url", default="")
    args = parser.parse_args()

    try:
        if args.current:
            with open(args.current, encoding="utf-8") as f:
                current_data = json.load(f)
        elif args.current_data:
            current_data = json.loads(args.current_data)
        else:
            print(json.dumps({"error": "provide --current or --current-data"}))
            sys.exit(2)

        if args.previous and os.path.exists(args.previous):
            with open(args.previous, encoding="utf-8") as f:
                previous_data = json.load(f)
        elif args.previous_data:
            previous_data = json.loads(args.previous_data)
        else:
            previous_data = None
    except Exception as e:
        print(json.dumps({"error": f"parse_error: {e}"}))
        sys.exit(2)

    handler = DIFF_HANDLERS.get(args.change_type, diff_careers)
    changes = handler(current_data, previous_data)

    new_signals = []
    if args.write_signals and changes:
        for change in changes:
            if change.get("signal_type"):
                new_signals.append(build_signal(args.company_id, change, args.source_url))
        if new_signals:
            count = append_signals(new_signals, args.signals_dir)
            print(f"[detect_changes] wrote {count} new signals", file=sys.stderr)

    has_changes = bool(changes)
    high_changes = [c for c in changes if c.get("significance") == "high"]
    summary_parts = []
    added = [c for c in changes if c.get("change_kind") == "added"]
    removed = [c for c in changes if c.get("change_kind") == "removed"]
    if added:
        summary_parts.append(f"{len(added)} added")
    if removed:
        summary_parts.append(f"{len(removed)} removed")

    result = {
        "company_id": args.company_id,
        "change_type": args.change_type,
        "detected_at": _now(),
        "has_changes": has_changes,
        "first_run": previous_data is None,
        "changes": changes,
        "signals_written": len(new_signals),
        "summary": ", ".join(summary_parts) if summary_parts else "no changes",
        "high_significance_count": len(high_changes),
    }

    print(json.dumps(result, ensure_ascii=False))
    sys.exit(1 if has_changes else 0)


if __name__ == "__main__":
    main()
