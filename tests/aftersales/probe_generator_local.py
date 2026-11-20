"""Local, workspace-free probe of the synthetic generator (ADR 002 D1): runs it twice on the Tela 1 registrations,
checks byte-identical output, calendar/grid rules, the D1 fill-rate target and a leak scan (counts only).

Usage: python3 -I tests/aftersales/probe_generator_local.py <generator src dir> <registrations.csv> <work dir> \
           <legacy csv dir> <real brands.txt>
registrations.csv: SELECT ref_month, model, units FROM market_synthetic_registrations (CSV with header).
brands.txt: SELECT DISTINCT brand FROM market_brand_monthly (kept outside the repo; never committed).
"""
import hashlib
import os
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
src, regs, work, legacy, brands = sys.argv[1:6]
hashes = []
for run in ("out1", "out2"):
    subprocess.run([sys.executable, "-I", str(HERE / "probe" / "run_gen.py"), src, regs, os.path.join(work, run)], check=True)
    h = hashlib.sha256()
    for f in sorted(Path(work, run).rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(Path(work, run))).encode()); h.update(f.read_bytes())
    hashes.append(h.hexdigest())
print("byte-identical across 2 runs:", hashes[0] == hashes[1], hashes[0][:16])
sys.argv = ["probe.py", os.path.join(work, "out1"), legacy, brands]
runpy.run_path(str(HERE / "probe" / "probe.py"), run_name="__main__")
