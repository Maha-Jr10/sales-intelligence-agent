# Workflow: Stakeholder Mapping

## Objective
Identify the four key stakeholder roles for a target company from public sources: Economic Buyer (budget approver), Technical Evaluator (runs the PoC), Champion (internal advocate), and Executive Sponsor (strategic owner). Determine outreach readiness based on confidence in Economic Buyer identification.

## Required Inputs
- Company ID (must exist in `data/companies.json`)
- Company website URL and LinkedIn URL (from `data/companies.json`)
- `data/signal_weights.json` — seniority keyword patterns used for classification

## Outreach Readiness Rules
| economic_buyer.confidence | Action |
|--------------------------|--------|
| ≥ 0.8 (proceed) | Generate outreach immediately |
| 0.5–0.79 (caution) | Note gap in brief, flag for LinkedIn verification |
| < 0.5 (escalate) | Do not generate outreach — request manual research |

Confidence formula: `1 - (0.5 ** n)` where n = number of independent title signals for that role.
- 1 signal → 0.50, 2 → 0.75, 3 → 0.875, 4+ → 0.9375+ (capped at 0.95)

## Agent Steps

### Step 1 — Run Stakeholder Mapping Tool
```
python tools/map_stakeholders.py --company-id {id} --output-dir outputs/stakeholder_maps/
```

The tool scrapes `/team`, `/about`, `/leadership`, `/company`, and the LinkedIn company public page.

### Step 2 — Review `outreach_readiness` Field
- **`proceed`**: Economic buyer identified with ≥ 0.8 confidence. Move to Step 4.
- **`caution`**: Economic buyer identified but confidence < 0.8. Note the gap. Move to Step 3 before outreach.
- **`escalate`**: Economic buyer not identified. Stop and request manual research. Do not generate outreach sequences without an economic buyer.

### Step 3 — Gap Resolution (if caution or escalate)
If economic buyer is missing or low-confidence:

Option A — LinkedIn manual check:
Look up the company on LinkedIn, identify current C-suite and VP-level titles in the relevant department. Add the contact manually by running:
```
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field known_contacts \
    --value '[{"name": "...", "title": "...", "role": "economic_buyer", "source": "linkedin_manual"}]'
```

Option B — Accept partial coverage:
If the company is small (<50 employees) and the founder/CEO is clearly the economic buyer, note this explicitly: "CEO is likely economic buyer at this company size."

Option C — Deprioritize:
If no public leadership information is findable, move the account to `caution` status in memory and revisit in 2 weeks.

### Step 4 — Review All Identified Contacts
For each stakeholder role:
- Is the identified person still at the company? (Check their LinkedIn title is current)
- Is the `rationale` sensible? (Title pattern match for CTO = valid; "Director of People Ops" classified as economic_buyer = incorrect)
- Are any roles duplicated? (The same person might be both champion and technical evaluator at a small company — that's valid)

### Step 5 — Confirm `recommended_first_contact`
The tool selects the highest-confidence economic_buyer as the recommended first contact. Verify this makes sense for your outreach motion:
- If the economic buyer is C-suite but your product typically sells to directors, note: "Approach technical evaluator first as champion, then escalate to CTO"
- If multiple contacts share the same role with similar confidence, pick the one most relevant to your product's pain point

### Step 6 — Update Account Memory
```
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field known_contacts \
    --value '[{identified contacts as JSON}]'
```

Note the stakeholder map generation in the brief's `data_freshness` field.

### Step 7 — Pass to Deal Playbook Generation
If outreach_readiness is `proceed` or `caution` (with noted gaps), proceed to `deal_playbook_generation.md`.

If `escalate`, stop here and inform the user that manual contact research is needed.

## Expected Outputs
- `outputs/stakeholder_maps/{company_id}.json`
- Memory updated with known contacts
- Clear outreach_readiness status reported to user

## Error Handling
- **Website pages return 403**: The tool continues to next page candidates. If all pages fail, check if the company uses a custom domain or has a different `/about` path.
- **Very small company**: The team page may list only the founders. A 3-person company with just a CEO listed: classify CEO as economic_buyer + technical_evaluator + executive_sponsor (note this overlap explicitly).
- **No LinkedIn URL in companies.json**: The LinkedIn scrape step is skipped. Add the URL to companies.json if available.
- **False title classifications**: e.g., "VP of Marketing" classified as economic_buyer — correct this manually and note the correct role.

## Validation Checks
- [ ] Stakeholder map file exists at `outputs/stakeholder_maps/{company_id}.json`
- [ ] `schema_version: "2.0"` present
- [ ] `outreach_readiness` is one of: `proceed`, `caution`, `escalate`
- [ ] Each stakeholder role has a top-level `confidence` field (not just per-contact confidence)
- [ ] `recommended_first_contact` is populated (or explicitly null if no contacts found)

## Lessons Learned
_Updated by agent as patterns are discovered._

- Team pages often list only 10-15 people even at 200-person companies. The stakeholder map is a starting point, not a complete org chart.
- Founders often hold multiple stakeholder roles simultaneously. At Series A/B companies, the CEO or CTO is usually economic_buyer + executive_sponsor.
- Companies with `/leadership` pages typically have more structured executive listings than `/about` pages — check this path first.
- LinkedIn company pages show job titles only in their "People" tab, which is sometimes gated. The public About page may show leadership with titles.
