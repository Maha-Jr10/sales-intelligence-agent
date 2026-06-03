# Workflow: Competitive Intelligence

## Objective
(1) Monitor your competitors for product updates, pricing changes, and news that you should know about. (2) Detect when target companies mention, use, or are evaluating your competitors — and classify the competitive context as `neutral`, `competitive_defense`, or `displacement`.

## Required Inputs
- `data/competitors.json` — your competitor list with aliases and detection keywords
- `data/companies.json` — target company list
- `.tmp/research_cache/{company_id}_{date}.json` — existing research bundles (for mention scanning)

## When to Run
- **Daily (automated):** GitHub Actions `daily_scan.yml` runs `monitor_competitors.py --mode both` for all companies
- **On-demand:** Before generating a playbook for a specific account, run `--mode accounts --company-id {id}` to get fresh competitive context

## Agent Steps

### Step 1 — Run Competitive Monitor
```
python tools/monitor_competitors.py \
    --mode both \
    --all-companies \
    --output-dir outputs/competitive/ \
    --days-lookback 7
```

For a single account:
```
python tools/monitor_competitors.py \
    --mode accounts \
    --company-id {id} \
    --output-dir outputs/competitive/
```

### Step 2 — Review Competitor News (`_competitor_news_{date}.json`)
Read `outputs/competitive/_competitor_news_{date}.json`. For each competitor:
- Any major product launches or announcements?
- Any pricing changes (mentioned in news headlines)?
- Any controversy or negative coverage?
- Any customer churn signals?

Note anything relevant for briefings this week. Competitor product launches are worth monitoring — if a target account mentions evaluating a competitor's new feature, it contextualizes their buying behavior.

### Step 3 — Review Account Competitive Intel
For each account with `competitor_mentions_in_target` entries:

**`neutral`**: Competitor name appears in job description as a "familiar with" skill requirement. No action needed — it's a tech signal, not a buying signal.

**`competitive_defense`**: Account is actively evaluating competitor alternatives (keyword: "evaluating", "comparing", "vs"). Act immediately:
- This is a live evaluation. Your window is days, not weeks.
- Override the playbook template to `competitive-displacement` in `deal_playbook_generation.md`
- Reference the specific detection in the brief's `competitive_intel` field

**`displacement`**: Account is actively replacing or has recently moved away from a competitor. Highest-priority signal:
- They're already in motion — get in before the new vendor is selected
- Lead with your switch/migration story
- Reference the matched_text in your outreach ("I saw you're moving away from...")

### Step 4 — Check `matched_text` for Accuracy
The tool extracts sentences containing competitor aliases. Verify each detection:
- "Experience with Competitor A preferred" → skill requirement, not active use → `neutral`
- "We're replacing Competitor A with..." → active displacement → change to `displacement`
- "Competitor A and similar tools" → possible evaluation → `evaluation`

If the classification is wrong, note the correction — the tool applies keyword rules mechanically; the agent applies judgment.

### Step 5 — Incorporate Into Brief or Playbook
If a competitive signal is detected, it must appear in the relevant account's:
- Intelligence brief: `competitive_intel` field (note the competitor, the context, and the recommended strategy)
- Playbook: `competitive_context` field and template selection

If the account has `competitive_defense` or `displacement` strategy, override the playbook template to `competitive-displacement` (priority 95) regardless of other signals.

### Step 6 — Update `data/competitors.json` if Needed
If a new competitor emerges in detection results that's not in your config:
- Add it to `data/competitors.json` with appropriate aliases
- Run the monitor again to retroactively catch mentions in existing research bundles

## Expected Outputs
- `outputs/competitive/{company_id}/{today}.json` — per-company competitive intel
- `outputs/competitive/_competitor_news_{today}.json` — competitor news digest
- Agent notes any competitive escalations for immediate action

## Error Handling
- **No research bundle for company**: `monitor_competitors.py` can't scan for mentions without a research bundle. Run `research_company.py` first, then re-run competitor scan.
- **Competitor aliases too generic**: e.g., "A" as an alias will match everything. Keep aliases specific (full product name, domain, common shorthand).
- **False positive detection**: Common words matching competitor names (e.g., "Segment" in a non-segmentation context). Review `matched_text` field — if it's clearly unrelated, the tool's keyword matching is too broad. Update `data/competitors.json` aliases to be more specific.
- **No competitors configured**: `data/competitors.json` has placeholder entries. Competitive mode is effectively disabled until you configure real competitors.

## Validation Checks
- [ ] Competitive intel file exists for companies where research bundle exists
- [ ] `schema_version: "2.0"` in all competitive intel files
- [ ] `matched_text` populated for all detected mentions (not empty)
- [ ] `recommended_strategy` is one of: `neutral`, `competitive_defense`, `displacement`, `expansion`
- [ ] Any `competitive_defense` or `displacement` accounts are flagged for immediate review

## Lessons Learned
_Updated by agent as patterns are discovered._

- Job description mentions of competitor tools (as skill requirements) are NOT competitive signals — they're tech signals. A job requiring "Snowflake or similar data warehouse experience" doesn't mean the company is choosing Snowflake.
- Displacement signals in press releases are the most reliable — companies rarely announce publicly that they're switching unless it's a significant move.
- Monitor your competitors' careers pages for job titles that signal new product areas or customer segments — useful for anticipating their roadmap.
