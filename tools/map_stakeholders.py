"""
Identify likely stakeholder roles (champion, technical evaluator, economic buyer,
executive sponsor) from public company pages.

Uses scrape_website.py subprocess for all HTTP — no direct requests in this tool.
Confidence formula: 1 - (0.5 ** n), capped at 0.95.

Usage:
    python tools/map_stakeholders.py --company-id stripe
    python tools/map_stakeholders.py --companies-file data/companies.json \
        --output-dir outputs/stakeholder_maps/

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


ROLE_PATTERNS = {
    "economic_buyer": [
        r"\bCTO\b", r"\bCPO\b", r"\bCEO\b", r"\bCOO\b",
        r"\bVP\s+(?:of\s+)?Engineering\b", r"\bVP\s+(?:of\s+)?Product\b",
        r"\bVP\s+(?:of\s+)?Technology\b", r"\bHead\s+of\s+Engineering\b",
        r"\bHead\s+of\s+Product\b", r"\bChief\s+Technology\b",
        r"\bChief\s+Product\b", r"\bChief\s+Information\b",
    ],
    "technical_evaluator": [
        r"\bStaff\s+(?:Software\s+)?Engineer\b", r"\bPrincipal\s+Engineer\b",
        r"\bDistinguished\s+Engineer\b", r"\bSenior\s+Staff\b",
        r"\bArchitect\b", r"\bTech(?:nical)?\s+Lead\b",
        r"\bLead\s+(?:Software\s+)?Engineer\b", r"\bPlatform\s+(?:Lead|Architect)\b",
        r"\bInfrastructure\s+(?:Lead|Architect)\b", r"\bData\s+(?:Architect|Lead)\b",
    ],
    "champion": [
        r"\bDirector\s+(?:of\s+)?Engineering\b", r"\bDirector\s+(?:of\s+)?Product\b",
        r"\bDirector\s+(?:of\s+)?Technology\b", r"\bEngineering\s+Manager\b",
        r"\bProduct\s+Manager\b", r"\bSenior\s+(?:Product|Engineering)\s+Manager\b",
        r"\bGroup\s+(?:Product|Engineering)\s+Manager\b",
    ],
    "executive_sponsor": [
        r"\bCEO\b", r"\bCOO\b", r"\bChief\s+Executive\b",
        r"\bChief\s+Operating\b", r"\bPresident\b",
        r"\bCRO\b", r"\bChief\s+Revenue\b",
        r"\bFounder\b", r"\bCo-Founder\b",
    ],
}

PAGES_TO_SCRAPE = ["/team", "/about", "/leadership", "/company", "/about-us"]


def scrape_page(url: str) -> str | None:
    try:
        result = subprocess.run(
            [sys.executable, "tools/scrape_website.py", "--url", url, "--skip-robots"],
            capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            if not data.get("error"):
                return data.get("text_content", "")
    except Exception as e:
        print(f"[stakeholders] scrape error for {url}: {e}", file=sys.stderr)
    return None


def extract_person_mentions(text: str) -> list[str]:
    title_pattern = re.compile(
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[\n,|·•]\s*([A-Z][^,\n]{5,60})",
        re.MULTILINE
    )
    mentions = []
    for match in title_pattern.finditer(text):
        name_candidate = match.group(1).strip()
        title_candidate = match.group(2).strip()
        if 2 <= len(name_candidate.split()) <= 4 and 3 <= len(title_candidate) <= 80:
            mentions.append(f"{name_candidate} | {title_candidate}")
    return mentions


def classify_title(title: str) -> list[str]:
    matched_roles = []
    for role, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, title, re.IGNORECASE):
                matched_roles.append(role)
                break
    return matched_roles


def confidence(n_signals: int) -> float:
    if n_signals == 0:
        return 0.0
    raw = 1.0 - (0.5 ** n_signals)
    return min(round(raw, 4), 0.95)


def map_stakeholders_for_company(company: dict, output_dir: str) -> dict:
    company_id = company["id"]
    company_name = company.get("name", company_id)
    website = company.get("website", f"https://{company.get('domain', '')}")
    domain = company.get("domain", "")

    stakeholders: dict[str, list] = {
        "economic_buyer": [],
        "technical_evaluator": [],
        "champion": [],
        "executive_sponsor": [],
    }
    data_sources = []
    all_text = ""

    for slug in PAGES_TO_SCRAPE:
        url = f"{website.rstrip('/')}{slug}"
        text = scrape_page(url)
        if text and len(text) > 200:
            all_text += " " + text
            data_sources.append(f"website{slug}")

    if company.get("linkedin_url"):
        li_text = scrape_page(company["linkedin_url"])
        if li_text:
            all_text += " " + li_text
            data_sources.append("linkedin_public")

    mentions = extract_person_mentions(all_text)

    contact_by_role: dict[str, list] = {k: [] for k in stakeholders}
    role_signal_counts: dict[str, int] = {k: 0 for k in stakeholders}

    for mention in mentions:
        parts = mention.split(" | ", 1)
        if len(parts) != 2:
            continue
        name, title = parts[0].strip(), parts[1].strip()
        roles = classify_title(title)
        for role in roles:
            if role in contact_by_role:
                existing_names = [c["name"] for c in contact_by_role[role]]
                if name not in existing_names:
                    role_signal_counts[role] += 1
                    conf = confidence(role_signal_counts[role])
                    contact_by_role[role].append({
                        "name": name,
                        "title": title,
                        "source_url": website,
                        "confidence": conf,
                        "rationale": f"Title pattern match: {title}",
                    })

    for role in stakeholders:
        n = role_signal_counts[role]
        role_conf = confidence(n)
        stakeholders[role] = {
            "description": {
                "economic_buyer": "Approves the budget — VP+/C-suite with P&L in the technical domain",
                "technical_evaluator": "Conducts the technical evaluation and PoC",
                "champion": "Internal advocate — user of your solution who pushes for adoption",
                "executive_sponsor": "C-suite owner of the strategic outcome",
            }[role],
            "confidence": role_conf,
            "identified": contact_by_role[role],
        }

    ec_confidence = stakeholders["economic_buyer"]["confidence"]
    if ec_confidence >= 0.8:
        outreach_readiness = "proceed"
    elif ec_confidence >= 0.5:
        outreach_readiness = "caution"
    else:
        outreach_readiness = "escalate"

    recommended_contact = None
    for role in ["economic_buyer", "technical_evaluator", "champion", "executive_sponsor"]:
        contacts = stakeholders[role]["identified"]
        if contacts:
            best = max(contacts, key=lambda c: c["confidence"])
            if recommended_contact is None or best["confidence"] > recommended_contact.get("confidence", 0):
                recommended_contact = {
                    "name": best["name"],
                    "title": best["title"],
                    "role": role,
                    "confidence": best["confidence"],
                    "rationale": f"Highest-confidence {role.replace('_', ' ')} identified",
                }

    gaps = [role for role, data in stakeholders.items() if not data["identified"]]
    coverage_note = (
        "All stakeholder roles identified." if not gaps
        else f"Missing roles: {', '.join(gaps)}. Manual research recommended."
    )

    result = {
        "schema_version": SCHEMA_VERSION,
        "company_id": company_id,
        "company_name": company_name,
        "generated_at": _now(),
        "data_sources": list(set(data_sources)),
        "stakeholders": stakeholders,
        "role_confidence_thresholds": {"proceed": 0.8, "caution": 0.5, "escalate": 0.0},
        "recommended_first_contact": recommended_contact,
        "outreach_readiness": outreach_readiness,
        "coverage_notes": coverage_note,
    }

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"{company_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"[stakeholders] written to {out_path}", file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(description="Map stakeholder roles from public company pages")
    parser.add_argument("--company-id", help="Single company ID")
    parser.add_argument("--companies-file", default="data/companies.json")
    parser.add_argument("--output-dir", default="outputs/stakeholder_maps")
    args = parser.parse_args()

    with open(args.companies_file, encoding="utf-8") as f:
        companies_data = json.load(f)

    if args.company_id:
        companies = [c for c in companies_data["companies"] if c["id"] == args.company_id]
        if not companies:
            print(json.dumps({"error": f"company_id '{args.company_id}' not found"}))
            sys.exit(2)
    else:
        companies = companies_data["companies"]

    results = []
    errors = []
    for company in companies:
        try:
            result = map_stakeholders_for_company(company, args.output_dir)
            results.append(result)
        except Exception as e:
            print(f"[stakeholders] error for {company['id']}: {e}", file=sys.stderr)
            errors.append({"company_id": company["id"], "error": str(e)})

    if len(results) == 1 and not errors:
        print(json.dumps(results[0], ensure_ascii=False))
    else:
        print(json.dumps({
            "processed": len(results),
            "errors": errors,
            "results": results,
        }, ensure_ascii=False))

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
