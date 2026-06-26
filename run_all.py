"""
run_all.py — execute the full FMCG analytics pipeline in order.

Order matters: simulate -> eda -> elasticity -> forecasting -> export_powerbi.
Each step writes to data/ and outputs/; later steps read those files.
"""
import subprocess
import sys
import time

STEPS = [
    ("Data generation",        "src/simulate.py"),
    ("Exploratory analysis",   "src/eda.py"),
    ("Elasticity & validation","src/elasticity.py"),
    ("Demand forecasting",     "src/forecasting.py"),
    ("Power BI export",        "src/export_powerbi.py"),
]


def main():
    print("=" * 64)
    print("FMCG Sales & Promotion Analytics — full pipeline")
    print("=" * 64)
    for i, (label, script) in enumerate(STEPS, 1):
        print(f"\n[{i}/{len(STEPS)}] {label}  ({script})")
        print("-" * 64)
        t0 = time.time()
        result = subprocess.run([sys.executable, script])
        if result.returncode != 0:
            print(f"\n!! Step failed: {script} (exit {result.returncode}). Stopping.")
            sys.exit(result.returncode)
        print(f"   done in {time.time() - t0:.1f}s")
    print("\n" + "=" * 64)
    print("Pipeline complete. See data/, outputs/, powerbi/ and POWERBI_GUIDE.md")
    print("=" * 64)


if __name__ == "__main__":
    main()
