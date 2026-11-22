"""Validator: independence, re-derivation to the cent, every planted error family, verdict rules."""
import copy
import inspect

import pytest

from portfolio_agent import data, evals, portfolio as P, validation as V

AS_OF = "2025-12"
CATALOG = data.DATA_DIR / data.FILES["catalog"]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    hal = data.load()
    m, truth = data.plant(hal.monthly, hal.catalog, AS_OF, seed=1)
    path = data.write_monthly(m, tmp_path_factory.mktemp("v") / "monthly.csv")
    gate = P.data_gate(m, hal.catalog, AS_OF)
    rep = P.monthly_exceptions(gate.clean, hal.catalog, AS_OF, gate.excluded, gate.annotated)
    return truth, path, P.draft_claims(rep, gate)


def test_validator_is_a_separate_implementation():
    imports = [l for l in inspect.getsource(V).splitlines() if l.startswith(("import ", "from "))]
    for line in imports:
        assert not any(b in line for b in ("pandas", "numpy", "portfolio_agent")), line


def test_governed_labels_match_the_monitor():
    assert V.GOVERNED == {"metric": P.METRIC, "period": P.PERIOD, "revenue_scope": P.REVENUE_SCOPE,
                          "expected_definition": P.EXPECTED_DEFINITION}


def test_clean_claims_pass_and_rederive_to_the_cent(run):
    truth, path, claims = run
    res = V.validate(claims, path, CATALOG)
    assert res["verdict"] == "PASS", res["findings"]
    for r in res["rederivation"]:
        assert r["status"] == "pass" and r["rederived"] == pytest.approx(r["claimed"], abs=0.02)


def test_raw_records_duplicates_and_missing_rows(run):
    truth, path, _ = run
    raw = V.Raw(path, CATALOG)
    issues = {d["kind"]: d["listing_id"] for d in truth["data_issues"]}
    assert (issues["duplicate_row"], AS_OF) in raw.duplicates
    assert issues["missing_row"] in raw.missing_rows(AS_OF)


def test_blind_view_drops_reasoning():
    c = {"id": "C1", "kind": "total", "filters": {}, "value": 1, "text": "x", "analyst_notes": "secret"}
    assert "analyst_notes" not in V.blind_view([c])[0]


def test_claims_hash_tracks_changes(run):
    claims = run[2]
    c2 = copy.deepcopy(claims)
    c2[1]["value"] += 1
    assert V.claims_hash(c2) != V.claims_hash(claims) == V.claims_hash(copy.deepcopy(claims))


EXPECT = {"wrong_value": ("rederive", "FAIL"), "text_mismatch": ("text_matches", "FAIL"),
          "wrong_period_label": ("labels", "REVISE"), "wrong_revenue_scope": ("labels", "REVISE"),
          "causal_language": ("causal_language", "REVISE"), "wrong_scope": ("scope_exists", "FAIL"),
          "unadjusted_baseline": ("expected_definition", "FAIL"), "data_issue_leak": ("data_issue_leak", "FAIL")}


@pytest.mark.parametrize("family", sorted(EXPECT))
def test_each_error_family_is_caught(run, family):
    truth, path, claims = run
    mut = evals.mutations(claims, truth, V.Raw(path, CATALOG))[family]
    if mut is None:
        pytest.skip("inside tolerance for this seed")
    res = V.validate(mut, path, CATALOG)
    check, verdict = EXPECT[family]
    assert check in {f["check"] for f in res["findings"]}, res["findings"]
    assert res["verdict"] == verdict


def test_hedged_text_is_not_causal():
    assert not V.CAUSAL.search("revenue was $5,000 below expected; consistent with a listing problem")
    assert V.CAUSAL.search("revenue fell, caused by a listing problem")


def test_money_parser():
    assert V.money_in_text("$1.2m, $35k and $1,234") == [1_200_000, 35_000, 1_234]


def test_verdict_rules():
    F = V.Finding
    assert V.verdict([]) == "PASS"
    assert V.verdict([F("c", "x", "minor", "", "")]) == "PASS"
    assert V.verdict([F("c", "x", "major", "", "")]) == "REVISE"
    assert V.verdict([F("c", "x", "major", "", ""), F("c", "y", "blocking", "", "")]) == "FAIL"


def test_wilson():
    lo, hi = evals.wilson(56, 56)
    assert lo == pytest.approx(0.936, abs=0.002) and hi == 1.0
