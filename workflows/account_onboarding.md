# Workflow: Account Onboarding

## Objective
Add a new target company to the monitoring system with correct configuration, establish baseline snapshots, and generate an initial intelligence brief.

## Required Inputs
- Company name
- Company domain (e.g. `acme.com`)
- Company website URL
- Optional: careers URL, blog RSS URL, GitHub org, LinkedIn URL
- Tier classification (A/B/C)
- Owner (sales rep email)

## Agent Steps

### Step 1 — Gather Basic Profile
Run a quick research sweep to get initial company data:
```
python tools/research_company.py --company-id {new_id} --depth quick --companies-file data/companies.json
```
If the company isn't in `data/companies.json` yet, create a minimal entry first with just `id`, `name`, `domain`, `website`, and `tier`.

### Step 2 — Detect Tech Stack
```
python tools/fetch_tech_signals.py --domain {domain} --company-id {new_id}
```
Note any technology signals relevant to your ICP (see `data/icp_criteria.json` `positive_tech_signals`).

### Step 3 — Establish Baseline Snapshots
Run careers monitoring to create the first snapshot (no changes will be detected on first run — this is expected):
```
python tools/monitor_careers_page.py --company-id {new_id} --companies-file data/companies.json
```
Note: first run always returns `"first_run": true` and `"change_detected": false`. All current jobs are recorded as the baseline.

### Step 4 — Assess ICP Fit
Read the research bundle from `.tmp/research_cache/{company_id}_{date}.json`.

Assess against `data/icp_criteria.json`:
- **Industry match**: is this company in an ideal or acceptable industry?
- **Employee count**: does it fall in the ideal range (50-500)?
- **Funding stage**: Series A/B/C are ideal
- **Tech signals**: are any positive tech signals present (Snowflake, Kubernetes, Datadog, etc.)?
- **Behavioral signals**: any hiring patterns or content that suggest buying intent?

Write a brief ICP assessment in plain language.

### Step 5 — Update companies.json
Add the complete entry to `data/companies.json`. Fill in all discovered fields:
- Set `careers_url` to the actual careers page URL or ATS board URL
- Set `blog_rss` if found (check `/blog/rss.xml`, `/feed`, `/blog/feed`)
- Set `github_org` if the company has a public GitHub organization
- Set `monitoring_config` flags appropriately (disable `check_github` if no org found)
- Set `icp_fit_score` based on your Step 4 assessment (0-100)
- Update `last_researched` to today's date

### Step 6 — Generate Initial Intelligence Brief
Follow `intelligence_brief_generation.md` workflow to produce the first brief. Even with limited data, write what you know and mark gaps explicitly (e.g., "tech stack: unknown from initial scan").

### Step 7 — Confirm Monitoring Is Active
Report back to the user:
- Company ID and name
- Tier assignment
- ICP fit assessment summary
- Number of jobs detected on baseline snapshot
- Technologies detected
- Any monitoring limitations (e.g., "careers page is JS-rendered — using Greenhouse board")
- Path to the initial brief

## Expected Outputs
- New or updated entry in `data/companies.json`
- Baseline snapshot in `outputs/snapshots/{company_id}_careers_{date}.json`
- Tech stack snapshot in `outputs/snapshots/{company_id}_tech_stack_{date}.json`
- Initial intelligence brief in `outputs/briefs/{company_id}/{date}.json` and `.md`

## Error Handling
- **Company website 404**: Ask the user to confirm the correct URL before proceeding. Do not guess.
- **Careers page not found**: Try common paths (`/careers`, `/jobs`, `/work-with-us`). If none work, set `check_careers: false` in monitoring config and note in the company record.
- **No blog/RSS found**: Check `/blog`, `/news`, `/feed`, `/rss`, `/blog/rss.xml`. If none found, set `blog_rss: null` and `check_blog: false`.
- **No GitHub org**: Set `check_github: false`. Don't try to guess the org slug.
- **Tech scan fails (403/JS-rendered)**: Note `tech_stack: "scan_blocked"` in the company record. Use job descriptions to infer tech stack instead.
- **Company has no online presence**: This is a data quality issue. Raise it with the user before adding to the system.

## Validation Checks
Before confirming onboarding is complete:
- [ ] Company appears in `data/companies.json` with all fields populated
- [ ] At least one monitoring source is enabled (`check_news` should always be true)
- [ ] Baseline snapshot exists in `outputs/snapshots/`
- [ ] Initial brief created or explicitly noted as pending

## Lessons Learned
_This section is updated by the agent when new constraints or behaviors are discovered._

- Greenhouse board slugs often differ from the company domain (e.g., Linear uses "linear" but their domain is linear.app)
- Some companies use Ashby for ATS — check jobs.ashbyhq.com/{company_slug} as a fallback
- Blog RSS paths vary widely; feedparser will handle both RSS 2.0 and Atom formats
- LinkedIn company page slugs sometimes include hyphens in place of spaces
