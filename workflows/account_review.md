# Workflow: Account Review (Master v2 Workflow)

## Objective
Load all available v2 context for one account and produce a single, specific account recommendation. This is the operator-facing workflow that ties together all v2 capabilities into one coherent view before any major account decision.

## When to Use
- Before sending the first outreach message to an account
- Before re-engaging an account after a gap
- Before an account review call with sales leadership
- Before escalating an opportunity to an AE from an SDR
- When a rep asks: "What should I do with this account right now?"

## Quality Bar
The output recommendation must be specific enough that a rep can act immediately, without any additional research. 

**Good:** "Contact Jane Smith (CTO, Stripe — identified with 0.91 confidence) via email today using the new-executive-hire playbook. Reference the VP Engineering search that went live 8 days ago. Action window closes in ~22 days. CTA: 15-min call before the new VP onboards."

**Poor:** "Reach out to a stakeholder at Stripe about their hiring activity."

## Required Inputs (7 sources — read all before synthesizing)
All files may not exist for every account. Missing files are noted in the recommendation — they do not block the workflow.

1. Account memory: `outputs/memory/{company_id}.json`
2. Latest intelligence brief: `outputs/briefs/{company_id}/{most_recent_date}.json`
3. Stakeholder map: `outputs/stakeholder_maps/{company_id}.json`
4. Competitive intel: `outputs/competitive/{company_id}/{most_recent_date}.json`
5. Latest playbook: `outputs/playbooks/{company_id}/{most_recent_date}.json`
6. Multi-factor score: `outputs/signals/multi_factor_scores-{today}.json` (company's entry)
7. Correlation output: `outputs/signals/correlations-{today}.json` (company's entry)

## Agent Steps

### Step 1 — Load All Context
Run each read command sequentially:

```
python tools/update_account_memory.py --action read --company-id {id}
```

Then read the most recent file from each of the remaining directories:
- `outputs/briefs/{company_id}/` → most recent `.json` by date
- `outputs/stakeholder_maps/{company_id}.json`
- `outputs/competitive/{company_id}/` → most recent `.json` by date
- `outputs/playbooks/{company_id}/` → most recent `.json` by date
- In `outputs/signals/multi_factor_scores-{today}.json`, find the entry for this company_id
- In `outputs/signals/correlations-{today}.json`, find the entry for this company_id

Note the data freshness of each file (date in filename or `generated_at` field). Files older than 14 days should be flagged as potentially stale.

### Step 2 — Assess Current State (5 questions)

**Q1: What is the current engagement state?**
From memory `relationship_context.engagement_status`:
- `not_contacted` → first touch opportunity
- `in_sequence` → continue or conclude the active sequence
- `replied` → respond and advance
- `meeting_booked` → prepare for the call
- `paused` → check notes for reason and timing
- `closed_*` → do not re-engage without explicit instruction

**Q2: What is the strongest reason to act NOW?**
From brief `buying_signals` + correlation `composite_narrative`:
- Find the signal with the highest urgency and the shortest action window
- Quantify: "The VP Engineering search was posted 8 days ago. Industry average time-to-fill for VP Eng is 45-60 days. Remaining window: ~37-52 days."
- If no fresh signal (all signals > 30 days old), state: "No urgent time pressure — monitoring mode recommended."

**Q3: Who should be contacted, and how confident are we?**
From stakeholder map `recommended_first_contact`:
- Name + title + role + confidence
- If confidence < 0.5: "Contact identity is uncertain — recommend LinkedIn verification before outreach."
- If `outreach_readiness: escalate`: "Do not send outreach — economic buyer not identified. Run stakeholder_mapping.md first."

**Q4: What angle and what playbook?**
From playbook `template_used` + `recommended_angle` + `suggested_cta`:
- State the playbook name, the recommended angle in one sentence, and the CTA
- If competitive displacement is detected: override to displacement angle regardless of playbook

**Q5: What are the risks?**
- Brief staleness (> 7 days old → signal may have changed)
- Low-confidence stakeholder identification
- Active competitor evaluation (requires urgency upgrade)
- Account already in a sequence (do not duplicate)
- Previous negative response in memory (`last_response_sentiment: negative`)

### Step 3 — Synthesize the Recommendation

Write a structured recommendation with these sections:

```
ACCOUNT: {company_name}
DATE: {today}

STATUS: {engagement_status} | COMPOSITE SCORE: {composite_score} ({composite_tier})

STRONGEST SIGNAL:
{signal title} — detected {N} days ago. {Action window calculation.}

RECOMMENDED ACTION:
{Specific: channel + contact + angle + CTA}

RISKS / BLOCKERS:
{List any flags from Step 2 Q5}

NEXT MONITORING EVENT:
{What to watch for next: e.g., "VP Engineering hire announcement on LinkedIn"}
```

### Step 4 — Write to Memory (Optional)
If the recommendation contains important context for future sessions:
```
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.notes \
    --value "{brief summary of recommendation and reasoning}"
```

### Step 5 — Trigger Downstream Workflows
Based on the recommendation:
- **First outreach ready**: Pass to `outreach_generation.md` with the playbook as context
- **Needs brief refresh**: Run `company_research.md` + `intelligence_brief_generation.md` first
- **Needs stakeholder research**: Run `stakeholder_mapping.md` first
- **Already in sequence**: Determine which step is due next based on `outreach_history` in memory
- **Meeting prep needed**: Read brief and stakeholder map; prepare 3 key talking points and anticipated objections

## Expected Outputs
The agent produces the recommendation as structured text output.
Optionally appended to `outputs/memory/{company_id}.json` `relationship_context.notes`.

## Error Handling
- **No brief exists**: State "No intelligence brief available" in the recommendation. Run `company_research.md` + `intelligence_brief_generation.md` before outreach.
- **No stakeholder map**: State "Stakeholder roles not mapped." Include as a risk. Optionally trigger `stakeholder_mapping.md`.
- **No multi-factor scores (v2 scores not yet generated)**: Use v1 score from `outputs/signals/scores-{today}.json` as a fallback. Note the substitution.
- **All files are stale**: If the most recent brief, stakeholder map, and competitive intel are all > 14 days old, recommend a full research refresh before taking action.
- **Memory says `engagement_status: in_sequence`**: Do NOT recommend starting new outreach. Instead, determine which step in the existing sequence is due next based on `outreach_history` dates and `sequence_plan.follow_up_days`.

## Validation Checks
- [ ] All 7 context sources were checked (even if some don't exist)
- [ ] Recommendation includes specific name + title for the contact (not "a stakeholder")
- [ ] Recommendation includes a quantified action window (not just "act soon")
- [ ] Risks section is populated (not "none" — there are always at least 1-2 considerations)
- [ ] Next monitoring event is named specifically (not "watch for updates")

## Lessons Learned
_Updated by agent as patterns are discovered._

- The most valuable output of this workflow is the action window quantification. Reps respond to deadlines, not just "good opportunities."
- If a rep asks "should I reach out now?", the answer is always one of: yes (proceed), not yet (specify what's missing), or no (specify why). Never "it depends" without explaining what it depends on.
- When multiple v2 signals converge on the same account (correlation match + stakeholder identified + competitive displacement), this is a high-conviction moment. The recommendation should reflect that urgency clearly.
- The account review workflow is also useful as a weekly self-check: run it for your top 5 accounts every Monday morning and ensure actions from last week's recommendations were taken.
