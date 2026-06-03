# Workflow: Signal Collection

## Objective
Gather all raw signals for every active company in `data/companies.json` for today's monitoring cycle. This workflow is the first phase of the daily scan. It produces raw data that `signal_detection.md` will process.

## Required Inputs
- `data/companies.json` — the active company list
- Date (defaults to today)
- Optional: `GITHUB_TOKEN` environment variable for higher GitHub API rate limits

## Agent Steps

### Step 1 — Read Active Company List
Load `data/companies.json` and identify all companies with at least one monitoring source enabled. Log the count: "Monitoring N companies."

### Step 2 — Fetch RSS Feeds
For all companies with `check_blog: true` and a non-null `blog_rss` URL:
```
python tools/fetch_rss_feeds.py --companies-file data/companies.json \
                                  --output-dir .tmp/raw_signals/ \
                                  --max-age-days 2
```
This fetches only items from the last 2 days to minimize noise on daily runs. On the first run of the week, consider `--max-age-days 7`.

### Step 3 — Search News
For all companies with `check_news: true`:
```
python tools/search_news.py --companies-file data/companies.json \
                              --output-dir .tmp/raw_signals/ \
                              --max-age-days 2
```
Space requests 2 seconds apart (handled internally by the tool). Log any companies where news search returns 0 results for 3+ consecutive runs — their name search query may need adjustment.

### Step 4 — Monitor Careers Pages
For all companies with `check_careers: true`:
```
python tools/monitor_careers_page.py --companies-file data/companies.json \
                                       --output-dir .tmp/raw_signals/ \
                                       --snapshots-dir outputs/snapshots/
```
This tool creates new snapshots and compares against the previous run. `change_detected: false` is normal for most days — it means no new jobs posted. Log which companies showed changes.

### Step 5 — Fetch GitHub Activity
For all companies with `check_github: true` and a non-null `github_org`:
```
python tools/search_github_activity.py --companies-file data/companies.json \
                                         --output-dir .tmp/raw_signals/
```
Pass `GITHUB_TOKEN` via environment if available. Without a token, the rate limit is 60 requests/hour — sufficient for up to ~20 companies per run.

### Step 6 — Check Product Hunt
For all companies with `check_product_hunt: true`:
```
python tools/check_product_hunt.py --companies-file data/companies.json \
                                     --output-dir .tmp/raw_signals/ \
                                     --max-age-days 7
```
This is optional per company — most companies don't launch on PH frequently enough to warrant daily checks. Use a 7-day window to catch any launches.

### Step 7 — Summarize Collection
After all sources complete, report:
- Number of raw files created in `.tmp/raw_signals/`
- Total raw items collected (estimate from file sizes)
- Any sources that failed (continue to `signal_detection.md` regardless)
- Execution time

Pass control to `signal_detection.md`.

## Expected Outputs
Per-company JSON files in `.tmp/raw_signals/`:
- `rss_{company_id}_{date}.json`
- `news_{company_id}_{date}.json`
- `careers_{company_id}_{date}.json`
- `github_{company_id}_{date}.json` (if applicable)
- `ph_{company_id}_{date}.json` (if applicable)

## Error Handling
- **Single source fails for a company**: Log the error, continue with other sources and other companies. Do not abort the entire collection.
- **All sources fail for a company**: Log as a monitoring failure. Check if the company's website is still accessible.
- **Network unavailable**: Retry 3x with 30-second exponential backoff. After 3 failures, abort collection for that source and report.
- **GitHub rate limit hit**: Stop GitHub collection for this run. The remaining API requests will be available in the next run.
- **Careers page 403**: The site is blocking scrapers. Try at a different time, or set `check_careers: false` and configure the Greenhouse/Lever public board URL in `careers_url`.

## Rate Limiting Guidelines
- Google News RSS: no limit, but add 2-second delay between queries
- GitHub API unauth: 60 req/hr. With token: 5000 req/hr
- Indeed: may block — always have DuckDuckGo fallback
- Product Hunt RSS: no limit

## Validation Checks
Before proceeding to `signal_detection.md`:
- [ ] At least one raw signal file exists in `.tmp/raw_signals/`
- [ ] No catastrophic errors that would make signal quality unreliable
- [ ] Careers snapshots created for all companies with `check_careers: true`

## Lessons Learned
_Updated by agent when new patterns are discovered._

- Some careers pages load jobs via JavaScript (Angular/React SPAs) — the HTML scraper returns no jobs. Use Greenhouse/Lever board URLs for these companies.
- Google News RSS returns many false positives when the company name is a common English word (e.g. "Linear", "Stripe"). Scoring and normalization filter most noise, but consider appending the company's category to the query (e.g. "Linear project management software") in search_news.py for better precision.
- GitHub rate limits reset every hour. If running >20 companies, stagger GitHub checks across multiple runs or use a personal access token.
- The HTML heuristic job scraper picks up navigation menu items as "jobs" on modern React/Next.js career pages. All items will have `source: "html_heuristic"` and blank `location`/`department` fields. For companies like Stripe that use Greenhouse, set `careers_url` to their Greenhouse board (e.g. `https://stripe.com/jobs#openings`) for cleaner results.
- `generate_report.py` expects signals at `outputs/signals/{date}.json` OR `outputs/signals/signals_{date}.json` and scores at `outputs/signals/scores-{date}.json`. Run `score_opportunity --all-companies` and save output as the scores file before generating the report.
- On Windows, pip may install to a different Python than the system default. Run `python -m pip install -r requirements.txt` (not just `pip install`) to ensure packages land in the correct environment.
- GitHub per-company output files store detected signals under the key `signals_detected`, not `items` or `signals`. The `normalize_signals.py` tool handles this — if GitHub signals aren't appearing, verify `signals_detected` is in the `collect_raw_from_dir` field list.
- When adding companies with generic/common names (Ramp, Stripe, Linear), Google News RSS picks up unrelated articles using those words. The scoring layer attenuates most noise, but signal quality improves significantly if you narrow the query in `search_news.py` to include the company's category (e.g. "Ramp corporate cards fintech").
- Verify GitHub org slugs before onboarding: `ramp-finance` is not Ramp's real GitHub org (they don't have a prominent public one). Always confirm via `github.com/{slug}` before setting `github_org` in companies.json.
