# Games Portfolio Agent: house rules

This repo is a Claude Code agent that monitors a premium game catalog month by month. The data is
Halcyon, a fictional publisher: AI-generated, fake, and used only for evaluation.

1. Start portfolio questions with `/games-portfolio <question>`. It frames, gates the data, delegates to
   the analyst agent, has the validator check the result, and stops for human approval when required.
2. Every number comes from `python -m portfolio_agent.run ...` outputs. Never compute a figure by hand.
3. Monitoring shows where revenue moved. Name hypotheses and the checks that would confirm them; never
   state a cause.
4. A strategic question (price, delist, sunset, invest, deal) needs a person to approve the frame before
   any analysis.
5. Only the orchestrator delegates. The validator never edits claims.
6. Read and write files with UTF-8. Run `python -m pytest` after any change to `portfolio_agent/`.
