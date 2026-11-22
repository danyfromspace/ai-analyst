---
name: games-portfolio-validation
description: >-
  Independent review of portfolio claims: re-derive every number from raw
  rows by a separate implementation, check labels, the expected-month
  definition, data-issue leaks and causal wording, and return PASS, REVISE
  or FAIL with exact fixes. Use after a portfolio analysis is drafted and
  before anyone sees it, or for "check these numbers". Not for producing an
  analysis (games-portfolio-monitor).
---

# Skill: Games Portfolio Validation

## Purpose
A second reviewer that did not write the analysis decides whether the claims can
go to a person, and if not, exactly what to fix.

## Independence
- Read `claims.json` and the raw data only. Do not read `exceptions.json`,
  `report_draft.md` or the analyst's messages before you have your own numbers.
- The re-derivation in `portfolio_agent/validation.py` uses only the Python
  standard library and does not import the monitor: a second implementation of
  the written definition.
- You cannot edit claims. You report; the analyst fixes.

## Procedure
1. `python -m portfolio_agent.run validate <run_dir>`
   Writes `validation.json` and moves the run to its next state.
2. Read the re-derivation table: claim id, claimed, re-derived, status.
3. Read each finding:

| Check | What it catches | Severity |
|---|---|---|
| rederive | value differs from the re-derived value by > 0.5% and > $1 | blocking |
| text_matches | the dollar figure in the sentence is not the claim value | blocking |
| scope_exists | month or listing not in the data | blocking |
| data_issue_leak | a listing with a data issue this month reported as performance, no note | blocking |
| labels | metric, period or revenue scope missing or wrong | major |
| expected_definition | a delta claim uses another expected-month definition | major |
| causal_language | "caused", "due to", "because", "drove", "proves" | major |
| hypothesis_check | a move with no hypothesis or check named | minor |

4. Then judge what code cannot: is the first hypothesis the most plausible given
   the storefronts, the negative-net flag and the storefront factor? Record these
   as minor notes; they do not change the verdict.

## Output
- Verdict: PASS, REVISE or FAIL.
- The re-derivation table.
- Each finding: claim id, check, severity, the exact fix.
- What was not checked (from `validation.json`, plus anything you skipped).

## Verdict rules (enforced in code)
- Any blocking finding: FAIL. Blocked; cannot be approved.
- Any major finding: REVISE. Back to the analyst; after 2 revisions a person decides.
- Otherwise PASS. Routine runs release; consequential and strategic runs wait for a
  named person's approval.
