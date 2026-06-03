# Workflow: Signal Detection

## Objective
Process raw collected signals from `signal_collection.md`, normalize and deduplicate them, detect changes from previous snapshots, classify signals by type, and score opportunities. Produce the day's canonical signal file.

## Required Inputs
- Raw signal files from `.tmp/raw_signals/` (output of `signal_collection.md`)
- Previous snapshots from `outputs/snapshots/` (for change detection)
- `data/signal_weights.json` — scoring weights
- `data/icp_criteria.json` — ICP profile for relevance filtering

## Agent Steps

### Step 1 — Normalize All Raw Signals
Merge all raw signal files into normalized, deduplicated signal records:
```
python tools/normalize_signals.py \
    --input-dir .tmp/raw_signals/ \
    --output-file outputs/signals/{today}.json
```
Review the output: note `input_count`, `output_count`, and `duplicates_removed`. A high duplicate rate is normal (news items often appear in both Google and Yahoo RSS).

### Step 2 — Apply Context-Aware Reasoning (Agent Task)
Read `outputs/signals/{today}.json`. For each signal, apply reasoning that the deterministic normalizer cannot:

**Hiring signals require context:**
- "Hiring 5 engineers" at a 500-person company = normal growth. At a 30-person company = significant scaling signal.
- Cross-reference with `employee_count_estimate` in `data/companies.json`.
- An executive hire (VP Eng, CTO) is significant at *any* company size.

**News signals require disambiguation:**
- "Stripe raises $XM" — is this about Stripe the payments company or a different Stripe?
- Verify the company_id matches the actual company before including the signal.
- If ambiguous, flag with `"confidence": "low"` rather than discarding.

**Funding signals are time-sensitive:**
- A funding announcement from 3+ months ago is not a fresh signal. Check if it already appeared in a previous signal file.

**Tech signals from job descriptions:**
- A job posting requiring "Snowflake experience" is a softer tech signal than a blog post announcing Snowflake adoption. Distinguish the strength.

For any signal that appears to be a false positive, set `"processed": true` and add a note in `structured_data.agent_note`.

### Step 3 — Score All Companies With Signals
```
python tools/score_opportunity.py \
    --all-companies \
    --companies-file data/companies.json \
    --signals-file outputs/signals/{today}.json \
    --output-file outputs/signals/scores-{today}.json
```
Review the ranked scores. Do the top-scored companies make intuitive sense? If a company scores 90 but you know it's a poor fit, that's a calibration issue in `data/signal_weights.json` — note it.

### Step 4 — Agent Sanity Check
Before finalizing, answer these questions:
1. Are the top 3 scored companies genuinely the most interesting opportunities today?
2. Is there any signal that scored low but deserves higher priority due to context (e.g., a quiet leadership change announcement)?
3. Are there any companies with signals today that already have an open outreach sequence? (Check `outputs/outreach/` — if yes, this signal is a follow-up opportunity, not a new outreach.)
4. Did any company show *multiple* simultaneous signals? Multiple signals together are more significant than any single signal — adjust priority accordingly.

### Step 5 — Write Final Signal File
The normalized signals file at `outputs/signals/{today}.json` is now the authoritative record. If you made any manual adjustments to signal records in Step 2 (marking false positives, adding agent notes), ensure those are written back.

Pass control to `daily_reporting.md` for report generation, or to `intelligence_brief_generation.md` for priority accounts.

## Expected Outputs
- `outputs/signals/{today}.json` — normalized, deduplicated, agent-reviewed signals
- `outputs/signals/scores-{today}.json` — opportunity scores for all companies

## Error Handling
- **No signals for today**: This is valid. Write an empty `[]` to the signals file and proceed to generate a "no signals" daily report. Do not treat this as an error.
- **Signals file from a previous run already exists**: Do not overwrite — append new signals (normalize_signals.py handles this with `--output-file`).
- **Score drops dramatically from previous run**: Investigate whether a key signal expired (recency decay) or whether a monitoring source broke. Flag for review.
- **All signals appear to be false positives**: Rare but possible. Report "weak signal day" and proceed.

## Validation Checks
Before proceeding:
- [ ] `outputs/signals/{today}.json` exists and is valid JSON
- [ ] `outputs/signals/scores-{today}.json` exists
- [ ] At least 1 company was scored (even if score is 0)
- [ ] No signals from a different day contaminate today's file (check `detected_at` dates)

## Lessons Learned
_Updated by agent when new patterns are discovered._

- Leadership changes are frequently announced in LinkedIn posts that don't appear in news RSS. If a rep mentions a leadership change, manually add a signal record.
- "Who is Hiring" HN posts are monthly — only one per company per month maximum.
- Careers snapshot diffs can produce false "new jobs" when a company reformats its careers page (new URL structure but same jobs). Check if job titles are identical before calling it a signal.
- Tech signals from job descriptions (Snowflake, dbt, etc.) appear with 2-4 week lag — by the time the job is posted, the tool decision is often already made.
