"""Evaluation harness (deterministic layer) on the Halcyon data.

  python -m portfolio_agent.evals --seeds 40 --out docs

Each seed picks an as-of month between 2021-01 and 2025-12, truncates the data there, and plants four
business anomalies and two data issues into that month (portfolio_agent.data.plant).

E1 Monitor recall by kind: a planted anomaly counts as found when its title is a top-10 incident in the
   right direction and the incident includes at least one planted listing. Unplanted incidents are
   reported as alerts per month; the base data can hold real movements, so they are not all false.
E2 Detection curve: one listing at a time shocked by a factor (x0.1 ... x5) in an otherwise as-delivered
   month: the share flagged. This is the monitor's minimum detectable effect on monthly data.
E3 Gate ablation: a naive preparation (duplicates summed, a missing month read as zero) against the gate.
E4 Validator calibration: clean claims must PASS; nine planted error families must not.

The planted errors and the checks were written by the same author: E4 shows the checks catch the families
they were built for. Errors nobody anticipated are untested.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from portfolio_agent import data, portfolio, validation

MONTHS = data.month_range("2021-01", "2025-12")
SHOCKS = [0.1, 0.3, 0.5, 0.7, 1.5, 2.0, 3.0, 5.0]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def _found(inc: dict, a: dict) -> bool:
    return inc["title"] == a["title"] and inc["direction"] == a["direction"] and bool(set(inc["listings"]) & set(a["listings"]))


def _naive(monthly: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """What a quick groupby does: duplicates summed, a listing missing this month read as zero."""
    g = monthly.groupby(["listing_id", "title", "platform", "month"], as_index=False).net_usd.sum()
    prior = data.month_range(data.add_months(as_of, -6), data.add_months(as_of, -1))
    have = g[g.month.isin(prior)].groupby("listing_id").month.nunique()
    now = set(g[g.month == as_of].listing_id)
    meta = g.drop_duplicates("listing_id").set_index("listing_id")
    zeros = [{"listing_id": l, "title": meta.title[l], "platform": meta.platform[l], "month": as_of, "net_usd": 0.0}
             for l in have[have == 6].index if l not in now]
    return pd.concat([g, pd.DataFrame(zeros)], ignore_index=True)


# --------------------------------------------------------------------------- planted claim errors
def mutations(claims: list[dict], truth: dict, raw: validation.Raw) -> dict[str, list[dict] | None]:
    i = next(k for k, c in enumerate(claims) if c["kind"] == "delta_vs_expected")
    t = claims[i]
    out = {}

    def swap(new):
        cs = copy.deepcopy(claims)
        cs[i] = new
        return cs

    def retext(c, v):
        c["text"] = re.sub(r"\$[0-9,]+", f"${abs(v):,.0f}", c["text"], count=1)

    c = copy.deepcopy(t); c["value"] = round(c["value"] * 1.08, 2); retext(c, c["value"]); out["wrong_value"] = swap(c)
    c = copy.deepcopy(t); retext(c, abs(c["value"]) * 1.3); out["text_mismatch"] = swap(c)
    c = copy.deepcopy(t); c["period"] = "week"; out["wrong_period_label"] = swap(c)
    c = copy.deepcopy(t); c["revenue_scope"] = "gross sales"; out["wrong_revenue_scope"] = swap(c)
    c = copy.deepcopy(t)
    c["text"] = re.sub(r"; likely explanation to check: ([^;.]*)", r", caused by \1", c["text"])
    out["causal_language"] = swap(c)
    c = copy.deepcopy(t); c["filters"] = {**c["filters"], "listings": ["nosuchtitle::steam"]}; out["wrong_scope"] = swap(c)

    # Baseline without the storefront adjustment: plain 6-month median, definition string changed to match.
    c = copy.deepcopy(t)
    m = c["filters"]["month"]
    wrong = sum(raw.s[l][m] - raw.base(l, m) for l in c["filters"]["listings"])
    if abs(wrong - t["value"]) <= max(validation.ABS_TOL, validation.REL_TOL * abs(t["value"])):
        out["unadjusted_baseline"] = None
    else:
        c["value"] = round(wrong, 2); retext(c, wrong)
        c["expected_definition"] = "median of the listing's 6 previous months"
        out["unadjusted_baseline"] = swap(c)

    # Data-issue leak: the duplicated listing reported as a spike, number computed with the duplicate summed.
    dup = next(d["listing_id"] for d in truth["data_issues"] if d["kind"] == "duplicate_row")
    b = raw.base(dup, m)
    e = (b + 1) * math.exp(raw.peer(raw.platform[dup], m)) - 1
    leak = round(2 * raw.s[dup][m] - e, 2)
    out["data_issue_leak"] = claims + [{**copy.deepcopy(t), "id": "CX", "filters": {"month": m, "listings": [dup]},
                                        "value": leak,
                                        "text": f"{dup} net revenue was ${abs(leak):,.0f} above its expected month; "
                                                f"likely explanation to check: promotion not on the calendar."}]
    return out


# --------------------------------------------------------------------------- run
def run(seeds: int = 40, curve_listings: int = 6) -> dict:
    h = data.load()
    rng = np.random.default_rng(2026)
    cat_path = data.DATA_DIR / data.FILES["catalog"]
    e1 = {"seeds": 0, "by_kind": defaultdict(lambda: [0, 0]), "ranks": [], "unplanted_alerts": 0,
          "data_issue_reported": 0}
    curve = {f: [0, 0] for f in SHOCKS}
    e3 = {"naive_data_issue_alerts": 0, "gated_data_issue_alerts": 0}
    e4c = {"runs": 0, "not_passed": 0}
    e4 = defaultdict(lambda: {"n": 0, "caught": 0, "no_op": 0, "checks": defaultdict(int)})
    with tempfile.TemporaryDirectory() as td:
        for seed in range(seeds):
            as_of = MONTHS[int(rng.integers(len(MONTHS)))]
            planted, truth = data.plant(h.monthly, h.catalog, as_of, seed)
            gate = portfolio.data_gate(planted, h.catalog, as_of)
            rep = portfolio.monthly_exceptions(gate.clean, h.catalog, as_of, gate.excluded, gate.annotated)
            top = rep["incidents"][:10]
            e1["seeds"] += 1
            for a in truth["business_anomalies"]:
                e1["by_kind"][a["kind"]][1] += 1
                hit = next((x for x in top if _found(x, a)), None)
                if hit:
                    e1["by_kind"][a["kind"]][0] += 1
                    e1["ranks"].append(hit["rank"])
            e1["unplanted_alerts"] += sum(1 for x in rep["incidents"]
                                          if not any(_found(x, a) for a in truth["business_anomalies"]))
            issue = {d["listing_id"] for d in truth["data_issues"]}
            e1["data_issue_reported"] += sum(1 for x in rep["incidents"] if not x["data_notes"] and set(x["listings"]) & issue)

            naive = portfolio.monthly_exceptions(_naive(planted, as_of), h.catalog, as_of)
            e3["naive_data_issue_alerts"] += sum(1 for x in naive["incidents"] if set(x["listings"]) & issue)
            e3["gated_data_issue_alerts"] += sum(1 for x in rep["incidents"] if set(x["listings"]) & issue)

            # Detection curve on the as-delivered month.
            base = data.truncate(h.monthly, as_of)
            g0 = portfolio.data_gate(base, h.catalog, as_of)
            med = data._trailing_median(base, as_of)
            first = base.groupby("listing_id").month.min()
            cand = sorted(l for l, v in med.items() if v >= 2_000 and l in set(base[base.month == as_of].listing_id)
                          and first[l] <= data.add_months(as_of, -portfolio.MIN_AGE_MONTHS))
            for l in rng.choice(cand, size=min(curve_listings, len(cand)), replace=False):
                for f in SHOCKS:
                    shocked = g0.clean.copy()
                    m = (shocked.month == as_of) & (shocked.listing_id == l)
                    shocked.loc[m, "net_usd"] *= f
                    r = portfolio.monthly_exceptions(shocked, h.catalog, as_of)
                    flagged = any(l in x["listings"] for x in r["incidents"])
                    curve[f][0] += flagged
                    curve[f][1] += 1

            path = data.write_monthly(planted, Path(td) / f"m{seed}.csv")
            claims = portfolio.draft_claims(rep, gate)
            if not any(c["kind"] == "delta_vs_expected" for c in claims):
                continue
            res = validation.validate(claims, path, cat_path)
            e4c["runs"] += 1
            e4c["not_passed"] += res["verdict"] != "PASS"
            raw = validation.Raw(path, cat_path)
            for fam, mut in mutations(claims, truth, raw).items():
                if mut is None:
                    e4[fam]["no_op"] += 1
                    continue
                r = validation.validate(mut, path, cat_path)
                e4[fam]["n"] += 1
                e4[fam]["caught"] += r["verdict"] != "PASS"
                for fnd in r["findings"]:
                    e4[fam]["checks"][fnd["check"]] += 1

    found = sum(v[0] for v in e1["by_kind"].values())
    total = sum(v[1] for v in e1["by_kind"].values())
    pn, pc = sum(v["n"] for v in e4.values()), sum(v["caught"] for v in e4.values())
    return {
        "E1_recall": {"seeds": e1["seeds"], "found": found, "planted": total, "wilson95": wilson(found, total),
                      "by_kind": {k: {"found": v[0], "planted": v[1], "wilson95": wilson(*v)} for k, v in e1["by_kind"].items()},
                      "median_rank": int(np.median(e1["ranks"])) if e1["ranks"] else None,
                      "unplanted_alerts_per_month": round(e1["unplanted_alerts"] / e1["seeds"], 2),
                      "data_issues_reported_without_note": e1["data_issue_reported"]},
        "E2_detection_curve": {str(f): {"flagged": v[0], "n": v[1], "rate": round(v[0] / v[1], 3) if v[1] else None}
                               for f, v in curve.items()},
        "E3_gate_ablation": e3,
        "E4_validator": {"clean_runs": e4c["runs"], "clean_not_passed": e4c["not_passed"], "planted": pn, "caught": pc,
                         "wilson95": wilson(pc, pn),
                         "by_family": {k: {"caught": v["caught"], "n": v["n"], "no_op": v["no_op"],
                                           "checks": dict(v["checks"])} for k, v in e4.items()}},
    }


def to_markdown(r: dict) -> str:
    e1, e2, e3, e4 = r["E1_recall"], r["E2_detection_curve"], r["E3_gate_ablation"], r["E4_validator"]
    L = ["# Evaluation results", "",
         f"Generated by `python -m portfolio_agent.evals --seeds {e1['seeds']}` on the Halcyon data. Each seed picks an "
         "as-of month between 2021-01 and 2025-12 and plants four business anomalies and two data issues into it.", "",
         "## E1 Monitor recall (planted anomaly in the top 10, right direction)", "",
         f"Overall: **{e1['found']}/{e1['planted']}** (Wilson 95% {e1['wilson95'][0]}-{e1['wilson95'][1]}), median rank "
         f"{e1['median_rank']}.", "", "| Planted anomaly | What was planted | Found | Wilson 95% |", "|---|---|---|---|"]
    what = {"listing_outage": "one listing at 2% of its month", "price_error": "one listing at 3x",
            "demand_collapse": "every established listing of a title at 0.4x", "clawback": "one listing at -0.5x its base (negative net)"}
    for k, v in e1["by_kind"].items():
        L.append(f"| {k} | {what[k]} | {v['found']}/{v['planted']} | {v['wilson95'][0]}-{v['wilson95'][1]} |")
    L += ["", f"- Unplanted alerts: {e1['unplanted_alerts_per_month']} per month. The base data is not clean by construction, "
          "so some are real movements in Halcyon's history and some are noise.",
          f"- Data issues reported as performance without a data-issue note: {e1['data_issues_reported_without_note']}.", "",
          "## E2 Detection curve (one monitored listing with a $2,000+ base shocked, everything else as delivered)", "",
          "| Shock | " + " | ".join(f"x{f}" for f in e2) + " |", "|---|" + "---|" * len(e2),
          "| Flagged | " + " | ".join(f"{v['rate']:.0%}" for v in e2.values()) + " |",
          f"| n | " + " | ".join(str(v["n"]) for v in e2.values()) + " |", "",
          f"Near-total losses are caught (x0.1: {e2['0.1']['rate']:.0%}); partial moves mostly are not (x0.5: "
          f"{e2['0.5']['rate']:.0%}, x2: {e2['2.0']['rate']:.0%}, x3: {e2['3.0']['rate']:.0%}). Listings in this data swing "
          "that much on their own promotions, so a monthly monitor with no promotion calendar cannot tell a 3x price "
          "error from a sale. That is the monitor's minimum detectable effect on monthly data, and the main reason the "
          "next version needs weekly data with a promotion calendar.", "",
          "## E3 Gate ablation", "",
          f"- Naive preparation (duplicates summed, missing month read as zero): **{e3['naive_data_issue_alerts']}** data "
          f"issues reported as business anomalies.",
          f"- With the data gate: **{e3['gated_data_issue_alerts']}** (any that remain carry a data-issue note).", "",
          "## E4 Validator calibration", "",
          f"- Clean claim sets: {e4['clean_runs']}; not passed: {e4['clean_not_passed']}.",
          f"- Planted claim errors caught: **{e4['caught']}/{e4['planted']}** (Wilson 95% {e4['wilson95'][0]}-{e4['wilson95'][1]}).",
          "", "| Error family | Caught | Checks that fired |", "|---|---|---|"]
    for k, v in e4["by_family"].items():
        noop = f" ({v['no_op']} skipped: inside tolerance)" if v["no_op"] else ""
        L.append(f"| {k} | {v['caught']}/{v['n']}{noop} | {', '.join(f'{c} ({n})' for c, n in v['checks'].items())} |")
    L += ["", "## How to read this", "",
          "- The planted errors and the checks were written by the same author. E4 shows the checks catch the families "
          "they were designed for; errors nobody anticipated are untested.",
          "- Halcyon is AI-generated evaluation data. Real storefront statements add currency, bundles, restatements and fees.",
          "- These evals cover the deterministic layer. Model behaviour (framing, wording, routing) is covered by the "
          "hand-run cases in `evals/agent_cases.yaml`."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate the portfolio agent's deterministic layer")
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--out", default="docs")
    a = ap.parse_args(argv)
    r = run(a.seeds)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_results.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (out / "eval_results.md").write_text(to_markdown(r), encoding="utf-8")
    print(to_markdown(r))


if __name__ == "__main__":
    main()
