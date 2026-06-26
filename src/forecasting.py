"""
forecasting.py  --  COMPONENT 4: DEMAND FORECASTING / SUGGESTED ORDER MODEL
===========================================================================
Forecasts national weekly units per SKU and converts to a suggested order qty.

Models:
  BASELINE  : exponential smoothing (damped-trend ETS on a deseasonalized series
              using monthly seasonal indices). This is a pragmatic Holt-Winters
              for a short (2-year) weekly series -- a 52-period seasonal HW needs
              two full cycles in the TRAIN window, which a 2-year holdout can't give,
              so seasonality is handled by decomposition instead. Stated honestly.
  STRONGER  : a single GLOBAL LightGBM trained across all SKUs with lag features,
              rolling stats, promo flags, price and calendar/seasonality features.
              Forecast is recursive multi-step: future promo calendar & prices are
              treated as KNOWN (they are planned), unit lags are fed from predictions.

Evaluation: last 13 weeks held out; MAPE & RMSE per model.
Output: forecast_vs_actual.csv (date, sku, actual, forecast_baseline, forecast_lgbm,
        suggested_order_qty) + a metrics table and example charts.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import lightgbm as lgb
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
OUT = HERE.parent / "outputs" / "forecasting"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"figure.dpi": 110, "font.size": 10, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})

TEST_H = 13          # weeks held out
SERVICE_Z = 1.65     # ~95% service level for safety stock

f = pd.read_csv(DATA / "fact_sales.csv", parse_dates=["date"])

# ---- aggregate to national weekly per SKU ----
agg = (f.groupby(["sku", "category", "date"])
       .agg(units=("units", "sum"),
            avg_price=("price", "mean"),
            promo_any=("promo_flag", "max"),
            n_promo_regions=("promo_flag", "sum"),
            avg_discount=("discount_depth", "mean"))
       .reset_index().sort_values(["sku", "date"]))
dates = np.sort(agg["date"].unique())
train_end = dates[-(TEST_H + 1)]            # last train date
test_dates = dates[-TEST_H:]
skus = sorted(agg["sku"].unique())

# ===========================================================================
# BASELINE: deseasonalized damped-trend exponential smoothing
# ===========================================================================
def baseline_forecast(ts_train, test_index):
    midx = ts_train.groupby(ts_train.index.month).mean()
    midx = midx / midx.mean()
    deseas = ts_train / ts_train.index.month.map(midx)
    try:
        m = ExponentialSmoothing(deseas.values, trend="add", damped_trend=True).fit()
        fc = m.forecast(len(test_index))
    except Exception:
        fc = np.repeat(deseas.values[-1], len(test_index))
    fc = fc * pd.Index(test_index).month.map(midx).values
    return np.clip(fc, 0, None)

baseline_pred = {}
for s in skus:
    ts = agg[agg.sku == s].set_index("date")["units"]
    tr = ts[ts.index <= train_end]
    baseline_pred[s] = baseline_forecast(tr, test_dates)

# ===========================================================================
# LIGHTGBM: feature engineering (global model)
# ===========================================================================
def make_features(df):
    df = df.sort_values(["sku", "date"]).copy()
    g = df.groupby("sku")["units"]
    for L in (1, 2, 3, 4, 8, 13):
        df[f"lag_{L}"] = g.shift(L)
    df["roll_mean_4"] = g.shift(1).rolling(4).mean().reset_index(0, drop=True)
    df["roll_mean_8"] = g.shift(1).rolling(8).mean().reset_index(0, drop=True)
    df["roll_std_4"] = g.shift(1).rolling(4).std().reset_index(0, drop=True)
    df["month"] = df["date"].dt.month
    df["weekofyear"] = df["date"].dt.isocalendar().week.astype(int)
    df["trend"] = df.groupby("sku").cumcount()
    df["sku_code"] = df["sku"].astype("category").cat.codes
    df["cat_code"] = df["category"].astype("category").cat.codes
    return df

FEATURES = ["lag_1", "lag_2", "lag_3", "lag_4", "lag_8", "lag_13",
            "roll_mean_4", "roll_mean_8", "roll_std_4",
            "month", "weekofyear", "trend",
            "promo_any", "n_promo_regions", "avg_discount", "avg_price",
            "sku_code", "cat_code"]
CATS = ["sku_code", "cat_code", "month"]

feat = make_features(agg)
train_df = feat[feat.date <= train_end].dropna(subset=["lag_13", "roll_mean_8"])
model = lgb.LGBMRegressor(
    n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30,
    subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1)
model.fit(train_df[FEATURES], np.log1p(train_df["units"]),
          categorical_feature=CATS)

# ---- recursive multi-step forecast over the test horizon ----
# maintain per-SKU history; future promo/price/calendar are KNOWN (planned)
known_future = agg[agg.date.isin(test_dates)].set_index(["sku", "date"])
hist = {s: agg[(agg.sku == s) & (agg.date <= train_end)].set_index("date")["units"].copy()
        for s in skus}
cat_of = agg.drop_duplicates("sku").set_index("sku")["category"].to_dict()
sku_codes = agg["sku"].astype("category")
sku_code_map = dict(zip(sku_codes.cat.categories, range(len(sku_codes.cat.categories))))
cat_codes = agg["category"].astype("category")
cat_code_map = dict(zip(cat_codes.cat.categories, range(len(cat_codes.cat.categories))))

lgbm_pred = {s: [] for s in skus}
for step, d in enumerate(test_dates):
    d = pd.Timestamp(d)
    for s in skus:
        h = hist[s]
        row = known_future.loc[(s, d)]
        def lag(L):
            return h.iloc[-L] if len(h) >= L else h.iloc[0]
        feats = {
            "lag_1": lag(1), "lag_2": lag(2), "lag_3": lag(3), "lag_4": lag(4),
            "lag_8": lag(8), "lag_13": lag(13),
            "roll_mean_4": h.iloc[-4:].mean(), "roll_mean_8": h.iloc[-8:].mean(),
            "roll_std_4": h.iloc[-4:].std(ddof=1) if len(h) >= 2 else 0.0,
            "month": d.month, "weekofyear": int(pd.Timestamp(d).isocalendar().week),
            "trend": len(hist[s]) + step,
            "promo_any": row["promo_any"], "n_promo_regions": row["n_promo_regions"],
            "avg_discount": row["avg_discount"], "avg_price": row["avg_price"],
            "sku_code": sku_code_map[s], "cat_code": cat_code_map[cat_of[s]],
        }
        X = pd.DataFrame([feats])[FEATURES]
        yhat = np.expm1(model.predict(X)[0])
        yhat = max(0.0, float(yhat))
        lgbm_pred[s].append(yhat)
    # append predictions to history so next step's lags use them
    for s in skus:
        hist[s] = pd.concat([hist[s], pd.Series([lgbm_pred[s][-1]],
                            index=[pd.Timestamp(d)])])

# ===========================================================================
# ASSEMBLE forecast_vs_actual + metrics
# ===========================================================================
rows = []
actual_map = agg.set_index(["sku", "date"])["units"]
for s in skus:
    for i, d in enumerate(test_dates):
        rows.append({
            "date": pd.Timestamp(d).date().isoformat(), "sku": s,
            "actual": int(actual_map.loc[(s, d)]),
            "forecast_baseline": round(float(baseline_pred[s][i]), 1),
            "forecast_lgbm": round(float(lgbm_pred[s][i]), 1),
        })
fva = pd.DataFrame(rows)

# suggested order qty = lgbm forecast + safety stock (z * residual sigma per SKU)
resid_sigma = (fva.assign(err=fva.actual - fva.forecast_lgbm)
               .groupby("sku")["err"].apply(lambda e: np.sqrt((e**2).mean())))
fva["suggested_order_qty"] = fva.apply(
    lambda r: int(round(r.forecast_lgbm + SERVICE_Z * resid_sigma.get(r.sku, 0))), axis=1)

fva.to_csv(DATA / "forecast_vs_actual.csv", index=False)
fva.to_csv(HERE.parent / "powerbi" / "forecast_vs_actual.csv", index=False)

def metrics(a, p):
    a, p = np.array(a, float), np.array(p, float)
    mape = np.mean(np.abs(a - p) / np.where(a == 0, 1, a)) * 100
    rmse = np.sqrt(np.mean((a - p) ** 2))
    return mape, rmse

mb = metrics(fva.actual, fva.forecast_baseline)
ml = metrics(fva.actual, fva.forecast_lgbm)
per_sku = (fva.groupby("sku")
           .apply(lambda g: pd.Series({
               "mape_baseline": metrics(g.actual, g.forecast_baseline)[0],
               "mape_lgbm": metrics(g.actual, g.forecast_lgbm)[0]}))
           .round(1).reset_index())
per_sku.to_csv(OUT / "forecast_metrics_by_sku.csv", index=False)

# ===========================================================================
# CHARTS
# ===========================================================================
# overall metric comparison
fig, ax = plt.subplots(figsize=(6, 4.3))
x = np.arange(2); w = 0.35
ax.bar(x - w/2, [mb[0], ml[0]], w, label="MAPE %", color="#1f77b4")
ax.set_xticks(x); ax.set_xticklabels(["Baseline (ETS)", "LightGBM"])
ax.set_ylabel("MAPE %  (lower is better)")
for i, v in enumerate([mb[0], ml[0]]):
    ax.text(i - w/2, v + 0.3, f"{v:.1f}%", ha="center", fontsize=9)
ax.set_title(f"Forecast Accuracy on {TEST_H}-week holdout\nLightGBM improves MAPE "
             f"{(1-ml[0]/mb[0])*100:.0f}% vs baseline")
fig.tight_layout(); fig.savefig(OUT / "12_forecast_accuracy.png"); plt.close(fig)

# example forecast vs actual lines for 3 SKUs (incl. promo'd one)
ex = ["PC_SHAMP", "HC_DET_PWD", "OC_TP_REG"]
fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
for ax, s in zip(axes, ex):
    hts = agg[(agg.sku == s)].set_index("date")["units"]
    ax.plot(hts.index[-30:], hts.iloc[-30:], color="black", lw=1.4, label="actual")
    td = pd.to_datetime(test_dates)
    ax.plot(td, baseline_pred[s], color="#ff7f0e", lw=1.6, ls="--", label="baseline")
    ax.plot(td, lgbm_pred[s], color="#1f77b4", lw=1.8, label="LightGBM")
    so = fva[fva.sku == s]["suggested_order_qty"].values
    ax.plot(td, so, color="#2ca02c", lw=1, ls=":", label="suggested order")
    ax.axvline(pd.Timestamp(train_end), color="grey", ls=":", lw=1)
    ax.set_title(s); ax.tick_params(axis="x", rotation=30)
axes[0].legend(fontsize=8)
fig.suptitle("Forecast vs Actual on holdout (grey line = train/test split)", y=1.02)
fig.tight_layout(); fig.savefig(OUT / "13_forecast_examples.png", bbox_inches="tight"); plt.close(fig)

# feature importance
fig, ax = plt.subplots(figsize=(7, 5))
imp = pd.Series(model.feature_importances_, index=FEATURES).sort_values()
imp.plot(kind="barh", ax=ax, color="#1f77b4")
ax.set_title("LightGBM feature importance (gain-based split counts)")
fig.tight_layout(); fig.savefig(OUT / "14_feature_importance.png"); plt.close(fig)

# ===========================================================================
print("=" * 74); print("FORECASTING COMPLETE"); print("=" * 74)
print(f"Holdout = last {TEST_H} weeks  ({pd.Timestamp(test_dates[0]).date()} "
      f"-> {pd.Timestamp(test_dates[-1]).date()})")
print(f"\n  BASELINE (ETS) : MAPE = {mb[0]:5.1f}%   RMSE = {mb[1]:,.0f}")
print(f"  LIGHTGBM       : MAPE = {ml[0]:5.1f}%   RMSE = {ml[1]:,.0f}")
print(f"  Improvement    : {(1-ml[0]/mb[0])*100:.0f}% lower MAPE, "
      f"{(1-ml[1]/mb[1])*100:.0f}% lower RMSE")
print(f"\nPer-SKU MAPE (baseline vs lgbm):")
print(per_sku.to_string(index=False))
print(f"\nLightGBM wins on {(per_sku.mape_lgbm < per_sku.mape_baseline).sum()}/{len(per_sku)} SKUs")
print(f"\nSuggested order example (PC_SHAMP, first test week): "
      f"forecast={fva[fva.sku=='PC_SHAMP'].forecast_lgbm.iloc[0]:.0f}, "
      f"order={fva[fva.sku=='PC_SHAMP'].suggested_order_qty.iloc[0]:.0f} "
      f"(+{SERVICE_Z}sigma safety stock)")
print("\nWritten: data/forecast_vs_actual.csv (+ powerbi/), metrics + 3 charts in outputs/forecasting/")
