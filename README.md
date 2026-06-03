# Sales Intelligence Agent

A zero-recurring-cost B2B sales intelligence system that monitors target companies, detects buying signals from public sources, generates account intelligence briefs, writes personalized outreach, and produces daily and weekly reports — all automated via GitHub Actions.

**Cost:** $0/month. Runs entirely on GitHub's free tier using only public data sources.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [How to Use It](#how-to-use-it)
3. [Architecture — The WAT Framework](#architecture--the-wat-framework)
4. [The Signal Pipeline](#the-signal-pipeline)
5. [Scoring System](#scoring-system)
6. [Tools Reference](#tools-reference) — all 23 scripts
7. [Data Configuration Files](#data-configuration-files)
8. [Workflows Reference](#workflows-reference) — all 17 SOPs
9. [GitHub Actions Automation](#github-actions-automation)
10. [Setup](#setup)
11. [API Keys and Integrations](#api-keys-and-integrations)
12. [Output Directory Structure](#output-directory-structure)
13. [Known Limitations](#known-limitations)
14. [Extending the System](#extending-the-system)

---

## What It Does

A sales rep provides a list of target companies. Every day the system:

1. **Collects** raw signals from 7 public sources: RSS/blog feeds, Google and Yahoo News, careers pages (Greenhouse, Lever, Ashby), GitHub org activity, Product Hunt, job boards, and company websites
2. **Normalizes** all raw data — deduplicates by content hash, classifies into signal types (hiring spike, funding event, leadership change, product launch, tech adoption, etc.), and assigns importance scores
3. **Scores** every company twice: once on ICP fit + signal strength (v1), and again with intent signals, urgency factors, and multi-signal pattern boosts (v2 composite)
4. **Correlates** simultaneous signals across sources to detect high-conviction buying moments (e.g., "post-funding + VP Engineering hired within 45 days")
5. **Generates** daily and weekly Markdown reports ranked by composite score
6. **Monitors** competitors — tracking news and detecting when target accounts mention or evaluate them
7. **Persists** per-account memory: engagement status, signal history, outreach history, known contacts
8. **Exports** CRM-ready JSON payloads for HubSpot, Salesforce, and Pipedrive
9. **Notifies** via Slack after every scan with a ranked account summary and direct links to all output files

**Agent-driven steps** (run interactively with Claude Code):
- Account intelligence briefs (deep reasoning from research bundles)
- Stakeholder mapping (who to contact and why)
- Outreach sequences (cold email + LinkedIn, 4-step, signal-specific)
- Deal playbook generation (from 5 pre-built templates)
- Account reviews (synthesize all context before any major action)

---

## How to Use It

You don't run commands. You talk to Claude Code.

```bash
cd sales-intelligence-agent
claude
```

Then tell it what you want:

| What you want | What to say |
|--------------|-------------|
| Add a company to monitor | *"Add Notion to our target companies and run onboarding"* |
| See today's buying signals | *"Run today's signal collection and show me what's hot"* |
| Deep research on a company | *"Research Anthropic thoroughly and tell me what you find"* |
| Write an account brief | *"Generate an intelligence brief for Ramp"* |
| Write cold outreach | *"Write outreach for the VP Engineering at OpenAI — her name is Mira"* |
| See who to prioritize | *"Score all accounts and rank them by urgency"* |
| Map stakeholders | *"Who should I contact first at Plaid and why?"* |
| Build a deal playbook | *"Generate a playbook for Anthropic based on their latest signals"* |
| Get a weekly digest | *"Run this week's reporting"* |
| Export to my CRM | *"Generate a HubSpot export for all accounts"* |
| Full account review | *"What should I do with Stripe right now?"* |

Claude reads the workflow SOPs in `workflows/`, runs the Python scripts in `tools/`, and handles reasoning, error recovery, and decision-making. You stay in the conversation.

---

## Architecture — The WAT Framework

The system separates concerns across three layers so that probabilistic AI handles reasoning while deterministic code handles execution.

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: WORKFLOWS  (workflows/*.md)                    │
│  Markdown SOPs — define objectives, required inputs,     │
│  which tools to run, expected outputs, error handling    │
└──────────────────────────┬──────────────────────────────┘
                           │ Claude reads these
┌──────────────────────────▼──────────────────────────────┐
│  Layer 2: AGENT  (Claude Code)                           │
│  Orchestrates tools, applies reasoning, handles          │
│  failures, asks clarifying questions, makes              │
│  priority decisions and writes intelligence briefs       │
└──────────────────────────┬──────────────────────────────┘
                           │ spawns subprocesses
┌──────────────────────────▼──────────────────────────────┐
│  Layer 3: TOOLS  (tools/*.py)                            │
│  23 deterministic Python scripts — HTTP requests,        │
│  data normalization, scoring math, file I/O,             │
│  report assembly. No AI inside these scripts.            │
└─────────────────────────────────────────────────────────┘
```

**Why this architecture matters:** If each step in a chain is 90% accurate, five steps in a row succeeds only 59% of the time. By keeping the AI focused on reasoning and offloading execution to deterministic scripts, the system stays reliable. Every tool is stateless, idempotent, and fast.

**Data model:**
- **Intermediates** (`.tmp/`) — raw collected data, research caches. Regenerated on every run.
- **Outputs** (`outputs/`) — processed signals, scores, reports, briefs, memory. Committed to the repo by GitHub Actions.
- **Deliverables** — anything the sales team needs lives in cloud services (Slack messages link back to GitHub; CRM exports imported manually or via API).

---

## The Signal Pipeline

The daily scan runs this pipeline in order. Each step's output is the next step's input.

```
COLLECTION
  fetch_rss_feeds.py ──────────────────────────────────┐
  search_news.py ──────────────────────────────────────┤
  monitor_careers_page.py ─────────────────────────────┤──► .tmp/raw_signals/
  search_github_activity.py ───────────────────────────┤
  check_product_hunt.py ───────────────────────────────┘

NORMALIZATION
  normalize_signals.py (.tmp/raw_signals/ → outputs/signals/{date}.json)
    - Deduplicates by content hash
    - Classifies into signal_type + signal_subtype
    - Assigns importance_score from signal_weights.json
    - Applies recency decay

SCORING v1 (ICP Fit)
  score_opportunity.py (signals + icp_criteria + signal_weights → scores-{date}.json)
    - Firmographic fit: employee count, funding stage, industry, geography
    - Signal strength: weighted sum of all signals with recency decay
    - Output: total score (0–95), tier (A / B / C)

CORRELATION (Pattern Detection)
  correlate_signals.py (signals + signal_combinations → correlations-{date}.json)
    - Detects named multi-signal patterns within time windows
    - 6 patterns: post-funding-expansion, leadership-driven-evaluation,
      tech-migration-cycle, product-launch-infrastructure,
      post-funding-leadership, triple-signal-conviction
    - Output: priority boost (10–25 pts per pattern), confidence, narrative

SCORING v2 (Composite)
  score_multi_factor.py (scores + correlations → multi_factor_scores-{date}.json)
    - composite = (v1 × 30%) + (intent × 40%) + (urgency × 30%)
    - intent: signal cluster bonus + intent keyword matches in job descriptions
    - urgency: executive window, post-funding window, correlation boost (capped at 50)
    - Output: composite score (0–95), priority tier (P1 / P2 / P3)

SIDE EFFECTS
  monitor_competitors.py ──► outputs/competitive/{company}/{date}.json
  update_account_memory.py ─► outputs/memory/{company_id}.json

REPORTING
  generate_report.py ──────► outputs/reports/daily_{date}.md
  notify_slack.py ─────────► Slack channel

COMMIT
  Git commit outputs/ → viewable in repo, linked from Slack
```

**Execution order constraint:** normalize → score_opportunity → correlate_signals → score_multi_factor. These four steps are strictly sequential. Everything else can be parallelized.

---

## Scoring System

### v1 Score (ICP Fit + Signal Strength)

Computed by `score_opportunity.py`. Maximum: 95 points.

```
v1_score = firmographic_fit + signal_strength + timing_bonus

Firmographic fit (up to ~40 pts):
  Employee count   ideal [50–500] → full score | acceptable [20–2000] → half
  Funding stage    ideal [Series A/B/C] → full | acceptable [Seed, D, Bootstrapped] → half
  Industry         ideal list → full | acceptable list → half
  Geography        ideal list → full | acceptable list → half

Signal strength (up to ~45 pts):
  Each signal type has a base weight (from data/signal_weights.json):
    leadership_change : new_cto      → 9.5 pts
    funding_event     : series_b     → 9.0 pts
    hiring_spike      : engineering  → 9.0 pts
    tech_change       : migration    → 8.0 pts
    product_launch    : new_product  → 7.5 pts
    github_signal     : star_spike   → 6.0 pts
    news_mention      : press_release→ 6.0 pts
    content_signal    : case_study   → 4.0 pts
  Weight × recency decay:
    ≤7 days  → 1.0×   |   ≤30 days → 0.8×
    ≤90 days → 0.5×   |   >90 days → 0.2×

Timing bonus (up to 15 pts):
  Applied if any signal is under 7 days old

Tier assignment: A (≥75) | B (≥50) | C (<50)
```

### Correlation Boosts

Computed by `correlate_signals.py`. Detects named patterns and applies priority boosts.

| Pattern | Window | Boost | Confidence |
|---------|--------|-------|-----------|
| `triple-signal-conviction` | 30 days | +25 | 0.93 |
| `post-funding-leadership` | 90 days | +22 | 0.89 |
| `leadership-driven-evaluation` | 45 days | +20 | 0.91 |
| `post-funding-expansion` | 60 days | +15 | 0.87 |
| `tech-migration-cycle` | 30 days | +12 | 0.78 |
| `product-launch-infrastructure` | 30 days | +10 | 0.72 |

### v2 Composite Score

Computed by `score_multi_factor.py`. Maximum: 95 points.

```
composite = (v1_score × 0.30) + (intent_score × 0.40) + (urgency_score × 0.30)

intent_score:
  +12  if ≥3 signals detected in the last 7 days (signal cluster)
  +3   per intent keyword matched in job descriptions (max 20 pts)

urgency_score (capped at 50 total):
  +15  new executive hire within 90 days
  +12  post-funding event within 180 days
  +10  active competitive pressure detected
  +8   multiple signals detected on the same day
  +N   correlation boost (from correlate_signals.py, capped at 30)

Priority tiers: P1 (≥80) | P2 (≥60) | P3 (≥40)
```

---

## Tools Reference

### Collection Tools

#### `fetch_rss_feeds.py`
Fetches RSS and Atom feeds for companies that have `blog_rss` configured.

```
Input:  data/companies.json (feed URLs)
Output: .tmp/raw_signals/rss_{company}_{date}.json
Args:   --companies-file, --company-id, --output-dir, --max-age-days
```

Filters entries older than `max-age-days`. Handles malformed feeds (feedparser bozo detection), missing publication dates, and truncates summaries to 500 characters.

---

#### `search_news.py`
Queries Google News RSS and Yahoo News RSS for each company.

```
Input:  Company names/queries from data/companies.json
Output: .tmp/raw_signals/news_{company}_{date}.json
Args:   --companies-file, --company-id, --output-dir, --max-age-days
```

Searches both sources to maximize coverage. Deduplicates by title+URL hash. For companies with generic names (Stripe, Linear), consider appending the category to the search query in companies.json (`search_query` field) to reduce noise.

---

#### `monitor_careers_page.py`
Scrapes careers pages and compares against the previous snapshot to detect new job postings.

```
Input:  careers_url from data/companies.json
Output: .tmp/raw_signals/careers_{company}_{date}.json
        outputs/snapshots/{company}_careers_{date}.json
Args:   --companies-file, --company-id, --output-dir, --snapshots-dir
```

**ATS support:** Greenhouse (`boards.greenhouse.io`), Lever (`jobs.lever.co`), Ashby (`jobs.ashbyhq.com`), and generic HTML scraping. Structured ATS data is more reliable than HTML scraping — always set `careers_url` to the ATS board URL when available.

**Seniority classification:** executive, VP, director, manager, senior IC, IC — mapped from title keywords.

**Department classification:** Engineering, Product, Sales, Marketing, Finance, Operations, Data, Customer Success, HR, Legal.

On first run: creates a baseline snapshot (no change signals emitted). Change signals are only emitted on subsequent runs.

---

#### `search_github_activity.py`
Pulls public GitHub organization data — new repos, star spikes, events.

```
Input:  github_org from data/companies.json
Output: .tmp/raw_signals/github_{company}_{date}.json
Args:   --companies-file, --company-id, --org, --output-dir, --lookback-days
```

Signals detected:
- `new_public_repo` — repo created within 14 days
- `sudden_star_spike` — ≥2× star growth vs. prior period
- `new_org_member` — new public member added

With `GITHUB_TOKEN` set: 5,000 req/hr. Without: 60 req/hr (sufficient for ~20 companies).

---

#### `check_product_hunt.py`
Checks Product Hunt RSS and DuckDuckGo for company launches.

```
Input:  Company names from data/companies.json
Output: .tmp/raw_signals/product_hunt_{company}_{date}.json
Args:   --companies-file, --company-id, --output-dir, --max-age-days
```

Detects: featured launches, upvote counts, "#1 Product of the Day" rankings. Most companies don't launch on PH frequently — this runs with a 7-day lookback and is opt-in per company (`check_product_hunt: true`).

---

#### `fetch_tech_signals.py`
Detects what technology stack a company uses from their website headers, HTML, and cookies.

```
Input:  Company domain
Output: JSON with tech stack list (name, category, confidence, evidence)
Args:   --domain, --company-id, --companies-file
```

Uses `data/tech_keywords.json` (50+ tech patterns). Detection methods:
- HTTP response headers (Cloudflare, CDN identifiers, `x-powered-by`)
- Script `src` patterns (`/_next/static/`, `/wp-content/`, etc.)
- Meta generator tags
- Cookie name fingerprints

Confidence: 0.92 for header/script/meta matches; 0.75 for inline pattern matches.

---

#### `fetch_job_listings.py`
Scrapes job listing platforms (Indeed, HN Who's Hiring) as a supplementary source.

```
Input:  Company name and ID
Output: JSON with parsed job listings
Args:   --company, --company-id, --sources (indeed, hn_hiring)
```

Extracts: title, seniority, department, and technology mentions from job descriptions. Indeed blocks scrapers frequently — falls back to DuckDuckGo when a 403/429 is received.

---

### Processing Tools

#### `normalize_signals.py`
Merges all raw signal files, deduplicates, classifies, and assigns importance scores.

```
Input:  .tmp/raw_signals/*.json (all collection tool outputs)
Output: outputs/signals/{date}.json
Args:   --input-dir, --output-file, --company-id, --stdin
```

**Signal types** (9 types, ~40 subtypes total):

| Type | Example subtypes |
|------|-----------------|
| `hiring_spike` | `engineering_leadership`, `bulk_engineering`, `data_ai`, `generic` |
| `funding_event` | `seed`, `series_a`, `series_b`, `series_c`, `ipo`, `generic` |
| `leadership_change` | `new_cto`, `new_ceo`, `new_cpo`, `new_vp_eng`, `generic` |
| `product_launch` | `new_product`, `major_release`, `beta`, `generic` |
| `tech_change` | `migration_signal`, `cloud_adoption`, `generic` |
| `github_signal` | `new_public_repo`, `sudden_star_spike`, `generic` |
| `content_signal` | `blog_post_published`, `case_study`, `generic` |
| `news_mention` | `press_release`, `award`, `acquisition`, `generic` |
| `product_hunt_launch` | `featured`, `generic` |

Deduplication is by content hash (MD5 of title + URL). Missing dates default to `detected_at = now()`. Missing type defaults to `news_mention`.

**Normalized signal schema:**
```json
{
  "signal_id": "stripe-leadership_change-2026-06-03-abc123",
  "company_id": "stripe",
  "signal_type": "leadership_change",
  "signal_subtype": "new_cto",
  "title": "Stripe hires new CTO",
  "source": "careers_page",
  "source_url": "https://stripe.com/jobs/...",
  "detected_at": "2026-06-03T17:00:00Z",
  "importance_score": 9.5,
  "processed": false,
  "structured_data": { "title": "CTO", "department": "Engineering", "is_leadership": true }
}
```

---

#### `score_opportunity.py`
Computes v1 ICP fit + signal strength scores for all companies.

```
Input:  outputs/signals/{date}.json + data/companies.json + data/icp_criteria.json + data/signal_weights.json
Output: outputs/signals/scores-{date}.json
Args:   --all-companies, --company-id, --companies-file, --signals-file, --output-file
```

See [Scoring System](#scoring-system) above for the full formula.

---

#### `correlate_signals.py`
Detects named multi-signal patterns and generates buying conviction narratives.

```
Input:  outputs/signals/{date}.json + data/signal_combinations.json
Output: outputs/signals/correlations-{date}.json
Args:   --all-companies, --company-id, --signals-file, --lookback-days, --output-file
```

Each matched pattern produces:
- `pattern_id` and `pattern_name`
- `confidence_score` (0.72–0.93)
- `priority_boost` (10–25 points)
- `matched_signals` — the specific signal IDs that triggered the pattern
- `why_matched` — human-readable explainability trace
- `composite_narrative` — templated buying story (e.g., "Stripe closed a Series C and subsequently brought in a new VP Engineering...")

---

#### `score_multi_factor.py`
Computes the v2 composite score combining ICP fit, intent signals, urgency factors, and correlation boosts.

```
Input:  outputs/signals/{date}.json + scores-{date}.json + correlations-{date}.json
Output: outputs/signals/multi_factor_scores-{date}.json
Args:   --all-companies, --company-id, --signals-file, --scores-file, --correlations-file, --output-file
```

Also reads `.tmp/research_cache/{company_id}_{date}.json` when available to find intent keywords in job descriptions. See [Scoring System](#scoring-system) for the composite formula.

---

#### `detect_changes.py`
Diffs two snapshots and emits change events as signals.

```
Input:  Current + previous snapshot (JSON files or strings)
Output: JSON change events, or .tmp/raw_signals/ file (with --write-signals)
Args:   --current, --previous, --company-id, --change-type (careers|webpage|rss), --write-signals
```

Maps change types to signal types:
- Careers `added` → `hiring_spike` (subtype determined by seniority: `engineering_leadership`, `bulk_engineering`, `data_ai`, or `generic`)
- Webpage `content_changed` → `tech_change`
- RSS `new_item` → `content_signal:blog_post_published`

---

#### `store_snapshot.py`
Saves a versioned snapshot of scraped content for future diff comparisons.

```
Input:  Content (file or string), company ID, snapshot type
Output: outputs/snapshots/{company}_{type}_{date}_{hash}.json
        outputs/snapshots/_index.json (updated)
Args:   --company-id, --snapshot-type, --content-file, --content, --snapshots-dir
```

Retains up to 20 snapshots per type. `_index.json` enables fast lookups without scanning all files.

---

### Intelligence Synthesis Tools

#### `research_company.py`
Orchestrates a full research sweep for a single company. Does not make HTTP calls directly — spawns subprocesses.

```
Input:  Company ID + depth (quick/standard/deep)
Output: .tmp/research_cache/{company_id}_{date}.json
Args:   --company-id, --depth, --companies-file
```

**Depth levels:**
- `quick` (5 min): Website scrape + news only
- `standard` (15 min): Careers + news + GitHub + Product Hunt
- `deep` (30 min): Standard + job listings + tech stack + Wayback Machine + Wikipedia

**Research bundle schema:**
```json
{
  "company_id": "stripe",
  "collected_at": "ISO-8601",
  "data": {
    "company_profile": { "about_text": "...", "title": "...", "founded_year": 2010 },
    "recent_news": [{ "title", "url", "published", "snippet", "source" }],
    "job_listings": [{ "title", "department", "seniority", "tech_mentions" }],
    "github_activity": [{ "event_type", "repo_name", "signal_type", "created_at" }],
    "product_hunt_launches": [{ "name", "tagline", "upvotes", "featured" }],
    "rss_items": [{ "title", "link", "published", "summary" }],
    "tech_stack": [{ "name", "category", "confidence", "evidence" }],
    "hiring_signals": { "total_open_roles": 0, "engineering_roles": 0, "leadership_roles": 0 }
  }
}
```

---

#### `generate_report.py`
Generates daily and weekly Markdown intelligence reports.

```
Input:  Signals dir + scores dir + briefs dir + companies config
Output: outputs/reports/daily_{date}.md  or  outputs/reports/weekly_{week}.md
Args:   --type (daily|weekly), --date, --week, --signals-dir, --briefs-dir, --companies-file
```

**Daily report includes:**
- Signal count breakdown by type
- All accounts ranked by composite score with tier badge (A/B/C)
- Per-company top 5 signals with urgency indicator
- Executive summary excerpts from stored briefs (if available)

**Weekly report includes:**
- Aggregated signal volume and WoW trend
- Top 20 companies by composite score
- Signal type distribution chart
- New P1 accounts and momentum shifts
- Action handoff section

---

#### `generate_executive_report.py`
Produces the weekly executive intelligence digest.

```
Input:  Multi-factor scores + account memory + prior week history snapshot
Output: outputs/reports/executive_{week}.md
        outputs/reports/history/{week}.json
Args:   --week (YYYY-WXX), --output-dir
```

**Sections:**
1. Pipeline snapshot — total accounts, P1 count, sequences active, meetings booked
2. Priority ranking table — sorted by composite score with engagement status
3. Week-over-week delta — reads prior week's `history/{week}.json`
4. KPI summary — signal volume trends, top signal types, average score
5. Top 3 recommended actions — placeholder `[AGENT: insert recommendation]` for the agent to fill in before distributing

The history snapshot (`outputs/reports/history/{week}.json`) is committed every week and forms the basis for trend analysis over time.

---

#### `generate_playbook.py`
Assembles a complete deal playbook by selecting the highest-priority matching template.

```
Input:  outputs/briefs/{company}/{date}.json + stakeholder_map + competitive_intel + seller_profile + playbook_templates
Output: outputs/playbooks/{company_id}/{date}.json + .md
Args:   --company-id, --date, --output-dir
```

**Template selection logic (by priority):**
1. If competitive_intel shows `displacement` or `competitive_defense` → force `competitive-displacement` template (priority 95)
2. Otherwise: find all templates where `trigger_signal` matches the brief's top signal type
3. Select the highest-priority match
4. Fallback: lowest-priority template with a `template_is_fallback: true` flag

| Template | Trigger | Priority |
|----------|---------|---------|
| `leadership-driven-evaluation` | `leadership_change` | 100 |
| `competitive-displacement` | `competitive_pressure` | 95 |
| `post-funding-expansion` | `funding_event` | 85 |
| `product-launch-follow` | `product_launch` | 70 |
| `generic-signal` | any | 50 |

Requires a brief to exist first. Returns a `no brief found` error otherwise (by design).

---

#### `map_stakeholders.py`
Identifies the four key stakeholder roles from public company pages.

```
Input:  Company website (scraped via scrape_website.py subprocess)
Output: outputs/stakeholder_maps/{company_id}.json
Args:   --company-id, --companies-file, --output-dir
```

**Roles identified:**
- `economic_buyer` — VP+/C-suite with P&L authority in the relevant domain
- `technical_evaluator` — Runs the PoC; typically Head of Engineering or CTO
- `champion` — Internal advocate who pushes for adoption
- `executive_sponsor` — C-suite owner of the strategic outcome

**Confidence formula:** `1 - (0.5 ** n)`, capped at 0.95 (where n = number of independent title signals for that role)
- 1 signal → 0.50 | 2 signals → 0.75 | 3 signals → 0.875 | 4+ → 0.9375

**Outreach readiness:**
- `proceed` (≥0.80 confidence on economic buyer) — generate outreach
- `caution` (0.50–0.79) — flag the gap, proceed with a note
- `escalate` (<0.50) — stop, request manual LinkedIn research

---

#### `monitor_competitors.py`
Tracks competitor news and detects when target accounts mention or evaluate your competitors.

```
Input:  data/competitors.json + .tmp/research_cache/ (for account mode)
Output: outputs/competitive/{company}/{date}.json
        outputs/competitive/_competitor_news_{date}.json
Args:   --mode (competitors|accounts|both), --all-companies, --company-id, --output-dir, --days-lookback
```

**Modes:**
- `competitors` — Fetches news for each competitor in `data/competitors.json`
- `accounts` — Scans research bundles for competitor name mentions using displacement signal patterns
- `both` — Runs both

**Detection categories:**
- `neutral` — Competitor name appears in a job description as a skill requirement (not a buying signal)
- `evaluation` — Target is actively comparing ("evaluating X vs Y")
- `displacement` — Target is replacing a competitor ("moving away from X", "replacing X")

A `displacement` detection overrides all playbook template selection to `competitive-displacement` regardless of other signals.

---

#### `export_crm.py`
Generates CRM-ready JSON payloads for bulk import (does not make API calls).

```
Input:  outputs/briefs/ + outputs/signals/{date}.json + data/companies.json
Output: outputs/crm_exports/{date}_{crm_type}.json
Args:   --all-companies, --company-id, --crm (hubspot|salesforce|pipedrive), --date, --exports-dir
```

**HubSpot output includes:**
- Company records with custom properties: `axiora_account_tier`, `axiora_composite_score`, `axiora_top_signals`, `axiora_last_updated`, `axiora_brief_url`
- Contact records (from stakeholder maps; no invented email addresses)
- Deal records for Tier A/B accounts (stage: `signal_detected`)
- Notes with executive summary and top signals from the brief

Salesforce and Pipedrive use vendor-specific field mappings (Account/Contact vs. Company/Person).

---

#### `update_account_memory.py`
Maintains per-company relationship state across all conversations and pipeline runs.

```
Input:  Company ID + action + optional field/value or signal file
Output: outputs/memory/{company_id}.json
Args:   --action (init|read|write|append-signal|append-outreach|append-brief|reset)
        --company-id, --all-companies, --field, --value, --signal-file, --sequence-id, --step, --date, --brief-id
```

**Actions:**
- `init` — Create blank memory record (idempotent)
- `read` — Print current memory as JSON
- `write --field path.to.field --value "..."` — Update a specific field (dotted path)
- `append-signal --signal-file outputs/signals/{date}.json` — Add today's signals to history (auto-purges signals >90 days old)
- `append-outreach --sequence-id S1 --step 1 --date today` — Record a touch in outreach history; auto-sets `engagement_status: in_sequence`
- `append-brief --brief-id id` — Record that a brief or playbook was generated
- `reset` — Clear outreach history and reset engagement_status to `not_contacted` (preserves known_contacts)

**Atomic writes:** Uses tmp→rename to prevent race conditions when multiple GitHub Actions jobs run in parallel.

**Memory schema (key fields):**
```json
{
  "relationship_context": {
    "engagement_status": "not_contacted|in_sequence|replied|meeting_booked|paused|closed_won|closed_lost",
    "last_outreach_date": "2026-06-03",
    "last_response_sentiment": "positive|neutral|negative|not_interested",
    "open_outreach_sequence_id": "...",
    "notes": "..."
  },
  "known_contacts": [{ "name", "title", "email", "role", "last_contacted" }],
  "signal_history": [...],   // rolling 90-day window
  "outreach_history": [...], // append-only
  "brief_history": [...]     // playbooks + briefs generated
}
```

---

#### `notify_slack.py`
Posts formatted intelligence summaries to Slack.

```
Input:  outputs/signals/, outputs/reports/, outputs/briefs/ (depending on type)
Output: Slack Block Kit message via SLACK_WEBHOOK_URL
Args:   --type (daily|weekly|brief|research), --date, --week, --company-id
```

**Daily message:** signal counts by type + all accounts ranked by composite score + per-account top 3 signals + direct links to GitHub report files.

**Weekly message:** aggregated WoW trends + top 20 accounts + signal distribution + KPI summary.

**Brief message:** single company key facts + top signals + recommended action.

Silently exits 0 if `SLACK_WEBHOOK_URL` is not configured (non-fatal).

---

#### `scrape_website.py`
Fetches a URL and returns clean plain text (strips nav, footer, script, style tags).

```
Input:  URL
Output: JSON with text_content, url, fetched_at, error (if any)
Args:   --url, --selector (CSS), --output-format (text|json), --skip-robots
```

Used internally by `map_stakeholders.py` and `research_company.py` (via subprocess). Respects `robots.txt` unless `--skip-robots` is passed. Rotates user agents. One automatic retry on `ConnectionError`. Timeout: 10 seconds.

---

## Data Configuration Files

These files in `data/` are the primary configuration surface. Edit them to customize the system for your ICP, targets, and product.

### `data/companies.json`

Master target account list. Every monitoring tool reads this.

```json
{
  "id": "stripe",
  "name": "Stripe",
  "domain": "stripe.com",
  "website": "https://stripe.com",
  "careers_url": "https://boards.greenhouse.io/stripe",
  "blog_rss": "https://stripe.com/blog/feed.rss",
  "linkedin_url": "https://www.linkedin.com/company/stripe",
  "github_org": "stripe",
  "industry": "Fintech / Payments Infrastructure",
  "employee_count_estimate": "8000-10000",
  "headquarters": "San Francisco, CA",
  "funding_stage": "Late Stage / Pre-IPO",
  "tier": "A",
  "icp_fit_score": 70,
  "assigned_to": "rep@yourcompany.com",
  "monitoring_config": {
    "check_careers": true,
    "check_blog": true,
    "check_news": true,
    "check_github": true,
    "check_product_hunt": false
  }
}
```

**Tips:**
- Set `careers_url` to the ATS board URL (Greenhouse/Lever/Ashby) for structured job data
- For companies with generic names, add a `search_query` field with a more specific phrase (e.g., `"Stripe payments fintech"`)
- Disable monitoring flags for sources that don't apply (`check_github: false` if no public org)

---

### `data/icp_criteria.json`

Defines your Ideal Customer Profile for firmographic scoring.

**Fields:**
- `employee_count.ideal` — Range that gets full score (e.g., `[50, 500]`)
- `employee_count.acceptable` — Range that gets half score
- `funding_stages.ideal` — List (e.g., `["Series A", "Series B", "Series C"]`)
- `industries.ideal` / `industries.acceptable` — Industry strings that match company data
- `geographies.ideal` / `geographies.acceptable` — Country/city strings
- `positive_tech_signals` — Technologies that increase ICP fit score when detected
- `negative_tech_signals` — Technologies that indicate a poor fit

---

### `data/signal_weights.json`

Controls how much each signal type and subtype contributes to the v1 score. Also contains:
- `recency_decay` — Score multipliers by age bucket (7d, 30d, 90d, older)
- `signal_type_keywords` — Keyword lists used by `normalize_signals.py` for classification
- `seniority_keywords` — Patterns for executive/VP/director/senior detection

Adjust weights here to tune the scoring for your use case. Higher weights for signals most predictive of your typical buying moment.

---

### `data/signal_combinations.json`

Named multi-signal patterns for `correlate_signals.py`. Each pattern defines:
- `id`, `name`, `description`
- `required_signal_types` — Which types must appear
- `time_window_days` — Max days between first and last signal
- `priority_boost` — Points added to urgency score
- `confidence` — Narrative confidence (used in report formatting)
- `narrative_template` — Templated buying-cycle explanation

Add new patterns here to detect custom buying moments specific to your ICP.

---

### `data/competitors.json`

Competitors to monitor via `monitor_competitors.py`.

Per competitor:
- `name`, `domain`, `aliases` — Used for text matching in research bundles
- `monitoring_config` — Whether to track their news/PH/careers
- `displacement_signals` — Regex patterns indicating a target account wants to leave (e.g., `"replacing {competitor}"`, `"away from {competitor}"`)

---

### `data/playbook_templates.json`

Five deal playbooks. Each template defines:
- `trigger_signal` — Which signal type activates this template
- `priority` — Selection priority (higher wins)
- `recommended_angle` — The hook sentence for outreach
- `message_tone` — How to write (e.g., `"peer-level, direct, no pitch"`)
- `primary_cta` — The ask (e.g., `"15-min call before they're fully ramped"`)
- `value_hook` — One-line connecting signal to your value prop
- `objections` — Array of `{ "objection": "...", "response": "..." }`
- `sequence_timing` — `{ "step_1_channel": "email", "follow_up_days": [3, 7, 21] }`
- `urgency_note` — When the window closes

---

### `data/seller_profile.json`

Your company identity and outreach guidelines. Required before generating outreach or playbooks.

**Contains:**
- Company name, product name, one-liner, website
- Typical buyer (title, role, industry)
- Value proposition (primary + secondary)
- Differentiators and social proof (case studies, outcomes)
- Outreach rules (tone, word limits, banned phrases)
- CTA options (ranked by friction level)
- Target segments (specific problem patterns to look for)

---

### `data/tech_keywords.json`

Fingerprint patterns for 50+ technologies. Used by `fetch_tech_signals.py` and `fetch_job_listings.py` to detect tech stack from website headers, HTML, and job description text.

---

### `data/scoring_config.json`

Advanced tuning for the v2 composite scoring formula. Edit to change:
- Composite weights (`v1_weight`, `intent_weight`, `urgency_weight`)
- Intent scoring thresholds (cluster bonus, keyword scoring)
- Urgency scoring (per-factor bonuses, caps)
- Priority tier thresholds (P1/P2/P3)

---

### `data/schema_registry.json`

Version map for all structured output schemas. Ensures tools that read each other's outputs can detect and handle schema mismatches. Current version: `2.0` for all schemas.

---

## Workflows Reference

All 17 Markdown SOPs in `workflows/` are Claude's operating instructions. Claude reads the relevant workflow before taking any significant action.

| Workflow | Purpose | Key Tools Called |
|----------|---------|-----------------|
| `account_onboarding.md` | Add a new company to monitoring with baseline snapshots | `research_company.py`, `fetch_tech_signals.py`, `monitor_careers_page.py` |
| `signal_collection.md` | Phase 1: gather raw signals from all sources | `fetch_rss_feeds.py`, `search_news.py`, `monitor_careers_page.py`, `search_github_activity.py`, `check_product_hunt.py` |
| `signal_detection.md` | Phase 2: normalize, classify, context-analyze, score | `normalize_signals.py`, `score_opportunity.py` |
| `signal_correlation.md` | Phase 3: detect multi-signal patterns | `correlate_signals.py`, `score_multi_factor.py`, `update_account_memory.py` |
| `opportunity_scoring.md` | Manual scoring review with agent judgment | `score_opportunity.py` |
| `company_research.md` | Deep research for a single company | `research_company.py`, `scrape_website.py` |
| `intelligence_brief_generation.md` | Write account intelligence brief (agent reasoning task) | No tools — pure reasoning from research bundle |
| `outreach_generation.md` | Write personalized 4-step outreach sequence (agent task) | No tools — pure reasoning from brief + seller profile |
| `stakeholder_mapping.md` | Identify economic buyer and other stakeholder roles | `map_stakeholders.py`, `update_account_memory.py` |
| `competitive_intelligence.md` | Monitor competitors + detect competitive signals | `monitor_competitors.py` |
| `deal_playbook_generation.md` | Build a deal playbook from templates + account context | `generate_playbook.py`, `update_account_memory.py` |
| `account_memory.md` | Maintain per-account engagement state | `update_account_memory.py` |
| `daily_reporting.md` | Generate and post daily intelligence digest | `generate_report.py`, `notify_slack.py` |
| `weekly_reporting.md` | Analyze trends and produce weekly digest + CRM export | `generate_report.py`, `export_crm.py` |
| `executive_reporting.md` | Weekly executive report with KPIs and recommendations | `generate_executive_report.py` |
| `crm_export_generation.md` | Export CRM-ready records for all accounts | `export_crm.py` |
| `account_review.md` | Synthesize all context and produce a single clear recommendation | `update_account_memory.py` (reads all output dirs) |

**Workflows that are pure agent tasks (no tools needed):**
- `intelligence_brief_generation.md` — Claude reads the research bundle and writes the brief. The quality standard is explicit: every claim must be traceable to a source, banned words are listed, and a vague brief is a failed brief.
- `outreach_generation.md` — Claude reads the brief + seller profile and writes a 4-step sequence. Strict word limits: 100 words cold email, 40 words LinkedIn, 80 words follow-up, 45 words breakup.

---

## GitHub Actions Automation

Three workflows run automatically in GitHub Actions.

### `daily_scan.yml` — runs 6:00 AM UTC daily

```
Phase 1 (Collection)       All tools run with continue-on-error: true
  fetch_rss_feeds.py       → .tmp/raw_signals/
  search_news.py           → .tmp/raw_signals/
  monitor_careers_page.py  → .tmp/raw_signals/ + outputs/snapshots/
  search_github_activity.py→ .tmp/raw_signals/         [uses PERSONAL_GITHUB_TOKEN]
  check_product_hunt.py    → .tmp/raw_signals/

Phase 2 (Detection)
  normalize_signals.py     → outputs/signals/{date}.json
  score_opportunity.py     → outputs/signals/scores-{date}.json
  correlate_signals.py     → outputs/signals/correlations-{date}.json
  score_multi_factor.py    → outputs/signals/multi_factor_scores-{date}.json
  monitor_competitors.py   → outputs/competitive/
  update_account_memory.py → outputs/memory/

Phase 3 (Reporting)
  generate_report.py       → outputs/reports/daily_{date}.md
  notify_slack.py          → Slack channel             [uses SLACK_WEBHOOK_URL]

Phase 4 (Commit + Artifacts)
  Git commit outputs/ → repo
  Upload .tmp/raw_signals/ as artifact (7-day retention)
  Upload processed outputs as artifact (30-day retention)
```

---

### `weekly_report.yml` — runs 7:00 AM UTC every Monday

```
  generate_report.py --type weekly     → outputs/reports/weekly_{week}.md
  export_crm.py --crm hubspot          → outputs/crm_exports/{date}_hubspot.json
  generate_executive_report.py         → outputs/reports/executive_{week}.md
                                         outputs/reports/history/{week}.json
  notify_slack.py --type weekly        → Slack channel
  Git commit reports + CRM export
  Upload artifacts (90-day retention)
```

---

### `manual_research.yml` — triggered manually from the Actions tab

**Inputs:** `company_id` (required), `depth` (quick/standard/deep), `generate_crm_export` (boolean)

```
  research_company.py --depth {depth}  → .tmp/research_cache/{company}_{date}.json
  search_news.py (30-day lookback)     → .tmp/raw_signals/
  search_github_activity.py            → .tmp/raw_signals/
  check_product_hunt.py (30-day)       → .tmp/raw_signals/
  normalize_signals.py                 → outputs/signals/manual-{date}-{company}.json
  score_opportunity.py                 → scores
  correlate_signals.py                 → correlations
  score_multi_factor.py                → multi_factor_scores
  map_stakeholders.py                  → outputs/stakeholder_maps/{company}.json
  monitor_competitors.py --mode accounts → outputs/competitive/{company}/{date}.json
  generate_playbook.py                 → outputs/playbooks/{company}/{date}.json
  update_account_memory.py --action init → outputs/memory/{company}.json
  export_crm.py (if requested)
  notify_slack.py --type brief
  Git commit all outputs
  Upload artifacts (30-day retention)
```

After the Actions run, the output files are linked directly in the Slack message and viewable in the repo.

---

### GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Purpose | Required? |
|--------|---------|-----------|
| `PERSONAL_GITHUB_TOKEN` | Raises GitHub API rate limit to 5,000 req/hr | No (60/hr without) |
| `SLACK_WEBHOOK_URL` | Posts summaries to Slack after every scan | No |

No secrets are strictly required. The system runs entirely on public sources without any API keys.

---

## Setup

### Prerequisites

- Python 3.11+
- Git
- A GitHub repository (fork or clone this repo)
- Claude Code (`npm install -g @anthropic-ai/claude-code`)

### 1. Install dependencies

Use `python -m pip` to ensure packages land in the same Python environment that runs the tools.

```bash
python -m pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`. All variables are optional — the system runs without any keys. See [API Keys and Integrations](#api-keys-and-integrations) for what each key unlocks.

### 3. Configure your target companies

Edit `data/companies.json`. Replace the example entries with your real targets, or tell Claude:

> *"Add Notion (notion.so) as a new Tier A target — they're Series C, ~500 employees, B2B SaaS"*

Claude will run the `account_onboarding.md` workflow: research the company, detect tech stack, create a baseline careers snapshot, assess ICP fit, and generate an initial brief.

### 4. Configure your seller profile

Edit `data/seller_profile.json` with your company, product, value proposition, case studies, and outreach guidelines. This file is required before generating outreach or playbooks.

### 5. Configure your ICP

Edit `data/icp_criteria.json` to define your ideal customer: company size range, funding stages, target industries, geographies, and technology signals.

### 6. Configure competitors

Edit `data/competitors.json` with the competitors you want to monitor and detect in target account content.

### 7. Run your first signal collection

Tell Claude: *"Run today's signal collection for all companies"*

Or manually:
```bash
python tools/fetch_rss_feeds.py --companies-file data/companies.json --output-dir .tmp/raw_signals/ --max-age-days 7
python tools/search_news.py --companies-file data/companies.json --output-dir .tmp/raw_signals/ --max-age-days 7
python tools/monitor_careers_page.py --companies-file data/companies.json --output-dir .tmp/raw_signals/ --snapshots-dir outputs/snapshots/
python tools/search_github_activity.py --companies-file data/companies.json --output-dir .tmp/raw_signals/
python tools/normalize_signals.py --input-dir .tmp/raw_signals/ --output-file outputs/signals/$(date +%Y-%m-%d).json
python tools/score_opportunity.py --all-companies --companies-file data/companies.json --signals-file outputs/signals/$(date +%Y-%m-%d).json --output-file outputs/signals/scores-$(date +%Y-%m-%d).json
python tools/correlate_signals.py --all-companies --signals-file outputs/signals/$(date +%Y-%m-%d).json --output-file outputs/signals/correlations-$(date +%Y-%m-%d).json
python tools/score_multi_factor.py --all-companies --signals-file outputs/signals/$(date +%Y-%m-%d).json --scores-file outputs/signals/scores-$(date +%Y-%m-%d).json --correlations-file outputs/signals/correlations-$(date +%Y-%m-%d).json --output-file outputs/signals/multi_factor_scores-$(date +%Y-%m-%d).json
python tools/generate_report.py --type daily --date $(date +%Y-%m-%d) --signals-dir outputs/signals/ --briefs-dir outputs/briefs/ --companies-file data/companies.json
```

### 8. Generate an intelligence brief (interactive)

```bash
claude
```

Say: *"Generate an intelligence brief for Stripe based on today's research"*

Claude reads the research bundle, analyzes signals with context-aware reasoning (e.g., "hiring 5 engineers at a 30-person company is different than at a 500-person company"), and writes both JSON and Markdown brief files to `outputs/briefs/stripe/`.

### 9. Generate outreach (interactive)

After the brief is ready:

> *"Write outreach for the VP Engineering at Stripe — her name is Sarah Chen"*

Claude reads the brief + seller profile and generates a 4-step sequence to `outputs/outreach/stripe/`.

### 10. Enable automation

Push the repo to GitHub. Workflows activate automatically. No further configuration needed beyond adding the optional GitHub Secrets.

---

## API Keys and Integrations

All keys go in `.env`. None are required for the system to run.

| Key | What it unlocks | Cost |
|-----|----------------|------|
| `GITHUB_TOKEN` | GitHub API: 5,000 req/hr vs 60 without | Free (PAT) |
| `SLACK_WEBHOOK_URL` | Slack summaries after every scan | Free |
| `GITHUB_REPO_URL` | Repo URL embedded in Slack message links | Free |
| `HUNTER_API_KEY` | Email lookup for discovered contacts | Free: 25/month |
| `APOLLO_API_KEY` | Richer contact and company enrichment | Paid |
| `CLAY_API_KEY` | Data enrichment pipelines | Paid |
| `HUBSPOT_API_KEY` | Live CRM sync (vs manual JSON import) | Paid |
| `SALESFORCE_CLIENT_ID/SECRET/URL` | Live Salesforce sync | Paid |
| `PIPEDRIVE_API_KEY` | Live Pipedrive sync | Paid |
| `SMTP_HOST/PORT/USER/APP_PASSWORD` | Email digest notifications | Free (Gmail app password) |

---

## Output Directory Structure

All outputs are committed to the repository by GitHub Actions after each run. Slack messages link directly to these files.

```
outputs/
├── signals/
│   ├── {date}.json                      # Normalized signals (all companies)
│   ├── scores-{date}.json               # v1 ICP fit scores
│   ├── correlations-{date}.json         # Multi-signal pattern matches
│   └── multi_factor_scores-{date}.json  # v2 composite scores (P1/P2/P3)
│
├── reports/
│   ├── daily_{date}.md                  # Daily intelligence digest
│   ├── weekly_{YYYY-WXX}.md             # Weekly trend report
│   ├── executive_{YYYY-WXX}.md          # Executive report (with action placeholders)
│   └── history/
│       └── {YYYY-WXX}.json             # KPI snapshot for WoW delta
│
├── snapshots/
│   ├── {company}_careers_{date}.json    # Careers page snapshot
│   └── _index.json                      # Fast lookup index
│
├── briefs/
│   └── {company_id}/
│       ├── {date}.json                  # Machine-readable brief
│       └── {date}.md                    # Human-readable brief
│
├── competitive/
│   ├── {company_id}/
│   │   └── {date}.json                  # Competitor mentions in target account
│   └── _competitor_news_{date}.json     # Global competitor news digest
│
├── memory/
│   └── {company_id}.json                # Engagement status + signal/outreach history
│
├── stakeholder_maps/
│   └── {company_id}.json                # Economic buyer, evaluator, champion, sponsor
│
├── playbooks/
│   └── {company_id}/
│       ├── {date}.json                  # Machine-readable playbook
│       └── {date}.md                    # Human-readable playbook
│
├── crm_exports/
│   └── {date}_{crm_type}.json           # HubSpot/Salesforce/Pipedrive import payload
│
└── outreach/
    └── {company_id}/
        └── {sequence_id}.json           # 4-step outreach sequence
```

---

## Free Data Sources Used

| Source | What it provides | Notes |
|--------|-----------------|-------|
| Google News RSS | News mentions | No rate limit; 2s delay between queries |
| Yahoo News RSS | News mentions (secondary) | No rate limit |
| Company RSS feeds | Blog posts, press releases | No rate limit |
| GitHub API (unauth) | Org activity, repos, stars | 60 req/hr |
| GitHub API (with token) | Same | 5,000 req/hr |
| Greenhouse / Lever / Ashby | Structured job listings from public ATS boards | No rate limit |
| Website scraping | About, team, careers, tech stack | Respectful scraping with user-agent rotation |
| Product Hunt RSS | Product launches | No rate limit |
| Wikipedia REST API | Company background and founding date | No rate limit |
| Wayback Machine CDX API | First archived date, historical presence | No rate limit |
| Indeed | Job listings (fallback) | Blocks scrapers; falls back to DuckDuckGo |

---

## Known Limitations

**News signal noise:** Companies with generic names (Stripe, Linear, Ramp) match unrelated news. The scoring layer attenuates most noise, but for better precision set a custom `search_query` in `data/companies.json` (e.g., `"Ramp corporate cards fintech"`).

**JavaScript-rendered careers pages:** The HTML scraper returns no jobs on React/Next.js SPAs. Fix: set `careers_url` to the company's Greenhouse, Lever, or Ashby board URL. Most companies that use these ATSs have public board URLs.

**Stakeholder mapping depends on public team pages:** Many companies (especially large ones) don't list executives on public pages. When `map_stakeholders.py` returns zero contacts, manual LinkedIn research is required before outreach.

**GitHub activity requires a public org:** Companies without a public GitHub org can't be monitored for GitHub signals. Set `check_github: false` in `monitoring_config` for those accounts.

**Tech stack detection has false positives:** Shared CDNs (Cloudflare) appear on nearly every site. Category labels help disambiguate — `CDN / Security` vs. `Analytics` — but treat tech stack data as a signal, not a certainty.

**Intelligence briefs are agent-generated:** `generate_playbook.py` requires a brief to exist first. Briefs are written by Claude Code interactively (not by any tool) — they are reasoning artifacts, not script outputs.

---

## Extending the System

The WAT architecture makes extensions additive: add a Python tool, reference it from a workflow.

**To add a new data source:**
1. Create `tools/fetch_{source}.py` that outputs `.tmp/raw_signals/{source}_{company}_{date}.json`
2. Ensure the output schema matches the normalized signal format (signal_type, signal_subtype, etc.)
3. Add the tool call to `signal_collection.md` and `.github/workflows/daily_scan.yml`

**To add a new signal pattern:**
1. Add a pattern object to `data/signal_combinations.json` with required_signal_types, time_window_days, priority_boost
2. `correlate_signals.py` picks it up automatically on next run

**To add a new playbook template:**
1. Add a template object to `data/playbook_templates.json` with trigger_signal, priority, and messaging fields
2. `generate_playbook.py` picks it up automatically

**Planned integrations (not yet built):**

| Integration | File to create | Requires |
|------------|---------------|---------|
| Apollo contact enrichment | `tools/enrich_contact_apollo.py` | `APOLLO_API_KEY` |
| HubSpot live sync | `tools/sync_hubspot.py` | `HUBSPOT_API_KEY` |
| Salesforce live sync | `tools/sync_salesforce.py` | Salesforce OAuth credentials |
| Email digest | `tools/send_email_digest.py` | SMTP credentials in `.env` |

Tell Claude: *"Add an Apollo contact enrichment tool that reads the stakeholder map and enriches contacts with email addresses"* and it will build and wire it in.

---

## GitHub Actions Free Tier Budget

| Workflow | Estimated runtime | Runs/month | Minutes/month |
|----------|-------------------|-----------|--------------|
| Daily scan | ~10 min | 30 | 300 |
| Weekly report | ~5 min | 4 | 20 |
| Manual research | ~8 min | ~10 | 80 |
| **Total** | | | **~400 min** |
| **GitHub free tier** | | | **2,000 min** |

Comfortably within GitHub's free tier for both public and private repositories.

---

## License

MIT
