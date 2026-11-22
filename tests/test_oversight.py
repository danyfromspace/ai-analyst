"""Human oversight: tiers, release rules, approval gate, trace log, graceful failure."""
import json

import pytest

Q = "Which titles need attention this month?"

from portfolio_agent import data, oversight, run as portfolio_run


@pytest.mark.parametrize("q,usd,tier", [
    ("Which titles need attention this month?", 0, "routine"),
    ("Which titles need attention this month?", 75_000, "consequential"),
    ("Should we move marketing budget to Cindervale?", 0, "consequential"),
    ("Should we delist Wildspire on Steam?", 0, "strategic"),
    ("What price should Starfall Chronicles drop to?", 0, "strategic"),
    ("Should we raise the price on Cindervale?", 0, "strategic"),
    ("Is the Anthem of Umber deal worth renewing?", 0, "strategic"),
    ("How complete is this list? Could we be missing a price error?", 0, "routine"),
    ("Why did revenue cut in half for Mudlark Bay?", 0, "routine"),
])
def test_classify(q, usd, tier):
    assert oversight.classify(q, usd) == tier


@pytest.mark.parametrize("tier,verdict,revs,frame_ok,state", [
    ("strategic", None, 0, False, "awaiting_frame_approval"),
    ("strategic", "PASS", 0, False, "awaiting_frame_approval"),
    ("routine", None, 0, True, "awaiting_validation"),
    ("routine", "FAIL", 0, True, "blocked"),
    ("routine", "REVISE", 1, True, "revise"),
    ("routine", "REVISE", 2, True, "escalated_to_human"),
    ("routine", "PASS", 0, True, "released"),
    ("consequential", "PASS", 0, True, "awaiting_approval"),
    ("strategic", "PASS", 0, True, "awaiting_approval"),
])
def test_next_state(tier, verdict, revs, frame_ok, state):
    assert oversight.next_state(tier, verdict, revs, frame_ok) == state


def test_fail_is_never_releasable():
    for tier in ("routine", "consequential", "strategic"):
        st = {"state": oversight.next_state(tier, "FAIL", 0, True), "verdict": "FAIL", "approved_by": "X"}
        assert not oversight.can_release(st)


def test_full_run_waits_for_named_approval(tmp_path):
    rd = portfolio_run.frame(Q, "2025-12", runs=tmp_path, plant_seed=1)
    st = portfolio_run.analyze(rd)
    assert st["state"] == "awaiting_validation"
    assert st["tier"] == "consequential"  # planted anomalies put more than $50k at stake
    st = portfolio_run.validate(rd)
    assert st["verdict"] == "PASS" and st["state"] == "awaiting_approval"
    assert not oversight.can_release(st)
    with pytest.raises(PermissionError):
        oversight.approve(rd, by="  ")
    st = oversight.approve(rd, by="Reviewer", note="checked the hypotheses with store ops")
    assert st["state"] == "released" and oversight.can_release(st)
    events = [json.loads(l)["event"] for l in (rd / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == ["framed", "data_gate", "analyzed", "validated", "human_approval"]
    for f in ("frame.json", "monthly.csv", "truth.json", "gate.json", "exceptions.json", "claims.json",
              "report_draft.md", "validation.json"):
        assert (rd / f).exists()


def test_cannot_approve_a_failed_run(tmp_path):
    rd = portfolio_run.frame(Q, "2025-12", runs=tmp_path, plant_seed=1)
    portfolio_run.analyze(rd)
    claims = json.loads((rd / "claims.json").read_text(encoding="utf-8"))
    claims[1]["value"] *= 2
    (rd / "claims.json").write_text(json.dumps(claims), encoding="utf-8")
    st = portfolio_run.validate(rd)
    assert st["verdict"] == "FAIL" and st["state"] == "blocked"
    with pytest.raises(PermissionError):
        oversight.approve(rd, by="Reviewer")


def test_strategic_question_stops_for_frame_approval(tmp_path):
    rd = portfolio_run.frame("Should we delist Wildspire on Steam?", "2025-12", runs=tmp_path)
    assert oversight.read_status(rd)["state"] == "awaiting_frame_approval"
    with pytest.raises(PermissionError):
        portfolio_run.analyze(rd)
    oversight.approve_frame(rd, by="Reviewer")
    assert portfolio_run.analyze(rd)["state"] == "awaiting_validation"


def test_revise_loops_then_escalates(tmp_path):
    rd = portfolio_run.frame(Q, "2025-12", runs=tmp_path, plant_seed=1)
    portfolio_run.analyze(rd)
    claims = json.loads((rd / "claims.json").read_text(encoding="utf-8"))
    claims[1]["period"] = "week"
    (rd / "claims.json").write_text(json.dumps(claims), encoding="utf-8")
    assert portfolio_run.validate(rd)["state"] == "revise"
    assert portfolio_run.validate(rd)["state"] == "escalated_to_human"


def test_broken_data_stops_gracefully_without_numbers(tmp_path):
    rd = portfolio_run.frame(Q, "2025-12", runs=tmp_path, plant_seed=1)
    m = data.load_monthly(rd / "monthly.csv")
    m.loc[m.index[:3], "platform"] = "xbox"
    data.write_monthly(m, rd / "monthly.csv")
    st = portfolio_run.analyze(rd)
    assert st["state"] == "blocked_by_data" and st["reason"]
    assert not (rd / "claims.json").exists()


def test_as_delivered_run_completes(tmp_path):
    rd = portfolio_run.frame(Q, "2025-12", runs=tmp_path)
    portfolio_run.analyze(rd)
    st = portfolio_run.validate(rd)
    assert st["verdict"] == "PASS"
    assert not (rd / "truth.json").exists()
