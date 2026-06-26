"""
elasticity.py  --  COMPONENT 3: PRICE ELASTICITY / PROMO UPLIFT  (CORE DELIVERABLE)
==================================================================================
Estimates, from the OBSERVED data only:
  (a) price elasticity per SKU      -- log-log regression with controls
  (b) promo uplift % per SKU        -- seasonally-adjusted counterfactual baseline
  (c) cannibalization per pair      -- victim-volume dip during aggressor promos
  (d) net promo profitability        -- incremental margin vs discount subsidy

Then VALIDATES every estimate against data/ground_truth.json (the one place we are
allowed to open the truth) and writes the est-vs-true comparison + a clean summary.

Method choices (all interview-defensible):
  - Elasticity: OLS of log(units) on log(price) PLUS month dummies, region dummies,
    a linear trend and a promo flag. Price is identified because price also moves
    OUTSIDE promos (regional levels + weekly noise), so the log(price) coefficient
    is the pure own-price elasticity, while promo_flag absorbs the non-price lift.
  - Uplift: fit a "business-as-usual" baseline model on NON-PROMO weeks only, then
    predict each promo week at its normal (non-promo) price -> that prediction is the
    no-promo counterfactual. uplift = actual / counterfactual - 1. Honest limitation:
    it assumes the non-promo demand relationship extrapolates into promo weeks and
    that there is no pantry-loading/forward-buying (we checked: no post-promo dip).
  - Cannibalization: add an 'aggressor_on_promo' dummy to the victim's demand model
    (restricted to weeks the victim is NOT on its own promo). 1-exp(coef) = % diverted.
  - Profitability: net = incremental_units*promo_unit_margin
                          - baseline_units*discount_per_unit   (subsidy on base volume)
"""
import json
import warnings
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = HERE.parent / "outputs" / "elasticity"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"figure.dpi": 110, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})

f = pd.read_csv(DATA / "fact_sales.csv", parse_dates=["date"])
dim = pd.read_csv(DATA / "dim_product.csv").set_index("sku")
f["month"] = f["date"].dt.month
f["wk"] = f.groupby("sku").cumcount() // 5  # 0..103 week index (5 regions per week)
f["wk"] = (f["date"].rank(method="dense").astype(int) - 1)
f["logu"] = np.log(f["units"].clip(lower=1))
f["logp"] = np.log(f["price"])

# normal (non-promo) price per sku-region -> reference for discount & counterfactual
norm_price = (f[f.promo_flag == 0].groupby(["sku", "region"])["price"]
              .median().rename("norm_price").reset_index())
f = f.merge(norm_price, on=["sku", "region"], how="left")

skus = list(dim.index)

# ===========================================================================
# (a) ELASTICITY  -- naive vs controlled
# ===========================================================================
elas_rows = []
for s in skus:
    d = f[f.sku == s].copy()
    # naive: no controls (shows omitted-variable bias)
    naive = smf.ols("logu ~ logp", data=d).fit()
    # controlled: season + region + trend + promo flag
    formula = "logu ~ logp + C(month) + C(region) + wk"
    if d.promo_flag.nunique() > 1:
        formula += " + promo_flag"
    ctrl = smf.ols(formula, data=d).fit()
    elas_rows.append({
        "sku": s, "category": dim.loc[s, "category"],
        "elasticity_naive": round(naive.params["logp"], 3),
        "elasticity_est": round(ctrl.params["logp"], 3),
        "elasticity_se": round(ctrl.bse["logp"], 3),
        "r2": round(ctrl.rsquared, 3),
    })
elas = pd.DataFrame(elas_rows)

# ===========================================================================
# (b) PROMO UPLIFT  -- counterfactual baseline from non-promo model
# ===========================================================================
def uplift_for(s):
    d = f[f.sku == s].copy()
    promo = d[d.promo_flag == 1]
    if promo.empty:
        return None
    base = d[d.promo_flag == 0]
    # business-as-usual model fit on non-promo weeks only
    bmodel = smf.ols("logu ~ logp + C(month) + C(region) + wk", data=base).fit()
    # counterfactual: predict promo weeks at their NORMAL (non-promo) price
    cf = promo.copy()
    cf["logp"] = np.log(cf["norm_price"])
    pred_logu = bmodel.predict(cf)
    cf_units = np.exp(pred_logu)
    actual_units = promo["units"].values
    uplift = actual_units.sum() / cf_units.sum() - 1
    return {"sku": s, "promo_uplift_est": round(float(uplift) * 100, 2),
            "promo_weeks": int(promo["date"].nunique()),
            "_cf_units": cf_units.values, "_actual": actual_units,
            "_promo_df": promo, "_cf_baseline_units": cf_units.values}

uplift_data = {s: uplift_for(s) for s in skus}
uplift = pd.DataFrame([{k: v[k] for k in ("sku", "promo_uplift_est", "promo_weeks")}
                       for v in uplift_data.values() if v])

# ===========================================================================
# (c) CANNIBALIZATION  -- victim dip during aggressor promos
# Analyst hypothesis: within a category, a premium SKU's promo may pull volume
# from its regular sibling. Test the within-category premium->regular pairs.
# ===========================================================================
CANDIDATE_PAIRS = [
    ("OC_TP_PREM", "OC_TP_REG"),
    ("PC_SOAP_PREM", "PC_SOAP_REG"),
    ("HC_DET_LIQ", "HC_DET_PWD"),
]
cannib_rows = []
for agg, vic in CANDIDATE_PAIRS:
    # aggressor promo weeks
    agg_weeks = set(f.loc[(f.sku == agg) & (f.promo_flag == 1), "date"])
    d = f[f.sku == vic].copy()
    d["agg_on_promo"] = d["date"].isin(agg_weeks).astype(int)
    # restrict to weeks the victim is NOT on its own promo so we isolate diversion
    d = d[d.promo_flag == 0]
    m = smf.ols("logu ~ logp + C(month) + C(region) + wk + agg_on_promo", data=d).fit()
    coef = m.params["agg_on_promo"]
    est = 1 - np.exp(coef)            # fraction diverted
    cannib_rows.append({
        "aggressor": agg, "victim": vic,
        "cannib_pct_est": round(float(est) * 100, 2),
        "coef": round(float(coef), 4),
        "p_value": round(float(m.pvalues["agg_on_promo"]), 4),
        "cannibalization_flag": bool(est > 0.02 and m.pvalues["agg_on_promo"] < 0.05),
    })
cannib = pd.DataFrame(cannib_rows)

# ===========================================================================
# (d) NET PROMO PROFITABILITY  -- per SKU's promo programme
# ===========================================================================
prof_rows = []
for s in skus:
    ud = uplift_data[s]
    if ud is None:
        continue
    cost = dim.loc[s, "unit_cost"]
    promo = ud["_promo_df"]
    cf_units = ud["_cf_baseline_units"]
    actual = promo["units"].values
    promo_price = promo["price"].values
    norm_p = promo["norm_price"].values
    incr_units = actual.sum() - cf_units.sum()
    # incremental margin on extra units sold at promo price
    promo_unit_margin = promo_price - cost
    # subsidy: discount given on the base volume that would have sold anyway
    discount_per_unit = norm_p - promo_price
    incr_margin = float((promo_unit_margin * (actual - cf_units)).sum()
                        - (discount_per_unit * cf_units).sum())
    # simpler equivalent decomposition for reporting
    net = incr_margin
    prof_rows.append({
        "sku": s,
        "incremental_units_est": int(incr_units),
        "margin_impact_est": round(net, 0),
        "net_profitable_est": bool(net > 0),
    })
prof = pd.DataFrame(prof_rows)

# ===========================================================================
# VALIDATION  -- open ground truth (allowed ONLY here)
# ===========================================================================
gt = json.loads((DATA / "ground_truth.json").read_text())
gt_elas = {s: gt["skus"][s]["elasticity_true"] for s in skus}
gt_uplift = {s: v["true_uplift_pct"] for s, v in gt["promo_effects_true"].items() if v}
gt_margin = {s: v["true_incremental_margin"] for s, v in gt["promo_effects_true"].items() if v}
gt_profit = {s: v["true_net_profitable"] for s, v in gt["promo_effects_true"].items() if v}
gt_cannib = {(c["aggressor"], c["victim"]): c["true_cannib_pct_realized"]
             for c in gt["cannibalization_true"]}

elas["elasticity_true"] = elas["sku"].map(gt_elas)
elas["abs_pct_err"] = ((elas.elasticity_est - elas.elasticity_true).abs()
                       / elas.elasticity_true.abs() * 100).round(1)

uplift["promo_uplift_true"] = uplift["sku"].map(gt_uplift)
uplift["uplift_abs_err_pp"] = (uplift.promo_uplift_est - uplift.promo_uplift_true).abs().round(1)

prof["margin_impact_true"] = prof["sku"].map(gt_margin)
prof["net_profitable_true"] = prof["sku"].map(gt_profit)
prof["flag_correct"] = prof.net_profitable_est == prof.net_profitable_true

cannib["cannib_pct_true"] = cannib.apply(
    lambda r: gt_cannib.get((r.aggressor, r.victim)), axis=1)
cannib["cannib_abs_err_pp"] = (cannib.cannib_pct_est - cannib.cannib_pct_true).abs().round(1)

# ---- headline accuracy metrics ----
elas_mape = elas["abs_pct_err"].mean()
uplift_mae = uplift["uplift_abs_err_pp"].mean()
cannib_mae = cannib["cannib_abs_err_pp"].mean()
flag_acc = prof["flag_correct"].mean()

# ===========================================================================
# SUMMARY TABLE (required output)
# ===========================================================================
summary = (elas[["sku", "category", "elasticity_naive", "elasticity_est",
                 "elasticity_true", "abs_pct_err"]]
           .merge(uplift[["sku", "promo_uplift_est", "promo_uplift_true"]], on="sku", how="left")
           .merge(prof[["sku", "margin_impact_est", "margin_impact_true",
                        "net_profitable_est", "net_profitable_true"]], on="sku", how="left"))
# cannibalization flag at SKU level (is this SKU a detected victim?)
victim_flag = {r.victim: r.cannibalization_flag for r in cannib.itertuples()}
summary["cannibalization_flag"] = summary["sku"].map(victim_flag).fillna(False)
summary.rename(columns={
    "elasticity_est": "estimated_elasticity", "elasticity_true": "true_elasticity",
    "promo_uplift_est": "promo_uplift_est_pct", "promo_uplift_true": "promo_uplift_true_pct",
    "margin_impact_est": "margin_impact", "net_profitable_est": "net_profitable"}, inplace=True)
summary.to_csv(DATA / "elasticity_summary.csv", index=False)
summary.to_csv(HERE.parent / "powerbi" / "elasticity_summary.csv", index=False)
cannib.to_csv(OUT / "cannibalization_detail.csv", index=False)

# ===========================================================================
# VALIDATION CHARTS
# ===========================================================================
# 1) elasticity: estimated vs true (the money chart)
fig, ax = plt.subplots(figsize=(7, 6.2))
lo, hi = elas.elasticity_true.min() - 0.2, 0
ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="perfect recovery (y=x)")
ax.scatter(elas.elasticity_true, elas.elasticity_naive, c="#bbbbbb", s=55,
           label=f"naive (no controls)", zorder=3)
ax.scatter(elas.elasticity_true, elas.elasticity_est, c="#1f77b4", s=70,
           label=f"controlled model", zorder=4)
for _, r in elas.iterrows():
    ax.annotate(r.sku.replace("_", "\n", 1), (r.elasticity_true, r.elasticity_est),
                fontsize=6, alpha=0.7, xytext=(3, 3), textcoords="offset points")
ax.set_xlabel("TRUE elasticity"); ax.set_ylabel("ESTIMATED elasticity")
ax.set_title(f"Elasticity Recovery: estimated vs true\ncontrolled MAPE = {elas_mape:.1f}%  "
             f"(naive is visibly biased)")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "07_elasticity_validation.png"); plt.close(fig)

# 2) uplift: estimated vs true
fig, ax = plt.subplots(figsize=(7, 6))
m = max(uplift.promo_uplift_true.max(), uplift.promo_uplift_est.max()) * 1.1
ax.plot([0, m], [0, m], "k--", lw=1, label="y=x")
ax.scatter(uplift.promo_uplift_true, uplift.promo_uplift_est, c="#d62728", s=70, zorder=3)
for _, r in uplift.iterrows():
    ax.annotate(r.sku, (r.promo_uplift_true, r.promo_uplift_est), fontsize=6.5,
                xytext=(3, 3), textcoords="offset points")
ax.set_xlabel("TRUE promo uplift %"); ax.set_ylabel("ESTIMATED promo uplift %")
ax.set_title(f"Promo Uplift Recovery: estimated vs true\nmean abs error = {uplift_mae:.1f} pp")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "08_uplift_validation.png"); plt.close(fig)

# 3) profitability: estimated vs true margin, colored by correct flag
fig, ax = plt.subplots(figsize=(7.5, 6))
colors = ["#2ca02c" if p else "#d62728" for p in prof.net_profitable_true]
ax.axhline(0, color="grey", lw=0.8); ax.axvline(0, color="grey", lw=0.8)
mm = max(prof.margin_impact_true.abs().max(), prof.margin_impact_est.abs().max()) * 1.1
ax.plot([-mm, mm], [-mm, mm], "k--", lw=1, label="y=x")
ax.scatter(prof.margin_impact_true / 1e6, prof.margin_impact_est / 1e6, c=colors, s=80, zorder=3)
for _, r in prof.iterrows():
    ax.annotate(r.sku, (r.margin_impact_true / 1e6, r.margin_impact_est / 1e6),
                fontsize=6.5, xytext=(3, 3), textcoords="offset points")
ax.set_xlabel("TRUE incremental margin (INR M)")
ax.set_ylabel("ESTIMATED incremental margin (INR M)")
ax.set_title(f"Promo Profitability Recovery\nsign(flag) accuracy = {flag_acc:.0%} "
             f"(green=true profit, red=true loss)")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "09_profitability_validation.png"); plt.close(fig)

# 4) cannibalization: est vs true bars
fig, ax = plt.subplots(figsize=(8, 4.8))
x = np.arange(len(cannib)); w = 0.38
ax.bar(x - w/2, cannib.cannib_pct_true, w, label="true", color="#7f7f7f")
ax.bar(x + w/2, cannib.cannib_pct_est, w, label="estimated", color="#ff7f0e")
ax.set_xticks(x); ax.set_xticklabels([f"{a}\n->{v}" for a, v in
                zip(cannib.aggressor, cannib.victim)], fontsize=8)
ax.set_ylabel("% volume diverted from victim")
ax.set_title(f"Cannibalization Recovery: estimated vs true (mean abs err {cannib_mae:.1f} pp)")
ax.legend(); fig.tight_layout(); fig.savefig(OUT / "10_cannibalization_validation.png"); plt.close(fig)

# 5) category-volume-shift illustration for the strongest pair
agg, vic = "PC_SOAP_PREM", "PC_SOAP_REG"
agg_weeks = set(f.loc[(f.sku == agg) & (f.promo_flag == 1), "date"])
gv = f[f.sku.isin([agg, vic])].groupby(["date", "sku"])["units"].sum().unstack()
fig, ax = plt.subplots(figsize=(11, 4))
ax.plot(gv.index, gv[agg], color="#d62728", label=f"{agg} (aggressor)")
ax.plot(gv.index, gv[vic], color="#1f77b4", label=f"{vic} (victim)")
for wkd in agg_weeks:
    ax.axvspan(wkd - pd.Timedelta(days=3), wkd + pd.Timedelta(days=3), color="#d62728", alpha=0.12)
ax.set_title(f"Cannibalization in action: when {agg} promotes (shaded), {vic} dips")
ax.set_ylabel("units"); ax.legend(fontsize=8)
fig.tight_layout(); fig.savefig(OUT / "11_cannibalization_timeseries.png"); plt.close(fig)

# ===========================================================================
# CONSOLE REPORT
# ===========================================================================
print("=" * 78); print("CORE ANALYSIS + GROUND-TRUTH VALIDATION"); print("=" * 78)
print(f"\n>>> HEADLINE VALIDATION METRICS")
print(f"  Elasticity   : controlled-model MAPE vs true = {elas_mape:.1f}%   "
      f"(naive MAPE = {((elas.elasticity_naive-elas.elasticity_true).abs()/elas.elasticity_true.abs()*100).mean():.1f}%)")
print(f"  Promo uplift : mean abs error = {uplift_mae:.1f} percentage points")
print(f"  Cannibaliz.  : mean abs error = {cannib_mae:.1f} percentage points")
print(f"  Promo P&L    : profit/loss flag accuracy = {flag_acc:.0%} "
      f"({prof.flag_correct.sum()}/{len(prof)} promos correctly classified)")

print(f"\n>>> ELASTICITY (est vs true)")
print(elas[["sku", "category", "elasticity_naive", "elasticity_est",
            "elasticity_true", "abs_pct_err"]].to_string(index=False))

print(f"\n>>> PROMO UPLIFT (est vs true)")
print(uplift[["sku", "promo_uplift_est", "promo_uplift_true", "uplift_abs_err_pp"]].to_string(index=False))

print(f"\n>>> CANNIBALIZATION (est vs true)")
print(cannib[["aggressor", "victim", "cannib_pct_est", "cannib_pct_true",
              "cannib_abs_err_pp", "p_value", "cannibalization_flag"]].to_string(index=False))

print(f"\n>>> PROMO PROFITABILITY (est vs true)  -- did we catch the bad promos?")
pp = prof.copy()
pp["margin_impact_est"] = pp.margin_impact_est.map(lambda v: f"{v:>12,.0f}")
pp["margin_impact_true"] = pp.margin_impact_true.map(lambda v: f"{v:>12,.0f}")
print(pp[["sku", "margin_impact_est", "margin_impact_true",
          "net_profitable_est", "net_profitable_true", "flag_correct"]].to_string(index=False))

bad_true = set(prof.loc[~prof.net_profitable_true, "sku"])
bad_caught = set(prof.loc[(~prof.net_profitable_true) & (~prof.net_profitable_est), "sku"])
print(f"\n  Deliberately/true-unprofitable promos: {sorted(bad_true)}")
print(f"  Correctly flagged as loss-making     : {sorted(bad_caught)}")
print(f"\nWritten: data/elasticity_summary.csv (+ powerbi/), 5 validation charts in outputs/elasticity/")
