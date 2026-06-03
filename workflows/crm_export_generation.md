# Workflow: CRM Export Generation

## Objective
Generate CRM-ready JSON records for all accounts with briefs or signals from today. These exports are ready to import into HubSpot, Salesforce, or Pipedrive, or to be pushed via their APIs when a sync tool is configured.

## Required Inputs
- Intelligence briefs in `outputs/briefs/` (for companies that have been briefed)
- Signals from `outputs/signals/{today}.json`
- `data/companies.json`
- Target CRM platform (default: hubspot)

## Agent Steps

### Step 1 — Run the Export Tool
```
python tools/export_crm.py \
    --all-companies \
    --crm hubspot \
    --date {today} \
    --exports-dir outputs/crm_exports/
```

For a specific company only:
```
python tools/export_crm.py \
    --company-id {company_id} \
    --crm hubspot \
    --date {today}
```

Supported CRM targets: `hubspot`, `salesforce`, `pipedrive`

### Step 2 — Review the Export
Open the generated file at `outputs/crm_exports/{today}_hubspot.json` and verify:

**Companies:**
- Domain is populated (required for HubSpot upsert)
- Industry maps to a recognized industry value
- Custom properties include `icp_tier`, `last_signal_date`, `top_signal`

**Contacts:**
- Only contacts sourced from public data are included
- No email addresses invented or guessed
- `outreach_priority` is set correctly (1 = top priority)

**Deals:**
- Only created for companies with score ≥ 50 (Tier A or B)
- `dealstage` is set to `signal_detected` (not a stage that implies pipeline commitment)

**Notes:**
- Body includes the executive summary and key signals
- Length is under 5000 characters

### Step 3 — Note Missing Data
For contacts without email addresses (most will be missing — that's expected), note:
- Contact name and title are populated from public sources
- Email enrichment can be added later via Hunter.io (`tools/enrich_contact_hunter.py` if configured)
- Do not attempt to guess email formats

### Step 4 — Confirm File Location
Report the export file path and a summary to the user:
```
CRM export written to: outputs/crm_exports/{today}_hubspot.json
Companies: N
Records: N (M companies, N contacts, P deals, Q notes)
```

### Step 5 — For Live CRM Sync (Optional, Future)
If `HUBSPOT_API_KEY` is configured in `.env`, a future `tools/sync_hubspot.py` tool can push these records directly. For now, the JSON file is the deliverable — import it manually via HubSpot's import interface or use their API.

HubSpot import guide: https://knowledge.hubspot.com/crm-setup/import-objects

## Expected Outputs
- `outputs/crm_exports/{today}_{crm}.json` — CRM-ready JSON export

## Error Handling
- **No briefs exist for today**: Export still runs — company and signal records are populated even without a brief. Notes will contain signal information only.
- **Company missing from `data/companies.json`**: Skip it. Only export companies that are actively monitored.
- **CRM target not recognized**: Output in HubSpot format with a warning. All formats are structurally similar.
- **Signal data but no brief**: Create company record and note only. Do not create a Deal record without a brief (no enough information to properly qualify it).

## Validation Checks
- [ ] Export file exists at correct path
- [ ] No fabricated email addresses in contact records
- [ ] Deals only created for Tier A/B companies
- [ ] All domain fields populated (required for CRM upsert matching)

## Lessons Learned
_Updated by agent as patterns are discovered._

- HubSpot's company upsert requires `domain` as the match field. If domain is missing or wrong, the import creates a duplicate company record. Always verify domain in `data/companies.json` before running.
- Salesforce uses "Account" not "Company" — the field mapping is different. Use `--crm salesforce` for Salesforce exports.
- CRM imports should be reviewed before committing — a bad import creates noise that sales reps have to clean up manually.
- The most valuable CRM records are the Notes — this is where the AI-generated intelligence brief lands in the rep's workflow.
