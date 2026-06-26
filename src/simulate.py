"""
simulate.py  --  COMPONENT 1: DATA GENERATION
=============================================
Generates a realistic synthetic FMCG panel (SKU x region x week) from a
structural log-linear demand model with KNOWN ground-truth parameters.

Outputs (in data/):
  - fact_sales.csv      : the OBSERVED dataset an analyst would see
  - dim_product.csv     : product master (list price + standard cost) - known to analyst
  - ground_truth.json   : ALL hidden true parameters + counterfactual aggregates
  - counterfactual.csv   : promo-OFF twin (used ONLY for building ground truth;
                           the analysis scripts must not read this)

Design recap (see README for the full writeup):
  log(units) = intercept + elasticity*log(price/ref) + log(season) + trend*(t/T)
               + log(region_mult) + promo_lift*promo + log(1-cannib)*aggressor_promo
               + noise
The counterfactual twin reuses the SAME noise draws with promos switched off, so
"true uplift" and "true incremental margin" are exactly what each promo CAUSED.
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path

import config as C

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
DATA.mkdir(exist_ok=True)

rng = np.random.default_rng(C.SEED)

# ---------------------------------------------------------------------------
# 0. scaffolding
# ---------------------------------------------------------------------------
weeks = pd.date_range(C.START_DATE, periods=C.N_WEEKS, freq="W-MON")
week_idx = np.arange(C.N_WEEKS)
months = weeks.month.to_numpy()

regions = list(C.REGIONS.keys())
skus = list(C.SKUS.keys())

# reference price per SKU = base list price (centre of log-price)
ref_price = {s: C.SKUS[s]["base_price"] for s in skus}

# ---------------------------------------------------------------------------
# 1. build promo + discount flags per (sku, week)
# ---------------------------------------------------------------------------
promo_flag = {s: np.zeros(C.N_WEEKS, dtype=int) for s in skus}
discount   = {s: np.zeros(C.N_WEEKS) for s in skus}
for s, p in C.PROMO_CALENDAR.items():
    for (start, length) in p["windows"]:
        promo_flag[s][start:start + length] = 1
        discount[s][start:start + length] = p["discount_depth"]

# aggressor-on-promo indicator for each victim
victim_under_attack = {s: np.zeros(C.N_WEEKS, dtype=int) for s in skus}
cannib_lookup = {}  # victim -> (aggressor, frac)
for pair in C.CANNIBALIZATION:
    agg, vic, frac = pair["aggressor"], pair["victim"], pair["cannib_frac"]
    cannib_lookup[vic] = (agg, frac)
    victim_under_attack[vic] = promo_flag[agg].copy()

# ---------------------------------------------------------------------------
# 2. pre-draw ALL noise so observed & counterfactual share identical draws
# ---------------------------------------------------------------------------
# demand noise per (sku, region, week)
demand_noise = {
    s: {r: rng.normal(0, C.SKUS[s]["noise_sd"], C.N_WEEKS) for r in regions}
    for s in skus
}
# independent log-price noise per (sku, region, week)  -> identification
price_noise = {
    s: {r: rng.normal(0, C.PRICE_NOISE_SD, C.N_WEEKS) for r in regions}
    for s in skus
}

# ---------------------------------------------------------------------------
# 3. generate observed + counterfactual rows
# ---------------------------------------------------------------------------
obs_rows, cf_rows = [], []

for s in skus:
    meta = C.SKUS[s]
    cat = meta["category"]
    season = np.array([C.SEASONALITY[cat][m] for m in months])
    e = meta["elasticity_true"]
    base_demand = meta["base_demand"]
    trend = meta["trend_true"]
    plift = C.PROMO_CALENDAR.get(s, {}).get("promo_lift", 0.0)

    for r in regions:
        rmeta = C.REGIONS[r]
        # ---- price path (same for obs & cf EXCEPT the promo discount) ----
        base_path = (meta["base_price"] * rmeta["region_price_mult"]
                     * np.exp(price_noise[s][r]))
        price_obs = base_path * (1 - discount[s])      # promo cuts price
        price_cf  = base_path.copy()                   # no promo cut

        # ---- structural log-demand pieces shared by obs & cf ----
        log_base = (np.log(base_demand)
                    + np.log(season)
                    + trend * (week_idx / C.N_WEEKS)
                    + np.log(rmeta["region_demand_mult"])
                    + demand_noise[s][r])

        # OBSERVED: includes price response + promo lift + cannibalization
        log_units_obs = (log_base
                         + e * np.log(price_obs / ref_price[s])
                         + plift * promo_flag[s])
        if s in cannib_lookup:
            _, frac = cannib_lookup[s]
            # victim loses share only when attacked AND not on its own promo
            attacked = victim_under_attack[s] * (1 - promo_flag[s])
            log_units_obs = log_units_obs + np.log(1 - frac) * attacked
        units_obs = np.clip(np.round(np.exp(log_units_obs)), 0, None).astype(int)

        # COUNTERFACTUAL: same noise, promos OFF (no discount, no lift, no cannib)
        log_units_cf = log_base + e * np.log(price_cf / ref_price[s])
        units_cf = np.clip(np.round(np.exp(log_units_cf)), 0, None).astype(int)

        for t in range(C.N_WEEKS):
            obs_rows.append((
                weeks[t].date().isoformat(), s, cat, r,
                int(units_obs[t]), round(float(price_obs[t]), 2),
                int(promo_flag[s][t]), round(float(discount[s][t]), 3),
                round(float(units_obs[t] * price_obs[t]), 2),
            ))
            cf_rows.append((
                weeks[t].date().isoformat(), s, r,
                int(units_cf[t]), round(float(price_cf[t]), 2),
            ))

fact = pd.DataFrame(obs_rows, columns=[
    "date", "sku", "category", "region", "units", "price",
    "promo_flag", "discount_depth", "revenue"])
cf = pd.DataFrame(cf_rows, columns=["date", "sku", "region", "units_cf", "price_cf"])

fact.to_csv(DATA / "fact_sales.csv", index=False)
cf.to_csv(DATA / "counterfactual.csv", index=False)

# product dimension (analyst-visible cost master)
dim = pd.DataFrame([
    {"sku": s, "name": C.SKUS[s]["name"], "category": C.SKUS[s]["category"],
     "list_price": C.SKUS[s]["base_price"], "unit_cost": C.SKUS[s]["unit_cost"],
     "gross_margin_pct": round(1 - C.SKUS[s]["unit_cost"] / C.SKUS[s]["base_price"], 3)}
    for s in skus])
dim.to_csv(DATA / "dim_product.csv", index=False)

# ---------------------------------------------------------------------------
# 4. build GROUND TRUTH (true params + counterfactual-derived true effects)
# ---------------------------------------------------------------------------
merged = fact.merge(cf, on=["date", "sku", "region"])

def true_promo_effects(sku):
    """True uplift % and true incremental margin for a SKU's promo weeks,
    derived from the counterfactual twin (identical noise)."""
    cal = C.PROMO_CALENDAR.get(sku)
    if cal is None:
        return None
    cost = C.SKUS[sku]["unit_cost"]
    sub = merged[(merged.sku == sku) & (merged.promo_flag == 1)]
    actual_u = sub["units"].sum()
    cf_u = sub["units_cf"].sum()
    uplift = actual_u / cf_u - 1 if cf_u > 0 else np.nan
    # incremental margin = actual promo margin - counterfactual margin
    actual_margin = ((sub["price"] - cost) * sub["units"]).sum()
    cf_margin = ((sub["price_cf"] - cost) * sub["units_cf"]).sum()
    incr_margin = actual_margin - cf_margin
    return {
        "discount_depth": cal["discount_depth"],
        "promo_lift_param": cal["promo_lift"],
        "label_design": cal["label"],
        "true_uplift_pct": round(float(uplift) * 100, 2),
        "true_incremental_units": int(actual_u - cf_u),
        "true_incremental_margin": round(float(incr_margin), 0),
        "true_net_profitable": bool(incr_margin > 0),
    }

def true_cannibalization(pair):
    """True cannibalization %: victim volume lost during aggressor promos
    (victim not on own promo), vs counterfactual."""
    agg, vic, frac = pair["aggressor"], pair["victim"], pair["cannib_frac"]
    aggp = pd.Series(promo_flag[agg], index=range(C.N_WEEKS))
    vicp = pd.Series(promo_flag[vic], index=range(C.N_WEEKS))
    attack_weeks = weeks[(aggp.values == 1) & (vicp.values == 0)]
    sub = merged[(merged.sku == vic) & (merged.date.isin(
        [d.date().isoformat() for d in attack_weeks]))]
    lost = sub["units_cf"].sum() - sub["units"].sum()
    realized = lost / sub["units_cf"].sum() if sub["units_cf"].sum() > 0 else np.nan
    return {
        "aggressor": agg, "victim": vic,
        "cannib_frac_param": frac,
        "true_cannib_pct_realized": round(float(realized) * 100, 2),
        "true_units_lost": int(lost),
    }

ground_truth = {
    "_README": ("HIDDEN ground-truth parameters. Analysis scripts must NOT read "
                "this file. Used only by validate step in elasticity.py."),
    "seed": C.SEED, "n_weeks": C.N_WEEKS, "start_date": C.START_DATE,
    "regions": C.REGIONS, "seasonality": C.SEASONALITY,
    "price_noise_sd": C.PRICE_NOISE_SD,
    "skus": {s: {
        "category": C.SKUS[s]["category"], "name": C.SKUS[s]["name"],
        "base_price": C.SKUS[s]["base_price"], "unit_cost": C.SKUS[s]["unit_cost"],
        "elasticity_true": C.SKUS[s]["elasticity_true"],
        "trend_true": C.SKUS[s]["trend_true"], "noise_sd": C.SKUS[s]["noise_sd"],
    } for s in skus},
    "promo_effects_true": {s: true_promo_effects(s)
                           for s in C.PROMO_CALENDAR},
    "cannibalization_true": [true_cannibalization(p) for p in C.CANNIBALIZATION],
}

with open(DATA / "ground_truth.json", "w") as f:
    json.dump(ground_truth, f, indent=2)

# ---------------------------------------------------------------------------
# 5. console summary
# ---------------------------------------------------------------------------
print("=" * 70)
print("SIMULATION COMPLETE")
print("=" * 70)
print(f"fact_sales.csv : {len(fact):,} rows "
      f"({len(skus)} SKUs x {len(regions)} regions x {C.N_WEEKS} weeks)")
print(f"date range     : {fact.date.min()} -> {fact.date.max()}")
print(f"total units    : {fact.units.sum():,}")
print(f"total revenue  : INR {fact.revenue.sum():,.0f}")
print(f"promo weeks    : {fact.promo_flag.sum():,} SKU-region-weeks on promo")
print("\nGround-truth promo design (audit):")
for s, e in ground_truth["promo_effects_true"].items():
    if e:
        tag = "PROFIT" if e["true_net_profitable"] else "LOSS  "
        print(f"  {s:14s} {e['label_design']:4s} disc={e['discount_depth']:.0%} "
              f"true_uplift={e['true_uplift_pct']:6.1f}%  "
              f"incr_margin={e['true_incremental_margin']:>12,.0f}  [{tag}]")
print("\nGround-truth cannibalization design (audit):")
for c in ground_truth["cannibalization_true"]:
    print(f"  {c['aggressor']:14s} -> {c['victim']:14s} "
          f"param={c['cannib_frac_param']:.0%}  "
          f"realized={c['true_cannib_pct_realized']:.1f}%")
print("\nFiles written to data/: fact_sales.csv, dim_product.csv, "
      "ground_truth.json, counterfactual.csv")
