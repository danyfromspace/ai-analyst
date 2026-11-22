# Quickstart

How to get the Games Portfolio Agent running and what to ask it. About 10 minutes.

All data here is **Halcyon**, a fictional publisher. It is AI-generated and fake, and exists only to
evaluate the agent (see the [README](README.md#the-data)).

## 1. What you need

- **Python 3.11 or newer.** Check with `python --version`.
- **Git**, or download the code as a ZIP (step 2).
- **Claude Code**, for the agent itself ([docs](https://docs.claude.com/en/docs/claude-code/overview)).
  You can run and check the whole pipeline without it (step 5).

## 2. Get the code

With Git:
```powershell
git clone -b portfolio-agent https://github.com/danyfromspace/ai-analyst.git games-portfolio-agent
cd games-portfolio-agent
```

Without Git: open https://github.com/danyfromspace/ai-analyst/tree/portfolio-agent, choose
**Code > Download ZIP**, unzip it, and open a terminal in the unzipped folder.

Check that you're in the right folder; you should see `README.md`, `requirements.txt` and `portfolio_agent`:
```powershell
dir            # Windows
ls             # macOS / Linux
```

## 3. Set up Python

Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Check it works

```powershell
python -m pytest
```
Expect `72 passed`. If anything fails, stop here: the agent's numbers rely on these tests.

## 5. Run it without a model

The same pipeline the agent uses, run by hand. Good for reviewing the logic.

```powershell
# The data as delivered, for December 2025
python -m portfolio_agent.run all --question "Which titles need attention this month?" --as-of 2025-12

# The same month with known problems planted (answers in runs/<run_id>/truth.json)
python -m portfolio_agent.run all --question "Which titles need attention this month?" --as-of 2025-12 --plant-seed 1
```

Each command prints the run's status and a `run_dir`. Open `runs/<run_id>/report_draft.md` to read the
result. Approve or reject a run that is waiting for a person:
```powershell
python -m portfolio_agent.oversight status  runs/<run_id>
python -m portfolio_agent.oversight approve runs/<run_id> --by "Your Name"
python -m portfolio_agent.oversight reject  runs/<run_id> --by "Your Name" --note "why"
```

## 6. Run the agent in Claude Code

Start Claude Code **from the repo folder**, so it loads the agents and skills in `.claude/`:
```powershell
claude
```
Then type the questions below at the **Claude Code prompt**, not in PowerShell. Claude Code asks permission
the first time it runs `python -m portfolio_agent.run`; allow it. Type `/clear` between questions.

### What to ask, and what should happen

| Ask | What should happen |
|---|---|
| `/games-portfolio Which titles need attention this month? --as-of 2025-12 --plant-seed 1` | Frames the question, sends the run to the analyst agent, then the validator agent. Compare its top incidents with `truth.json` in the run folder. Validator PASS. Enough is at stake that it **stops and asks you to approve**. |
| `/games-portfolio Which titles need attention this month? --as-of 2025-12` | The data as delivered. Each exception comes with a hypothesis and the check that would confirm it. |
| `/games-portfolio Should we delist Wildspire on Steam?` | Strategic question. **Stops before reading any data** and asks you to approve the frame. |
| `/games-portfolio Which titles need attention? --as-of 2026-03` | The data ends at 2025-12, so the data gate blocks the run. It says why, with no numbers. |
| `/games-portfolio How complete is this list? Could we be missing a price error?` | Explains the detection limit: on monthly data a large move on one listing can look like a promotion (see `docs/eval_results.md`). |
| `/games-portfolio What's the year-one retention curve for Cindervale?` | Out of scope; says so and stops. |

Other questions in the same shape work too, for example a different month (`--as-of 2024-07`) or another
seed (`--plant-seed 5`). The full list of agent test cases is in `evals/agent_cases.yaml`.

### Things to look for
- Every number in the answer appears in the run's `claims.json` and passed the validator.
- Movements are written as hypotheses with checks ("likely", "to check"), never as causes.
- A FAIL from the validator is never shown as a final answer.
- Every run folder has a `trace.jsonl` with one line per step.

## 7. Re-run the evaluation (optional)

```powershell
python -m portfolio_agent.evals --seeds 40 --out docs
```
About 3 minutes. Writes `docs/eval_results.md` and `docs/eval_results.json`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `'/games-portfolio' is not recognized as the name of a cmdlet` | You typed it in PowerShell. Run `claude` first, then type it at the Claude Code prompt. |
| `/games-portfolio` doesn't appear in Claude Code | Start `claude` from the repo folder. Check `.claude/skills` exists (`dir -Force .claude\skills` on Windows); unzip tools sometimes skip hidden folders. |
| `Could not open requirements file` | You're not in the repo folder. `cd` into the folder that contains `requirements.txt`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again. |
| `ModuleNotFoundError: No module named 'portfolio_agent'` | Run commands from the repo folder (the one with `portfolio_agent/` in it). |
| `python` not found on macOS / Linux | Use `python3`. |
