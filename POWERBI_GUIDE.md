# Power BI Dashboard Guide — FMCG Sales & Promotion Analytics

This guide turns the four exported CSVs into a 3-page executive dashboard. It tells you
exactly which visuals to drop on each page and gives copy-paste DAX measures.

## Data model (set up first)

Import these four files from the `powerbi/` folder, plus build one Date table.

| Table | Grain | Role |
|---|---|---|
| `fact_sales` | date × sku × region | Fact: units, price, revenue, promo flag, discount |
| `dim_product` | sku | Dimension: list price, unit cost, gross margin % |
| `elasticity_summary` | sku | Analysis output: est vs true elasticity/uplift/margin |
| `forecast_vs_actual` | date × sku | Forecast holdout: actual, baseline, lgbm, suggested order |

**Build a Date table** (Modeling → New Table):
```DAX
Date =
ADDCOLUMNS (
    CALENDAR ( DATE(2023,1,1), DATE(2024,12,31) ),
    "Year", YEAR([Date]),
    "Month", FORMAT([Date],"MMM"),
    "MonthNo", MONTH([Date]),
    "Quarter", "Q" & FORMAT([Date],"Q")
)
```

**Relationships** (all single-direction, one-to-many from the "one" side):
- `dim_product[sku]` → `fact_sales[sku]`
- `dim_product[sku]` → `elasticity_summary[sku]`
- `dim_product[sku]` → `forecast_vs_actual[sku]`
- `Date[Date]` → `fact_sales[date]`
- `Date[Date]` → `forecast_vs_actual[date]`

Mark `Date` as a date table (Table tools → Mark as date table) so time-intelligence works.

---

## DAX measures (create all in a dedicated `_Measures` table)

**1. Core revenue & margin**
```DAX
Total Revenue = SUM ( fact_sales[revenue] )

Total Units = SUM ( fact_sales[units] )

Gross Margin INR =
SUMX (
    fact_sales,
    fact_sales[units] * ( fact_sales[price] - RELATED ( dim_product[unit_cost] ) )
)
```

**2. Promo ROI %** — net incremental margin recovered by the analysis, divided by the
discount money actually spent. (Margin impact comes from `elasticity_summary`; discount
spend is computed live from the fact table.)
```DAX
Promo Discount Spend =
SUMX (
    FILTER ( fact_sales, fact_sales[promo_flag] = 1 ),
    fact_sales[units] * ( RELATED ( dim_product[list_price] ) - fact_sales[price] )
)

Promo Net Margin Impact = SUM ( elasticity_summary[margin_impact] )

Promo ROI % =
DIVIDE ( [Promo Net Margin Impact], [Promo Discount Spend] )
```
A **negative Promo ROI %** = the promo destroyed value (the deliberately-bad promos
surface here in red).

**3. YoY revenue growth %**
```DAX
Revenue PY =
CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( 'Date'[Date] ) )

YoY Growth % =
DIVIDE ( [Total Revenue] - [Revenue PY], [Revenue PY] )
```

**4. Forecast accuracy (MAPE) — LightGBM vs baseline**
```DAX
MAPE LightGBM % =
AVERAGEX (
    forecast_vs_actual,
    DIVIDE ( ABS ( forecast_vs_actual[actual] - forecast_vs_actual[forecast_lgbm] ),
             forecast_vs_actual[actual] )
) * 100

MAPE Baseline % =
AVERAGEX (
    forecast_vs_actual,
    DIVIDE ( ABS ( forecast_vs_actual[actual] - forecast_vs_actual[forecast_baseline] ),
             forecast_vs_actual[actual] )
) * 100
```

**5. Elasticity recovery error** (proves the model recovers truth)
```DAX
Elasticity MAPE vs Truth % =
AVERAGEX (
    elasticity_summary,
    DIVIDE ( ABS ( elasticity_summary[estimated_elasticity] - elasticity_summary[true_elasticity] ),
             ABS ( elasticity_summary[true_elasticity] ) )
) * 100
```

---

## Page 1 — Executive Overview ("what happened")

- **Top row: 4 KPI cards** → `Total Revenue`, `Total Units`, `YoY Growth %`, `Gross Margin INR`.
- **Line chart**: `Total Revenue` by `Date[Date]` (week), legend = `category`.
  Shows the trend + festival/summer spikes.
- **Clustered bar**: `Total Revenue` by `region`, legend `category`.
- **Slicers**: `category`, `region`, `Date[Year]` down the left rail.
- *Insight callout text box*: "~7% YoY growth; Personal Care drives the seasonal peaks."

## Page 2 — Elasticity & Promo Validation ("does the method work")

This is the differentiator page — lead your interview demo here.

- **Scatter chart (the money visual)**: X = `true_elasticity`, Y = `estimated_elasticity`,
  details = `sku`, play axis off. Add a reference line y = x (Analytics pane → Y-axis
  constant won't draw a diagonal, so add a calculated `true_elasticity` line as a second
  series, or use a measure pair). Title: "Estimated vs True Elasticity — points on the
  diagonal = recovered truth."
- **Card**: `Elasticity MAPE vs Truth %` (shows ~6.6%).
- **Clustered bar**: `promo_uplift_est_pct` vs `promo_uplift_true_pct` by `sku`.
- **Table / matrix**: `sku`, `estimated_elasticity`, `true_elasticity`, `margin_impact`,
  `net_profitable`, `cannibalization_flag`. Conditional-format `margin_impact` red/green
  on sign, and put a filter icon on `cannibalization_flag = TRUE`.
- **Card**: `Promo ROI %` (turns red for the loss-making promos).

## Page 3 — Forecast & Suggested Orders ("what to do next")

- **Two cards**: `MAPE Baseline %` and `MAPE LightGBM %` side by side (13.4% vs 9.6%).
- **Line chart**: for a selected SKU (slicer), plot `actual`, `forecast_baseline`,
  `forecast_lgbm` over `date`, with `suggested_order_qty` as a dotted overlay.
- **Bar chart**: `suggested_order_qty` by `sku` for the next planning week (filter to
  `FIRSTDATE`), so planners see the order list at a glance.
- **SKU slicer** + a tooltip showing per-SKU MAPE.

> Demo flow for the interview: Page 1 (the business), Page 2 (prove the model recovers
> true effects and catches the bad promos), Page 3 (turn it into an order recommendation).
