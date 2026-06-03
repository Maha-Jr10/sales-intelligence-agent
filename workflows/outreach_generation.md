# Workflow: Outreach Generation

## Objective
Generate a complete, personalized outreach sequence (cold email + LinkedIn + follow-ups) for a specific target account. Sequences must be signal-specific, direct, and under the word limits defined below.

**This is a pure agent reasoning task. No tools are required.**

## Required Inputs
- Intelligence brief (must be current — from `intelligence_brief_generation.md`, generated within 7 days)
- Target contact name and title (from brief or user-provided)
- `data/seller_profile.json` — your value proposition, case studies, CTAs

## Quality Bar
- **Email 1 opening sentence**: must hook in under 10 words AND reference a specific named signal
- **Max words per email**: 100 (cold), 40 (LinkedIn), 80 (follow-up), 45 (breakup)
- **Each step must add new information** — never send a "just bumping this" message
- **Banned words**: synergy, leverage, solution, world-class, best-in-class, cutting-edge, revolutionary, game-changing, holistic, robust, seamless, innovative, transformative
- **No phrases**: "I hope this email finds you well", "I wanted to reach out", "I came across your profile", "touching base"

## Agent Steps

### Step 1 — Select the Primary Outreach Angle
From the brief's `recommended_outreach_angles`, select the strongest angle. The strongest angle is the one that:
- Is most time-sensitive (leadership change > product launch > content signal)
- Is most specific to the contact's role (VP Eng cares about infrastructure, not sales signals)
- Creates natural urgency without manufacturing it

### Step 2 — Write Step 1 — Cold Email (Day 0)
**Structure:**
1. **Opening** (1 sentence, ≤10 words): Name the signal directly. No preamble.
2. **Connection** (1 sentence): One line connecting that signal to what you do. Be specific, not generic.
3. **Social proof** (1 sentence): One relevant example — a company, outcome, or insight. Do not list features.
4. **CTA** (1 sentence): Low-friction ask (15-min call, not "full demo"). Make it easy to say yes.

**Example structure:**
```
Saw the VP Engineering role go up — first exec engineering hire?

We work with CTOs at companies at exactly this inflection point, specifically the moment before a new VP arrives and inherits whatever's already in place.

[Company X] went through the same thing at 250 people — their CTO told me afterward the tool decisions made in that 60-day window shaped their infrastructure for 3 years.

Worth a 15-min call before your search wraps up?
```

### Step 3 — Write Step 2 — LinkedIn Message (Day 3)
If no reply to email.

**Rules:**
- 30-40 words maximum
- Conversational, not a pitch
- Reference the email without being passive-aggressive about it
- Add one new piece of information or question

**Example:**
```
Hi [Name] — sent a note about the VP Eng timing last week. Noticed you're also expanding the data team. Worth a quick chat? Happy to share what we've seen work at this scale.
```

If not yet connected on LinkedIn: send a connection request with a brief note first. No pitch in the connection request itself.

### Step 4 — Write Step 3 — Follow-Up Email (Day 7)
If no reply to email 1 or LinkedIn.

**Rules:**
- 70-80 words maximum
- Must add *new* information — a case study, a recent relevant event, an insight
- Do not recap the previous email
- New CTA (same or softer)

**Example structure:**
```
Subject: RE: [original subject line]

Hi [Name],

Circling back with something relevant: [Company X] just published a case study on how they handled exactly this transition at 300 people. [One specific finding from the case study].

Thought it might be useful regardless of timing: [link or offer to send it].

No pressure — happy to connect when the moment's right.

[Signature]
```

### Step 5 — Write Step 4 — Breakup Email (Day 21)
Final email. Graceful exit. Keep the door open permanently.

**Rules:**
- 40-50 words maximum
- No guilt, no passive aggression, no "I don't want to bother you anymore"
- Leave a clear invitation to reconnect
- Do not ask for a referral to someone else in this email

**Example:**
```
Hi [Name],

I'll stop following up — I know the VP Eng search keeps things packed right now.

If things shift later in the year, I'm at [email].

All the best,
[Signature]
```

### Step 6 — Write the JSON Sequence File
Write the complete sequence to `outputs/outreach/{company_id}/{today}.json`:
```json
{
  "sequence_id": "{company_id}-outreach-{today}",
  "company_id": "{company_id}",
  "generated_at": "{now}",
  "based_on_brief": "{brief_id}",
  "primary_angle": "{angle text}",
  "target_contact": {
    "name": "{name or placeholder}",
    "title": "{title}",
    "company": "{company_name}"
  },
  "sequence": [
    {
      "step": 1,
      "channel": "email",
      "send_timing": "Day 0",
      "subject": "...",
      "body": "...",
      "cta": "...",
      "word_count": N
    },
    {
      "step": 2,
      "channel": "linkedin",
      "send_timing": "Day 3 (if no reply to step 1)",
      "message": "...",
      "word_count": N
    },
    {
      "step": 3,
      "channel": "email",
      "send_timing": "Day 7 (if no reply)",
      "subject": "RE: {original subject}",
      "body": "...",
      "cta": "...",
      "word_count": N
    },
    {
      "step": 4,
      "channel": "email",
      "send_timing": "Day 21 (breakup)",
      "subject": "Closing the loop — {company_name}",
      "body": "...",
      "cta": "none — leave door open",
      "word_count": N
    }
  ],
  "metadata": {
    "tone": "direct, peer-level, no fluff",
    "angle_confidence": 0.0,
    "signal_referenced": "{signal_type}:{signal_subtype}",
    "personalization_depth": "high/medium/low"
  }
}
```

### Step 7 — Self-Review
Before finalizing, verify:
- [ ] Email 1 opening is under 10 words
- [ ] Email 1 body is under 100 words
- [ ] LinkedIn is under 40 words
- [ ] Each step adds new information (emails 2 and 3 are not just reminders)
- [ ] No banned words
- [ ] Signal is named specifically (not "I noticed your company is growing")
- [ ] CTA is low-friction (15-min call, not "full demo" or "can we get on a call to discuss your needs?")
- [ ] Contact name placeholder is marked clearly if real name unknown

## Expected Outputs
- `outputs/outreach/{company_id}/{today}.json`

## Error Handling
- **Contact name unknown**: Use `[Contact Name]` placeholder. Note clearly that personalization is required before sending.
- **Seller profile not configured** (`data/seller_profile.json` has placeholder content): Stop. Ask the user to fill in the value proposition before generating outreach. Generic outreach is worse than no outreach.
- **Brief is older than 7 days**: Flag to the user. The primary angle may no longer be timely. Either update the research or generate with a note that timing verification is needed.
- **Multiple contacts identified in brief**: Generate one sequence targeting the highest-priority contact. Note the other contacts for follow-up or parallel sequencing.

## Validation Checks
- [ ] Sequence has all 4 steps
- [ ] Word counts are within limits
- [ ] JSON file written to correct path
- [ ] Brief reference is accurate (brief must exist at `based_on_brief` path)

## Lessons Learned
_Updated by agent as patterns are discovered._

- The most common mistake in AI-generated outreach is being too long. When in doubt, cut 30% of the words. Short, specific, and direct always wins.
- Leadership change signals have the shortest action window. Draft and send within 72 hours of detection, not at the end of the week.
- Case studies referenced in Step 3 must be real. Do not invent or generalize. If no case study exists, reference a relevant insight or published finding instead.
- The breakup email (Step 4) often generates more replies than Step 2 or 3. Keep it genuinely gracious.
