# Workflow: Competitive Intelligence

## Objective
(1) Monitor competitor websites for new blog posts, case studies, team changes, homepage repositioning, and hiring. (2) Monitor target companies for competitor mentions and classify the competitive context as `neutral`, `competitive_defense`, or `displacement`. (3) Surface displacement opportunities — when a competitor lands a new client or pivots, understand the implication.

## Required Inputs
- `data/competitors.json` — competitor list with domains, aliases, and detection keywords
- `data/companies.json` — target company list
- `.tmp/research_cache/{company_id}_{date}.json` — existing research bundles (for mention scanning)
- `.tmp/competitor_snapshots/{id}_{date}.json` — website snapshots (auto-created on first run)

## When to Run
- **Daily (automated):** GitHub Actions `daily_scan.yml` runs both competitor tools
- **On-demand:** Before generating a playbook for a specific account

## Agent Steps

### Step 1 — Scrape Competitor Websites
```
python tools/monitor_competitor_sites.py \
    --snapshot-dir .tmp/competitor_snapshots \
    --output-dir outputs/competitive
```

For a single competitor:
```
python tools/monitor_competitor_sites.py --competitor-id primeforge
```

Snapshots are stored in `.tmp/competitor_snapshots/` and compared to the previous run. On the **first run** for a competitor, no diff is produced — it just establishes the baseline. Changes appear from the **second run** onward.

**What it detects:**
- `new_case_study` (HIGH) — competitor landed a new client. Check if the client is in your target territory.
- `team_page_changed` (MEDIUM) — headcount shift. Growing fast = they're winning business.
- `homepage_changed` (MEDIUM) — rebranding or service pivot. Review the new positioning.
- `new_blog_post` (LOW) — marketing activity. Note the topic — are they going after your ICP?
- `new_job_opening` (LOW) — expansion signal.

### Step 2 — Run News + Account Competitor Monitor
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

**Note on news monitoring:** Most Axiora competitors (regional Moroccan/Gambian shops) are too small to appear in Google News RSS. The news monitor is most useful for detecting if a competitor's name appears in a target account's content — not for competitor news itself. Use `monitor_competitor_sites.py` for that.

### Step 3 — Review Competitor Website Changes (`_competitor_sites_{date}.json`)
Read `outputs/competitive/_competitor_sites_{date}.json`. Focus on `high_significance_changes` first:

- **`new_case_study`** (HIGH): Competitor landed a new client. Visit the URL, note industry/use case — are they in your target territory?
- **`team_page_changed`** with positive delta (MEDIUM): They're growing headcount. Growing fast = winning business.
- **`homepage_changed`** (MEDIUM): Read `text_preview` in the detail. Are they rebranding, adding a new service line, or going upmarket?
- **`new_blog_post`** (LOW): Note the topic — are they pursuing your ICP with thought leadership?
- **`new_job_opening`** (LOW): Expansion signal. What roles? Technical = delivery scaling; sales = market expansion.

**First-run note:** On the first run for each competitor, only a baseline snapshot is taken — no diff output. Changes surface from the second run onward (next day in production).

### Step 4 — Review Account Competitive Intel
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
