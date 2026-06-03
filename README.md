# Sales Intelligence Agent

A zero-recurring-cost Sales Intelligence Agent for B2B SaaS sales teams. Built on the WAT (Workflows, Agents, Tools) framework.

**What it does:** Monitors target accounts, detects buying signals from public sources, generates account intelligence briefs, writes personalized outreach, exports CRM-ready data, produces daily/weekly reports, and delivers summaries directly to Slack — all automated via GitHub Actions.

**Cost:** $0/month. Runs entirely on GitHub's free tier.

---

## How to Use This (The Short Version)

You don't run commands. You talk to Claude.

Open Claude Code in this folder:
```bash
claude
```

Then just tell it what you want:

| What you want | What to say |
|--------------|-------------|
| Add a company to monitor | *"Add Notion to our target companies and run onboarding"* |
| See today's buying signals | *"Run today's signal collection and show me what's hot"* |
| Deep research on a company | *"Research Linear thoroughly and tell me what you find"* |
| Write an account brief | *"Generate an intelligence brief for Retool"* |
| Write cold outreach | *"Write a cold email for the CTO at Linear — his name is Tuomas"* |
| See who to prioritize | *"Score all accounts and rank them by urgency"* |
| Get a weekly digest | *"Run this week's reporting"* |
| Export to my CRM | *"Generate a HubSpot export for all accounts"* |

Claude reads the workflow instructions in `workflows/`, runs the Python scripts in `tools/`, and handles everything else. You stay in the conversation.

---

## What This System Does

A sales rep provides a list of target companies. The system then:

1. **Monitors** those accounts continuously (via GitHub Actions, 6am UTC daily)
2. **Detects** buying signals — hiring spikes, product launches, leadership changes, tech adoptions
3. **Researches** companies from 10+ free public sources
4. **Scores** opportunities using ICP fit + signal strength + urgency
5. **Generates** account intelligence briefs (via Claude Code, interactively)
6. **Maps** stakeholders and suggests first contacts
7. **Writes** personalized outreach sequences (email + LinkedIn, 4 steps)
8. **Exports** CRM-ready records (HubSpot, Salesforce, Pipedrive)
9. **Reports** daily and weekly intelligence digests
10. **Notifies** via Slack — summary posted to your channel after every scan

---

## Architecture — WAT Framework

```
Layer 1: Workflows (workflows/*.md)
   ↓  Markdown SOPs — what to do and how
Layer 2: Agent (Claude Code)
   ↓  Reads workflows, orchestrates tools, handles all reasoning
Layer 3: Tools (tools/*.py)
      Python scripts — deterministic execution, no AI inside
```

**The agent handles:** signal analysis, brief writing, outreach generation, priority decisions, adapting to failures.
**Tools handle:** HTTP requests, data normalization, file I/O, scoring math, report assembly.

Why it's built this way: if every step is 90% accurate, five steps in a row gives you 59% success. By keeping the AI focused on reasoning and offloading execution to deterministic scripts, the system stays reliable.

---

## Setup

### Prerequisites
- Python 3.11+
- Git
- A GitHub repository (fork or clone this repo)
- Claude Code (`npm install -g @anthropic-ai/claude-code`)

### 1. Install dependencies

**Important:** use `python -m pip` to ensure packages go to the same Python Claude Code uses.

```bash
python -m pip install -r requirements.txt
```

### 2. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and fill in the values you want. All are optional — the system runs on public sources with no keys. See the table below for what each key unlocks.

### 3. Configure your target companies

Edit `data/companies.json` — replace the example entries with your real targets:

```json
{
  "companies": [
    {
      "id": "acme",
      "name": "Acme Corp",
      "domain": "acme.com",
      "website": "https://acme.com",
      "careers_url": "https://acme.com/careers",
      "industry": "B2B SaaS",
      "tier": "A",
      "monitoring_config": {
        "check_careers": true,
        "check_news": true,
        "check_github": true
      }
    }
  ]
}
```

Or just tell Claude: *"Add Acme Corp (acme.com) as a new Tier A target"* and it will do it for you.

### 4. Configure your seller profile

Edit `data/seller_profile.json` with your company name, product, value proposition, and outreach guidelines. Required before generating outreach. The file has comments explaining every field.

### 5. Configure your ICP (optional but recommended)

Edit `data/icp_criteria.json` to match your Ideal Customer Profile — industries, company size, funding stage, tech signals.

### 6. Run your first research

Open Claude Code and say:

> *"Run signal collection for all companies and generate a daily report"*

Or manually:

```bash
python tools/research_company.py --company-id acme --depth standard
python tools/search_news.py --companies-file data/companies.json --output-dir .tmp/raw_signals/ --max-age-days 7
python tools/search_github_activity.py --companies-file data/companies.json --output-dir .tmp/raw_signals/
python tools/monitor_careers_page.py --companies-file data/companies.json --output-dir .tmp/raw_signals/ --snapshots-dir outputs/snapshots/
python tools/normalize_signals.py --input-dir .tmp/raw_signals/ --output-file outputs/signals/signals_today.json
python tools/score_opportunity.py --all-companies --signals-file outputs/signals/signals_today.json --output-file outputs/signals/scores-today.json
python tools/generate_report.py --type daily --signals-dir outputs/signals/ --reports-dir outputs/reports/
```

### 7. Generate an intelligence brief (interactive)

```bash
claude
```

Say: *"Generate an intelligence brief for acme based on the latest research"*

Claude reads the research bundle, analyzes signals, and writes both JSON and Markdown brief files to `outputs/briefs/acme/`.

### 8. Generate outreach (interactive)

After the brief is ready, say:

> *"Write outreach for the Head of Engineering at Acme Corp — her name is Sarah Chen"*

Claude reads the brief + seller profile and writes a 4-step sequence (cold email, LinkedIn, follow-up 1, follow-up 2) to `outputs/outreach/`.

---

## GitHub Actions Automation

Push to a GitHub repository. The three workflows run automatically:

| Workflow | Schedule | What it does |
|----------|----------|-------------|
| `daily_scan.yml` | 6:00 AM UTC daily | Collect signals, detect changes, score opportunities, generate daily report, notify Slack |
| `weekly_report.yml` | Monday 7:00 AM UTC | Weekly digest + CRM export + executive report + notify Slack |
| `manual_research.yml` | On-demand | Full research for one company |

### Enable it

1. Push the repo to GitHub
2. Go to **Actions** tab → confirm workflows are enabled
3. Add your secrets (see below)
4. That's it — the daily scan runs automatically at 6am UTC

### GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Purpose | Required? |
|--------|---------|-----------|
| `PERSONAL_GITHUB_TOKEN` | Raises GitHub API rate limit from 60 to 5,000 req/hr | No |
| `SLACK_WEBHOOK_URL` | Posts daily/weekly summaries to your Slack channel | No |

No secrets are strictly required. The system works on public sources alone, and outputs are always committed back to the repo regardless.

### Where to find outputs

After each run the bot commits results back to the repository:

| Output | Location in repo | Retention |
|--------|-----------------|-----------|
| Daily report | `outputs/reports/daily_YYYY-MM-DD.md` | Permanent |
| Weekly report | `outputs/reports/weekly_YYYY-WXX.md` | Permanent |
| Signal data | `outputs/signals/YYYY-MM-DD.json` | Permanent |
| Opportunity scores | `outputs/signals/scores-YYYY-MM-DD.json` | Permanent |
| CRM export | `outputs/crm_exports/` | Permanent |
| Slack summary | Your Slack channel | After each run |
| Downloadable artifacts | Actions tab → run → Artifacts | 7–90 days |

### Trigger manual research

1. **Actions** tab → **"Manual Company Research"** → **"Run workflow"**
2. Enter the `company_id` and depth (`quick` / `standard` / `deep`)
3. Research bundle is saved as a GitHub Artifact

---

## API Keys & Optional Integrations

All keys are optional. Copy `.env.example` to `.env` and fill in what you have:

| Key | What it unlocks | Cost |
|-----|----------------|------|
| `GITHUB_TOKEN` | 5,000 req/hr GitHub API (vs 60 unauthenticated) | Free |
| `SLACK_WEBHOOK_URL` | Slack notifications after every scan | Free |
| `HUNTER_API_KEY` | Email lookup for contacts | Free tier: 25/month |
| `APOLLO_API_KEY` | Richer contact enrichment | Paid |
| `CLAY_API_KEY` | Data enrichment | Paid |
| `HUBSPOT_API_KEY` | Live CRM sync (vs JSON file exports) | Paid |
| `SALESFORCE_*` | Live Salesforce sync | Paid |
| `PIPEDRIVE_API_KEY` | Live Pipedrive sync | Paid |
| `SMTP_*` | Email digest notifications | Free (Gmail app password) |

---

## Directory Structure

```
├── CLAUDE.md                    # WAT framework instructions for Claude
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
│
├── .github/workflows/
│   ├── daily_scan.yml           # Automated daily signal collection + Slack
│   ├── weekly_report.yml        # Weekly intelligence digest + Slack
│   └── manual_research.yml      # On-demand company research
│
├── tools/                       # 22 deterministic Python scripts
│   │
│   ├── — Data Collection —
│   ├── scrape_website.py        # Fetch + parse any URL to clean text
│   ├── fetch_rss_feeds.py       # Pull company blogs and RSS feeds
│   ├── search_news.py           # Google News RSS search
│   ├── monitor_careers_page.py  # Scrape careers pages + ATS boards
│   ├── fetch_job_listings.py    # Job board fallbacks
│   ├── search_github_activity.py # GitHub org signals (new repos, stars)
│   ├── fetch_tech_signals.py    # Tech stack detection from website headers
│   ├── check_product_hunt.py    # Product Hunt launches via RSS
│   │
│   ├── — Processing —
│   ├── research_company.py      # Orchestrate full research bundle
│   ├── normalize_signals.py     # Deduplicate + classify raw signals
│   ├── detect_changes.py        # Diff snapshots, emit change events
│   ├── store_snapshot.py        # Version-controlled page snapshots
│   ├── correlate_signals.py     # Find multi-signal patterns (hiring + funding)
│   ├── update_account_memory.py # Persistent per-company memory store
│   │
│   ├── — Scoring —
│   ├── score_opportunity.py     # ICP fit + signal strength scoring
│   ├── score_multi_factor.py    # Extended scoring with urgency + correlation boosts
│   │
│   ├── — Output Generation —
│   ├── generate_report.py       # Daily + weekly intelligence reports
│   ├── generate_executive_report.py # Executive-level summary report
│   ├── generate_playbook.py     # Deal playbook generation
│   ├── map_stakeholders.py      # Stakeholder mapping from public pages
│   ├── monitor_competitors.py   # Competitor monitoring
│   ├── export_crm.py            # HubSpot / Salesforce / Pipedrive exports
│   └── notify_slack.py          # Post report summaries to Slack
│
├── workflows/                   # 17 Markdown SOPs (Claude reads these)
│   ├── account_onboarding.md
│   ├── signal_collection.md
│   ├── signal_detection.md
│   ├── signal_correlation.md
│   ├── company_research.md
│   ├── opportunity_scoring.md
│   ├── account_memory.md
│   ├── stakeholder_mapping.md
│   ├── competitive_intelligence.md
│   ├── intelligence_brief_generation.md
│   ├── outreach_generation.md
│   ├── deal_playbook_generation.md
│   ├── crm_export_generation.md
│   ├── daily_reporting.md
│   ├── weekly_reporting.md
│   ├── executive_reporting.md
│   └── account_review.md
│
├── data/                        # Configuration — edit these
│   ├── companies.json           # Your target company list
│   ├── icp_criteria.json        # Ideal Customer Profile definition
│   ├── signal_weights.json      # Signal type scoring weights
│   ├── seller_profile.json      # Your value prop, case studies, CTAs
│   ├── tech_keywords.json       # Tech stack fingerprints (100+ techs)
│   ├── scoring_config.json      # Advanced scoring configuration
│   ├── signal_combinations.json # Signal correlation rules
│   ├── competitors.json         # Competitors to monitor
│   ├── playbook_templates.json  # Deal playbook templates
│   └── schema_registry.json     # Output schema definitions
│
└── outputs/                     # All generated outputs (committed by Actions)
    ├── signals/                 # Daily signal + score JSON files
    ├── briefs/                  # Per-company intelligence briefs
    ├── outreach/                # Outreach sequences
    ├── crm_exports/             # CRM-ready JSON payloads
    ├── reports/                 # Daily + weekly Markdown reports
    ├── snapshots/               # Page hashes for change detection
    ├── memory/                  # Persistent per-company memory
    ├── stakeholder_maps/        # Stakeholder maps per company
    ├── playbooks/               # Deal playbooks
    └── competitive/             # Competitor intelligence
```

---

## Free Data Sources Used

| Source | What it provides | Rate limit |
|--------|-----------------|-----------|
| Google News RSS | Company news mentions | None |
| Company RSS feeds | Blog posts, press releases | None |
| GitHub API (unauthenticated) | Org activity, new repos, stars | 60 req/hr |
| GitHub API (with token) | Same, higher limit | 5,000 req/hr |
| Product Hunt RSS | Product launches | None |
| Wikipedia REST API | Company background | None |
| Wayback Machine CDX | Historical snapshots | None |
| Greenhouse / Lever / Ashby | Job listings (public ATS boards) | None |
| Direct website scraping | About, careers, tech stack detection | Be respectful |

---

## Signals Detected and Scored

| Signal Type | Examples | Default Score |
|------------|---------|--------------|
| **Leadership change** | New CTO/VP Eng hired | 9.5 |
| **Hiring spike** | 10+ engineering roles open | 8.0 |
| **Funding event** | Series A/B/C announcement | 8.5–9.0 |
| **Tech adoption** | Migration to Snowflake/k8s | 8.0 |
| **Product launch** | New product, major release | 7.5 |
| **GitHub signal** | New public SDK, star spike | 5.0–6.0 |
| **Content signal** | Blog post about scaling | 3.0 |
| **News mention** | Press release, media coverage | 4.0–6.0 |
| **Product Hunt** | Featured launch | 7.5 |

Scores decay with age (7-day signals score at 100%, 90-day signals at 50%). Final opportunity score combines ICP fit (0–40 pts) + signal strength (0–45 pts) + timing bonus (0–15 pts).

---

## Known Limitations

- **News signal noise:** Generic company names like "Stripe" or "Linear" match unrelated articles. The scoring layer handles most of this, but for better precision you can customize the search query in `search_news.py` per company.
- **Careers scraper noise:** Modern React/Next.js career pages can return navigation items as fake job listings. For companies using Greenhouse or Lever, set `careers_url` to their ATS board URL (e.g. `https://boards.greenhouse.io/stripe`) for clean structured data.
- **Stakeholder mapping:** `map_stakeholders.py` extracts from public about/team pages only. LinkedIn data requires a paid API.
- **No Brotli support:** The scraper requests `gzip` encoding only. Sites that enforce Brotli-only will return an error; these are rare.

---

## Extending the System

The WAT architecture makes extensions additive — add a tool, reference it from a workflow.

| Extension | File | Status |
|-----------|------|--------|
| Slack notifications | `tools/notify_slack.py` | Built |
| Apollo contact enrichment | `tools/enrich_contact_apollo.py` | Add `APOLLO_API_KEY` |
| HubSpot live sync | `tools/sync_hubspot.py` | Add `HUBSPOT_API_KEY` |
| Salesforce live sync | `tools/sync_salesforce.py` | Add Salesforce OAuth creds |
| Email digest | `tools/send_email_digest.py` | Add SMTP credentials |

Tell Claude: *"Add an Apollo contact enrichment tool"* and it will build and wire it in.

---

## GitHub Actions Free Tier Budget

| Workflow | Runtime | Runs/month | Minutes used |
|----------|---------|-----------|-------------|
| Daily scan | ~10 min | 30 | 300 |
| Weekly report | ~5 min | 4 | 20 |
| Manual research | ~8 min | ~10 runs | 80 |
| **Total** | | | **~400 min** |
| **Free tier** | | | **2,000 min** |

Well within GitHub's free tier for both public and private repositories.

---

## License

MIT
