# Workflow: Company Research

## Objective
Build a comprehensive profile of a single company from all available public sources. This workflow produces the research bundle that `intelligence_brief_generation.md` uses to write the account intelligence brief.

## Required Inputs
- Company ID (must exist in `data/companies.json`)
- Research depth: `quick` (5 min), `standard` (15 min), `deep` (30 min)

## Research Depth Definitions
- **Quick**: Website scrape + news search. Used for initial onboarding or rapid assessments.
- **Standard**: All quick sources + careers, GitHub, RSS, tech stack, Wikipedia. Used for daily brief generation.
- **Deep**: All standard sources + individual page scrapes (About, Product, Pricing, Blog) + Wayback Machine + SEC EDGAR (public companies only). Used before first outreach or major account reviews.

## Agent Steps

### Step 1 — Run Research Orchestrator
```
python tools/research_company.py --company-id {company_id} --depth {depth}
```
This calls all enabled tools sequentially and writes the bundle to `.tmp/research_cache/{company_id}_{today}.json`.

Review `collection_errors` in the output. Any errors are noted but don't block the workflow.

### Step 2 — Read and Evaluate the Bundle
Open `.tmp/research_cache/{company_id}_{today}.json` and assess data quality:

**Company Profile** (`data.company_profile`)
- Does the `about_text` clearly describe what the company does?
- Is there pricing information? (Pricing language reveals business model and typical buyer)
- What product names or categories appear repeatedly?

**Recent News** (`data.recent_news`)
- Any funding announcements? Leadership changes? Product launches? Awards?
- Are any items older than 30 days? (Less relevant for outreach timing)
- Are all items actually about this company? (Filter out false positives)

**Job Listings** (`data.job_listings`)
- What departments are hiring most?
- Are there leadership roles open? (VP/Director/Head of = scaling signal)
- What technologies appear repeatedly in job descriptions?
- Total job count: what does this suggest about company size and growth rate?

**Tech Stack** (`data.tech_stack.detected`)
- What analytics tools? (Segment, Amplitude, Mixpanel = data-mature)
- What monitoring tools? (Datadog, New Relic = engineering-focused)
- What CRM/sales tools? (HubSpot, Salesforce = has sales infrastructure)
- What does the CDN suggest? (Cloudflare = security-conscious, AWS = cloud-native)

**GitHub Signals** (`data.github_signals`)
- New public repos in the last 14 days?
- SDK or API repos? (External developer platform signal)
- Primary programming languages? (Confirms tech stack)

**Wikipedia** (`data.wikipedia_summary`)
- Useful for founding date, historical funding, acquisitions
- Often lags behind current company state — treat as background context, not current intelligence

### Step 3 — Deep Research Extras (if depth == "deep")

Run individual page scrapes for the most signal-rich pages:
```
python tools/scrape_website.py --url https://{domain}/pricing --skip-robots
python tools/scrape_website.py --url https://{domain}/customers --skip-robots
python tools/scrape_website.py --url https://{domain}/blog --skip-robots
```

Check Wayback Machine for historical presence:
- When was the site first archived? (Confirms founding date)
- Any snapshot from 1 year ago? (Spot major website redesigns = new positioning)

Check SEC EDGAR (public companies only):
- Recent 10-K or 10-Q for revenue growth, headcount, technology mentions
- URL: `https://efts.sec.gov/LATEST/search-index?q={company_name}&dateRange=custom&startdt={1yr_ago}`

### Step 4 — Identify Data Gaps
Note explicitly what is unknown:
- "Email finding not attempted (no Hunter API key configured)"
- "LinkedIn profile scraping unavailable"
- "No blog RSS — using Google News only"
- "Tech stack scan blocked (403)"

Do not fabricate data to fill gaps. Mark unknown fields explicitly.

### Step 5 — Prepare Brief Inputs
Confirm the research bundle is ready for `intelligence_brief_generation.md`:
- [ ] Company basics (name, industry, size, location) confirmed
- [ ] At least one meaningful signal present (news, hiring, product, tech)
- [ ] Outreach angle hypothesis forming (even if not fully articulated yet)

## Expected Outputs
- Research bundle at `.tmp/research_cache/{company_id}_{date}.json`
- Optionally a tech stack snapshot at `outputs/snapshots/{company_id}_tech_stack_{date}.json`

## Error Handling
- **Website 404 / domain not resolving**: Update `data/companies.json` with the correct URL. Do not proceed without a valid website.
- **All news searches return 0 results**: Try alternate company name forms ("Acme" vs "Acme Corp" vs "Acme, Inc."). If still nothing, the company may have very low public presence — note this in the bundle.
- **GitHub org not found**: The org slug in `companies.json` may be wrong. Try searching `https://api.github.com/search/users?q={company_name}+type:org`.
- **Wikipedia returns summary for wrong company**: Use `data.wikipedia_summary: null` rather than including incorrect data.
- **Careers page returns 0 jobs (possible JS rendering)**: Check if the company uses Greenhouse/Lever/Ashby — try `boards.greenhouse.io/{company_domain_prefix}`.

## Validation Checks
- [ ] Research bundle file exists in `.tmp/research_cache/`
- [ ] `ready_for_brief: true` in bundle (at least some data collected)
- [ ] No field contains fabricated data
- [ ] Collection errors are noted (partial data is acceptable)

## Lessons Learned
_Updated by agent as patterns are discovered._

- Wikipedia summaries for B2B SaaS companies are often 2-3 years stale. Use for founding date only, not current metrics.
- Pricing pages are goldmines: they reveal ICP (who is targeted), business model (per seat vs. usage), and competitive positioning.
- A careers page showing 20+ open engineering roles at a 150-person company is a stronger hiring signal than raw job count — always cross-reference with estimated company size.
- "Customer" or "case study" pages reveal which industries the company already serves — useful for competitive intelligence and for finding warm introduction paths.
