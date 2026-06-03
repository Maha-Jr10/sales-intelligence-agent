# Workflow: Daily Reporting

## Objective
Produce the daily intelligence digest from all signals and briefs detected today. This report is the primary daily artifact — it tells the sales team what happened, who the top opportunities are, and what to do next.

## Required Inputs
- `outputs/signals/{today}.json` — today's normalized signals
- `outputs/signals/scores-{today}.json` — today's opportunity scores
- Intelligence briefs in `outputs/briefs/` (for companies briefed today)
- `data/companies.json` — for context on accounts with no signals

## Agent Steps

### Step 1 — Generate the Structured Report
```
python tools/generate_report.py \
    --type daily \
    --date {today} \
    --signals-dir outputs/signals/ \
    --briefs-dir outputs/briefs/ \
    --companies-file data/companies.json
```

This creates `outputs/reports/daily_{today}.md`.

### Step 2 — Review the Generated Report
Open `outputs/reports/daily_{today}.md` and verify:
- **Executive summary** correctly states the count of signals and top-tier accounts
- **Tier A section** leads with the highest-scored company (not alphabetical)
- **Brief links** are accurate (brief files exist where referenced)
- **No Tier A account is missing** — all accounts that scored ≥75 must appear in this section
- **Accounts with no signals** list is complete

### Step 3 — Agent Quality Check
If any Tier A account lacks a current intelligence brief:
1. Flag it in the report: "_Brief not generated — run `intelligence_brief_generation` workflow for [Company]_"
2. Optionally, if time permits, run the brief generation workflow inline

If a Tier A account's brief is more than 7 days old:
1. Note the brief age in the report
2. Recommend running a research refresh

### Step 4 — Add Agent Commentary (if warranted)
For high-priority days (multiple Tier A accounts, or unusual signal patterns), add a brief "Agent Notes" section at the top of the report:
- "Three Tier A accounts with simultaneous signals today — unusual. Likely industry-wide event (check: series of funding announcements in X sector?)"
- "No signals from Y company this week — their careers page may have changed structure. Verify monitoring is working."

Keep this section short (2-3 bullet points max).

### Step 5 — Confirm Report Written
Report the file path to the user:
```
Daily report written: outputs/reports/daily_{today}.md
Top opportunity: {company_name} (Score: {N}, Tier A)
Total signals: {N} across {M} companies
```

In GitHub Actions (automated mode), the report is committed and pushed in the same step.

## Expected Outputs
- `outputs/reports/daily_{today}.md`
- Summary printed to stdout (for Actions log visibility)

## Error Handling
- **No signals today**: Generate a "no signals" report. Do not skip report generation — a day with no signals is still useful information.
- **Scores file missing** (score_opportunity.py didn't run): Generate report from signals only, without score breakdown. Note missing scores.
- **Brief referenced doesn't exist**: Display "brief pending" message in the report section — do not error.
- **Reports directory doesn't exist**: Create it before writing.

## Validation Checks
- [ ] Report file exists at correct path
- [ ] All Tier A accounts appear in the Tier A section
- [ ] Report date matches today's date
- [ ] Signal count in executive summary matches actual signal count in signals file
- [ ] No company appears in both "signals" and "no signals" sections

## Lessons Learned
_Updated by agent as patterns are discovered._

- Reports should be written for the rep, not for the data engineer. Use plain language in the executive summary. The rep's first question is "who should I call today and why?" — make that answerable in the first 5 lines.
- When no Tier A accounts are present on a given day, lead with the best Tier B opportunity rather than apologizing for weak signals. There is always *some* account worth attention.
- The "Accounts With No Signals" section is often overlooked but important — it surfaces accounts that may need monitoring configuration updates.
