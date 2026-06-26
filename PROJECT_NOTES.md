# Project Notes — FMCG Sales & Promotion Analytics (detailed write-up)

A complete, validated analytics pipeline for retail/FMCG revenue growth management (RGM):
measure **price elasticity**, quantify **promotion uplift and net profitability**, detect
**cannibalization** between sister SKUs, and **forecast demand** to drive suggested order
quantities — all wired into a **Power BI** dashboard.

The distinguishing feature of this project is **ground-truth validation**: the dataset is
simulated from a known structural demand model, so every estimate the analysis produces can
be checked against the true value that generated the data. The models are never shown those
true parameters — they recover them from the observed sales alone.

---

## Why simulated data (read this first)

Real promotional data never comes with an answer key. If you fit an elasticity of −1.4 on a
real dataset, you have no way to prove it's right — only that it's plausible. That makes it
impossible to demonstrate that a causal method actually *works* versus merely *runs*.

So I inverted the problem. I wrote down a structural demand model with **known** elasticities,
seasonality, promo uplifts, and cannibalization rates, generated two years of weekly sales
from it (with realistic noise), then **hid those parameters** and asked the analysis to recover
them from observed data only. The headline result — elasticity recovered to within **6.6% MAPE**
while a naive estimator is off by **55%** — is only a meaningful claim *because* there is a
ground truth to score against.

This is a deliberate methodological choice, not a shortcut. It lets me prove the pipeline is
correct before pointing it at messy real data, and it's the part I'd lead with in an interview:
*"I didn't just build models, I built a way to know whether they were right."*

---

## What's in the box

| Component | Script | Output |
|---|---|---|
| 1. Data generation | `src/simulate.py` | `data/fact_sales.csv`, `dim_product.csv`, `ground_truth.json` |
| 2. EDA (6 charts) | `src/eda.py` | `outputs/eda/*.png` |
| 3. Elasticity / uplift / cannibalization / P&L + **validation** | `src/elasticity.py` | `data/elasticity_summary.csv`, `outputs/elasticity/*` |
| 4. Forecasting (Holt-Winters vs LightGBM) | `src/forecasting.py` | `data/forecast_vs_actual.csv`, `outputs/forecasting/*` |
| 5. Power BI exports + DAX guide | `src/export_powerbi.py`, `POWERBI_GUIDE.md` | `powerbi/*.csv` |
| 6. Write-up | `README.md` | this file |

**Dataset:** 16 SKUs across 3 categories (Oral / Personal / Home Care), 5 regions, 104 weeks
(2023–2024) = 8,320 rows. ~2.76B INR revenue, 20.2M units, 305 promo SKU-region-weeks.

---

## How to run

```bash
pip install -r requirements.txt          # statsmodels, lightgbm, pandas, numpy, matplotlib
python run_all.py                          # runs all components in order
# or run individually, in order:
python src/simulate.py
python src/eda.py
python src/elasticity.py
python src/forecasting.py
python src/export_powerbi.py
```

Then open Power BI Desktop and follow `POWERBI_GUIDE.md` to load the four CSVs in `powerbi/`
and build the three dashboard pages.

> The analysis scripts read only `fact_sales.csv` / `dim_product.csv`. They are **forbidden**
> from reading the true parameters in `config.py` or `counterfactual.csv`. The single exception
> is the validation block in `elasticity.py`, which opens `ground_truth.json` *only to score*
> estimates that were already produced — never to inform them.

---

## Simulation design (how the ground truth is built)

Demand is generated from a log-linear structural model per SKU *s*, region *r*, week *t*:

```
log(units) = intercept
           + elasticity_s · log(price / ref_price)      # true price response
           + log(seasonality[category, month])           # category-specific seasonality
           + trend_s · (t / 104)                          # gentle per-SKU trend
           + log(region_mult[r])                          # regional demand level
           + promo_lift_s · promo_flag                    # non-price display/feature lift
           + log(1 − cannib_frac) · aggressor_on_promo    # sister-SKU cannibalization
           + noise
```

Two design decisions make recovery honest rather than circular:

1. **Price varies outside promotions.** I inject regional price multipliers and ~4% weekly
   log-price noise *everywhere*, plus varying discount depths. Without this, price and the promo
   flag would be collinear and elasticity would be unidentifiable. Because price moves on its own,
   the `log(price)` coefficient captures **pure elasticity** while `promo_flag` absorbs the
   separate display/feature lift.

2. **Truth is defined by a counterfactual twin.** I re-run the exact same noise draws with every
   promo switched **off** (flag = 0, discount = 0, cannibalization = 0). True uplift is then
   `actual / counterfactual − 1` over promo weeks, and true incremental margin is
   `actual margin − counterfactual margin`. "Truth" is therefore precisely *what each promotion
   caused* — the cleanest possible target to validate against.

The estimator used in the analysis (OLS with seasonality/region/trend controls) is **different
from** the data-generating process, so good recovery reflects a sound method, not a tautology.

---

## Key findings

**1. Price elasticity is recovered accurately — naive analysis is dangerously wrong.**
Controlling for seasonality, trend, and region, estimated elasticities land within **6.6% MAPE**
of the true values. A naive `log(units) ~ log(price)` regression with no controls is off by
**55.3% MAPE** and frequently flips the sign — staples appear to have *positive* elasticity
because demand and price both rise into seasonal peaks. This is the headline chart
(`outputs/elasticity/07_elasticity_validation.png`): controlled estimates hug the 45° line of
truth; naive estimates scatter wildly.

**2. The pipeline correctly flags unprofitable promotions.** Net-promo-P&L direction is correct
on **8 of 9** measured promos. Both deliberately money-losing flagship promos are caught:
`HC_DET_PWD` (true −6.29M INR, a deep cut on a thin-margin SKU) and `PC_SOAP_REG` (true −3.22M).
The single miss, `HC_DET_LIQ`, is a near-breakeven promo (true −20k) that also acts as a
cannibalization aggressor — so the category-level decision it implies is still correct.

**3. All three cannibalization pairs are detected, with the right magnitude.** Mean absolute
error of **1.6 pp**, all significant at p < 0.05:

| Aggressor → Victim | Estimated | True |
|---|---|---|
| OC_TP_PREM → OC_TP_REG | 16.8% | 18% |
| PC_SOAP_PREM → PC_SOAP_REG | 22.9% | 25% |
| HC_DET_LIQ → HC_DET_PWD | 16.4% | 15% |

**4. Promo uplift is recovered to ~6.5 pp mean absolute error** against true counterfactual lift,
across uplifts ranging from ~75% to ~270%.

**5. Demand forecasting: ML earns its keep where promos make demand spiky.**
On a 13-week holdout, a single global **LightGBM** model (lag/rolling/promo/seasonality features)
achieves **9.6% MAPE** vs **13.4%** for the Holt-Winters–style seasonal baseline — **28% lower
MAPE and 55% lower RMSE** (2,164 vs 4,767 units). The honest nuance: the baseline is already
fine on stable staples, and LightGBM's advantage concentrates on promo-active SKUs
(e.g. `OC_TP_PREM` 75.6% → 7.2% MAPE, `HC_DISH` 27.3% → 7.7%). The mature recommendation is to
use cheap exponential smoothing on steady items and ML where promotions drive volatility.
Forecasts convert to `suggested_order_qty = forecast + 1.65σ` (≈95% service level).

---

## Model & method choices (and why they're defensible)

- **Log-log OLS for elasticity** over fancier causal ML: every coefficient is directly
  interpretable as an elasticity, the identifying assumption (price varies for reasons unrelated
  to the demand shock, after controls) is explicit, and I can defend each control in plain
  language. Simplicity I can explain beats sophistication I can't.
- **Counterfactual-from-baseline for uplift**: fit demand on non-promo weeks, predict what promo
  weeks *would* have sold at normal price, and measure the gap. Transparent and standard.
- **Cannibalization via an aggressor-on-promo dummy** in the victim's own non-promo weeks, so the
  victim's own promotions don't contaminate the estimate.
- **Global LightGBM** (one model, SKU as a categorical feature) over 16 per-SKU models: shares
  statistical strength across SKUs, handles the short 91-week training window, and learns promo
  response from SKUs that promote often.

---

## Honest limitations

- **The data is simulated.** Recovery accuracy on real data will be lower — real demand has
  pantry-loading / forward-buying, competitor actions, stockouts, and structural breaks that this
  generator does not model. The value here is *proving the method is correct* before deploying it.
- **Causal assumptions are simplified.** Elasticity identification rests on price varying
  independently of unobserved demand shocks after controls. On real data I'd stress-test this with
  instrument-style checks, richer fixed effects, and holdout-store designs.
- **No forward-buying / pantry-loading.** A real promo often steals from the *following* weeks;
  this model treats uplift as within-window only, so it likely overstates true incremental volume
  on real data. Modeling post-promo dips is the first extension I'd add.
- **Holt-Winters is approximated.** A full 52-week seasonal Holt-Winters needs two complete cycles;
  the 91-week training window has fewer than two, so the baseline deseasonalizes with monthly
  indices then applies a damped-trend smoother. This is disclosed rather than hidden.
- **Forecasts assume promo calendar and prices are known** for the forecast horizon (true for
  *planned* promotions, which is the intended use — answering "given next quarter's promo plan,
  what should we order?").

---

## Resume bullet (3–4 sentences)

> Built an end-to-end FMCG sales & promotion analytics pipeline in Python (16 SKUs × 5 regions ×
> 2 years) that estimates price elasticity, promotion uplift, cannibalization, and net promo
> profitability, surfaced through a Power BI RGM dashboard. Validated every model against a
> simulated ground truth: recovered true elasticities within **6.6% MAPE** (vs 55% for naive
> analysis), detected all cannibalization pairs within **1.6 pp**, and correctly flagged
> **8 of 9** promotions as profit-positive or -negative — including two deliberately
> loss-making promos. Added demand forecasting (LightGBM vs Holt-Winters) cutting holdout MAPE
> from **13.4% to 9.6%** and converting forecasts into service-level-based suggested order
> quantities.

---

## 30-second interview pitch ("walk me through this")

> "FMCG promotions burn margin when they're priced or targeted wrong, so I built a pipeline that
> measures whether a promo actually pays. The hard part with promo analytics is you can never
> prove your numbers are right on real data — so I simulated two years of sales from a demand
> model with *known* elasticities and promo effects, hid those truths, and made the models
> recover them. They recovered elasticity within about 7%, where a naive analysis was off by 55%
> and even got the sign wrong on staples. The pipeline correctly flagged eight of nine promos as
> winners or losers — including the two I'd deliberately built to lose money — and caught all the
> cannibalization between premium and regular SKUs to within two points. On top of that I
> forecast demand with LightGBM, beating the seasonal baseline by about 30% on MAPE, and turned
> that into suggested order quantities at a 95% service level. The whole thing feeds a Power BI
> dashboard a category manager could use to decide which promotions to keep, cut, or re-price.
> The point isn't the models — it's that I built a way to *know they were right* before trusting
> them."
