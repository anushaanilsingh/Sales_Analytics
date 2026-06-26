"""
config.py
=========
Single source of truth for the SIMULATION parameters.

Everything an analyst is NOT supposed to know (true elasticity, true promo lift,
true cannibalization, unit cost behaviour) is defined here and flows into
ground_truth.json. The analysis scripts must NEVER import elasticity_true,
promo_lift_true or cannib_frac from here -- they only see data/fact_sales.csv
and data/dim_product.csv.

All parameters are deliberately laid out as plain dicts so the ground-truth file
is fully auditable.
"""

SEED = 20240615
N_WEEKS = 104                      # 2 years of weekly data
START_DATE = "2023-01-02"          # a Monday

# ---------------------------------------------------------------------------
# REGIONS
# region_demand_mult : structural demand scaler (market size)
# region_price_mult  : structural price level (gives cross-sectional price
#                      variation that helps identify elasticity)
# ---------------------------------------------------------------------------
REGIONS = {
    "North": {"region_demand_mult": 1.15, "region_price_mult": 1.02},
    "South": {"region_demand_mult": 1.05, "region_price_mult": 0.98},
    "West":  {"region_demand_mult": 1.20, "region_price_mult": 1.03},
    "East":  {"region_demand_mult": 0.85, "region_price_mult": 0.97},
    "Central": {"region_demand_mult": 0.95, "region_price_mult": 1.00},
}

# ---------------------------------------------------------------------------
# SEASONALITY  (monthly multipliers, month index 1..12)
# Indian FMCG rhythm:
#   - Oral Care: nearly flat (staple hygiene), tiny new-year/wedding-season bumps
#   - Personal Care: summer bump (Apr-Jun, deo/bodywash) + big Diwali Oct-Nov gifting
#   - Home Care: pre-Diwali cleaning (Sep-Oct) + summer (pest/floor) bump
# ---------------------------------------------------------------------------
SEASONALITY = {
    "Oral Care": {
        1: 1.05, 2: 1.02, 3: 1.00, 4: 0.99, 5: 0.98, 6: 0.98,
        7: 0.99, 8: 1.00, 9: 1.01, 10: 1.04, 11: 1.06, 12: 1.05,
    },
    "Personal Care": {
        1: 0.95, 2: 0.96, 3: 1.00, 4: 1.12, 5: 1.20, 6: 1.18,
        7: 1.02, 8: 1.00, 9: 1.05, 10: 1.30, 11: 1.28, 12: 1.10,
    },
    "Home Care": {
        1: 0.98, 2: 0.97, 3: 1.02, 4: 1.10, 5: 1.14, 6: 1.08,
        7: 0.98, 8: 0.97, 9: 1.18, 10: 1.25, 11: 1.06, 12: 1.00,
    },
}

# ---------------------------------------------------------------------------
# SKU MASTER
# Each SKU carries its TRUE structural parameters:
#   base_price       : list price (INR)
#   unit_cost        : standard COGS (INR) -> known to analyst via dim_product
#   base_demand      : intercept-ish weekly base units (national, pre-mult)
#   elasticity_true  : TRUE price elasticity (HIDDEN from analysis)
#   trend_true       : log-units drift over the full 2 yrs (HIDDEN)
#   noise_sd         : sd of log-demand noise
#
# Margin note: unit_cost / base_price sets the gross margin. The "bad promo"
# SKUs are intentionally thin-margin so deep discounts go underwater.
# ---------------------------------------------------------------------------
SKUS = {
    # ----------------------- ORAL CARE (staples, less elastic) -------------
    "OC_TP_REG":   {"category": "Oral Care", "name": "Toothpaste Regular 100g",
                    "base_price": 55,  "unit_cost": 33, "base_demand": 4200,
                    "elasticity_true": -0.85, "trend_true": 0.10, "noise_sd": 0.08},
    "OC_TP_PREM":  {"category": "Oral Care", "name": "Toothpaste Whitening 100g",
                    "base_price": 110, "unit_cost": 55, "base_demand": 1800,
                    "elasticity_true": -1.45, "trend_true": 0.22, "noise_sd": 0.10},
    "OC_BRUSH":    {"category": "Oral Care", "name": "Toothbrush MediumPk2",
                    "base_price": 80,  "unit_cost": 38, "base_demand": 2600,
                    "elasticity_true": -1.10, "trend_true": 0.05, "noise_sd": 0.09},
    "OC_MOUTH":    {"category": "Oral Care", "name": "Mouthwash 250ml",
                    "base_price": 165, "unit_cost": 92, "base_demand": 1100,
                    "elasticity_true": -1.30, "trend_true": 0.15, "noise_sd": 0.11},
    "OC_TP_KIDS":  {"category": "Oral Care", "name": "Toothpaste Kids 80g",
                    "base_price": 70,  "unit_cost": 40, "base_demand": 1400,
                    "elasticity_true": -1.20, "trend_true": 0.18, "noise_sd": 0.10},

    # ----------------- PERSONAL CARE (discretionary, more elastic) ---------
    "PC_SOAP_REG": {"category": "Personal Care", "name": "Bath Soap Regular Pk4",
                    "base_price": 120, "unit_cost": 70, "base_demand": 3000,
                    "elasticity_true": -1.70, "trend_true": 0.08, "noise_sd": 0.10},
    "PC_SOAP_PREM":{"category": "Personal Care", "name": "Bath Soap Luxury Pk3",
                    "base_price": 210, "unit_cost": 105, "base_demand": 1500,
                    "elasticity_true": -2.40, "trend_true": 0.20, "noise_sd": 0.12},
    "PC_SHAMP":    {"category": "Personal Care", "name": "Shampoo 340ml",
                    "base_price": 230, "unit_cost": 130, "base_demand": 1700,
                    "elasticity_true": -1.95, "trend_true": 0.12, "noise_sd": 0.11},
    "PC_BODYWASH": {"category": "Personal Care", "name": "Body Wash 250ml",
                    "base_price": 199, "unit_cost": 120, "base_demand": 950,
                    "elasticity_true": -2.20, "trend_true": 0.28, "noise_sd": 0.13},
    "PC_DEO":      {"category": "Personal Care", "name": "Deodorant 150ml",
                    "base_price": 250, "unit_cost": 150, "base_demand": 1300,
                    "elasticity_true": -2.05, "trend_true": 0.10, "noise_sd": 0.12},
    "PC_LOTION":   {"category": "Personal Care", "name": "Body Lotion 200ml",
                    "base_price": 180, "unit_cost": 100, "base_demand": 1050,
                    "elasticity_true": -1.85, "trend_true": 0.16, "noise_sd": 0.11},

    # ----------------------- HOME CARE (mixed elasticity) ------------------
    "HC_DISH":     {"category": "Home Care", "name": "Dishwash Liquid 750ml",
                    "base_price": 145, "unit_cost": 88, "base_demand": 2400,
                    "elasticity_true": -1.55, "trend_true": 0.14, "noise_sd": 0.10},
    "HC_FLOOR":    {"category": "Home Care", "name": "Floor Cleaner 1L",
                    "base_price": 175, "unit_cost": 100, "base_demand": 1600,
                    "elasticity_true": -1.40, "trend_true": 0.09, "noise_sd": 0.10},
    "HC_DET_PWD":  {"category": "Home Care", "name": "Detergent Powder 1kg",
                    "base_price": 130, "unit_cost": 95, "base_demand": 3500,
                    "elasticity_true": -1.05, "trend_true": 0.04, "noise_sd": 0.09},
    "HC_DET_LIQ":  {"category": "Home Care", "name": "Detergent Liquid 1L",
                    "base_price": 240, "unit_cost": 140, "base_demand": 1400,
                    "elasticity_true": -2.10, "trend_true": 0.30, "noise_sd": 0.13},
    "HC_TOILET":   {"category": "Home Care", "name": "Toilet Cleaner 500ml",
                    "base_price": 95,  "unit_cost": 58, "base_demand": 2000,
                    "elasticity_true": -1.25, "trend_true": 0.07, "noise_sd": 0.10},
}

# ---------------------------------------------------------------------------
# CANNIBALIZATION PAIRS  (aggressor on promo -> victim loses share)
# cannib_frac : fraction of victim volume diverted while aggressor promotes
#               (and the victim is NOT itself on promo)
# These are the pairs the analysis must rediscover.
# ---------------------------------------------------------------------------
CANNIBALIZATION = [
    {"aggressor": "OC_TP_PREM",   "victim": "OC_TP_REG",   "cannib_frac": 0.18},
    {"aggressor": "PC_SOAP_PREM", "victim": "PC_SOAP_REG", "cannib_frac": 0.25},
    {"aggressor": "HC_DET_LIQ",   "victim": "HC_DET_PWD",  "cannib_frac": 0.15},
]

# ---------------------------------------------------------------------------
# PROMO CALENDAR
# Each entry: sku, list of (start_week, n_weeks), discount_depth, promo_lift
#   discount_depth : fractional price cut (0.30 = 30% off)
#   promo_lift     : EXTRA log-uplift from display/feature, ON TOP of the price
#                    elasticity response. exp(promo_lift)-1 = incremental % lift
#                    from non-price mechanics.
#   label          : 'good' / 'bad' tag for our own audit (analyst doesn't see)
#
# Designed mix:
#   - PC_SOAP_PREM & HC_DET_LIQ & OC_TP_PREM promos drive the cannibalization
#   - HC_DET_PWD and PC_SOAP_REG carry DELIBERATELY BAD promos (deep cut, thin
#     margin, modest lift -> underwater)
#   - PC_SHAMP and OC_TP_PREM carry GOOD promos (healthy margin, strong lift)
# ---------------------------------------------------------------------------
PROMO_CALENDAR = {
    # --- cannibalization aggressors (well-defined promo windows) ---
    "OC_TP_PREM":   {"windows": [(14, 3), (44, 3), (88, 3)], "discount_depth": 0.25,
                     "promo_lift": 0.35, "label": "good"},      # premium, decent margin
    "PC_SOAP_PREM": {"windows": [(20, 4), (62, 4)],           "discount_depth": 0.30,
                     "promo_lift": 0.45, "label": "good"},
    "HC_DET_LIQ":   {"windows": [(30, 3), (78, 4)],           "discount_depth": 0.28,
                     "promo_lift": 0.40, "label": "good"},

    # --- DELIBERATELY BAD promos (thin margin + deep cut) ---
    "HC_DET_PWD":   {"windows": [(24, 4), (70, 3)],           "discount_depth": 0.32,
                     "promo_lift": 0.15, "label": "bad"},       # margin ~27%, 32% cut -> underwater
    "PC_SOAP_REG":  {"windows": [(36, 3), (90, 3)],           "discount_depth": 0.35,
                     "promo_lift": 0.20, "label": "bad"},

    # --- clearly GOOD promos (healthy margin, strong lift, moderate cut) ---
    "PC_SHAMP":     {"windows": [(16, 3), (54, 3), (96, 2)],  "discount_depth": 0.20,
                     "promo_lift": 0.50, "label": "good"},
    "HC_DISH":      {"windows": [(40, 3), (84, 3)],           "discount_depth": 0.18,
                     "promo_lift": 0.42, "label": "good"},

    # --- a few 'neutral/other' promos for realism ---
    "OC_MOUTH":     {"windows": [(48, 2), (100, 2)],          "discount_depth": 0.22,
                     "promo_lift": 0.30, "label": "good"},
    "PC_DEO":       {"windows": [(18, 3), (66, 3)],           "discount_depth": 0.25,
                     "promo_lift": 0.38, "label": "good"},
}

# Week-to-week independent price noise sd (gives elasticity identification even
# outside promo weeks). Applied in log space.
PRICE_NOISE_SD = 0.04
