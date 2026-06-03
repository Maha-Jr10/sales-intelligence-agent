# Workflow: Intelligence Brief Generation

## Objective
Generate a comprehensive, actionable account intelligence brief for a specific company. The brief must be specific enough that a sales rep can make a call immediately after reading it, without needing to do any additional research.

**This is primarily an agent reasoning task. No tools are required beyond reading the research bundle.**

## Required Inputs
- Company ID
- Research bundle from `company_research.md` at `.tmp/research_cache/{company_id}_{date}.json`
- Signals from `signal_detection.md` at `outputs/signals/{today}.json`
- Opportunity score from `opportunity_scoring.md` at `outputs/signals/scores-{today}.json`
- `data/seller_profile.json` — your value proposition (for outreach angle recommendations)

## Quality Bar
**A vague brief is a failed brief.** Before submitting:
- Every claim must be traceable to a source (news item, job listing, tech scan result)
- Signal implications must be specific: not "they're growing" but "VP Engineering search = tool consolidation decision imminent"
- Outreach angles must be concrete: not "reach out about scaling" but "contact CTO before new VP Eng onboards — they'll inherit whatever stack is in place"
- Banned language: "exciting opportunity", "synergy", "leverage", "solution", "world-class", "cutting-edge", "revolutionary"

## Agent Steps

### Step 1 — Load All Inputs
Read the three required files. If the research bundle doesn't exist for today, check yesterday's cache. If both are missing, run `company_research.md` workflow first.

### Step 2 — Write the Executive Summary
**Format:** 3-5 sentences maximum. Lead with the most important signal and its business implication.

Bad: "Acme Corp is a growing B2B SaaS company with 200 employees that recently raised funding."
Good: "Acme Corp closed a $42M Series B in November and immediately posted a VP Engineering role — their first executive engineering hire. This signals a 6-12 month infrastructure consolidation ahead of the next growth phase. The combination of Snowflake adoption (detected via tech scan) and three data engineer hires in January suggests a BI/analytics build-out is already underway."

### Step 3 — Document Buying Signals
For each detected signal, write:
- **Signal headline**: What happened (specific, named)
- **Implication**: Why this matters for outreach timing and angle
- **Urgency**: high / medium / low
- **Action window**: How many days until this signal becomes stale (typically 7-30 days)

Example:
```
Signal: VP of Engineering posted on Jan 15 — first executive engineering hire
Implication: New VPs evaluate and often replace existing tooling in their first 90 days. Window to influence evaluation before they arrive and set the stack.
Urgency: high
Action window: 30 days
```

### Step 4 — Compile Company Snapshot
From the research bundle, extract:
- Company description (1-2 sentences, your own words — not a copy of their About page)
- Estimated employee count (from job data, not just their self-reported number)
- Funding stage and amount if known
- Headquarters
- Known tech stack (from tech scan + job description mentions)
- Key products or service offerings

For anything unknown, write "unknown" explicitly. Do not estimate or infer beyond what the data supports.

### Step 5 — Note Competitive Intelligence
From job descriptions, blog posts, and tech scans, identify:
- Tools they currently use that compete with your solution (if any)
- Tools mentioned positively in job descriptions
- Any mentions of competitor names in their content
- Whether any of your existing customers are listed as case studies or references

### Step 6 — List Key Contacts
From public sources only (LinkedIn, team pages, press releases):
- Name, Title, Source URL
- Why they're relevant (economic buyer, technical champion, coach)
- Outreach priority (1 = highest)

Do NOT invent contact details. Do NOT guess email addresses. If no contacts are found from public sources, write "Key contacts: research required (LinkedIn Sales Navigator, Hunter.io, or warm introduction path)."

### Step 7 — Recommend Outreach Angles
Write 3 concrete outreach angles, ordered by strength:
1. Best angle — most specific to the company's current situation
2. Alternative angle — if primary doesn't land
3. Backup angle — for follow-up sequence variety

Each angle must reference a specific signal. "They're in a scaling phase" is not an angle. "New VP Engineering is evaluating infrastructure tooling — get in before they set the stack" is an angle.

### Step 8 — Define Next Actions
Write specific, dated actions:
- "Draft email to CTO before Jan 25 (before VP Eng hire lands)"
- "Monitor LinkedIn for VP Engineering announcement — warm congrats touch when announced"
- "Set news alert for next funding announcement"

### Step 9 — Write Both Output Files

**JSON brief** (`outputs/briefs/{company_id}/{today}.json`):
```json
{
  "brief_id": "{company_id}-brief-{today}",
  "company_id": "{company_id}",
  "generated_at": "{now}",
  "signals_analyzed": ["{signal_id_1}", "{signal_id_2}"],
  "company_snapshot": {
    "name": "...",
    "industry": "...",
    "employee_count": "...",
    "funding": "...",
    "headquarters": "...",
    "tech_stack": [...],
    "description": "..."
  },
  "executive_summary": "...",
  "buying_signals": [...],
  "opportunity_score": {
    "total": N,
    "tier": "A/B/C",
    "breakdown": {...}
  },
  "competitive_intel": "...",
  "recommended_outreach_angles": ["...", "...", "..."],
  "key_contacts": [...],
  "next_actions": ["...", "...", "..."],
  "data_freshness": "{research_bundle_date}",
  "sources": ["{url1}", "{url2}"]
}
```

**Markdown brief** (`outputs/briefs/{company_id}/{today}.md`):
Human-readable version with the same information, formatted for easy scanning. Lead with the most important signal, not with company background.

## Expected Outputs
- `outputs/briefs/{company_id}/{today}.json`
- `outputs/briefs/{company_id}/{today}.md`

## Error Handling
- **Research bundle is empty or mostly errors**: Write a minimal brief noting data limitations. Do not fabricate.
- **Signal data conflicts** (news says 500 employees, job count implies 150): Note the conflict explicitly. Use the more conservative estimate.
- **No key contacts found from public sources**: Write "key contacts: unknown — enrichment required" and suggest Hunter.io or LinkedIn.
- **Company has no buying signals**: Do not fabricate urgency. Write an honest brief noting low signal strength and recommending "monitor only" status.

## Validation Checks
- [ ] Every claim has a source reference
- [ ] Outreach angles are specific to named signals
- [ ] No banned words present
- [ ] Both JSON and Markdown files written
- [ ] `data_freshness` field reflects actual research date (not a guess)
- [ ] No email addresses invented or guessed

## Lessons Learned
_Updated by agent as patterns are discovered._

- The most valuable section of the brief is "Implication" on each buying signal. This is what the rep needs to understand to make a confident call.
- If a company has been monitored for 3+ weeks with no signals, the brief should note "low signal environment" — this is useful information, not a failure.
- Key contacts from team pages may be out of date. Always note the source date ("LinkedIn as of Jan 2025"). Contacts change, especially at scaling companies.
- The action window for leadership change signals is very short — typically 14-21 days before the new executive is embedded and has set their agenda.
