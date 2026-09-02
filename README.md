# Northline CX loss-pattern take-home

A 30-45 minute writeup exercise. The candidate reads support-agent traces plus one customer note, then names loss patterns a modeling team can actually hook.

This is a curriculum artifact for practicing the FDE / post-training hire bar. It is also usable as a take-home as-is.

## What you are scoring

Not "the model needs more RLHF." You are scoring whether the candidate can read traces, hear the customer, and separate **data mix / SFT**, **preference data**, **judge**, **harness**, and **RL**.

## Candidate flow (give them `packet/` only)

1. Read [`packet/BRIEF.md`](packet/BRIEF.md).
2. Skim [`packet/schema/tools.md`](packet/schema/tools.md) so tool names and required args are known.
3. Read [`packet/customer_note.md`](packet/customer_note.md). It is messy on purpose.
4. Open the 20 ATIF trajectories in [`packet/traces/`](packet/traces/). One JSON file per session. No gold labels in those files.
5. Write the four deliverables in the brief. Aim for 30-45 minutes, 1-2 pages.

Do not give the candidate `rubric/`.

## Interviewer only

[`rubric/`](rubric/) stays off the candidate packet.

- [`rubric/ANSWER_KEY.md`](rubric/ANSWER_KEY.md): gold clusters, customer-to-mode map, example loss patterns, what a strong candidate refuses to do first.
- [`rubric/SCORECARD.md`](rubric/SCORECARD.md): four axes, 1-4 each.

## ATIF

Traces are [Agent Trajectory Interchange Format](https://www.harborframework.com/docs/agents/trajectory-format) `ATIF-v1.7`. Read `steps[].source`, `tool_calls`, and `observation.results`. Root `extra.ticket_status` is ops metadata from the ticketing system, not a gold failure tag.

## Start here

`packet/BRIEF.md`
