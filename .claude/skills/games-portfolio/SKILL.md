---
name: games-portfolio
description: >-
  Entry point for publisher portfolio questions on the Halcyon catalog.
  Frames the question, sets the decision tier, delegates the analysis to
  games-portfolio-performance and the review to games-portfolio-validator,
  loops on REVISE, and stops for human approval. Use for /games-portfolio
  and any "how is the catalog doing this month" question.
argument-hint: "[question] [--as-of YYYY-MM] [--plant-seed N]"
---

# Skill: Games Portfolio (orchestrator)

Runs in the main session: subagents cannot start other subagents, so the
delegation happens here.

## Steps
1. **Frame.** Restate the question, the decision it informs and the hypothesis
   in two lines. Default month: 2025-12 (the last month in the data). Then:
   `python -m portfolio_agent.run frame --question "<q>" --as-of <YYYY-MM>`
   Add `--plant-seed N` only when the person asks for a test run with planted
   problems; say so in the frame. Read `status.json`. Tiers:
   - routine: recurring monitoring
   - consequential: a decision, or more than $50k at stake
   - strategic: price, delist, sunset, invest or deal questions
2. **Strategic: stop.** Show the frame and ask the person to approve it. Run
   nothing until they do; record it with
   `python -m portfolio_agent.oversight approve-frame <run_dir> --by "<name>"`.
3. **Analyze.** Delegate to the `games-portfolio-performance` agent with the run
   folder. It returns when `claims.json` and `report_draft.md` are final. If the
   gate blocked, report the reason and stop.
4. **Validate.** Delegate to the `games-portfolio-validator` agent with the run
   folder only, not the analyst's summary.
5. **Act on the verdict** (`status.json`):
   - `revise`: send the findings to the analyst agent, then validate again.
   - `escalated_to_human`: two revisions failed. Show the findings and stop.
   - `blocked`: FAIL. Show the findings. Nothing is released.
   - `released`: routine PASS. Show the report.
   - `awaiting_approval`: PASS on a consequential or strategic run. Show the
     report, the verdict and what was not checked, and ask a named person to
     approve or reject:
     `python -m portfolio_agent.oversight approve <run_dir> --by "<name>"`
6. **Close.** Give the run folder path; `trace.jsonl` holds every step.

## Rules
- You never change numbers or verdicts. You route and show.
- Never present a draft as final before its verdict.
- A person, not the agent, approves anything above routine.
- Questions about one title's retention, pricing tests or forecasts are out of
  scope: say so and stop.
