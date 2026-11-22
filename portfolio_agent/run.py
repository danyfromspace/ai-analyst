"""Portfolio run: frame -> data gate -> monitor -> claims -> validation -> oversight.

  python -m portfolio_agent.run frame    --question "Which titles need attention this month?" --as-of 2025-12
  python -m portfolio_agent.run analyze  runs/<run_id>
  python -m portfolio_agent.run validate runs/<run_id>
  python -m portfolio_agent.run all      --question "..." --as-of 2025-12 [--plant-seed 7]

--plant-seed N copies the data into the run folder with four business anomalies and two data issues
planted in the as-of month (truth.json is written next to it). Without it the run uses the data as
delivered. Every step reads and writes files in the run folder: frame.json, monthly.csv (planted runs),
truth.json (planted runs), gate.json, exceptions.json, claims.json, report_draft.md, validation.json,
status.json, trace.jsonl.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from portfolio_agent import data, oversight, portfolio, validation

RUNS = Path("runs")


def _write(run_dir: Path, name: str, obj) -> Path:
    p = run_dir / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str), encoding="utf-8")
    return p


def _paths(run_dir: Path, fr: dict) -> tuple[Path, Path]:
    monthly = run_dir / "monthly.csv" if fr.get("planted") else Path(fr["data_dir"]) / data.FILES["monthly"]
    return monthly, Path(fr["data_dir"]) / data.FILES["catalog"]


def frame(question: str, as_of: str, data_dir=data.DATA_DIR, runs: Path = RUNS,
          plant_seed: int | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40]
    run_dir = Path(runs) / f"{stamp}_{slug}"
    k = 1
    while run_dir.exists():
        k += 1
        run_dir = Path(runs) / f"{stamp}_{slug}_{k}"
    run_dir.mkdir(parents=True)
    tier = oversight.classify(question)
    fr = {"question": question, "as_of": as_of, "data_dir": str(data_dir), "tier": tier,
          "planted": plant_seed is not None, "plant_seed": plant_seed,
          "hypothesis": "most listings sit inside their expected band; a few move by more than noise",
          "metric": portfolio.METRIC, "period": portfolio.PERIOD, "revenue_scope": portfolio.REVENUE_SCOPE}
    if plant_seed is not None:
        h = data.load(data_dir)
        planted, truth = data.plant(h.monthly, h.catalog, as_of, plant_seed)
        data.write_monthly(planted, run_dir / "monthly.csv")
        _write(run_dir, "truth.json", truth)
    _write(run_dir, "frame.json", fr)
    oversight.log(run_dir, "framed", tier=tier, question=question, planted=fr["planted"])
    oversight.write_status(run_dir, {"state": "awaiting_frame_approval" if tier == "strategic" else "ready_to_analyze",
                                     "tier": tier, "frame_approved": tier != "strategic", "revisions": 0,
                                     "verdict": None})
    return run_dir


def analyze(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    st = oversight.read_status(run_dir)
    if st.get("state") == "awaiting_frame_approval":
        raise PermissionError("strategic question: a person must approve the frame first "
                              "(python -m portfolio_agent.oversight approve-frame <run_dir> --by NAME)")
    fr = json.loads((run_dir / "frame.json").read_text(encoding="utf-8"))
    h = data.load(fr["data_dir"])
    monthly_path, _ = _paths(run_dir, fr)
    monthly = data.truncate(data.load_monthly(monthly_path), fr["as_of"])
    gate = portfolio.data_gate(monthly, h.catalog, fr["as_of"])
    _write(run_dir, "gate.json", gate.to_dict())
    oversight.log(run_dir, "data_gate", status=gate.status, issues=len(gate.issues))
    if gate.status == "BLOCK":
        st.update(state="blocked_by_data", reason=[i.detail for i in gate.issues if i.severity == "block"])
        return oversight.write_status(run_dir, st)
    rep = portfolio.monthly_exceptions(gate.clean, h.catalog, fr["as_of"], gate.excluded, gate.annotated)
    _write(run_dir, "exceptions.json", rep)
    claims = portfolio.draft_claims(rep, gate)
    _write(run_dir, "claims.json", claims)
    _write(run_dir, "report_draft.md", portfolio.render_report(fr["question"], gate, rep, claims))
    at_stake = sum(abs(i["delta_usd"]) for i in rep["incidents"])
    tier = oversight.classify(fr["question"], at_stake)
    oversight.log(run_dir, "analyzed", incidents=len(rep["incidents"]), claims=len(claims),
                  dollars_at_stake=round(at_stake, 2), tier=tier)
    st.update(state="awaiting_validation", tier=tier, dollars_at_stake=round(at_stake, 2))
    return oversight.write_status(run_dir, st)


def validate(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    fr = json.loads((run_dir / "frame.json").read_text(encoding="utf-8"))
    claims = json.loads((run_dir / "claims.json").read_text(encoding="utf-8"))
    monthly_path, catalog_path = _paths(run_dir, fr)
    res = validation.validate(claims, monthly_path, catalog_path)
    _write(run_dir, "validation.json", res)
    st = oversight.read_status(run_dir)
    revisions = st.get("revisions", 0) + (1 if res["verdict"] == "REVISE" else 0)
    state = oversight.next_state(st.get("tier", "routine"), res["verdict"], revisions, st.get("frame_approved", True))
    st.update(verdict=res["verdict"], revisions=revisions, state=state, claims_hash=res["claims_hash"])
    oversight.log(run_dir, "validated", verdict=res["verdict"], findings=len(res["findings"]),
                  claims_hash=res["claims_hash"], state=state)
    return oversight.write_status(run_dir, st)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Portfolio run steps")
    ap.add_argument("step", choices=["frame", "analyze", "validate", "all"])
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--question")
    ap.add_argument("--as-of", default="2025-12")
    ap.add_argument("--data", default=str(data.DATA_DIR))
    ap.add_argument("--runs", default=str(RUNS))
    ap.add_argument("--plant-seed", type=int)
    a = ap.parse_args(argv)
    if a.step in ("frame", "all"):
        if not a.question:
            ap.error("--question is required")
        rd = frame(a.question, a.as_of, a.data, Path(a.runs), a.plant_seed)
        print(f"run_dir: {rd}")
        if a.step == "frame":
            print(json.dumps(oversight.read_status(rd), indent=2))
            return
    else:
        rd = Path(a.run_dir)
    if a.step in ("analyze", "all"):
        if oversight.read_status(rd).get("state") == "awaiting_frame_approval":
            print("Strategic question: a person must approve the frame before any analysis.\n"
                  f"  python -m portfolio_agent.oversight approve-frame {rd} --by \"Your Name\"\n"
                  f"  python -m portfolio_agent.run analyze {rd}")
            print(json.dumps(oversight.read_status(rd), indent=2))
            return
        st = analyze(rd)
        if a.step == "analyze" or st["state"] != "awaiting_validation":
            print(json.dumps(st, indent=2))
            return
    print(json.dumps(validate(rd), indent=2))


if __name__ == "__main__":
    main()
