"""The Halcyon dataset: loading, and planting known problems for evaluation.

Halcyon is a fictional premium game publisher. Its data is AI-generated and fake, built for evaluation
only; no real company, title or sale is described. Three files ship in data/halcyon/:

  halcyon_catalog.csv            listing_id, title, platform, release_month      (one row per store listing)
  halcyon_monthly_net.csv        listing_id, title, platform, month, net_usd     (one row per listing-month)
  halcyon_items_latest_year.csv  product_name, store_item_name, platform, item_type, net_usd

A listing is one title on one storefront (steam, playstation or nintendo). Months are calendar months as
delivered; the source does not state a timezone. net_usd is net revenue as delivered.

The base data has no answer key, so evaluation plants problems into a copy of it:
    plant(monthly, catalog, as_of, seed) -> (planted monthly rows, truth)
Business anomalies: listing_outage, price_error, demand_collapse (title-wide), clawback (negative net).
Data issues: duplicate_row, missing_row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "halcyon"
PLATFORMS = {"steam", "playstation", "nintendo"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
COLUMNS = {
    "catalog": ["listing_id", "title", "platform", "release_month"],
    "monthly": ["listing_id", "title", "platform", "month", "net_usd"],
    "items": ["product_name", "store_item_name", "platform", "item_type", "net_usd"],
}
FILES = {"catalog": "halcyon_catalog.csv", "monthly": "halcyon_monthly_net.csv",
         "items": "halcyon_items_latest_year.csv"}


@dataclass
class Halcyon:
    catalog: pd.DataFrame
    monthly: pd.DataFrame
    items: pd.DataFrame


def _money(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="raise")


def load(data_dir: Path | str = DATA_DIR) -> Halcyon:
    data_dir = Path(data_dir)
    frames = {}
    for key, name in FILES.items():
        df = pd.read_csv(data_dir / name, dtype=str, keep_default_na=False, encoding="utf-8")
        if list(df.columns) != COLUMNS[key]:
            raise ValueError(f"{name}: columns {list(df.columns)}, expected {COLUMNS[key]}")
        frames[key] = df.apply(lambda c: c.str.strip())
    frames["monthly"]["net_usd"] = _money(frames["monthly"]["net_usd"])
    frames["items"]["net_usd"] = _money(frames["items"]["net_usd"])
    return Halcyon(frames["catalog"], frames["monthly"], frames["items"])


def load_monthly(path: Path | str) -> pd.DataFrame:
    """Just the monthly file (as delivered, or a planted copy)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    if list(df.columns) != COLUMNS["monthly"]:
        raise ValueError(f"{path}: columns {list(df.columns)}, expected {COLUMNS['monthly']}")
    df = df.apply(lambda c: c.str.strip())
    df["net_usd"] = _money(df["net_usd"])
    return df


def add_months(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    t = y * 12 + (m - 1) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    out, m = [], start
    while m <= end:
        out.append(m)
        m = add_months(m, 1)
    return out


def truncate(monthly: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """The data as it would have looked at the end of the as_of month."""
    return monthly[monthly.month <= as_of].copy()


# --------------------------------------------------------------------------- planting
def _trailing_median(monthly: pd.DataFrame, as_of: str, n: int = 6) -> pd.Series:
    win = month_range(add_months(as_of, -n), add_months(as_of, -1))
    h = monthly[monthly.month.isin(win)]
    full = h.groupby("listing_id").month.nunique() == n
    med = h.groupby("listing_id").net_usd.median()
    return med[full[full].index]


def plant(monthly: pd.DataFrame, catalog: pd.DataFrame, as_of: str, seed: int,
          min_monthly_usd: float = 5_000.0, min_age_months: int = 12) -> tuple[pd.DataFrame, dict]:
    """Copy of the data up to as_of with four business anomalies and two data issues planted in the
    as_of month. Targets are listings the monitor covers (at least min_age_months of history, a full
    trailing 6 months, median >= min_monthly_usd), chosen on the trailing median so the as_of month's own
    noise does not drive selection."""
    rng = np.random.default_rng(seed)
    df = truncate(monthly, as_of).reset_index(drop=True)
    cur = df.month == as_of
    med = _trailing_median(df, as_of)
    present = set(df[cur].listing_id)
    first = df.groupby("listing_id").month.min()
    mature = {l for l, f in first.items() if f <= add_months(as_of, -min_age_months)}
    eligible = sorted(l for l, v in med.items() if v >= min_monthly_usd and l in present and l in mature)
    plat = dict(zip(catalog.listing_id, catalog.platform))
    title = dict(zip(catalog.listing_id, catalog.title))
    by_title: dict[str, list[str]] = {}
    for l in eligible:
        by_title.setdefault(title[l], []).append(l)
    multi = sorted(t for t, ls in by_title.items() if len(ls) >= 2)
    if not multi or len(eligible) < 8:
        raise ValueError(f"not enough established listings at {as_of} to plant problems")
    collapse_title = str(rng.choice(multi))
    used = set(by_title[collapse_title])
    singles = [l for l in eligible if l not in used]
    pick = [str(x) for x in rng.choice(singles, size=5, replace=False)]
    outage, price, clawback, dup, gap = pick

    def scale(listing, f):
        m = (df.month == as_of) & (df.listing_id == listing)
        df.loc[m, "net_usd"] = (df.loc[m, "net_usd"] * f).round(2)

    scale(outage, 0.02)
    scale(price, 3.0)
    for l in by_title[collapse_title]:
        scale(l, 0.4)
    m = (df.month == as_of) & (df.listing_id == clawback)
    df.loc[m, "net_usd"] = (-0.5 * med[clawback]).round(2)
    out = df[~((df.month == as_of) & (df.listing_id == gap))]
    out = pd.concat([out, out[(out.month == as_of) & (out.listing_id == dup)]], ignore_index=True)

    truth = {
        "seed": seed, "as_of": as_of,
        "business_anomalies": [
            {"kind": "listing_outage", "title": title[outage], "listings": [outage], "direction": "down"},
            {"kind": "price_error", "title": title[price], "listings": [price], "direction": "up"},
            {"kind": "demand_collapse", "title": collapse_title, "listings": sorted(by_title[collapse_title]),
             "direction": "down"},
            {"kind": "clawback", "title": title[clawback], "listings": [clawback], "direction": "down"},
        ],
        "data_issues": [
            {"kind": "duplicate_row", "listing_id": dup},
            {"kind": "missing_row", "listing_id": gap},
        ],
        "platforms": {l: plat[l] for l in pick + by_title[collapse_title]},
    }
    return out.sort_values(["month", "listing_id"]).reset_index(drop=True), truth


def write_monthly(monthly: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(path, index=False, encoding="utf-8")
    return path
