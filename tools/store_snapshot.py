"""
Save a versioned snapshot of any fetched content to outputs/snapshots/.

Usage:
    python tools/store_snapshot.py --company-id stripe --snapshot-type careers \
                                    --content-file .tmp/raw_html/stripe-careers.html
    python tools/store_snapshot.py --company-id stripe --snapshot-type tech_stack \
                                    --content '{"stack": [...]}'

Exit codes: 0 success, 2 fatal
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def find_previous_snapshot(company_id: str, snapshot_type: str, snapshots_dir: Path) -> dict | None:
    today_str = _today()
    candidates = sorted(
        snapshots_dir.glob(f"{company_id}_{snapshot_type}_*.json"),
        reverse=True
    )
    for c in candidates:
        if today_str not in c.name:
            try:
                with open(c, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def update_index(snapshot_meta: dict, snapshots_dir: Path):
    index_path = snapshots_dir / "_index.json"
    index = {}
    if index_path.exists():
        try:
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
        except Exception:
            index = {}

    company_id = snapshot_meta["company_id"]
    snap_type = snapshot_meta["snapshot_type"]
    key = f"{company_id}:{snap_type}"
    if key not in index:
        index[key] = []
    index[key].append({
        "snapshot_id": snapshot_meta["snapshot_id"],
        "stored_at": snapshot_meta["stored_at"],
        "content_hash": snapshot_meta["content_hash"],
        "file_path": snapshot_meta["file_path"],
    })
    index[key] = index[key][-20:]

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Save versioned snapshot to outputs/snapshots/")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--snapshot-type", required=True,
                        help="e.g. careers, tech_stack, webpage, research, rss")
    parser.add_argument("--content-file", help="Path to file containing content to snapshot")
    parser.add_argument("--content", help="Content as JSON string or plain text")
    parser.add_argument("--snapshots-dir", default="outputs/snapshots")
    args = parser.parse_args()

    snapshots_dir = Path(args.snapshots_dir)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    if args.content_file:
        try:
            with open(args.content_file, encoding="utf-8") as f:
                raw_content = f.read()
        except Exception as e:
            print(json.dumps({"error": f"cannot_read_file: {e}"}))
            sys.exit(2)
    elif args.content:
        raw_content = args.content
    else:
        print(json.dumps({"error": "provide --content-file or --content"}))
        sys.exit(2)

    try:
        content_obj = json.loads(raw_content)
        content_normalized = json.dumps(content_obj, sort_keys=True)
    except Exception:
        content_obj = raw_content
        content_normalized = raw_content

    content_hash = hashlib.sha256(content_normalized.encode()).hexdigest()[:16]
    snapshot_id = f"{args.company_id}_{args.snapshot_type}_{_today()}"
    file_path = snapshots_dir / f"{snapshot_id}.json"

    previous = find_previous_snapshot(args.company_id, args.snapshot_type, snapshots_dir)
    previous_id = previous.get("snapshot_id") if previous else None
    previous_hash = previous.get("content_hash") if previous else None
    changed = previous_hash != content_hash if previous_hash else True

    snapshot = {
        "snapshot_id": snapshot_id,
        "company_id": args.company_id,
        "snapshot_type": args.snapshot_type,
        "stored_at": _now(),
        "content_hash": content_hash,
        "previous_snapshot_id": previous_id,
        "changed_from_previous": changed,
        "content": content_obj,
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    meta = {
        "snapshot_id": snapshot_id,
        "company_id": args.company_id,
        "snapshot_type": args.snapshot_type,
        "stored_at": _now(),
        "file_path": str(file_path),
        "content_hash": content_hash,
        "previous_snapshot_id": previous_id,
        "changed_from_previous": changed,
    }
    update_index(meta, snapshots_dir)

    print(json.dumps(meta, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
