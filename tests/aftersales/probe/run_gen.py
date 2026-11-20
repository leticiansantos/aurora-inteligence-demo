import csv, sys, time
from datetime import date
src, regs_csv, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, src)
from aftersales_config import DEFAULT_CONFIG
from aftersales_generator import fleet_by_dealer_month
from aftersales_writer import write_all
regs = {}
for r in csv.DictReader(open(regs_csv)):
    regs[(date.fromisoformat(r["ref_month"]), r["model"])] = float(r["units"])
t = time.time()
print(write_all(out, fleet_by_dealer_month(regs, DEFAULT_CONFIG), DEFAULT_CONFIG), DEFAULT_CONFIG.version, f"{time.time()-t:.0f}s")
