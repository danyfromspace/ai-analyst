"""The Halcyon files load cleanly and planting is deterministic and well formed."""
import pandas as pd
import pytest

from portfolio_agent import data


@pytest.fixture(scope="module")
def hal():
    return data.load()


def test_files_load_with_expected_shape(hal):
    assert len(hal.catalog) == 238 and hal.catalog.listing_id.is_unique
    assert hal.monthly.month.min() == "2014-01" and hal.monthly.month.max() == "2025-12"
    assert set(hal.catalog.platform) == data.PLATFORMS
    assert not hal.monthly.duplicated(["listing_id", "month"]).any()
    assert set(hal.monthly.listing_id) <= set(hal.catalog.listing_id)
    assert set(hal.items.item_type) <= {"base", "dlc", "soundtrack"}


def test_money_with_thousands_separators_parses(hal):
    assert hal.items.net_usd.dtype.kind == "f" or hal.items.net_usd.dtype.kind == "i"
    assert data._money(pd.Series(["1,995", " 945 "])).tolist() == [1995, 945]


@pytest.mark.parametrize("m,k,out", [("2025-12", 1, "2026-01"), ("2025-01", -1, "2024-12"), ("2024-06", -18, "2022-12")])
def test_add_months(m, k, out):
    assert data.add_months(m, k) == out


def test_month_range_inclusive():
    assert data.month_range("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]


def test_plant_is_deterministic_and_does_not_touch_the_source(hal):
    before = hal.monthly.copy()
    a, ta = data.plant(hal.monthly, hal.catalog, "2025-06", seed=3)
    b, tb = data.plant(hal.monthly, hal.catalog, "2025-06", seed=3)
    assert ta == tb
    pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(before, hal.monthly)
    assert a.month.max() == "2025-06"


def test_plant_targets_are_distinct_monitored_listings(hal):
    planted, truth = data.plant(hal.monthly, hal.catalog, "2024-09", seed=11)
    listings = [l for a in truth["business_anomalies"] for l in a["listings"]] + [d["listing_id"] for d in truth["data_issues"]]
    assert len(listings) == len(set(listings))
    first = hal.monthly.groupby("listing_id").month.min()
    assert all(first[l] <= data.add_months("2024-09", -12) for l in listings)


def test_plant_applies_each_problem(hal):
    planted, truth = data.plant(hal.monthly, hal.catalog, "2025-03", seed=5)
    orig = hal.monthly[hal.monthly.month == "2025-03"].set_index("listing_id").net_usd
    cur = planted[planted.month == "2025-03"]
    kinds = {a["kind"]: a for a in truth["business_anomalies"]}
    val = lambda l: cur[cur.listing_id == l].net_usd.iloc[0]
    assert val(kinds["listing_outage"]["listings"][0]) == pytest.approx(orig[kinds["listing_outage"]["listings"][0]] * 0.02, abs=0.01)
    assert val(kinds["price_error"]["listings"][0]) == pytest.approx(orig[kinds["price_error"]["listings"][0]] * 3, abs=0.01)
    assert val(kinds["clawback"]["listings"][0]) < 0
    assert len(kinds["demand_collapse"]["listings"]) >= 2
    issues = {d["kind"]: d["listing_id"] for d in truth["data_issues"]}
    assert (cur.listing_id == issues["duplicate_row"]).sum() == 2
    assert (cur.listing_id == issues["missing_row"]).sum() == 0
