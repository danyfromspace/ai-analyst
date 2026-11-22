# Portfolio exceptions: 2025-12

**Question:** Which titles need attention this month?

Metric `halcyon_net_usd` (net_usd as delivered, USD), calendar month as delivered (source states no timezone). Expected month = median of the listing's 6 previous months, moved by the median change of its storefront peers that month.

## Data gate: WARN
- **duplicate_row** (warn): brassworkbastion::steam 2025-12: row loaded more than once; extra copy dropped. Action: deduplicated; report the load defect
- **missing_row** (warn): cindervale::steam: no row for 2025-12 although each of the 6 months before has one. Action: excluded this month: a missing row may be zero sales or a load gap
- **negative_net** (warn): mudlarkbay::steam 2025-12: net is negative ($-10,746.20). Action: kept: refunds or clawbacks can exceed sales; flag for review

## Ranked exceptions (by dollars at stake)

| Rank | Title | Storefronts | vs expected (USD) | Hypothesis to check | Check |
|---|---|---|---|---|---|
| 1 | Starfall Chronicles | steam | -162,258 | store listing or entitlement problem on that storefront | store page status, partner portal notices, delisting or rating changes |
| 2 | Mudlark Bay | steam | -34,386 | refund or chargeback clawback (net revenue is negative) | storefront payout statement adjustments and refund reasons |
| 3 | Cindervale | nintendo | +21,146 | unplanned price change or promotion not on the calendar | price history on that storefront; promotion calendar |
| 4 | The Wild Odyssey | steam | -13,687 | store listing or entitlement problem on that storefront | store page status, partner portal notices, delisting or rating changes |

## Not monitored this month (5 listings)
- 1 x data gate: missing row
- 3 x a gap in the 6 months before
- 1 x too little history to score

## Claims (what the validator checks)
- `C0` Catalog net revenue for 2025-12 was $1,162,952.
- `C1` Starfall Chronicles (steam) net revenue was $162,258 below its expected month; likely explanation to check: store listing or entitlement problem on that storefront.
- `C2` Mudlark Bay (steam) net revenue was $34,386 below its expected month; likely explanation to check: refund or chargeback clawback (net revenue is negative).
- `C3` Cindervale (nintendo) net revenue was $21,146 above its expected month; likely explanation to check: unplanned price change or promotion not on the calendar.
- `C4` The Wild Odyssey (steam) net revenue was $13,687 below its expected month; likely explanation to check: store listing or entitlement problem on that storefront.

Monitoring data shows *where* revenue moved. Each hypothesis needs its check before anyone acts.
