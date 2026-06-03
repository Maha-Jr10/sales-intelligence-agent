# Workflow: Weekly Reporting

## Objective
Generate the weekly intelligence report with trend analysis, sleeping account identification, and recommendations for next week's priorities. The weekly report is the higher-level view that daily reports don't provide — trends, momentum, and portfolio health.

## Required Inputs
- 7 days of signal files from `outputs/signals/` (Monday through Sunday)
- 7 days of daily reports from `outputs/reports/`
- All briefs updated in the last 7 days from `outputs/briefs/`
- `data/companies.json`

## Agent Steps

### Step 1 — Generate the Weekly Report Structure
```
python tools/generate_report.py \
    --type weekly \
    --week {YYYY-WXX} \
    --signals-dir outputs/signals/ \
    --briefs-dir outputs/briefs/ \
    --companies-file data/companies.json
```

This creates `outputs/reports/weekly_{YYYY_WXX}.md`.

### Step 2 — Analyze Week-Over-Week Trends (Agent Task)
Read 14 days of signal files (current week + prior week) and analyze:

**Rising accounts** (more signals or higher scores than last week):
- What's driving the increase? New signals from a specific source?
- Is this a genuine escalation in buying intent, or a monitoring artifact?

**Falling accounts** (fewer signals or lower scores than last week):
- Signal recency decay (normal) or a genuine drop in activity?
- Accounts that were Tier A last week but Tier B/C this week need explanation

**Emerging patterns**:
- Are multiple companies in the same industry showing simultaneous signals? (Industry-level event worth noting)
- Is there a type of signal dominating this week? (e.g., lots of funding news = typical end-of-quarter reporting)

### Step 3 — Identify Sleeping Accounts
A "sleeping" account is one that has had no signals in 14+ consecutive days. List these accounts and recommend one of:
- **Reduce monitoring frequency**: Keep in system but don't expect signals. Move tier to C or D.
- **Remove from monitoring**: If the company no longer fits the ICP or the rep has decided not to pursue.
- **Investigate monitoring**: Careers page URL may have changed. Check if the monitoring is still working.

### Step 4 — Generate Next Week Recommendations
Based on this week's analysis, produce a prioritized action list for next week:
- Top 3 accounts to focus on (with reason)
- Any brief generation needed for accounts with strong signals but no brief yet
- Any monitoring configuration updates needed (e.g., add a new company, fix a broken RSS feed)
- Any outreach sequences to review or continue

### Step 5 — Generate Weekly CRM Export
```
python tools/export_crm.py \
    --all-companies \
    --crm hubspot \
    --date {today} \
    --exports-dir outputs/crm_exports/
```
The weekly export aggregates all companies with signals this week, not just today. This is the most complete CRM sync of the week.

### Step 6 — Update data/companies.json (if needed)
Based on this week's analysis, the agent may recommend updates to `data/companies.json`:
- `tier` changes: A company that was Tier B for 4 consecutive weeks with no Tier A signals should be downgraded
- `last_researched` updates
- Add `notes` about any new context discovered this week

Ask the user before making changes to `data/companies.json` unless they've explicitly authorized autonomous updates.

### Step 7 — Finalize Report
Ensure the report includes:
- Week-over-week signal counts per company
- Rising and falling accounts (with explanation)
- Sleeping accounts list
- Next week's recommended focus list
- CRM export path

## Expected Outputs
- `outputs/reports/weekly_{YYYY_WXX}.md`
- `outputs/crm_exports/{today}_hubspot.json` (weekly CRM export)
- Agent provides a verbal summary of key findings

## Error Handling
- **Fewer than 3 days of signals available**: Generate report from available data. Note the gap ("Only 3 of 7 days had signal data — monitoring may have been interrupted Mon-Thu").
- **No signals across the entire week**: Rare. Check if GitHub Actions ran successfully. Note in report.
- **Prior week data unavailable**: Cannot compute week-over-week trends. Produce report without trend section.
- **Brief directory empty**: Generate report from signals only. Note that no briefs were produced this week.

## Validation Checks
- [ ] Report covers the correct 7-day window
- [ ] All monitored companies appear in either the "activity" or "sleeping" section
- [ ] Week-over-week analysis is based on actual data (not guessed)
- [ ] Next week recommendations are specific and actionable
- [ ] CRM export generated and path confirmed

## Lessons Learned
_Updated by agent as patterns are discovered._

- The most valuable part of the weekly report for sales leadership is the trend analysis — which accounts are accelerating and which are cooling off.
- End-of-quarter weeks (March, June, September, December) produce more funding and product news than other weeks. Calibrate signal significance accordingly.
- If a sleeping account was previously Tier A, investigate before removing — they may be in a quiet phase before a big announcement.
- The "Next Week Recommendations" section is only valuable if it's specific. "Focus on Acme Corp because their VP Eng search is in week 3 — window is closing" is actionable. "Focus on high-tier accounts" is not.
