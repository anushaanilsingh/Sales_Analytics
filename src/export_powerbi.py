"""
export_powerbi.py  --  COMPONENT 5: OUTPUTS FOR POWER BI
========================================================
Consolidates the three required fact/summary tables (+ a product dimension)
into powerbi/ as clean CSVs and prints their schemas for verification.
"""
import shutil
import pandas as pd
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
PB = HERE.parent / "powerbi"
PB.mkdir(exist_ok=True)

# fact_sales.csv  (analyst-facing transactional grain)
fact = pd.read_csv(DATA / "fact_sales.csv")
fact.to_csv(PB / "fact_sales.csv", index=False)

# dim_product.csv (star-schema dimension: list price, cost, margin)
shutil.copy(DATA / "dim_product.csv", PB / "dim_product.csv")

# elasticity_summary.csv and forecast_vs_actual.csv already written by their scripts;
# re-load to confirm presence and schema.
elas = pd.read_csv(PB / "elasticity_summary.csv")
fva = pd.read_csv(PB / "forecast_vs_actual.csv")

print("=" * 70); print("POWER BI EXPORTS"); print("=" * 70)
for name, df in [("fact_sales.csv", fact), ("dim_product.csv",
                 pd.read_csv(PB / "dim_product.csv")),
                 ("elasticity_summary.csv", elas), ("forecast_vs_actual.csv", fva)]:
    print(f"\n{name}  ({len(df):,} rows)")
    print("  columns:", ", ".join(df.columns))
print(f"\nAll files in: {PB}")
print("Files:", ", ".join(sorted(p.name for p in PB.glob('*.csv'))))
