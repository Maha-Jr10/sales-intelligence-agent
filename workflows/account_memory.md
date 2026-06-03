# Workflow: Account Memory

## Objective
Maintain a persistent, accurate record of each account's relationship context, signal history, outreach history, and engagement state. Account memory prevents duplicate outreach, surfaces prior engagement context before new touches, and powers the executive report's KPI metrics.

## Memory File Location
`outputs/memory/{company_id}.json` — one file per company, atomic writes.

## Engagement Status Values
| Status | Meaning |
|--------|---------|
| `not_contacted` | Never reached out |
| `in_sequence` | Active outreach sequence running (do not start another) |
| `replied` | Received a reply (positive, negative, or neutral) |
| `meeting_booked` | Call or demo scheduled |
| `paused` | Intentionally paused — revisit later |
| `closed_won` | Became a customer |
| `closed_lost` | Opportunity ended |

## Agent Steps

### Before Any Outreach
**Always read memory first:**
```
python tools/update_account_memory.py --action read --company-id {id}
```

Check:
- `engagement_status`: If `in_sequence`, do NOT start a new sequence. Check the `open_outreach_sequence_id` and `last_outreach_date` to determine if the existing sequence should continue or if sufficient time has passed to consider it concluded.
- `known_contacts`: Are any contacts already in memory? Avoid contacting the same person twice with different angles in the same 30-day window.
- `signal_history`: What signals have been detected in the last 90 days? Has anything changed that makes this a better or worse time to reach out?
- `outreach_history`: How many touches have been attempted? What was the last message sent?

### After Sending Outreach Step 1
```
python tools/update_account_memory.py --action append-outreach \
    --company-id {id} \
    --sequence-id {sequence_id} \
    --step 1 \
    --date {today}
```

This automatically sets `engagement_status` to `in_sequence` and records `last_outreach_date`.

### After Each Subsequent Step
```
python tools/update_account_memory.py --action append-outreach \
    --company-id {id} \
    --sequence-id {sequence_id} \
    --step {2|3|4} \
    --date {date}
```

### After Receiving a Reply
```
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.engagement_status \
    --value replied
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.last_response_date \
    --value {date}
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.last_response_sentiment \
    --value "positive|neutral|negative|not_interested"
```

### After Booking a Meeting
```
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.engagement_status \
    --value meeting_booked
```

### Daily Automated Signal Append (GitHub Actions)
GitHub Actions `daily_scan.yml` runs this automatically after normalization:
```
python tools/update_account_memory.py --action append-signal \
    --all-companies \
    --signal-file outputs/signals/{today}.json
```

Signal history is maintained as a rolling 90-day window. Older signals are automatically purged on each write.

### Pausing an Account
When a rep indicates an account should not be contacted for a period:
```
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.engagement_status \
    --value paused
python tools/update_account_memory.py --action write \
    --company-id {id} \
    --field relationship_context.notes \
    --value "Paused until Q3 — rep has prior relationship, approaching separately"
```

### After Generating a Brief or Playbook
```
python tools/update_account_memory.py --action append-brief \
    --company-id {id} \
    --brief-id {brief_id_or_playbook_id}
```
Records that a brief or playbook was generated for this account. Called automatically by `deal_playbook_generation.md` after each playbook run.

### Resetting an Account (new contact, new outreach cycle)
After a full sequence completes with no reply:
```
python tools/update_account_memory.py --action reset --company-id {id}
```
This clears outreach history and resets `engagement_status` to `not_contacted`, while preserving `known_contacts`.

### Initializing Memory for a New Account
When a new company is added to `data/companies.json`:
```
python tools/update_account_memory.py --action init --company-id {id}
```
This is idempotent — if memory already exists, it does nothing.

## Atomic Write Behavior
All writes use the tmp→rename pattern:
```
{company_id}.json.tmp → {company_id}.json
```
If the process is interrupted during write, the `.tmp` file remains (no data corruption). Stale `.tmp` files can be safely deleted.

## Expected Outputs
- `outputs/memory/{company_id}.json` — per-company memory record
- No stdout output from memory operations beyond confirmation JSON

## Error Handling
- **Memory file missing on read**: Tool auto-initializes a blank memory record and returns it. No manual init needed.
- **`.tmp` file exists from a previous interrupted write**: Safe to delete. The main `.json` file is intact.
- **Concurrent writes in GitHub Actions**: The tmp→rename pattern is atomic at the OS level for single-file operations. Multiple parallel jobs writing to different company files are safe.
- **Rolling window purge removes too many signals**: If a company goes quiet for 90+ days, their signal history becomes empty. This is correct behavior — the memory reflects only recent context.

## Validation Checks
- [ ] Memory file exists for all active companies (check after first daily_scan.yml run)
- [ ] No `.tmp` files remain after writes complete
- [ ] `engagement_status` accurately reflects current state
- [ ] `signal_history` is within 90-day window (no entries older than `SIGNAL_HISTORY_MAX_DAYS`)

## Lessons Learned
_Updated by agent as patterns are discovered._

- Always read memory before any outreach decision. The most common error is starting a new sequence for an account that already has one running.
- `outreach_history` is append-only. Even if an outreach was unsuccessful, keep the record — it provides context for the next rep who works the account.
- `notes` field is free-text and agent-writable. Use it to record verbal context from reps that doesn't fit structured fields: "Rep knows the CTO from a prior company — approach differently."
- Memory files are committed to the repository by GitHub Actions. This means outreach history is version-controlled — you can see exactly when each touch was recorded.
