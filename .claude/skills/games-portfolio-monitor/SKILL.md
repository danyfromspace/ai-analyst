---
name: games-portfolio-monitor
description: >-
  Monthly exceptions for a premium game catalog: which store listings moved
  against their expected month, ranked by dollars at stake, with a data gate
  first and hypotheses (never causes) for each move. Use for "which titles
  need attention", "what moved this month", "why is the catalog down". Not
  for checking someone's numbers (games-portfolio-validation).
---

# Skill: Games Portfolio Monitor

## Purpose
Tell a publisher which titles moved this month, by how many dollars, and what
to check first. The code computes every number; this skill says how to run it,
read it and write it up so the validator can check it.

## Definitions (print them in every output)
| Setting | Value |
|---|---|
| Data | Halcyon (`data/halcyon/`): AI-generated evaluation data, not a real company |
| Metric | `halcyon_net_usd`: net revenue in USD as delivered |
| Period | calendar month as delivered (the source states no timezone) |
| Grain | store listing = one title on one storefront (steam, playstation, nintendo) |
| Expected month | median of the listing's 6 previous months, moved by the median change of its storefront peers that month |
| Flag | robust z >= 3.5 against the listing's last 24 months **and** \|dollars\| >= $1,000 |
| Title-wide move | 2+ listings flagged and every other listing of the title moving the same way at \|z\| >= 2 |
| Not monitored | listings under 12 months old, a gap in the 6 months before, listings the gate excluded |

## Procedure
1. **Run the step.** The orchestrator gives you a run folder.
   `python -m portfolio_agent.run analyze <run_dir>`
   It runs the data gate and the monitor and drafts `claims.json` and
   `report_draft.md`.
2. **Read the gate first** (`gate.json`).
   - BLOCK: stop. Report what is broken and what would unblock it. No numbers.
   - Duplicate row: removed; any claim on that listing keeps its data-issue note.
   - Missing row: the listing is not monitored this month. Say so; never call it a drop.
   - Negative net: kept and flagged; it is often a refund or chargeback clawback.
3. **Read the incidents** (`exceptions.json`), largest dollars first: listings,
   storefronts, the storefront factor this month, hypotheses and checks.
4. **Edit wording only.** You may rewrite a claim's `text` for clarity. Keep its
   `value`, `filters` and labels unchanged, keep the dollar figure in the
   sentence equal to `value`, and keep the hypothesis and its check. Add no
   number that is not in a claim.
5. **Language.** Monitoring data shows where revenue moved. Write "likely",
   "consistent with", "to check". Never "caused", "due to", "because",
   "drove", "proves".
6. **Know the limit.** On monthly data a 2x-3x move on one listing is often a
   promotion; the monitor catches about 4 in 10 of those (docs/eval_results.md).
   Outages and clawbacks are caught almost every time. Say this when asked how
   complete the list is.

## Output
1. Definition block (table above).
2. Gate status and every issue with its action.
3. Ranked incidents: title, storefronts, dollars vs expected, first hypothesis,
   its check.
4. What was not monitored and why.
5. Stop when `claims.json` and `report_draft.md` are final. The validator checks
   them next; you do not grade your own work.
