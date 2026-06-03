"""
Atomic CRUD operations for per-company account memory records.

All writes use tmp→rename to prevent race conditions in GitHub Actions.

Usage:
    python tools/update_account_memory.py --action init --company-id stripe
    python tools/update_account_memory.py --action read --company-id stripe
    python tools/update_account_memory.py --action write --company-id stripe \
        --field relationship_context.engagement_status --value replied
    python tools/update_account_memory.py --action append-signal \
        --company-id stripe --signal-file outputs/signals/2026-06-03.json
    python tools/update_account_memory.py --action append-signal \
        --all-companies --signal-file outputs/signals/2026-06-03.json
    python tools/update_account_memory.py --action append-outreach \
        --company-id stripe --sequence-id seq-001 --step 1 --date 2026-06-03
    python tools/update_account_memory.py --action append-brief \
        --company-id stripe --brief-id stripe-brief-2026-06-03
    python tools/update_account_memory.py --action reset --company-id stripe

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


MEMORY_DIR = "outputs/memory"
SCHEMA_VERSION = "2.0"
SIGNAL_HISTORY_MAX_DAYS = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def memory_path(company_id: str, memory_dir: str = MEMORY_DIR) -> Path:
    return Path(memory_dir) / f"{company_id}.json"


def blank_memory(company_id: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "company_id": company_id,
        "created_at": _now(),
        "last_updated": _now(),
        "relationship_context": {
            "warm_intro": False,
            "engagement_status": "not_contacted",
            "last_outreach_date": None,
            "last_outreach_channel": None,
            "last_response_date": None,
            "last_response_sentiment": None,
            "open_outreach_sequence_id": None,
            "crm_deal_id": None,
            "crm_company_id": None,
            "notes": "",
        },
        "known_contacts": [],
        "signal_history": [],
        "brief_history": [],
        "outreach_history": [],
        "playbook_history": [],
    }


def atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_memory(company_id: str, memory_dir: str = MEMORY_DIR) -> dict:
    path = memory_path(company_id, memory_dir)
    if not path.exists():
        mem = blank_memory(company_id)
        atomic_write(path, mem)
        return mem
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "schema_version" not in data:
            data["schema_version"] = SCHEMA_VERSION
        return data
    except Exception as e:
        print(f"[memory] error reading {path}: {e}", file=sys.stderr)
        return blank_memory(company_id)


def set_nested(data: dict, dotted_key: str, value) -> dict:
    keys = dotted_key.split(".")
    obj = data
    for k in keys[:-1]:
        if k not in obj or not isinstance(obj[k], dict):
            obj[k] = {}
        obj = obj[k]
    try:
        obj[keys[-1]] = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        obj[keys[-1]] = value
    return data


def purge_old_signals(signal_history: list) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=SIGNAL_HISTORY_MAX_DAYS)
    result = []
    for sig in signal_history:
        date_str = sig.get("detected_at") or sig.get("published") or ""
        if date_str:
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(date_str.replace("+00:00", "+0000"), fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt >= cutoff:
                        result.append(sig)
                    break
                except ValueError:
                    pass
        else:
            result.append(sig)
    return result


def cmd_init(args) -> dict:
    path = memory_path(args.company_id, args.memory_dir)
    if path.exists():
        existing = load_memory(args.company_id, args.memory_dir)
        print(f"[memory] memory already exists for {args.company_id} — no change", file=sys.stderr)
        return {"action": "init", "company_id": args.company_id, "created": False}
    mem = blank_memory(args.company_id)
    atomic_write(path, mem)
    return {"action": "init", "company_id": args.company_id, "created": True}


def cmd_read(args) -> dict:
    return load_memory(args.company_id, args.memory_dir)


def cmd_write(args) -> dict:
    if not args.field or args.value is None:
        print(json.dumps({"error": "--field and --value are required for write action"}))
        sys.exit(2)
    mem = load_memory(args.company_id, args.memory_dir)
    mem = set_nested(mem, args.field, args.value)
    mem["last_updated"] = _now()
    path = memory_path(args.company_id, args.memory_dir)
    atomic_write(path, mem)
    return {"action": "write", "company_id": args.company_id, "field": args.field, "status": "ok"}


def cmd_append_signal(args) -> dict:
    if not args.signal_file:
        print(json.dumps({"error": "--signal-file required for append-signal"}))
        sys.exit(2)

    try:
        with open(args.signal_file, encoding="utf-8") as f:
            all_signals = json.load(f)
    except Exception as e:
        print(json.dumps({"error": f"cannot read signal file: {e}"}))
        sys.exit(2)

    company_ids = []
    if args.all_companies:
        if not args.companies_file:
            print(json.dumps({"error": "--companies-file required with --all-companies"}))
            sys.exit(2)
        with open(args.companies_file, encoding="utf-8") as f:
            cdata = json.load(f)
        company_ids = [c["id"] for c in cdata.get("companies", [])]
    else:
        company_ids = [args.company_id]

    results = []
    for cid in company_ids:
        company_signals = [s for s in all_signals if s.get("company_id") == cid]
        mem = load_memory(cid, args.memory_dir)
        existing_ids = {s.get("signal_id") for s in mem["signal_history"] if s.get("signal_id")}
        new_sigs = [s for s in company_signals if s.get("signal_id") not in existing_ids]

        slim_signals = [
            {
                "signal_id": s.get("signal_id"),
                "signal_type": s.get("signal_type"),
                "signal_subtype": s.get("signal_subtype"),
                "title": s.get("title"),
                "detected_at": s.get("detected_at"),
                "importance_score": s.get("importance_score"),
            }
            for s in new_sigs
        ]

        mem["signal_history"].extend(slim_signals)
        mem["signal_history"] = purge_old_signals(mem["signal_history"])
        mem["last_updated"] = _now()
        path = memory_path(cid, args.memory_dir)
        atomic_write(path, mem)
        results.append({"company_id": cid, "new_signals_added": len(new_sigs)})

    return {"action": "append-signal", "results": results}


def cmd_append_outreach(args) -> dict:
    required = [args.company_id, args.sequence_id, args.step, args.date]
    if any(r is None for r in required):
        print(json.dumps({"error": "--company-id --sequence-id --step --date all required"}))
        sys.exit(2)

    mem = load_memory(args.company_id, args.memory_dir)
    entry = {
        "sequence_id": args.sequence_id,
        "step": args.step,
        "date": args.date,
        "recorded_at": _now(),
    }
    mem["outreach_history"].append(entry)
    mem["relationship_context"]["last_outreach_date"] = args.date
    if args.step == 1:
        mem["relationship_context"]["engagement_status"] = "in_sequence"
        mem["relationship_context"]["open_outreach_sequence_id"] = args.sequence_id
    mem["last_updated"] = _now()
    path = memory_path(args.company_id, args.memory_dir)
    atomic_write(path, mem)
    return {"action": "append-outreach", "company_id": args.company_id, "step": args.step}


def cmd_append_brief(args) -> dict:
    if not args.brief_id:
        print(json.dumps({"error": "--brief-id required"}))
        sys.exit(2)
    mem = load_memory(args.company_id, args.memory_dir)
    entry = {"brief_id": args.brief_id, "recorded_at": _now()}
    if entry["brief_id"] not in [b.get("brief_id") for b in mem["brief_history"]]:
        mem["brief_history"].append(entry)
    mem["last_updated"] = _now()
    path = memory_path(args.company_id, args.memory_dir)
    atomic_write(path, mem)
    return {"action": "append-brief", "company_id": args.company_id, "brief_id": args.brief_id}


def cmd_reset(args) -> dict:
    mem = load_memory(args.company_id, args.memory_dir)
    contacts = mem.get("known_contacts", [])
    fresh = blank_memory(args.company_id)
    fresh["known_contacts"] = contacts
    fresh["created_at"] = mem.get("created_at", _now())
    path = memory_path(args.company_id, args.memory_dir)
    atomic_write(path, fresh)
    return {"action": "reset", "company_id": args.company_id, "contacts_preserved": len(contacts)}


ACTIONS = {
    "init": cmd_init,
    "read": cmd_read,
    "write": cmd_write,
    "append-signal": cmd_append_signal,
    "append-outreach": cmd_append_outreach,
    "append-brief": cmd_append_brief,
    "reset": cmd_reset,
}


def main():
    parser = argparse.ArgumentParser(description="Account memory CRUD with atomic writes")
    parser.add_argument("--action", required=True,
                        choices=list(ACTIONS.keys()),
                        help="Operation to perform")
    parser.add_argument("--company-id", help="Company ID")
    parser.add_argument("--all-companies", action="store_true")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--memory-dir", default=MEMORY_DIR)
    parser.add_argument("--field", help="Dotted field path for write action")
    parser.add_argument("--value", help="Value to set (JSON or string)")
    parser.add_argument("--signal-file", help="Signals JSON file for append-signal")
    parser.add_argument("--sequence-id", help="Outreach sequence ID")
    parser.add_argument("--step", type=int, help="Outreach step number")
    parser.add_argument("--date", help="Date string YYYY-MM-DD")
    parser.add_argument("--brief-id", help="Brief ID for append-brief")
    args = parser.parse_args()

    if not args.company_id and not args.all_companies:
        print(json.dumps({"error": "provide --company-id or --all-companies"}))
        sys.exit(2)

    fn = ACTIONS[args.action]
    result = fn(args)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
