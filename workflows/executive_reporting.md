# Workflow: Executive Reporting

## Objective
Produce a weekly executive intelligence digest that surfaces pipeline health, priority account ranking by composite score, week-over-week trends, and top recommended actions. This report is for leadership review — it must be dense with signal, free of noise, and end with specific named recommendations.

## Required Inputs
- `outputs/signals/multi_factor_scores-{date}.json` (preferred) or `outputs/signals/scores-{date}.json` (v1 fallback)
- `outputs/memory/*.json` — engagement status for all accounts
- `outputs/reports/history/{prior_week}.json` — for week-over-week comparison
- `data/companies.json`

## When to Run
After `weekly_reporting.md` is complete. GitHub Actions `weekly_report.yml` runs this automatically on Monday 7am UTC.

## Agent Steps

### Step 1 — Generate Report and History Snapshot
```
python tools/generate_executive_report.py \
    --week {YYYY-WXX} \
    --output-dir outputs/reports/
```

The tool writes:
- `outputs/reports/executive_{YYYY_WXX}.md` — the report
- `outputs/reports/history/{YYYY_WXX}.json` — the KPI snapshot for next week's delta

### Step 2 — Review Pipeline Snapshot
Verify the numbers make sense:
- **Total accounts**: should match the count in `data/companies.json`
- **P1 accounts**: should match accounts with composite_score ≥ 80
- **Sequences active**: should match count of accounts with `engagement_status: in_sequence` in memory
- **Meetings booked**: should match count of accounts with `engagement_status: meeting_booked`

If any numbers look wrong, check the memory files directly:
```
python tools/update_account_memory.py --action read --company-id {suspicious_id}
```

### Step 3 — Review Priority Ranking Table
Verify the top-ranked company deserves P1 status:
- Is their composite_score driven by genuine signals or a data artifact?
- Cross-reference with `correlations-{date}.json` — does the top account have matched patterns?
- Is the `Status` column accurate? An account marked `not_contacted` with a P1 score should be actioned immediately.

Accounts that were P2 last week but are now P1: these moved up due to new signals or recency decay falling off a competitor's signals. Note this in the recommendations.

Accounts that were P1 last week but are now P2: check if their key signal aged past the 7-day recency window (decay factor drops from 1.0x to 0.8x on day 8). If so, the urgency is still real — just the score calculation is lower.

### Step 4 — Fill In Top 3 Recommended Actions
The tool inserts `[AGENT: insert recommendation]` placeholders. Replace these with specific, actionable recommendations before distributing the report.

**Good recommendation format:**
```
1. Contact [Name, Title] at [Company] via email this week using the new-executive-hire playbook.
   Their VP Engineering action window closes in 18 days. Brief at: outputs/briefs/company/date.md
```

**Poor recommendation format:**
```
1. Follow up with high-tier accounts.
```

Each recommendation must name: who, what action, what channel, what urgency reason.

### Step 5 — Review Week-Over-Week Delta
If prior history exists, the report shows the delta in P1 accounts and signals detected. Explain any significant changes:
- "P1 count increased from 2 to 5: three accounts hit multi-signal correlation patterns this week (post-funding + leadership changes in the SaaS sector)"
- "Signal count dropped 40%: this is week 4 of the calendar quarter — historically lower news volume"

### Step 6 — Verify History Snapshot Written
```
ls outputs/reports/history/
```
Confirm this week's snapshot JSON exists. Without it, next week's delta calculation will show no comparison.

### Step 7 — Distribute (Manual Step)
The executive report is ready for distribution. Copy the Markdown or share the file path. The `[AGENT: insert recommendation]` placeholders must be replaced before distributing — the tool intentionally leaves them for the agent to fill in.

## Expected Outputs
- `outputs/reports/executive_{YYYY_WXX}.md` — the distributable report
- `outputs/reports/history/{YYYY_WXX}.json` — KPI snapshot (`schema_version: "2.0"`)

## Error Handling
- **No multi_factor_scores file**: Tool falls back to v1 scores. Report still generates. Note to user: "v2 scores not available — run daily_scan.yml to generate multi_factor_scores."
- **No history snapshot from prior week**: Week-over-week delta section is omitted. This is expected on the first week of using v2.
- **Memory files missing**: Sequences_active and meetings_booked default to 0. Run `update_account_memory.py --action init` for each company.
- **Report has incorrect P1 count**: Composite score threshold is `p1_threshold: 80` in `data/scoring_config.json`. If too many accounts score P1, consider raising the threshold. If too few, lower it.

## Validation Checks
- [ ] Report file exists at `outputs/reports/executive_{YYYY_WXX}.md`
- [ ] History snapshot at `outputs/reports/history/{YYYY_WXX}.json` with `schema_version: "2.0"`
- [ ] `[AGENT: insert recommendation]` placeholders replaced before distributing
- [ ] Priority ranking table sorted correctly (highest composite_score first)
- [ ] Week-over-week delta is present (or explicitly noted as unavailable)

## Lessons Learned
_Updated by agent as patterns are discovered._

- The Top 3 Recommended Actions section is the most-read part of the executive report. Invest the most time here.
- History snapshots are tiny (< 1KB each). Commit them every week — they're the foundation for trend analysis after 4+ weeks.
- The KPI `avg_composite_score` across all accounts is a useful leading indicator: if it rises week-over-week, more accounts are accumulating signals. If it falls, the pipeline is cooling.
- Executive reports should be reviewed by the agent before distribution — never auto-distribute without the recommendation placeholders filled in.
