"""
Assemble a deal playbook from existing outputs.

Reads: brief + stakeholder map + competitive intel + playbook templates + seller profile.
Selects the highest-priority matching template. Produces JSON + Markdown playbook.
No HTTP calls — pure assembly from existing output files.

Usage:
    python tools/generate_playbook.py --company-id stripe --date 2026-06-03
    python tools/generate_playbook.py --company-id stripe \
        --output-dir outputs/playbooks/

Exit codes: 0 success, 1 partial (missing inputs), 2 fatal
"""

import argparse
import json
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
    except Exception:
        return default


def find_latest_file(directory: Path, pattern: str) -> Path | None:
    candidates = sorted(directory.glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def load_brief(company_id: str, date_str: str, briefs_dir: str = "outputs/briefs") -> dict | None:
    path = Path(briefs_dir) / company_id / f"{date_str}.json"
    if path.exists():
        return load_json(str(path))
    latest = find_latest_file(Path(briefs_dir) / company_id, "*.json")
    return load_json(str(latest)) if latest else None


def load_stakeholder_map(company_id: str, maps_dir: str = "outputs/stakeholder_maps") -> dict | None:
    path = Path(maps_dir) / f"{company_id}.json"
    return load_json(str(path)) if path.exists() else None


def load_competitive_intel(company_id: str, date_str: str,
                            comp_dir: str = "outputs/competitive") -> dict | None:
    comp_path = Path(comp_dir) / company_id
    if not comp_path.exists():
        return None
    path = comp_path / f"{date_str}.json"
    if path.exists():
        return load_json(str(path))
    latest = find_latest_file(comp_path, "*.json")
    return load_json(str(latest)) if latest else None


def select_template(brief: dict, competitive_intel: dict | None, templates: list) -> dict | None:
    if not templates:
        return None

    if competitive_intel and competitive_intel.get("recommended_strategy") == "displacement":
        comp_template = next((t for t in templates if t["id"] == "competitive-displacement"), None)
        if comp_template:
            return comp_template

    signal_types_in_brief = set()
    for sig_id in brief.get("signals_analyzed", []):
        parts = str(sig_id).split("-")
        if len(parts) >= 3:
            signal_types_in_brief.add(parts[1] if len(parts) > 2 else "")

    buying_signals = brief.get("buying_signals", [])
    for sig in buying_signals:
        signal_types_in_brief.add(sig.get("signal_type", "").split(":")[0])

    for sig_ref in brief.get("signals_analyzed", []):
        for sig_type in ["leadership_change", "funding_event", "hiring_spike",
                         "product_launch", "tech_change", "competitive_pressure"]:
            if sig_type in str(sig_ref):
                signal_types_in_brief.add(sig_type)

    matching = []
    for template in templates:
        trigger = template.get("trigger_signal", "")
        if trigger in signal_types_in_brief:
            matching.append(template)

    if not matching:
        fallback = min(templates, key=lambda t: t.get("priority", 0))
        return {**fallback, "_fallback": True}

    matching.sort(key=lambda t: t.get("priority", 0), reverse=True)
    return matching[0]


def format_playbook_markdown(playbook: dict, brief: dict, seller_profile: dict) -> str:
    lines = []
    company_name = brief.get("company_snapshot", {}).get("name", playbook["company_id"])

    lines.append(f"# Deal Playbook — {company_name}")
    lines.append(f"\n_Generated: {playbook['generated_at']}_\n")
    lines.append("---\n")

    lines.append(f"## Template: {playbook['template_used']}")
    lines.append(f"**Priority:** {playbook['template_priority']} | **Trigger:** {', '.join(playbook['trigger_signals'])}\n")

    lines.append("## Recommended Angle")
    lines.append(f"{playbook['recommended_angle']}\n")

    contact = playbook.get("primary_contact", {})
    if contact:
        lines.append("## Primary Contact")
        lines.append(f"**Name:** {contact.get('name', '[Research needed]')}  ")
        lines.append(f"**Title:** {contact.get('title', '')}  ")
        lines.append(f"**Role:** {contact.get('role', '').replace('_', ' ').title()}  ")
        lines.append(f"**Confidence:** {contact.get('confidence', 0):.0%}\n")

    messaging = playbook.get("messaging", {})
    if messaging.get("value_angle"):
        lines.append("## Messaging")
        lines.append(f"**Value Hook:** {messaging['value_angle']}\n")
        if messaging.get("differentiation_points"):
            lines.append("**Differentiation:**")
            for pt in messaging["differentiation_points"]:
                lines.append(f"- {pt}")
            lines.append("")

    objections = playbook.get("objection_handling", [])
    if objections:
        lines.append("## Objection Handling")
        for obj in objections:
            lines.append(f"**Objection:** _{obj['objection']}_")
            lines.append(f"**Response:** {obj['response']}\n")

    cta = playbook.get("suggested_cta")
    if cta:
        lines.append("## Suggested CTA")
        lines.append(f"{cta}\n")

    seq = playbook.get("sequence_plan", {})
    if seq:
        lines.append("## Sequence Plan")
        lines.append(f"- **Step 1 Channel:** {seq.get('step_1_channel', 'email')}")
        follow_ups = seq.get("follow_up_days", [])
        if follow_ups:
            lines.append(f"- **Follow-up Days:** {', '.join(str(d) for d in follow_ups)}")
        lines.append("")

    comp_context = playbook.get("competitive_context", "neutral")
    if comp_context != "neutral":
        lines.append("## Competitive Context")
        lines.append(f"Strategy: **{comp_context.replace('_', ' ').title()}**\n")

    actions = playbook.get("next_actions", [])
    if actions:
        lines.append("## Next Actions")
        for action in actions:
            lines.append(f"- {action}")
        lines.append("")

    lines.append("\n---\n")
    lines.append(f"_Playbook ID: {playbook['playbook_id']}_")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Assemble deal playbook from existing output files")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--date", default=None)
    parser.add_argument("--briefs-dir", default="outputs/briefs")
    parser.add_argument("--stakeholder-maps-dir", default="outputs/stakeholder_maps")
    parser.add_argument("--competitive-dir", default="outputs/competitive")
    parser.add_argument("--templates-file", default="data/playbook_templates.json")
    parser.add_argument("--seller-profile-file", default="data/seller_profile.json")
    parser.add_argument("--output-dir", default="outputs/playbooks")
    args = parser.parse_args()

    date_str = args.date or _today()
    company_id = args.company_id

    brief = load_brief(company_id, date_str, args.briefs_dir)
    if not brief:
        print(json.dumps({"error": f"no brief found for {company_id}. Run intelligence_brief_generation first."}))
        sys.exit(1)

    stakeholder_map = load_stakeholder_map(company_id, args.stakeholder_maps_dir)
    competitive_intel = load_competitive_intel(company_id, date_str, args.competitive_dir)
    templates_data = load_json(args.templates_file, {})
    templates = templates_data.get("playbooks", [])
    seller_profile = load_json(args.seller_profile_file, {})

    template = select_template(brief, competitive_intel, templates)
    if not template:
        print(json.dumps({"error": "no templates available in playbook_templates.json"}))
        sys.exit(2)

    primary_contact = None
    if stakeholder_map:
        rec = stakeholder_map.get("recommended_first_contact")
        if rec:
            primary_contact = rec
        else:
            for role in ["economic_buyer", "technical_evaluator", "champion"]:
                contacts = stakeholder_map.get("stakeholders", {}).get(role, {}).get("identified", [])
                if contacts:
                    best = max(contacts, key=lambda c: c.get("confidence", 0))
                    primary_contact = {**best, "role": role}
                    break

    trigger_signals = []
    for sig in brief.get("buying_signals", []):
        sig_type = sig.get("signal_type") or ""
        if sig_type:
            trigger_signals.append(sig_type)
    if not trigger_signals:
        trigger_signals = [template.get("trigger_signal", "unknown")]

    outreach_readiness = stakeholder_map.get("outreach_readiness") if stakeholder_map else "unknown"
    comp_strategy = competitive_intel.get("recommended_strategy", "neutral") if competitive_intel else "neutral"

    playbook_id = f"{company_id}-playbook-{date_str}"
    brief_id = brief.get("brief_id", "")

    playbook = {
        "schema_version": SCHEMA_VERSION,
        "playbook_id": playbook_id,
        "company_id": company_id,
        "generated_at": _now(),
        "based_on_brief": brief_id,
        "based_on_stakeholder_map": bool(stakeholder_map),
        "based_on_competitive_intel": bool(competitive_intel),
        "template_used": template["id"],
        "template_priority": template.get("priority", 0),
        "template_is_fallback": template.get("_fallback", False),
        "trigger_signals": list(set(trigger_signals))[:5],
        "recommended_angle": template.get("recommended_angle", ""),
        "primary_contact": primary_contact,
        "outreach_readiness": outreach_readiness,
        "messaging": {
            "value_angle": template.get("value_hook", ""),
            "relevant_case_studies": [
                s.get("company") for s in seller_profile.get("social_proof", [])
                if s.get("case_study_url")
            ],
            "differentiation_points": seller_profile.get("value_proposition", {}).get("secondary", []),
        },
        "objection_handling": template.get("objections", []),
        "suggested_cta": template.get("primary_cta", "15-min call this week?"),
        "sequence_plan": {
            "step_1_channel": template.get("sequence_timing", {}).get("step_1_channel", "email"),
            "follow_up_days": template.get("sequence_timing", {}).get("follow_up_days", [3, 7, 21]),
        },
        "competitive_context": comp_strategy,
        "urgency_note": template.get("urgency_note", ""),
        "next_actions": [
            f"Send initial outreach via {template.get('sequence_timing', {}).get('step_1_channel', 'email')}",
            f"CTA: {template.get('primary_cta', '')}",
        ],
    }

    if args.output_dir:
        company_dir = Path(args.output_dir) / company_id
        company_dir.mkdir(parents=True, exist_ok=True)

        json_path = company_dir / f"{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(playbook, f, indent=2)

        md_content = format_playbook_markdown(playbook, brief, seller_profile)
        md_path = company_dir / f"{date_str}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"[playbook] written to {json_path} and {md_path}", file=sys.stderr)

    print(json.dumps(playbook, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
