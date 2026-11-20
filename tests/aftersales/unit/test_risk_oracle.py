"""Offline self-test of the QA D5 oracle (no workspace): hand-computed cases from ADR 002 D5."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import risk_oracle as ro  # noqa: E402


class D5(unittest.TestCase):
    def setUp(self):
        # part P1, region S: A short, B donor with stock on hand, C donor only on order; region N: D has surplus
        self.stock = {("A", "P1"): (0, 0, 10), ("B", "P1"): (100, 0, 7), ("C", "P1"): (0, 200, 7), ("D", "P1"): (500, 0, 7)}
        self.price = {"P1": 10.0}
        self.region = {"A": "S", "B": "S", "C": "S", "D": "N"}
        self.fut = {k: [7.0] * 8 for k in self.stock}
        self.sigma = {k: 0.5 for k in self.stock}
        self.out = ro.compute(self.stock, self.price, self.region, self.fut, self.sigma)

    def test_formulas_short_row(self):
        r = self.out[("A", "P1", 14)]
        self.assertEqual(r["forecast_units"], 14.0)
        self.assertAlmostEqual(r["forecast_sigma_units"], 0.5 * math.sqrt(2))
        self.assertAlmostEqual(r["safety_stock_units"], 1.65 * 0.5 * math.sqrt(10 / 7))
        self.assertEqual(r["days_to_stockout"], 1)          # 1 unit/day > 0 available on day 1
        self.assertEqual(r["risk_level"], "critical")       # 1 <= min(14, 10)
        self.assertEqual(r["shortfall_units"], math.ceil(14 + 1.65 * 0.5 * math.sqrt(10 / 7)))
        self.assertEqual(r["lost_sales_brl"], 140.0)
        self.assertIsNone(r["days_of_stock"] if r["stock_units"] else None)
        self.assertAlmostEqual(r["stockout_probability"], 1 - ro.phi(-14 / (0.5 * math.sqrt(2))))

    def test_transfer_only_same_region_and_on_hand(self):
        r = self.out[("A", "P1", 14)]
        self.assertEqual(r["action"], "transfer")
        self.assertEqual(r["transfer_from_dealer_id"], "B")  # C has 0 on hand, D other region
        self.assertEqual(r["transfer_from_excess_units"], min(100, math.floor(100 - 14 - 1.65 * 0.5 * 1)))

    def test_donor_on_order_only_is_not_donor(self):
        stock = dict(self.stock)
        stock[("B", "P1")] = (0, 0, 7)
        out = ro.compute(stock, self.price, self.region, self.fut, self.sigma)
        self.assertEqual(out[("A", "P1", 14)]["action"], "reorder")

    def test_monitor_and_dos(self):
        r = self.out[("D", "P1", 56)]
        self.assertEqual((r["action"], r["recommended_qty"], r["risk_level"]), ("monitor", 0, "low"))
        self.assertAlmostEqual(r["days_of_stock"], 500 / (56 / 56))
        self.assertIsNone(r["days_to_stockout"])

    def test_zero_sigma_probability(self):
        out = ro.compute({("A", "P1"): (0, 0, 7)}, self.price, {"A": "S"}, {("A", "P1"): [0.0] * 8}, {("A", "P1"): 0.0})
        r = out[("A", "P1", 28)]
        self.assertEqual(r["stockout_probability"], 0.0)
        self.assertIsNone(r["days_of_stock"])


if __name__ == "__main__":
    unittest.main()
