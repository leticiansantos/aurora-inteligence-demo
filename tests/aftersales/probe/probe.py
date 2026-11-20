import csv, glob, os, re, sys
from collections import defaultdict
from datetime import date
out, legacy, brands_file = sys.argv[1], sys.argv[2], sys.argv[3]
R = lambda p: list(csv.DictReader(open(p, encoding="utf-8")))
dealers = R(f"{out}/dealers/dealers.csv"); parts = R(f"{out}/parts/parts.csv")
print("dealers", len(dealers), "parts", len(parts), "headers", list(dealers[0]), list(parts[0]))
opened = {d["dealer_id"]: date.fromisoformat(d["opened_on"]) for d in dealers}
price = {p["part_id"]: float(p["unit_price_brl"]) for p in parts}
n = sun_bad = lost_bad = pre_open = 0; days = set()
dem4 = sold4 = 0; yr = defaultdict(lambda: [0, 0]); hdr = None
for f in sorted(glob.glob(f"{out}/daily_sales/*.csv")):
    for r in csv.DictReader(open(f)):
        hdr = hdr or list(r)
        n += 1; d = date.fromisoformat(r["sale_date"]); days.add(d)
        dm, so, lo = int(r["demand_units"]), int(r["sold_units"]), int(r["lost_units"])
        if d.weekday() == 6 and dm: sun_bad += 1
        if lo != dm - so or lo < 0 or so < 0: lost_bad += 1
        if d < opened[r["dealer_id"]] and dm > 0: pre_open += 1
        if date(2026, 10, 19) <= d <= date(2026, 11, 15): dem4 += dm; sold4 += so
        yr[d.year][0] += dm; yr[d.year][1] += lo
print("daily header", hdr)
print("rows", n, "expected", 720 * len(days), "range", min(days), max(days))
print("sunday_bad", sun_bad, "lost_bad", lost_bad, "demand_before_opened_on", pre_open)
print("fill_rate_last4w", round(sold4 / dem4, 4) if dem4 else None, "(D1 target 0.88..0.97)")
print("yearly demand / lost share", {y: (v[0], round(v[1] / v[0], 3)) for y, v in sorted(yr.items())})
# leak scan over every landing file
codes = {r["codigo_original"].strip().upper() for r in csv.DictReader(open(f"{legacy}/pecas.csv")) if len(r["codigo_original"].strip()) >= 6}
names = {r["loja"].strip().upper() for r in csv.DictReader(open(f"{legacy}/lojas.csv"))}
brands = {b.strip().strip('"').upper() for b in open(brands_file) if b.strip()} - {"AURORA MOTORS"}
brands = {b for b in brands if not b.startswith("OUTRAS")}
text = "\n".join(open(f, encoding="utf-8").read().upper() for f in [f"{out}/dealers/dealers.csv", f"{out}/parts/parts.csv"])
def hits(words): return sum(1 for w in words if re.search(r"(?<![A-Z0-9])" + re.escape(w) + r"(?![A-Z0-9])", text))
print("leak: legacy codes", hits(codes), "of", len(codes), "| legacy dealer names", hits(names), "of", len(names), "| real brands", hits(brands), "of", len(brands), "| cloudfront", "CLOUDFRONT" in text)
