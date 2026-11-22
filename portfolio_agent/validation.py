"""Validation layer: blind re-derivation, deterministic checks, verdict.

Independence
- This module never imports portfolio_agent.portfolio, pandas or numpy. It re-implements each claim's
  written definition from the raw CSV with the standard library (csv, math, statistics). A bug in the
  monitor's code path does not repeat here.
- It sees the claims (blind_view) and the raw rows, never the analyst's reasoning or intermediate tables.

Checks, graded blocking / major / minor
  V1 rederive             value matches the re-derived value within 0.5% or $1          blocking
  V2 text_matches         the dollar figure in the sentence is the claim value            blocking
  V3 scope_exists         month and listings exist in the data                            blocking
  V4 data_issue_leak      a listing with a data issue this month reported as
                          performance without a data-issue note                           blocking
  V5 labels               metric, period and revenue scope labels present and correct     major
  V6 expected_definition  delta claims use the governed expected-month definition         major
  V7 causal_language      "caused", "due to", "because", "drove", "proves"...               major
  V8 hypothesis_check     a delta claim names a hypothesis or check                       minor
Verdict: any blocking -> FAIL; else any major -> REVISE; else PASS.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass

GOVERNED = {
    "metric": "halcyon_net_usd",
    "period": "calendar month as delivered (source states no timezone)",
    "revenue_scope": "net_usd as delivered",
    "expected_definition": ("median of the listing's 6 previous months, moved by the median change "
                            "of its storefront peers that month"),
}
CAUSAL = re.compile(r"\b(caused|causes|due to|because|drove|driven by|proves?|resulted in|led to)\b", re.I)
HEDGE = re.compile(r"\b(likely|consistent with|hypothesis|to check|may|might|could)\b", re.I)
MONEY = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]+)?)\s?(k|m)?", re.I)
REL_TOL, ABS_TOL = 0.005, 1.0


@dataclass
class Finding:
    claim_id: str
    check: str
    severity: str
    detail: str
    fix: str


def _add(month: str, k: int) -> str:
    t = int(month[:4]) * 12 + int(month[5:7]) - 1 + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


class Raw:
    """Raw monthly rows read with csv; exact duplicate listing-months are kept once and recorded."""

    def __init__(self, monthly_path, catalog_path):
        self.platform = {}
        with open(catalog_path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                self.platform[r["listing_id"].strip()] = r["platform"].strip()
        self.s: dict[str, dict[str, float]] = defaultdict(dict)
        self.duplicates: set[tuple[str, str]] = set()
        with open(monthly_path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                lid, m = r["listing_id"].strip(), r["month"].strip()
                if m in self.s[lid]:
                    self.duplicates.add((lid, m))
                    continue
                self.s[lid][m] = float(r["net_usd"].replace(",", ""))
        self.months = sorted({m for s in self.s.values() for m in s})

    def base(self, lid: str, m: str):
        vals = [self.s[lid].get(_add(m, -k)) for k in range(1, 7)]
        return None if any(v is None for v in vals) else statistics.median(vals)

    def peer(self, platform: str, m: str) -> float:
        lrs = []
        for lid, s in self.s.items():
            if self.platform.get(lid) == platform and m in s:
                b = self.base(lid, m)
                if b is not None:
                    lrs.append(math.log((max(s[m], 0.0) + 1) / (max(b, 0.0) + 1)))
        return statistics.median(lrs) if len(lrs) >= 10 else 0.0

    def missing_rows(self, m: str) -> set[str]:
        return {lid for lid, s in self.s.items()
                if m not in s and all(_add(m, -k) in s for k in range(1, 7))}


def rederive(claim: dict, raw: Raw) -> float:
    m = claim["filters"]["month"]
    if claim["kind"] == "total":
        return round(sum(s[m] for s in raw.s.values() if m in s), 2)
    if claim["kind"] == "delta_vs_expected":
        total = 0.0
        for lid in claim["filters"]["listings"]:
            b = raw.base(lid, m)
            if b is None or m not in raw.s[lid]:
                raise ValueError(f"cannot re-derive {claim['id']}: {lid} lacks {m} or its 6 prior months")
            e = (b + 1) * math.exp(raw.peer(raw.platform[lid], m)) - 1
            total += raw.s[lid][m] - e
        return round(total, 2)
    raise ValueError(f"unknown claim kind {claim['kind']!r}")


def blind_view(claims: list[dict]) -> list[dict]:
    keep = ("id", "kind", "metric", "period", "revenue_scope", "unit", "filters", "expected_definition",
            "value", "text")
    return [{k: c[k] for k in keep if k in c} for c in claims]


def claims_hash(claims: list[dict]) -> str:
    return hashlib.sha256(json.dumps(blind_view(claims), sort_keys=True).encode("utf-8")).hexdigest()[:16]


def money_in_text(text: str) -> list[float]:
    out = []
    for num, suf in MONEY.findall(text):
        out.append(float(num.replace(",", "")) * ({"k": 1e3, "m": 1e6}[suf.lower()] if suf else 1))
    return out


def check_claim(c: dict, raw: Raw) -> tuple[list[Finding], dict]:
    cid, f = c.get("id", "?"), c.get("filters", {})
    m = f.get("month")
    fs: list[Finding] = []
    row = {"claim_id": cid, "claimed": c.get("value"), "rederived": None, "status": "not run"}

    missing = [] if m in raw.months else [f"month {m}"]
    missing += [f"listing {l}" for l in f.get("listings", []) if l not in raw.s]
    if missing:
        fs.append(Finding(cid, "scope_exists", "blocking", "not in data: " + ", ".join(missing),
                          "use a month and listings that exist"))
        return fs, row

    try:
        rv = rederive(c, raw)
        row["rederived"] = rv
        ok = abs(rv - c["value"]) <= max(ABS_TOL, REL_TOL * abs(rv))
        row["status"] = "pass" if ok else "fail"
        if not ok:
            fs.append(Finding(cid, "rederive", "blocking", f"claimed {c['value']:,.2f}, re-derived {rv:,.2f}",
                              f"use {rv:,.2f} and update the sentence"))
    except ValueError as e:
        row["status"] = "fail"
        fs.append(Finding(cid, "rederive", "blocking", str(e), "say what data is missing instead of a number"))

    text = c.get("text", "")
    amounts, target = money_in_text(text), abs(c.get("value", 0))
    if not amounts:
        fs.append(Finding(cid, "text_matches", "blocking", "no dollar figure in the text", "state the number"))
    elif not any(abs(a - target) <= max(1.0, 0.005 * target) for a in amounts):
        fs.append(Finding(cid, "text_matches", "blocking",
                          f"text says {', '.join(f'${a:,.0f}' for a in amounts)}; value is ${target:,.0f}",
                          "make the sentence use the claim value"))

    if c.get("kind") == "delta_vs_expected":
        flagged = {l for (l, mm) in raw.duplicates if mm == m} | raw.missing_rows(m)
        hit = [l for l in f.get("listings", []) if l in flagged]
        if hit and not re.search(r"data (issue|problem|gap)|duplicate|missing row", text, re.I):
            fs.append(Finding(cid, "data_issue_leak", "blocking",
                              f"{', '.join(hit)} has a data issue in {m} but is reported as performance",
                              "drop the claim or report it as a data issue"))
        if c.get("expected_definition") != GOVERNED["expected_definition"]:
            fs.append(Finding(cid, "expected_definition", "major",
                              f"expected month defined as {c.get('expected_definition')!r}",
                              "use the governed expected-month definition"))
        if not HEDGE.search(text):
            fs.append(Finding(cid, "hypothesis_check", "minor", "no hypothesis or check named",
                              "add the likely explanation as a hypothesis with its check"))

    for key in ("metric", "period", "revenue_scope"):
        if c.get(key) != GOVERNED[key]:
            fs.append(Finding(cid, "labels", "major", f"{key} is {c.get(key)!r}",
                              f"set {key} to {GOVERNED[key]!r}"))

    hit = CAUSAL.search(text)
    if hit:
        fs.append(Finding(cid, "causal_language", "major", f"states a cause: '{hit.group(0)}'",
                          "describe the movement; name the hypothesis and the check that would confirm it"))
    return fs, row


def verdict(findings: list[Finding]) -> str:
    sev = {f.severity for f in findings}
    return "FAIL" if "blocking" in sev else ("REVISE" if "major" in sev else "PASS")


def validate(claims: list[dict], monthly_path, catalog_path) -> dict:
    raw = Raw(monthly_path, catalog_path)
    findings, table = [], []
    for c in blind_view(claims):
        fs, row = check_claim(c, raw)
        findings += fs
        table.append(row)
    return {"verdict": verdict(findings), "claims_hash": claims_hash(claims), "claims_checked": len(table),
            "rederivation": table, "findings": [asdict(f) for f in findings],
            "not_checked": ["whether the hypotheses are the true causes (needs the named checks)",
                            "anything outside the monthly file (prices, promotions, store status)"]}
