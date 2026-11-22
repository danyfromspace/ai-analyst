"""Human oversight for portfolio runs: decision tiers, the approval gate and the run log.

Rules enforced in code (tests in tests/test_oversight.py):
- Every run gets a tier before analysis:
    routine        recurring monitoring ("what moved this week")
    consequential  a total at stake above CONSEQUENTIAL_USD, or a question about a specific decision
    strategic      price, delist/sunset, invest or deal questions
- Strategic questions stop after framing: a person approves the frame before analysis runs.
- Nothing is released without a validator verdict. FAIL is never releasable. REVISE goes back to the
  analyst; after MAX_REVISIONS it escalates to a person instead of looping.
- PASS + routine may release automatically (logged). PASS + consequential or strategic needs a named
  person's approval.
- Every step appends to runs/<run_id>/trace.jsonl with a UTC timestamp.

CLI:
  python -m portfolio_agent.oversight status  <run_dir>
  python -m portfolio_agent.oversight approve <run_dir> --by "Name" [--note "..."]
  python -m portfolio_agent.oversight reject  <run_dir> --by "Name" --note "why"
  python -m portfolio_agent.oversight approve-frame <run_dir> --by "Name"
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CONSEQUENTIAL_USD = 50_000
MAX_REVISIONS = 2
STRATEGIC = re.compile(
    r"\b(delist|sunset|invest|greenlight|discontinu|kill)\w*|\bdeals?\b"          # portfolio decisions
    r"|\b(what|which|set|change|raise|lower|cut)\b[^.?]*\bpric(e|es|ing)\b"       # choosing a price
    r"|\bpric(e|es|ing)\b[^.?]*\b(drop|cut|raise|change|move)\b",
    re.I)
CONSEQUENTIAL = re.compile(r"\b(should we|decide|decision|budget|forecast|recommend)\b", re.I)


def classify(question: str, dollars_at_stake: float = 0.0) -> str:
    if STRATEGIC.search(question):
        return "strategic"
    if CONSEQUENTIAL.search(question) or abs(dollars_at_stake) >= CONSEQUENTIAL_USD:
        return "consequential"
    return "routine"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(run_dir: Path, event: str, **data) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    rec = {"ts": _now(), "event": event, **data}
    with open(run_dir / "trace.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def read_status(run_dir: Path) -> dict:
    p = Path(run_dir) / "status.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_status(run_dir: Path, status: dict) -> dict:
    (Path(run_dir) / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def next_state(tier: str, verdict: str | None, revisions: int, frame_approved: bool) -> str:
    """The release decision as a pure function of the run's facts."""
    if tier == "strategic" and not frame_approved:
        return "awaiting_frame_approval"
    if verdict is None:
        return "awaiting_validation"
    if verdict == "FAIL":
        return "blocked"
    if verdict == "REVISE":
        return "escalated_to_human" if revisions >= MAX_REVISIONS else "revise"
    if verdict == "PASS":
        return "released" if tier == "routine" else "awaiting_approval"
    raise ValueError(f"unknown verdict {verdict!r}")


def can_release(status: dict) -> bool:
    return status.get("state") == "released" or (
        status.get("state") == "awaiting_approval" and status.get("verdict") == "PASS"
        and bool(status.get("approved_by")))


def approve(run_dir: Path, by: str, note: str = "") -> dict:
    st = read_status(run_dir)
    if st.get("state") != "awaiting_approval":
        raise PermissionError(f"cannot approve a run in state {st.get('state')!r}")
    if st.get("verdict") != "PASS":
        raise PermissionError("only a PASS verdict can be approved")
    if not by.strip():
        raise PermissionError("approval needs a named person")
    st.update(state="released", approved_by=by, approved_at=_now(), approval_note=note)
    log(Path(run_dir), "human_approval", by=by, note=note)
    return write_status(run_dir, st)


def reject(run_dir: Path, by: str, note: str) -> dict:
    st = read_status(run_dir)
    st.update(state="rejected", rejected_by=by, rejected_at=_now(), rejection_note=note)
    log(Path(run_dir), "human_rejection", by=by, note=note)
    return write_status(run_dir, st)


def approve_frame(run_dir: Path, by: str) -> dict:
    st = read_status(run_dir)
    if st.get("state") != "awaiting_frame_approval":
        raise PermissionError(f"no frame waiting for approval (state {st.get('state')!r})")
    st.update(frame_approved=True, frame_approved_by=by, state="ready_to_analyze")
    log(Path(run_dir), "frame_approval", by=by)
    return write_status(run_dir, st)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Approve, reject or inspect a portfolio run")
    ap.add_argument("action", choices=["status", "approve", "reject", "approve-frame"])
    ap.add_argument("run_dir")
    ap.add_argument("--by", default="")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    rd = Path(a.run_dir)
    if a.action == "status":
        st = read_status(rd)
    elif a.action == "approve":
        st = approve(rd, a.by, a.note)
    elif a.action == "reject":
        st = reject(rd, a.by, a.note)
    else:
        st = approve_frame(rd, a.by)
    print(json.dumps(st, indent=2))


if __name__ == "__main__":
    main()
