# Aftersales forecast review: notebook output (synthetic data)

- Notebook: `evidence/aftersales/notebooks/aftersales_forecast_review.py` at commit `832fd22` (read-only: trains, registers and writes nothing).
- Run: one-off serverless job run `15962304165436`, result SUCCESS, 2026-11-20, workspace profile `classic-stable-new`.
- Output below is the notebook's `dbutils.notebook.exit` text, verbatim (98 lines). The workspace export has source only, so no `.ipynb` with outputs exists.
- Known cosmetic issue: in section 3 the per-version lines for v1..v3 print `aliases=<bound method ...>` because UC `search_model_versions` rows expose `aliases`/`tags` as methods. The champion alias and tags are shown correctly by the lines above them (`aliases: {'champion': '3'}`, `@champion -> version 3`). The source was fixed afterwards (`get_model_version` per version); that fix has not been re-run.
- v1 and v2 are orphan versions from earlier failed runs (no alias), documented in the ADR.

What the output shows:
- Recomputed holdout WAPE 0.2004 for the model vs 0.3015 for the seasonal-naive baseline (lift +33.5%, bias +0.0334); identical to the logged champion row, and the gate (WAPE < 0.95 x baseline) holds.
- The model beats the baseline in every horizon week and every category. The weakest category is `air_conditioning` (0.2640), and critical parts are harder than non-critical ones (0.2544 vs 0.1911).

```text
holdout rows=9360 series=720 weeks=13 (2026-08-17 .. 2026-11-09)
recomputed  WAPE model=0.2004  baseline=0.3015  lift=+33.5%  bias=+0.0334
                                                   model_name model_version                           run_id cutoff_date forecast_date  holdout_weeks  n_series     wape  baseline_wape     bias  baseline_bias  is_champion                  logged_at
classic_stable.auto_intelligence.aftersales_demand_forecaster             3 21423ab98f7b479a89ffeffc017e0a28  2026-08-16    2026-11-16             13       720 0.200374       0.301496 0.033414      -0.211795         True 2026-11-20 18:16:55.556140
OK: logged champion metrics == recomputed; gate WAPE < 0.95 x baseline holds
by horizon_week
              wape_model  wape_baseline
horizon_week                           
1                 0.1992         0.3181
2                 0.2102         0.3363
3                 0.1968         0.3218
4                 0.1884         0.2961
5                 0.1807         0.3127
6                 0.2008         0.2946
7                 0.2126         0.2843
8                 0.2021         0.3011
9                 0.2084         0.2858
10                0.1977         0.2805
11                0.1997         0.3016
12                0.1999         0.3064
13                0.2081         0.2845

by category
                  wape_model  wape_baseline
category_id                                
air_conditioning      0.2640         0.3715
brakes                0.2023         0.3045
cooling               0.2568         0.3455
electrical            0.2096         0.3208
engine                0.1696         0.2822
filters               0.1769         0.2653
lighting              0.1870         0.2807
suspension            0.2452         0.3585

by is_critical
             wape_model  wape_baseline
is_critical                           
False            0.1911         0.2896
True             0.2544         0.3706
model: classic_stable.auto_intelligence.aftersales_demand_forecaster | aliases: {'champion': '3'}
tags: {'aid_domain': 'aftersales', 'synthetic': 'true'}
@champion -> version 3, run_id 21423ab98f7b479a89ffeffc017e0a28
  v1 aliases=<bound method ModelVersionSearch.aliases of <ModelVersionSearch: >> run_id=b8fa6f2075ff48a59847988d8be340c9 tags=<bound method ModelVersionSearch.tags of <ModelVersionSearch: >>
  v2 aliases=<bound method ModelVersionSearch.aliases of <ModelVersionSearch: >> run_id=6bf91d136fa849deb9595bfc9f68fe4e tags=<bound method ModelVersionSearch.tags of <ModelVersionSearch: >>
  v3 aliases=<bound method ModelVersionSearch.aliases of <ModelVersionSearch: >> run_id=21423ab98f7b479a89ffeffc017e0a28 tags=<bound method ModelVersionSearch.tags of <ModelVersionSearch: >>
params : {'cutoff': '2026-08-16', 'gate_factor': '0.95', 'holdout_weeks': '13', 'last_actual_week': '2026-11-09', 'model': 'HistGradientBoostingRegressor(poisson)', 'n_series': '720', 'season': '52', 'seed': '42', 'strategy': 'direct'}
metrics: {'baseline_wape': 0.3015, 'bias': 0.0334, 'lift_vs_baseline': 0.3354, 'wape': 0.2004}
forecast_weekly rows: 24480 | per series: [34]
model_version(s): ['3'] ['3']
future weeks: 2026-11-16 .. 2027-01-04
stockout_risk rows: 2160 | horizons: [14, 28, 56]
risk_level    critical  high  low  medium
horizon_days                             
14                  11     3  694      12
28                  13    89  564      54
56                  13   427  219      61
action        monitor  reorder  transfer
horizon_days                            
14                694        0        26
28                564       23       133
56                219      406        95
dealer_id part_id  stock_units  on_order_units  forecast_units  days_to_stockout  stockout_probability risk_level  shortfall_units  lost_sales_brl   action  recommended_qty transfer_from_dealer_id
     D011    P021           21               0          91.128               7.0                 1.000   critical               87       41368.362  reorder               87                    None
     D001    P033          718               0        1385.657              15.0                 1.000       high              721       36654.356 transfer              721                    D004
     D005    P001          109               0         240.389              14.0                 1.000   critical              155       24950.732 transfer              155                    D007
     D001    P003           41               0         110.817              12.0                 1.000   critical               91       24428.834 transfer               91                    D004
     D003    P014           26               0          76.035              10.0                 1.000   critical               62       23011.055 transfer               62                    D002
     D003    P003          103               0         123.426              24.0                 0.842       high               43        7147.188 transfer               43                    D002
     D011    P054           61               0         139.458              14.0                 1.000       high               86        7053.348 transfer               86                    D012
     D003    P035            5               0          22.628               7.0                 0.999   critical               26        6696.795  reorder               26                    None

forecast series for D011 / P021
week_start  is_future  horizon_week  actual_units  forecast_units  lower_units  upper_units  baseline_units
2026-07-27      False           NaN          25.0             NaN          NaN          NaN             NaN
2026-08-03      False           NaN          18.0             NaN          NaN          NaN             NaN
2026-08-10      False           NaN          21.0             NaN          NaN          NaN             NaN
2026-08-17      False           1.0          10.0           21.57        12.47        30.67            16.0
2026-08-24      False           2.0          14.0           21.71        12.61        30.82            10.0
2026-08-31      False           3.0          37.0           21.00        11.90        30.11            20.0
2026-09-07      False           4.0          21.0           21.86        12.76        30.96            13.0
2026-09-14      False           5.0          24.0           21.91        12.81        31.01            21.0
2026-09-21      False           6.0          17.0           21.58        12.48        30.69            23.0
2026-09-28      False           7.0          16.0           21.22        12.11        30.32            14.0
2026-10-05      False           8.0          26.0           20.36        11.25        29.46            16.0
2026-10-12      False           9.0          14.0           21.42        12.32        30.53            16.0
2026-10-19      False          10.0          18.0           20.47        11.37        29.57            17.0
2026-10-26      False          11.0          24.0           20.29        11.19        29.39            12.0
2026-11-02      False          12.0          27.0           20.62        11.51        29.72            16.0
2026-11-09      False          13.0          23.0           20.61        11.51        29.72            15.0
2026-11-16       True           1.0           NaN           22.07        12.97        31.18             NaN
2026-11-23       True           2.0           NaN           22.56        13.45        31.66             NaN
2026-11-30       True           3.0           NaN           23.14        14.04        32.24             NaN
2026-12-07       True           4.0           NaN           23.36        14.26        32.46             NaN
2026-12-14       True           5.0           NaN           23.57        14.47        32.67             NaN
2026-12-21       True           6.0           NaN           22.45        13.35        31.56             NaN
2026-12-28       True           7.0           NaN           23.34        14.24        32.44             NaN
2027-01-04       True           8.0           NaN           23.78        14.68        32.88             NaN

```
