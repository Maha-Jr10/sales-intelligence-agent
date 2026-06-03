# Workflow: Signal Correlation

## Objective
Detect named signal combination patterns across all monitored accounts, produce buying-event narratives with explainability, and pass correlation confidence and priority boosts into the multi-factor scoring pipeline.

## Position in Pipeline
Run **after** `signal_detection.md` and **before** `opportunity_scoring.md`. The correlation output (`correlations-{date}.json`) must exist before `score_multi_factor.py` runs.

Daily pipeline order:
```
normalize_signals → score_opportunity (v1) → correlate_signals → score_multi_factor → update_account_memory
```

## Required Inputs
- `outputs/signals/{today}.json` — normalized signals from `signal_detection.md`
- `data/signal_combinations.json` — named pattern definitions

## Agent Steps

### Step 1 — Run Correlation Engine
```
python tools/correlate_signals.py \
    --all-companies \
    --signals-file outputs/signals/{today}.json \
    --lookback-days 30 \
    --output-file outputs/signals/correlations-{today}.json
```

Review the output: `companies_with_correlations` count and the top-ranked company by `total_priority_boost`.

### Step 2 — Review Matched Patterns
For each company with `correlation_detected: true`:

**Read `why_matched`** — this is the explainability trace. Verify the listed signals are genuine independent events, not artifacts:
- Two news items about the same press release on the same day = NOT a genuine "two signals"
- A hiring signal and a news signal both referring to the same VP hire = NOT independent
- A careers page change AND a news article about the same hire = one underlying event

**Genuine multi-signal:** funding round (source: news) + VP Engineering hire (source: careers page, detected independently) = genuinely independent signals from different sources on different dates.

If a matched pattern is NOT genuine, note it:
```
[Override: leadership-driven-evaluation pattern for Stripe is false positive — 
both signals (leadership_change-2026-05-28 and hiring_spike-2026-06-01) 
refer to the same VP Eng announcement from different sources]
```

Mark the pattern as a false positive in your note — `score_multi_factor.py` will still apply the boost, but you can manually adjust the resulting priority rank.

### Step 3 — Evaluate Narrative Quality
Read `composite_narrative` for each matched account. The narrative must be:
- Specific to the company (name + signal specifics)
- Actionable (implies a window and a recommended action)
- Accurate (matches the actual signals detected)

If the narrative is generic or inaccurate (template substitution failed), note this for the brief generation step — the agent will write a better narrative in the intelligence brief.

### Step 4 — Surface Priority Escalations
List accounts where `total_priority_boost` ≥ 20. These are high-conviction opportunities that should be reviewed for immediate brief generation, regardless of their v1 score tier.

The correlation boost will increase their urgency score in `score_multi_factor.py`. Verify the final composite score after that step runs.

### Step 5 — Pass to Multi-Factor Scoring
Signal to the next step: "Correlation complete. {N} accounts with detected patterns. Top boost: {company} (+{N} points). Proceed to score_multi_factor."

## Expected Outputs
- `outputs/signals/correlations-{today}.json` — correlation results per company
- Agent notes on any false positives or override decisions

## Error Handling
- **No signals file exists**: `correlate_signals.py` emits empty result and exits 0. Proceed to scoring — correlation boost will be 0 for all companies.
- **All companies have 0 signals**: Same — all boosts are 0. Normal on low-signal days.
- **Pattern match seems wrong**: Override by noting it here. The tool is deterministic — if signals match the time window criteria, it matches. Agent judgment supersedes.
- **`signal_combinations.json` missing patterns**: Tool will error (no patterns loaded). Check file integrity.

## Validation Checks
- [ ] `outputs/signals/correlations-{today}.json` exists and has `schema_version: "2.0"`
- [ ] `companies_with_correlations` count is ≥ 0 (never negative)
- [ ] `why_matched` is present for all matched patterns (explainability intact)
- [ ] Any false positives are noted before score_multi_factor runs

## Lessons Learned
_Updated by agent as patterns are discovered._

- The `triple-signal-conviction` pattern (≥3 signals in 30 days) requires care — verify signals are from different source types (not just different tools returning the same underlying event)
- `post-funding-leadership` pattern has the highest practical predictive value — companies that both raised and brought in a new executive in the same 90-day window are almost always in an active buying cycle
- Correlation boosts are capped at 30 before being applied to urgency scoring — a single high-boost pattern can at most add 30 points to urgency (then capped again at max_total_urgency_bonus: 50)
