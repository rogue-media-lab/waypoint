# Waypoint vs CarUs — Tech Workflow Gap Analysis

*Audit date: 2026-07-07. Mason's demo to Mike N (Midas) is tomorrow 2026-07-08.*

## Waypoint (Discord) — The Target

Waypoint is the workflow Mason actually uses daily at Midas. It's command-driven, headset-friendly, and sub-second on every action.

```
@Waypoint record EXAMPLE000000VIN1          ← decode VIN (instant, NHTSA)
@Waypoint add job oil change                ← create open job (instant)
@Waypoint complete job 12 0.5               ← close with hours (instant)
@Waypoint how long radiator?                ← labor lookup (instant)
@Waypoint weekly                            ← hours summary (instant)
```

Key attributes:
- **Command-driven**: explicit verbs — record, add, complete, delete
- **Stateless**: no "conversation" to maintain. Each command is independent.
- **Open jobs = scratch pad**: create a job, it stays "active" until completed. Immutable after completion.
- **Instant**: NHTSA decode, SQLite writes, local DB — no cloud latency.
- **Voice/hands-free**: works through Discord on Mason's headset.

## CarUs (Web) — Current State

A conversation-driven web app. Every interaction goes through AI (OpenRouter, 30-80s latency).

```
Type VIN in compose bar → wait 30-80s → AI: "2014 Chevy Sonic, specs on file" → type service → wait 30-80s → AI: "1.5-2 hours" → click Log Complete
```

## What Works (verified 2026-07-07)

- Tech login: `<redacted@example.com>` / `<redacted>` (test credentials scrubbed pre-publication)
- VIN text intake → AI decodes, returns specs, links vehicle
- Follow-up chat → AI returns labor estimates
- Log Complete → creates service job with hours
- Vehicle Lookup → shows vehicles with year/make/model/engine
- Job detail view with Edit/Delete
- Labor procedure chips (7 chips on spec sheet)

## What's Broken (verified 2026-07-07)

| # | Issue | Details |
|---|-------|---------|
| 1 | **Photo upload button not functional** | Camera icon label exists on compose bar but is not clickable. VIN photo flow is inaccessible. |
| 2 | **Customer Lookup page empty** | `/carus/customer_lookups` loads blank — heading renders, no data. Zero car owners. |
| 3 | **Compose bar submission issues** | Enter key doesn't trigger submit in some browsers. Had to use JS `form.submit()`. |
| 4 | **Year/Make/Model dropdowns don't filter** | Populated from DB distinct values but no JS filter logic. Clicking a value does nothing. |

## What's Missing (vs Waypoint)

| # | Gap | Why It Matters |
|---|-----|----------------|
| 1 | **No open/active jobs** | Waypoint has active/pending state. CarUs collapses add+complete into "Log Complete". A tech doing an oil change wants to record it, work on it, then close it. |
| 2 | **No hours summary** | Waypoint: `weekly` shows hours per job + total. CarUs: jobs disappear into vehicle history. |
| 3 | **No quick labor lookup** | Waypoint: instant labor-lookup from CLI. CarUs: must start AI conversation (30-80s) or scroll 7 chips. |
| 4 | **No conversation delete/archive** | List grows forever. No filter for "last 7 days." |
| 5 | **Ambiguous single input** | One compose bar handles VIN + service + photo. Waypoint separates concerns with explicit commands. |
| 6 | **AI latency kills momentum** | Every interaction waits 30-80 seconds. A tech moving between bays can't wait. |

## The Core Problem

**CarUs forces conversation where Waypoint uses commands.** The AI should be behind the scenes — enriching data, suggesting labor times — not the primary interface. A tech doesn't want to chat. They want to:

1. Identify the car (VIN → specs)
2. Log what they did (description + hours)
3. See their week (hours summary)

## What Would Close the Gap

1. **Quick VIN intake** — dedicated VIN field with instant NHTSA decode + AI enrichment in background
2. **Active jobs list** — "My Jobs" tab showing open jobs with Complete button
3. **Hours summary** — "This week: 5 jobs, 12.3 hours"
4. **Labor lookup** — search field on Log Job form, type "radiator" → matching labor times, click to populate
5. **Fix photo button** — the VIN photo snap is the killer feature

## Demo Readiness (2026-07-08)

The conversation flow works for a demo if you:
- Use text VIN intake (not photo)
- Accept AI latency as "it's thinking about your car"
- Skip Customer Lookup (empty anyway)
- Focus on: type VIN → AI responds → ask about service → Log Complete → show job on vehicle

But the workflow is NOT daily-use ready. The latency alone makes it impractical for shop-floor use.