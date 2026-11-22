"""Monthly portfolio monitor for the Halcyon catalog.

1. data_gate(monthly, catalog, as_of)   Data Steward checks before any analysis.
2. monthly_exceptions(clean, ...)        Every listing's as-of month against its expected month, ranked by
                                         dollars at stake, grouped into incidents per title.
3. draft_claims / render_report          Checkable claims and the reviewer's draft.

Expected month (the definition the validator re-derives; see EXPECTED_DEFINITION):
  base(l, m)   = median of listing l's 6 months before m (all 6 must be present)
  lr(l, m)     = ln((net + 1) / (base + 1))                   the listing's change against its own base
  peer(p, m)   = median lr over every listing on storefront p in month m (0 if fewer than 10 listings)
  expect(l, m) = (base + 1) x exp(peer) - 1                   seasonality and store-wide sales move the peers too
  resid(l, m)  = lr - peer
Score: z = resid(as_of) / (1.4826 x MAD of resid over the listing's previous 24 months, floored at 0.05).
Flag when |z| >= Z and |actual - expect| >= MIN_USD.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Optional

import numpy as np
import pandas as pd

from portfolio_agent.data import PLATFORMS, MONTH_RE, add_months, month_range

KEY = ["listing_id", "month"]
METRIC = "halcyon_net_usd"
PERIOD = "calendar month as delivered (source states no timezone)"
REVENUE_SCOPE = "net_usd as delivered"
BASE_MONTHS, RESID_MONTHS = 6, 24
EXPECTED_DEFINITION = ("median of the listing's 6 previous months, moved by the median change "
                       "of its storefront peers that month")
Z, MIN_USD, CORROBORATE_Z, MIN_AGE_MONTHS = 3.5, 1_000.0, 2.0, 12


# --------------------------------------------------------------------------- 1. data gate
@dataclass
class GateIssue:
    check: str
    severity: str  # block or warn
    detail: str
    listing_id: Optional[str] = None
    action: str = ""


@dataclass
class GateResult:
    status: str
    issues: list[GateIssue]
    clean: pd.DataFrame = field(repr=False)
    excluded: list[str] = field(default_factory=list)   # listings not comparable this month
    annotated: dict = field(default_factory=dict)       # listing -> disclosure note for any claim

    def to_dict(self) -> dict:
        return {"status": self.status, "issues": [asdict(i) for i in self.issues],
                "excluded_listings": self.excluded,
                "annotated_listings": [[k, v] for k, v in self.annotated.items()]}


def data_gate(monthly: pd.DataFrame, catalog: pd.DataFrame, as_of: str) -> GateResult:
    issues: list[GateIssue] = []
    df = monthly.copy()
    excluded, annotated = set(), {}

    if not MONTH_RE.match(as_of) or as_of not in set(df.month):
        issues.append(GateIssue("as_of_in_data", "block", f"as-of month {as_of} has no rows in the data",
                                action="pick a month the data covers"))
    if not df.month.astype(str).str.match(MONTH_RE).all():
        issues.append(GateIssue("month_format", "block", "months not in YYYY-MM form", action="fix the extract"))
    bad = sorted(set(df.platform) - PLATFORMS)
    if bad:
        issues.append(GateIssue("platforms", "block", f"unknown platforms {bad}", action="map or drop them"))
    orphans = sorted(set(df.listing_id) - set(catalog.listing_id))
    if orphans:
        issues.append(GateIssue("catalog_join", "block", f"{len(orphans)} listings not in the catalog: {orphans[:3]}",
                                action="fix the catalog before analysis"))

    dup = df.duplicated(KEY, keep="first")
    for (lid, m), _g in df[dup].groupby(KEY):
        issues.append(GateIssue("duplicate_row", "warn", f"{lid} {m}: row loaded more than once; extra copy dropped",
                                lid, "deduplicated; report the load defect"))
        if m == as_of:
            annotated[lid] = "a duplicate row was removed before comparison (data issue)"
    df = df[~dup]

    prior = month_range(add_months(as_of, -BASE_MONTHS), add_months(as_of, -1))
    h = df[df.month.isin(prior)].groupby("listing_id").month.nunique()
    full = set(h[h == BASE_MONTHS].index)
    present = set(df[df.month == as_of].listing_id)
    for lid in sorted(full - present):
        issues.append(GateIssue("missing_row", "warn",
                                f"{lid}: no row for {as_of} although each of the 6 months before has one",
                                lid, "excluded this month: a missing row may be zero sales or a load gap"))
        excluded.add(lid)

    neg = df[(df.month == as_of) & (df.net_usd < 0)]
    for r in neg.itertuples():
        issues.append(GateIssue("negative_net", "warn", f"{r.listing_id} {as_of}: net is negative (${r.net_usd:,.2f})",
                                r.listing_id, "kept: refunds or clawbacks can exceed sales; flag for review"))

    status = "BLOCK" if any(i.severity == "block" for i in issues) else ("WARN" if issues else "PASS")
    return GateResult(status, issues, df.reset_index(drop=True), sorted(excluded), annotated)


# --------------------------------------------------------------------------- 2. monitor
def _pivot(clean: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for lid, m, v in clean[["listing_id", "month", "net_usd"]].itertuples(index=False):
        out.setdefault(lid, {})[m] = float(v)
    return out


def _base(series: dict[str, float], month: str) -> Optional[float]:
    vals = [series.get(add_months(month, -k)) for k in range(1, BASE_MONTHS + 1)]
    if any(v is None for v in vals):
        return None
    return float(median(vals))


def peer_factors(series_by: dict, platform_of: dict, months: list[str]) -> dict[tuple[str, str], float]:
    """Median change-against-base of every listing on a storefront in a month."""
    vals: dict[tuple[str, str], list[float]] = {}
    for lid, s in series_by.items():
        for m in months:
            if m in s:
                b = _base(s, m)
                if b is not None:
                    vals.setdefault((platform_of[lid], m), []).append(_log_ratio(s[m], b))
    return {k: (float(median(v)) if len(v) >= 10 else 0.0) for k, v in vals.items()}


def _log_ratio(a: float, e: float) -> float:
    return float(np.log((max(a, 0.0) + 1.0) / (max(e, 0.0) + 1.0)))


def monthly_exceptions(clean: pd.DataFrame, catalog: pd.DataFrame, as_of: str,
                       exclude=(), annotated: Optional[dict] = None) -> dict:
    platform_of = dict(zip(catalog.listing_id, catalog.platform))
    title_of = dict(zip(catalog.listing_id, catalog.title))
    series_by = _pivot(clean[clean.month <= as_of])
    months = month_range(add_months(as_of, -RESID_MONTHS), as_of)
    peer = peer_factors(series_by, platform_of, months)
    exclude, annotated = set(exclude), annotated or {}
    rows, not_monitored = [], []
    for lid, s in sorted(series_by.items()):
        if as_of not in s and lid not in exclude:
            continue
        if lid in exclude:
            not_monitored.append({"listing_id": lid, "reason": "data gate: missing row"})
            continue
        if len(month_range(min(s), as_of)) - 1 < MIN_AGE_MONTHS:
            not_monitored.append({"listing_id": lid, "reason": f"under {MIN_AGE_MONTHS} months of history"})
            continue
        p = platform_of[lid]
        b = _base(s, as_of)
        if b is None:
            not_monitored.append({"listing_id": lid, "reason": "a gap in the 6 months before"})
            continue
        resid = [_log_ratio(s[m], _base(s, m)) - peer.get((p, m), 0.0)
                 for m in months[:-1] if m in s and _base(s, m) is not None]
        if len(resid) < 6:
            not_monitored.append({"listing_id": lid, "reason": "too little history to score"})
            continue
        mad = max(float(np.median(np.abs(np.array(resid) - np.median(resid)))), 0.05)
        f = peer.get((p, as_of), 0.0)
        a = s[as_of]
        e = (b + 1.0) * float(np.exp(f)) - 1.0
        z = (_log_ratio(a, b) - f) / (1.4826 * mad)
        delta = a - e
        rows.append({"listing_id": lid, "title": title_of[lid], "platform": p, "actual": round(a, 2),
                     "expected": round(e, 2), "delta_usd": round(delta, 2),
                     "delta_pct": round(delta / e, 4) if e else None, "robust_z": round(z, 2),
                     "flagged": bool(abs(z) >= Z and abs(delta) >= MIN_USD)})
    series = pd.DataFrame(rows)
    flags = series[series.flagged] if len(series) else series

    incidents = []
    for t, g in (flags.groupby("title") if len(flags) else []):
        all_l = series[series.title == t]
        sign = np.sign(g.delta_usd.sum())
        corr = all_l[(~all_l.flagged) & (np.sign(all_l.delta_usd) == sign) & (all_l.robust_z.abs() >= CORROBORATE_Z)]
        title_wide = len(all_l) >= 2 and len(g) + len(corr) == len(all_l)
        inc = {"title": t, "scope": "title" if title_wide else "listing",
               "listings": sorted(g.listing_id), "platforms": sorted(g.platform),
               "corroborating_listings": sorted(corr.listing_id) if title_wide else [],
               "delta_usd": round(float(g.delta_usd.sum()), 2),
               "direction": "up" if g.delta_usd.sum() > 0 else "down",
               "any_negative_net": bool((g.actual < 0).any()),
               "data_notes": [annotated[l] for l in sorted(g.listing_id) if l in annotated],
               "series": g.drop(columns=["flagged"]).to_dict("records")}
        inc["hypotheses"] = hypotheses(inc)
        incidents.append(inc)
    incidents.sort(key=lambda i: abs(i["delta_usd"]), reverse=True)
    for r, inc in enumerate(incidents, 1):
        inc["rank"] = r
    return {"as_of": as_of, "metric": METRIC, "revenue_scope": REVENUE_SCOPE, "period": PERIOD,
            "expected_definition": EXPECTED_DEFINITION,
            "thresholds": {"robust_z": Z, "min_usd": MIN_USD, "corroborate_z": CORROBORATE_Z,
                           "min_age_months": MIN_AGE_MONTHS},
            "storefront_factor_as_of": {pp: round(float(np.exp(peer.get((pp, as_of), 0.0))), 3)
                                        for pp in sorted(PLATFORMS)},
            "listings_checked": int(len(series)), "incidents": incidents, "not_monitored": not_monitored}


def hypotheses(inc: dict) -> list[dict]:
    """Likely explanations with the check that would confirm each. Never a conclusion."""
    hs = []
    if inc["any_negative_net"]:
        hs.append({"hypothesis": "refund or chargeback clawback (net revenue is negative)",
                   "check": "storefront payout statement adjustments and refund reasons"})
    if inc["direction"] == "down" and inc["scope"] == "title":
        hs.append({"hypothesis": "demand drop across every storefront",
                   "check": "competitor releases, featuring that ended, review score changes"})
    if inc["direction"] == "down" and inc["scope"] == "listing" and not inc["any_negative_net"]:
        hs.append({"hypothesis": "store listing or entitlement problem on that storefront",
                   "check": "store page status, partner portal notices, delisting or rating changes"})
    if inc["direction"] == "up":
        hs.append({"hypothesis": "unplanned price change or promotion not on the calendar",
                   "check": "price history on that storefront; promotion calendar"})
    if not hs:
        hs.append({"hypothesis": "unexplained movement", "check": "compare with next month's data"})
    return hs


# --------------------------------------------------------------------------- 3. claims and report
def draft_claims(report: dict, gate: GateResult, top_n: int = 10) -> list[dict]:
    as_of = report["as_of"]
    total = float(gate.clean[gate.clean.month == as_of].net_usd.sum())
    labels = {"metric": METRIC, "period": PERIOD, "revenue_scope": REVENUE_SCOPE, "unit": "USD"}
    claims = [{"id": "C0", "kind": "total", **labels, "filters": {"month": as_of}, "value": round(total, 2),
               "text": f"Catalog net revenue for {as_of} was ${total:,.0f}."}]
    for inc in report["incidents"][:top_n]:
        verb = "above" if inc["delta_usd"] > 0 else "below"
        notes = "".join(f"; note: {n}" for n in inc["data_notes"])
        claims.append({
            "id": f"C{inc['rank']}", "kind": "delta_vs_expected", **labels,
            "filters": {"month": as_of, "listings": inc["listings"]},
            "expected_definition": report["expected_definition"], "value": inc["delta_usd"],
            "text": (f"{inc['title']} ({', '.join(inc['platforms'])}) net revenue was ${abs(inc['delta_usd']):,.0f} "
                     f"{verb} its expected month; likely explanation to check: "
                     f"{inc['hypotheses'][0]['hypothesis']}{notes}."),
        })
    return claims


def render_report(question: str, gate: GateResult, report: dict, claims: list[dict]) -> str:
    lines = [f"# Portfolio exceptions: {report['as_of']}", "", f"**Question:** {question}", "",
             f"Metric `{report['metric']}` ({report['revenue_scope']}, USD), {report['period']}. "
             f"Expected month = {report['expected_definition']}.", "", f"## Data gate: {gate.status}"]
    for i in gate.issues:
        lines.append(f"- **{i.check}** ({i.severity}): {i.detail}. Action: {i.action}")
    lines += ["", "## Ranked exceptions (by dollars at stake)", "",
              "| Rank | Title | Storefronts | vs expected (USD) | Hypothesis to check | Check |", "|---|---|---|---|---|---|"]
    for inc in report["incidents"]:
        h = inc["hypotheses"][0]
        lines.append(f"| {inc['rank']} | {inc['title']} | {', '.join(inc['platforms'])} | {inc['delta_usd']:+,.0f} | "
                     f"{h['hypothesis']} | {h['check']} |")
    if report["not_monitored"]:
        lines += ["", f"## Not monitored this month ({len(report['not_monitored'])} listings)"]
        reasons: dict[str, int] = {}
        for n in report["not_monitored"]:
            reasons[n["reason"]] = reasons.get(n["reason"], 0) + 1
        for r, k in reasons.items():
            lines.append(f"- {k} x {r}")
    lines += ["", "## Claims (what the validator checks)"] + [f"- `{c['id']}` {c['text']}" for c in claims]
    lines += ["", "Monitoring data shows *where* revenue moved. Each hypothesis needs its check before anyone acts."]
    return "\n".join(lines) + "\n"
