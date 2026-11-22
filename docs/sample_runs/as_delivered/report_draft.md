# Portfolio exceptions: 2025-12

**Question:** Which titles need attention this month?

Metric `halcyon_net_usd` (net_usd as delivered, USD), calendar month as delivered (source states no timezone). Expected month = median of the listing's 6 previous months, moved by the median change of its storefront peers that month.

## Data gate: PASS

## Ranked exceptions (by dollars at stake)

| Rank | Title | Storefronts | vs expected (USD) | Hypothesis to check | Check |
|---|---|---|---|---|---|
| 1 | Cindervale | nintendo | +21,146 | unplanned price change or promotion not on the calendar | price history on that storefront; promotion calendar |
| 2 | The Wild Odyssey | steam | -14,014 | store listing or entitlement problem on that storefront | store page status, partner portal notices, delisting or rating changes |

## Not monitored this month (4 listings)
- 3 x a gap in the 6 months before
- 1 x too little history to score

## Claims (what the validator checks)
- `C0` Catalog net revenue for 2025-12 was $1,408,142.
- `C1` Cindervale (nintendo) net revenue was $21,146 above its expected month; likely explanation to check: unplanned price change or promotion not on the calendar.
- `C2` The Wild Odyssey (steam) net revenue was $14,014 below its expected month; likely explanation to check: store listing or entitlement problem on that storefront.

Monitoring data shows *where* revenue moved. Each hypothesis needs its check before anyone acts.
