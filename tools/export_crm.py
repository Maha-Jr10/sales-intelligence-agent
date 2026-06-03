"""
Transform intelligence briefs and signals into CRM-ready JSON payloads.

Supports HubSpot (default), Salesforce, and Pipedrive schemas.
Does NOT make any API calls — produces JSON payloads for manual upload or future sync tools.

Usage:
    python tools/export_crm.py --company-id stripe --crm hubspot
    python tools/export_crm.py --all-companies --crm hubspot --date 2025-01-15
    python tools/export_crm.py --all-companies --crm salesforce

Exit codes: 0 success, 1 partial, 2 fatal
"""

import argparse
import json
import sys
from datetime import datetime, timezone
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


def load_brief(company_id: str, date_str: str = None, briefs_dir: str = "outputs/briefs") -> dict | None:
    if date_str:
        path = Path(briefs_dir) / company_id / f"{date_str}.json"
        if path.exists():
            return load_json(str(path))

    company_briefs = sorted(
        Path(briefs_dir).glob(f"{company_id}/*.json"),
        reverse=True
    )
    for brief_path in company_briefs:
        data = load_json(str(brief_path))
        if data:
            return data
    return None


def load_score_for_company(company_id: str, date_str: str, signals_dir: str = "outputs/signals") -> float | None:
    for name in (f"scores-{date_str}.json", f"multi_factor_scores-{date_str}.json"):
        path = Path(signals_dir) / name
        if not path.exists():
            continue
        data = load_json(str(path))
        if not data:
            continue
        entries = data if isinstance(data, list) else data.get("scores", [])
        for entry in entries:
            if entry.get("company_id") == company_id:
                return (
                    entry.get("composite_score")
                    or entry.get("score", {}).get("total")
                )
    return None


US_STATE_ABBREVS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def _infer_country(headquarters: str) -> str | None:
    if not headquarters:
        return None
    parts = [p.strip() for p in headquarters.split(",")]
    if any(p in US_STATE_ABBREVS for p in parts):
        return "US"
    if "United States" in headquarters or " US" in headquarters:
        return "US"
    return None


def load_signals_for_company(company_id: str, date_str: str, signals_dir: str = "outputs/signals") -> list:
    path = Path(signals_dir) / f"{date_str}.json"
    if not path.exists():
        return []
    all_signals = load_json(str(path), [])
    return [s for s in all_signals if s.get("company_id") == company_id]


def build_hubspot_records(company: dict, brief: dict | None, signals: list, date_str: str,
                          signals_dir: str = "outputs/signals") -> list:
    records = []
    company_id = company["id"]
    company_name = company.get("name", "")
    domain = company.get("domain", "")

    emp_estimate = company.get("employee_count_estimate", "")
    emp_count = None
    if emp_estimate:
        import re
        nums = re.findall(r"\d+", emp_estimate.replace(",", ""))
        if nums:
            emp_count = int(nums[0])

    score = brief.get("opportunity_score", {}).get("total") if brief else None
    if score is None:
        score = load_score_for_company(company_id, date_str, signals_dir)
    tier = brief.get("opportunity_score", {}).get("tier") if brief else company.get("tier")
    top_signal = signals[0].get("title", "") if signals else ""
    exec_summary = brief.get("executive_summary", "") if brief else ""

    tech_stack = []
    if brief:
        tech_stack = brief.get("company_snapshot", {}).get("tech_stack", [])

    brief_path = ""
    if brief:
        brief_path = f"outputs/briefs/{company_id}/{date_str}.md"

    records.append({
        "record_type": "company",
        "action": "upsert",
        "match_field": "domain",
        "platform": "hubspot",
        "data": {
            "domain": domain,
            "name": company_name,
            "industry": company.get("industry", ""),
            "numberofemployees": emp_count,
            "city": (company.get("headquarters") or "").split(",")[0].strip() or None,
            "country": _infer_country(company.get("headquarters") or ""),
            "website": company.get("website", ""),
            "linkedincompanypage": company.get("linkedin_url", ""),
            "custom_properties": {
                "icp_fit_score": score,
                "icp_tier": tier,
                "funding_stage": company.get("funding_stage", ""),
                "tech_stack_detected": ", ".join(tech_stack[:8]) if tech_stack else "",
                "last_signal_date": date_str,
                "top_signal": top_signal[:200],
                "intelligence_brief_path": brief_path,
                "monitoring_tier": company.get("tier", ""),
                "sales_owner": company.get("assigned_to", ""),
            },
        },
    })

    if brief:
        key_contacts = brief.get("key_contacts", [])
        for contact in key_contacts[:3]:
            records.append({
                "record_type": "contact",
                "action": "upsert",
                "match_field": "linkedin_url",
                "platform": "hubspot",
                "data": {
                    "firstname": (contact.get("name") or "").split()[0] if contact.get("name") else "",
                    "lastname": " ".join((contact.get("name") or "").split()[1:]) or "",
                    "jobtitle": contact.get("title", ""),
                    "company": company_name,
                    "email": contact.get("email"),
                    "hs_linkedin_biography": contact.get("linkedin_url"),
                    "custom_properties": {
                        "outreach_priority": contact.get("outreach_priority", 1),
                        "outreach_angle": (brief.get("recommended_outreach_angles") or [""])[0][:200],
                        "relevance": contact.get("relevance", ""),
                        "data_source": contact.get("source", "public_research"),
                    },
                },
            })

    if brief and score and score >= 50:
        records.append({
            "record_type": "deal",
            "action": "create_if_not_exists",
            "match_field": "dealname",
            "platform": "hubspot",
            "data": {
                "dealname": f"{company_name} — Intelligence Brief {date_str}",
                "pipeline": "outbound",
                "dealstage": "signal_detected",
                "closedate": None,
                "amount": None,
                "custom_properties": {
                    "trigger_signal": signals[0].get("signal_type", "") if signals else "",
                    "opportunity_score": score,
                    "recommended_action": (brief.get("next_actions") or [""])[0][:300],
                    "icp_tier": tier,
                },
            },
        })

    if brief:
        note_body = f"[AI Intelligence Brief — {date_str}]\n\n"
        note_body += f"COMPANY: {company_name}\n\n"
        if exec_summary:
            note_body += f"SUMMARY:\n{exec_summary}\n\n"
        if signals:
            note_body += "SIGNALS DETECTED:\n"
            for sig in signals[:5]:
                note_body += f"- {sig.get('title', '')}\n"
            note_body += "\n"
        angles = brief.get("recommended_outreach_angles", [])
        if angles:
            note_body += f"RECOMMENDED ANGLE:\n{angles[0]}\n\n"
        if brief_path:
            note_body += f"FULL BRIEF: {brief_path}"

        records.append({
            "record_type": "note",
            "action": "create",
            "associated_company_domain": domain,
            "platform": "hubspot",
            "data": {
                "body": note_body[:5000],
                "timestamp": _now(),
            },
        })

    return records


def build_salesforce_records(company: dict, brief: dict | None, signals: list, date_str: str) -> list:
    records = []
    company_name = company.get("name", "")
    domain = company.get("domain", "")
    score = brief.get("opportunity_score", {}).get("total") if brief else None
    top_signal = signals[0].get("title", "") if signals else ""

    records.append({
        "record_type": "Account",
        "action": "upsert",
        "match_field": "Website",
        "platform": "salesforce",
        "data": {
            "Name": company_name,
            "Website": company.get("website", ""),
            "Industry": company.get("industry", ""),
            "NumberOfEmployees": None,
            "BillingCity": (company.get("headquarters") or "").split(",")[0].strip() or None,
            "Description": brief.get("executive_summary", "") if brief else "",
            "Intelligence_Score__c": score,
            "Top_Signal__c": top_signal[:255],
            "Last_Signal_Date__c": date_str,
        },
    })

    if brief:
        exec_summary = brief.get("executive_summary", "")
        records.append({
            "record_type": "Task",
            "action": "create",
            "platform": "salesforce",
            "data": {
                "Subject": f"Review intelligence brief: {company_name}",
                "Description": exec_summary[:2000],
                "Status": "Not Started",
                "Priority": "High" if (score or 0) >= 75 else "Normal",
                "ActivityDate": date_str,
            },
        })

    return records


def build_pipedrive_records(company: dict, brief: dict | None, signals: list, date_str: str) -> list:
    records = []
    company_name = company.get("name", "")
    score = brief.get("opportunity_score", {}).get("total") if brief else None
    top_signal = signals[0].get("title", "") if signals else ""

    records.append({
        "record_type": "Organization",
        "action": "upsert",
        "platform": "pipedrive",
        "data": {
            "name": company_name,
            "web_site": company.get("website", ""),
            "address": company.get("headquarters", ""),
            "customFields": {
                "Intelligence Score": score,
                "Top Signal": top_signal[:200],
                "Last Signal Date": date_str,
            },
        },
    })

    if brief and (score or 0) >= 50:
        records.append({
            "record_type": "Deal",
            "action": "create_if_not_exists",
            "platform": "pipedrive",
            "data": {
                "title": f"{company_name} — Outbound Signal {date_str}",
                "status": "open",
                "stage_id": None,
                "probability": min(100, int(score or 0)) if score else None,
            },
        })

    return records


SCHEMA_BUILDERS = {
    "hubspot": build_hubspot_records,
    "salesforce": build_salesforce_records,
    "pipedrive": build_pipedrive_records,
}


def export_company(company: dict, crm: str, date_str: str,
                   briefs_dir: str, signals_dir: str) -> dict:
    brief = load_brief(company["id"], date_str, briefs_dir)
    signals = load_signals_for_company(company["id"], date_str, signals_dir)

    builder = SCHEMA_BUILDERS.get(crm)
    if builder:
        if crm == "hubspot":
            records = builder(company, brief, signals, date_str, signals_dir)
        else:
            records = builder(company, brief, signals, date_str)
    else:
        print(f"[export_crm] unknown CRM '{crm}', using universal format", file=sys.stderr)
        records = build_hubspot_records(company, brief, signals, date_str, signals_dir)

    return {
        "company_id": company["id"],
        "company_name": company.get("name", ""),
        "crm_target": crm,
        "has_brief": brief is not None,
        "signals_count": len(signals),
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate CRM-ready JSON export records")
    parser.add_argument("--company-id", help="Export one company")
    parser.add_argument("--all-companies", action="store_true")
    parser.add_argument("--crm", default="hubspot", choices=["hubspot", "salesforce", "pipedrive"])
    parser.add_argument("--date", help="Date to load signals/briefs for (default: today)")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--briefs-dir", default="outputs/briefs")
    parser.add_argument("--signals-dir", default="outputs/signals")
    parser.add_argument("--exports-dir", default="outputs/crm_exports")
    parser.add_argument("--output-file", help="Write export to this path")
    args = parser.parse_args()

    date_str = args.date or _today()
    Path(args.exports_dir).mkdir(parents=True, exist_ok=True)

    companies_data = load_json(args.companies_file, {"companies": []})

    if args.company_id:
        companies = [c for c in companies_data["companies"] if c["id"] == args.company_id]
        if not companies:
            print(json.dumps({"error": f"company_id not found"}))
            sys.exit(2)
    else:
        companies = companies_data["companies"]

    all_exports = []
    for company in companies:
        result = export_company(company, args.crm, date_str, args.briefs_dir, args.signals_dir)
        all_exports.append(result)

    export_doc = {
        "export_id": f"crm-export-{date_str}-{args.crm}",
        "generated_at": _now(),
        "crm_target": args.crm,
        "date": date_str,
        "companies_exported": len(all_exports),
        "exports": all_exports,
    }

    out_file = args.output_file or str(Path(args.exports_dir) / f"{date_str}_{args.crm}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(export_doc, f, indent=2)
    print(f"[export_crm] written to {out_file}", file=sys.stderr)

    print(json.dumps(export_doc, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
