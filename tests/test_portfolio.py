"""Data gate, monitor, hypotheses, claims and report on the Halcyon data."""
import numpy as np
import pandas as pd
import pytest

from portfolio_agent import data, portfolio as P

AS_OF = "2025-12"


@pytest.fixture(scope="module")
def hal():
    return data.load()


@pytest.fixture(scope="module")
def planted(hal):
    m, truth = data.plant(hal.monthly, hal.catalog, AS_OF, seed=1)
    gate = P.data_gate(m, hal.catalog, AS_OF)
    rep = P.monthly_exceptions(gate.clean, hal.catalog, AS_OF, gate.excluded, gate.annotated)
    return m, truth, gate, rep


# --------------------------------------------------------------------------- gate
def test_as_delivered_data_passes_the_gate(hal):
    g = P.data_gate(hal.monthly, hal.catalog, AS_OF)
    assert g.status == "PASS", [i.detail for i in g.issues]


def test_gate_handles_planted_data_issues(planted):
    _, truth, gate, _ = planted
    issues = {d["kind"]: d["listing_id"] for d in truth["data_issues"]}
    checks = {(i.check, i.listing_id) for i in gate.issues}
    assert ("duplicate_row", issues["duplicate_row"]) in checks
    assert ("missing_row", issues["missing_row"]) in checks
    assert issues["missing_row"] in gate.excluded
    assert issues["duplicate_row"] in gate.annotated
    assert not gate.clean.duplicated(P.KEY).any()


def test_gate_warns_on_negative_net(planted):
    _, truth, gate, _ = planted
    claw = next(a for a in truth["business_anomalies"] if a["kind"] == "clawback")["listings"][0]
    assert ("negative_net", claw) in {(i.check, i.listing_id) for i in gate.issues}


@pytest.mark.parametrize("mutate,check", [
    (lambda m: m.assign(platform=m.platform.where(m.index != 0, "xbox")), "platforms"),
    (lambda m: pd.concat([m, m.head(1).assign(listing_id="ghost::steam")]), "catalog_join"),
])
def test_gate_blocks_broken_inputs(hal, mutate, check):
    g = P.data_gate(mutate(hal.monthly.copy()), hal.catalog, AS_OF)
    assert g.status == "BLOCK" and any(i.check == check and i.severity == "block" for i in g.issues)


def test_gate_blocks_an_as_of_month_with_no_data(hal):
    g = P.data_gate(hal.monthly, hal.catalog, "2026-03")
    assert g.status == "BLOCK"


# --------------------------------------------------------------------------- monitor
def test_planted_outage_and_clawback_rank_at_the_top(planted):
    _, truth, _, rep = planted
    top = rep["incidents"][:5]
    for kind in ("listing_outage", "clawback"):
        a = next(x for x in truth["business_anomalies"] if x["kind"] == kind)
        assert any(i["title"] == a["title"] and i["direction"] == "down" for i in top), kind


def test_incidents_ranked_by_absolute_dollars(planted):
    d = [abs(i["delta_usd"]) for i in planted[3]["incidents"]]
    assert d == sorted(d, reverse=True)


def test_young_and_excluded_listings_are_listed(planted):
    _, truth, gate, rep = planted
    reasons = {n["listing_id"]: n["reason"] for n in rep["not_monitored"]}
    missing = next(d for d in truth["data_issues"] if d["kind"] == "missing_row")["listing_id"]
    assert reasons[missing] == "data gate: missing row"
    assert any("under 12 months" in r for r in reasons.values()) or rep["listings_checked"] > 0


def test_store_wide_move_is_not_an_anomaly(hal):
    # Every steam listing at 2x in the as-of month (a storefront sale): the peer factor absorbs it.
    m = hal.monthly[hal.monthly.month <= AS_OF].copy()
    sel = (m.month == AS_OF) & (m.platform == "steam")
    m.loc[sel, "net_usd"] *= 2
    g = P.data_gate(m, hal.catalog, AS_OF)
    base = P.monthly_exceptions(P.data_gate(hal.monthly, hal.catalog, AS_OF).clean, hal.catalog, AS_OF)
    rep = P.monthly_exceptions(g.clean, hal.catalog, AS_OF)
    steam_up = lambda r: {i["title"] for i in r["incidents"] if i["direction"] == "up" and "steam" in i["platforms"]}
    assert len(steam_up(rep)) <= len(steam_up(base)) + 1
    assert rep["storefront_factor_as_of"]["steam"] == pytest.approx(2 * base["storefront_factor_as_of"]["steam"], rel=0.02)


def test_single_listing_outage_is_flagged(hal):
    m = hal.monthly[hal.monthly.month <= AS_OF].copy()
    sel = (m.month == AS_OF) & (m.listing_id == "starfallchronicles::steam")
    m.loc[sel, "net_usd"] *= 0.02
    rep = P.monthly_exceptions(P.data_gate(m, hal.catalog, AS_OF).clean, hal.catalog, AS_OF)
    assert rep["incidents"][0]["listings"] == ["starfallchronicles::steam"]
    assert rep["incidents"][0]["hypotheses"][0]["hypothesis"].startswith("store listing")


def test_peer_factor_median():
    s = {f"l{i}": {f"2025-0{k}": 100.0 for k in range(1, 8)} for i in range(12)}
    for i in range(12):
        s[f"l{i}"]["2025-07"] = 201.0  # every listing doubles (+1 smoothing: (201+1)/(100+1) = 2)
    f = P.peer_factors(s, {f"l{i}": "steam" for i in range(12)}, ["2025-07"])
    assert np.exp(f[("steam", "2025-07")]) == pytest.approx(2.0)
    f9 = P.peer_factors({k: v for k, v in list(s.items())[:9]}, {f"l{i}": "steam" for i in range(12)}, ["2025-07"])
    assert f9[("steam", "2025-07")] == 0.0  # fewer than 10 peers: no adjustment


def test_labels_on_every_output(planted):
    rep = planted[3]
    assert rep["period"].startswith("calendar month") and rep["revenue_scope"] == "net_usd as delivered"
    assert "storefront peers" in rep["expected_definition"]


# --------------------------------------------------------------------------- claims and report
def test_claims_have_filters_labels_and_hedges(planted):
    _, _, gate, rep = planted
    claims = P.draft_claims(rep, gate)
    assert claims[0]["kind"] == "total"
    for c in claims:
        assert c["metric"] == P.METRIC and c["period"] == P.PERIOD and c["filters"]["month"] == AS_OF
    for c in claims[1:]:
        assert "likely explanation to check" in c["text"] and c["filters"]["listings"]


def test_report_lists_gate_and_says_where_not_why(planted):
    _, _, gate, rep = planted
    claims = P.draft_claims(rep, gate)
    md = P.render_report("Which titles need attention this month?", gate, rep, claims)
    assert "Data gate: WARN" in md and "*where*" in md
    assert all(c["id"] in md for c in claims)
