"""
Competitive intelligence tool.

Mode 'competitors': Fetch news for each competitor in data/competitors.json.
Mode 'accounts': Scan target company research bundles for competitor mentions.
Mode 'both': Run both modes.

Uses subprocess calls to search_news.py for HTTP — no direct requests here.

Usage:
    python tools/monitor_competitors.py --mode both --all-companies \
        --output-dir outputs/competitive/
    python tools/monitor_competitors.py --mode accounts --company-id stripe \
        --output-dir outputs/competitive/

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
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
    except Exception as e:
        print(f"[competitors] cannot load {path}: {e}", file=sys.stderr)
        return default


def load_research_bundle(company_id: str, cache_dir: str = ".tmp/research_cache") -> dict:
    today = _today()
    cache_path = Path(cache_dir) / f"{company_id}_{today}.json"
    if cache_path.exists():
        return load_json(str(cache_path), {})
    candidates = sorted(Path(cache_dir).glob(f"{company_id}_*.json"), reverse=True)
    if candidates:
        return load_json(str(candidates[0]), {})
    return {}


def extract_sentences_with_match(text: str, keyword: str) -> list[str]:
    pattern = re.compile(r'[^.!?]*' + re.escape(keyword) + r'[^.!?]*[.!?]?', re.IGNORECASE)
    return [m.group(0).strip()[:200] for m in pattern.finditer(text)][:3]


def scan_research_bundle_for_competitors(bundle: dict, competitors: list) -> list:
    mentions = []
    data = bundle.get("data", {})

    text_fields = []
    for item in data.get("recent_news", []):
        text_fields.append(("news_title", item.get("title", "")))
        text_fields.append(("news_summary", item.get("summary", "") or item.get("snippet", "")))
    for job in data.get("job_listings", []):
        text_fields.append(("job_description", job.get("description_snippet", "") or job.get("title", "")))
    for rss in data.get("rss_items", []):
        text_fields.append(("rss", rss.get("title", "") + " " + rss.get("summary", "")))
    profile = data.get("company_profile", {})
    text_fields.append(("website", profile.get("about_text", "")))

    for comp in competitors:
        comp_id = comp["id"]
        comp_name = comp["name"]
        aliases = comp.get("aliases", [comp_name])

        for alias in aliases:
            for source_type, text in text_fields:
                if not text:
                    continue
                if re.search(re.escape(alias), text, re.IGNORECASE):
                    sentences = extract_sentences_with_match(text, alias)
                    matched_text = sentences[0] if sentences else f"...{alias}..."

                    signal_type = "neutral"
                    displacement_kws = comp.get("displacement_signals", [])
                    eval_kws = ["evaluating", "comparing", "vs ", "versus", "alternative to"]
                    for dkw in displacement_kws:
                        if dkw.lower() in text.lower():
                            signal_type = "displacement"
                            break
                    if signal_type == "neutral":
                        for ekw in eval_kws:
                            if ekw.lower() in text.lower():
                                signal_type = "evaluation"
                                break

                    mentions.append({
                        "competitor_id": comp_id,
                        "competitor_name": comp_name,
                        "context": f"{source_type} mentions {alias}",
                        "matched_text": matched_text,
                        "source_type": source_type,
                        "source_url": "",
                        "signal_type": signal_type,
                        "signal_strength": "high" if signal_type == "displacement" else "medium",
                    })

    seen = set()
    unique = []
    for m in mentions:
        key = (m["competitor_id"], m["matched_text"][:50])
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique


def recommended_strategy(mentions: list) -> str:
    if any(m["signal_type"] == "displacement" for m in mentions):
        return "displacement"
    if any(m["signal_type"] == "evaluation" for m in mentions):
        return "competitive_defense"
    return "neutral"


def fetch_competitor_news(competitor: dict, days_lookback: int = 7) -> list:
    try:
        result = subprocess.run(
            [
                sys.executable, "tools/search_news.py",
                "--query", competitor["name"],
                "--company-id", competitor["id"],
                "--max-age-days", str(days_lookback),
            ],
            capture_output=True, text=True, timeout=30, encoding="utf-8",
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            return data.get("items", [])
    except Exception as e:
        print(f"[competitors] news fetch error for {competitor['name']}: {e}", file=sys.stderr)
    return []


def run_accounts_mode(company_id: str, competitors: list, output_dir: str) -> dict:
    bundle = load_research_bundle(company_id)
    mentions = []
    if bundle:
        mentions = scan_research_bundle_for_competitors(bundle, competitors)

    displacement_signals = [m for m in mentions if m["signal_type"] == "displacement"]
    evaluation_signals = [m for m in mentions if m["signal_type"] == "evaluation"]
    target_uses_competitor = any(
        m["signal_strength"] == "high" and m["source_type"] in ("website", "job_description")
        for m in mentions
    )

    strategy = recommended_strategy(mentions)
    strategic_notes = {
        "displacement": "Target shows signs of displacing a competitor. Lead with your displacement playbook.",
        "competitive_defense": "Target is evaluating alternatives. Get in now before they choose.",
        "neutral": "No strong competitive signals detected. Standard approach.",
    }.get(strategy, "")

    result = {
        "schema_version": SCHEMA_VERSION,
        "company_id": company_id,
        "assessed_at": _now(),
        "competitor_mentions_in_target": mentions,
        "target_uses_competitor": target_uses_competitor,
        "competitive_displacement_signals": displacement_signals,
        "evaluation_signals": evaluation_signals,
        "recommended_strategy": strategy,
        "strategic_notes": strategic_notes,
    }

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        company_dir = Path(output_dir) / company_id
        company_dir.mkdir(parents=True, exist_ok=True)
        out_path = company_dir / f"{_today()}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"[competitors] written to {out_path}", file=sys.stderr)

    return result


def run_competitors_mode(competitors: list, output_dir: str, days_lookback: int = 7) -> list:
    all_news = []
    for comp in competitors:
        news = fetch_competitor_news(comp, days_lookback)
        all_news.extend(news)
        print(f"[competitors] {comp['name']}: {len(news)} news items", file=sys.stderr)

    if output_dir and all_news:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"_competitor_news_{_today()}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": SCHEMA_VERSION,
                "generated_at": _now(),
                "items": all_news,
            }, f, indent=2)

    return all_news


def main():
    parser = argparse.ArgumentParser(description="Competitive intelligence — monitor competitors + scan accounts")
    parser.add_argument("--mode", choices=["competitors", "accounts", "both"], default="both")
    parser.add_argument("--company-id", help="Single target company")
    parser.add_argument("--all-companies", action="store_true")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--competitors-file", default="data/competitors.json")
    parser.add_argument("--output-dir", default="outputs/competitive")
    parser.add_argument("--days-lookback", type=int, default=7)
    args = parser.parse_args()

    competitors_data = load_json(args.competitors_file, {})
    competitors = competitors_data.get("your_competitors", [])

    if not competitors:
        print(json.dumps({"note": "No competitors configured in data/competitors.json"}))
        sys.exit(0)

    output = {}

    if args.mode in ("competitors", "both"):
        news = run_competitors_mode(competitors, args.output_dir, args.days_lookback)
        output["competitor_news_items"] = len(news)

    if args.mode in ("accounts", "both"):
        companies_data = load_json(args.companies_file, {"companies": []})

        if args.company_id:
            target_companies = [c for c in companies_data["companies"] if c["id"] == args.company_id]
        else:
            target_companies = companies_data["companies"]

        account_results = []
        for company in target_companies:
            result = run_accounts_mode(company["id"], competitors, args.output_dir)
            account_results.append(result)

        output["accounts_scanned"] = len(account_results)
        output["accounts_with_mentions"] = sum(1 for r in account_results if r["competitor_mentions_in_target"])
        output["account_results"] = account_results

    output["generated_at"] = _now()
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
