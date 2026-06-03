# Workflow: Opportunity Scoring

## Objective
Compute prioritized opportunity scores for all accounts with recent signals and output a ranked list for daily action. Combine deterministic scoring with qualitative agent judgment to produce a reliable priority ranking.

## Required Inputs
- `outputs/signals/{today}.json` — today's normalized signals
- `data/icp_criteria.json` — ICP scoring configuration
- `data/signal_weights.json` — signal weight configuration
- `data/companies.json` — company metadata (employee count, funding stage, etc.)

## Agent Steps

### Step 1 — Run Deterministic Scoring
```
python tools/score_opportunity.py \
    --all-companies \
    --companies-file data/companies.json \
    --signals-file outputs/signals/{today}.json \
    --output-file outputs/signals/scores-{today}.json
```

Review the ranked output. The scores are computed as:
- **ICP fit** (up to ~40 points): industry match, employee count, funding stage, geography
- **Signal strength** (up to ~35 points): weighted sum of all signals with recency decay applied
- **Timing bonus** (up to 15 points): bonus for very recent signals (< 7 days)

### Step 2 — Qualitative Review (Agent Task)
The deterministic score is a starting point. Apply judgment to adjust priorities:

**Positive adjustments (rank higher than score suggests):**
- Company has multiple simultaneous signals (e.g., funding + leadership change in same week)
- You have an existing relationship with a contact at this company
- The detected signal directly relates to your ICP's pain point (e.g., you sell data tools, and the signal is a Snowflake adoption)
- The company recently hired from a competitor or from a mutual customer

**Negative adjustments (rank lower than score suggests):**
- Company is currently in an active sales cycle with a competitor (check your CRM)
- The rep assigned to this account (`owner` field) has noted they're not ready to engage
- The signal is a false positive (company name collision with a different company)
- The company is in a budget freeze (known from a previous touch)
- The same signal appeared in last week's report and was already actioned

### Step 3 — Define Today's Action Cohort
Based on adjusted rankings, identify:
- **Immediate action** (Tier A, act today or this week): Maximum 3 accounts per day
- **Prepare brief** (Tier B, generate brief this week): Up to 5 accounts
- **Monitor** (Tier C/D, no action today): All others

Do not try to action every account every day. Focused effort on fewer accounts with strong signals outperforms scattered effort across many.

### Step 4 — Identify Multi-Signal Accounts
Accounts with signals from 2+ distinct sources on the same day should be flagged with elevated priority regardless of total score. Multiple independent data points confirming the same buying signal are more reliable than a single strong signal.

Example: Hiring VP Engineering (careers signal) + Blog post about "scaling our platform" (RSS signal) + Press coverage of Series B close (news signal) = three simultaneous signals → immediate action regardless of ICP fit score.

### Step 5 — Output Priority List
Produce a clear priority list in your response:

```
PRIORITY ACCOUNTS — {today}

IMMEDIATE ACTION (Tier A):
1. [Company A] — Score: 87 | Signal: VP Engineering hire | Action window: 30 days
2. [Company B] — Score: 79 | Signal: Series B close | Action window: 30 days

BRIEF GENERATION (Tier B):
3. [Company C] — Score: 64 | Signal: Product launch + hiring spike
4. [Company D] — Score: 58 | Signal: Tech migration signal

MONITORING (Tier C/D):
- [Company E] — Score: 38 | Signal: blog post
- [Company F] — Score: 22 | No significant signals today
```

## Expected Outputs
- `outputs/signals/scores-{today}.json` — scored and ranked company list
- Agent produces a plain-language priority summary

## Error Handling
- **Scoring produces a tie**: Break by recency of the most recent signal (newer = higher priority). If still tied, break by Tier assignment in `data/companies.json`.
- **All accounts score below Tier C**: Surface them anyway with a note "weak signal day — monitor only." Do not suppress the report.
- **Score changes dramatically from yesterday**: Investigate — likely a key signal just expired (recency decay from day 7 to day 8 drops from 1.0x to 0.8x multiplier) or a new signal was added. Explain the change in the daily report.
- **New company added but no prior signals**: Score based on ICP fit only. Signal strength component will be 0.

## Validation Checks
- [ ] All active companies in `data/companies.json` appear in the scores file
- [ ] No company has a score above 100
- [ ] Tier A threshold is applied correctly (≥75 = Tier A)
- [ ] Priority list has no more than 3 "Immediate Action" accounts

## Lessons Learned
_Updated by agent as patterns are discovered._

- Recency decay creates predictable score drops. A signal scored on day 1 will drop ~20% by day 8 automatically. When a rep asks "why did Company X drop in priority?", check whether their last signal is now >7 days old.
- ICP fit scoring is not symmetric — being in an excluded industry means a score of zero for that component even with strong signals. This is intentional.
- Multiple weak signals (3x score 4.0) often outweigh one strong signal (1x score 8.0) in raw math, but the agent should apply judgment — multiple signals from the same source (e.g., 3 news items all from the same press release) should be counted once.
