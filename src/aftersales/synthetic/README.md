# Aftersales synthetic generator

100% synthetic data for the fictional Aurora Motors: fictional dealers (real Brazilian cities), generic parts,
no real brands or codes. Contract: `docs/data-model/aftersales.md`.

- Entry point: `main.py --catalog C --schema S` (job task `generate`). It reads `market_synthetic_registrations`
  with Spark, runs the pure generator (`aftersales_generator.py`, stdlib only) and **overwrites** the CSVs under
  `/Volumes/C/S/raw_landing/aftersales/`. Same `seed` + `generator_version` => byte-identical files.
- Parameters live in `aftersales_config.py` (`version`, `seed`, dealers, parts, seasonality, stock policy).
  Changing anything that alters the output means bumping `version` and running a **full refresh** of
  `aftersales_pipeline` (Auto Loader ignores rewritten files with the same name).
- Local run (no workspace): see `tests/unit/aftersales_data/` and `evidence/aftersales/data/generator-local-run.txt`.

## Demo events (deliberate, so the screen has a story)

1. **Supplier disruption (Aug-Oct 2026):** orders for filters, engine and lighting parts placed 2026-08-15..2026-10-31
   arrive 45 days late, producing real stockouts in the last 4 weeks (fill rate ~0.90).
2. **Inventory write-off (2026-11-15):** long-lead critical parts with nothing on order lose 85% of their stock at
   the end of the last day (a count adjustment). It does not change sales; it only lowers the final snapshot so that
   some dealer x part pairs are genuinely `critical` at forecast time.
3. Background noise: ~10% of supplier orders are delayed (lead time x2.2), giving occasional lost-sales episodes.
