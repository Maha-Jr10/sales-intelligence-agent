# Workflow: Deal Playbook Generation

## Objective
Assemble a complete deal playbook for a target account by selecting the highest-priority matching template and populating it with specific context from the account's intelligence brief, stakeholder map, and competitive intel. The playbook is the operational guide that connects intelligence to action.

## Prerequisites (must exist before running)
- Intelligence brief: `outputs/briefs/{company_id}/{date}.json`
- Stakeholder map: `outputs/stakeholder_maps/{company_id}.json` (recommended — proceed with caution if missing)
- Competitive intel: `outputs/competitive/{company_id}/{date}.json` (optional but recommended)
- `data/playbook_templates.json` with at least one template
- `data/seller_profile.json` with your value proposition populated

## Template Selection Logic
Templates are sorted by `priority` descending. Rules applied in order:

1. If competitive_intel `recommended_strategy` is `displacement` or `competitive_defense` → force select `competitive-displacement` template (priority 95), regardless of other signals
2. Otherwise, find all templates where `trigger_signal` matches any `signal_type` in the brief
3. Select the highest-priority match
4. Fallback: use the lowest-priority template if no match found (note the mismatch)

| Signal type | Template selected | Priority |
|------------|-----------------|---------|
| `leadership_change` | leadership-driven-evaluation | 100 |
| `competitive_pressure` | competitive-displacement | 95 |
| `funding_event` | post-funding-expansion | 85 |
| `product_launch` | product-launch-follow | 70 |
| `news_mention` | generic-signal | 10 |

## Agent Steps

### Step 1 — Verify Prerequisites
Check that the brief exists and is current (< 7 days old). If the brief is older than 7 days:
- Note the staleness in the playbook (`urgency_note` field)
- Recommend running `company_research.md` + `intelligence_brief_generation.md` before distributing the playbook

If stakeholder map is missing:
- Run `stakeholder_mapping.md` first if time permits
- If not, proceed with `primary_contact: null` and note enrichment needed

### Step 2 — Generate Playbook
```
python tools/generate_playbook.py \
    --company-id {id} \
    --date {today} \
    --output-dir outputs/playbooks/
```

### Step 3 — Review Template Selection
Verify `template_used` is the right choice given the account context:

**Override scenarios:**
- Brief shows leadership_change as the top signal but you know from context that the company is also evaluating a competitor → override to `competitive-displacement`
- Brief shows funding_event but a leadership change happened the same week → override to `leadership-driven-evaluation` (the new exec window is more urgent)
- `template_is_fallback: true` in the output → the template selection was approximate; review the angle manually

To override, re-run with explicit context in the brief, or note the preferred template in your manual review.

### Step 4 — Validate Primary Contact
Review `primary_contact` in the playbook:
- Is this the right person to contact first for your product's motion?
- If technical evaluator is identified with higher confidence than economic buyer, consider starting there if your sales motion involves a technical champion before executive approval
- If `primary_contact` is null: flag to user — outreach cannot begin without a named contact

### Step 5 — Review Messaging Sections
**`recommended_angle`**: Should directly reference the trigger signal. "New executives evaluate and reset the technology stack" is good for leadership_change. Verify it's specific to the account.

**`objection_handling`**: The template provides generic objections. Agent should customize responses with account-specific context:
- Generic: "Post-raise is when infrastructure decisions set the trajectory."
- Specific: "Post-raise is when infrastructure decisions set the trajectory — and with a new VP Eng joining in the next 30 days, those decisions are being made right now."

**`suggested_cta`**: Verify it matches the stakeholder role's typical buying behavior. A CTO gets a "15-min call" ask. A technical evaluator might prefer "happy to share a technical comparison doc."

### Step 6 — Record in Memory
```
python tools/update_account_memory.py --action append-brief \
    --company-id {id} \
    --brief-id {playbook_id}
```

### Step 7 — Pass to Outreach Generation
The playbook is the input frame for `outreach_generation.md`. Pass:
- `template_used` → informs the email tone and structure
- `primary_contact` → the outreach target
- `recommended_angle` → the hook for email 1
- `suggested_cta` → the ask
- `objection_handling` → for follow-up emails

## Expected Outputs
- `outputs/playbooks/{company_id}/{today}.json`
- `outputs/playbooks/{company_id}/{today}.md`

## Error Handling
- **No brief found**: Fatal — cannot generate a playbook without intelligence. Run `intelligence_brief_generation.md` first.
- **`data/seller_profile.json` has placeholder content**: The playbook generates but `relevant_case_studies` and `differentiation_points` will be empty. Warn the user that these must be populated before outreach.
- **Template is fallback (`template_is_fallback: true`)**: This means no template matched the brief's signal types. Review `data/playbook_templates.json` — you may need to add a template for this signal type, or the brief's `signals_analyzed` may not contain the expected signal IDs.
- **Competitive intel file missing**: Playbook generates without competitive context. `competitive_context` defaults to `neutral`. Run `competitive_intelligence.md` to add context if needed.

## Validation Checks
- [ ] Playbook JSON and Markdown both exist at correct paths
- [ ] `schema_version: "2.0"` present
- [ ] `template_used` makes sense given the account's top signal
- [ ] `template_is_fallback: false` (unless genuinely no match)
- [ ] `primary_contact` is populated or explicitly null with a note
- [ ] `objection_handling` list is non-empty

## Lessons Learned
_Updated by agent as patterns are discovered._

- The `competitive-displacement` template should almost always win when a competitive mention is detected — even if a leadership_change is also present. Displacement signals are more time-sensitive.
- CTA matching to stakeholder role matters significantly. An executive gets a time-bound ask ("before your VP Eng onboards"). A technical evaluator gets a peer-level ask ("happy to share a technical comparison").
- Template `urgency_note` fields contain the most important timing guidance. Always surface these to the rep in the Markdown version of the playbook.
