"""Independent oracle: monthly Autos / Light Commercial totals from Fenabrave PDFs.

Uses only `pdftotext` (poppler) and the standard library.
Usage: python3 -I extract_pdf_totals.py <download_dir> <output_csv>
"""
import csv
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PDFTOTEXT = shutil.which("pdftotext") or "pdftotext"
MONTHS_PT = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
             "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
             "outubro": 10, "novembro": 11, "dezembro": 12}
FILE_RE = re.compile(r"^(\d{4})_(\d{2})_(\w+)\.pdf$")
# Matches "Resumo Mensal Junho de 2008" and the older "RESUMO MENSAL JANEIRO 2004".
TITLE_RE = re.compile(r"Resumo\s+Mensal\s+([^\W\d_]+)\s+(?:de\s+)?(\d{4})", re.I)
INT_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*$|^\d+$")
COLUMNS = ["month", "source_file", "autos_month", "light_commercial_month",
           "autos_plus_lc_month", "autos_prev_month", "light_commercial_prev_month",
           "autos_ytd", "light_commercial_ytd", "parse_status"]


def parse_row(lines, prefix_re):
    """Return (label_text, [A, B, C, D, E]) for the first line matching prefix_re."""
    for line in lines:
        m = prefix_re.match(line)
        if not m:
            continue
        rest = line[m.end():]
        label = re.match(r"\s*([^\d\n]*?)\s{2,}|\s*([^\d\n]*?)\s+(?=\d)", rest)
        label_text = ((label.group(1) or label.group(2) or "") if label else "").strip()
        tokens = rest[len(label.group(0)) if label else 0:].split()
        nums = []
        for t in tokens:
            if INT_RE.match(t):
                nums.append(int(t.replace(".", "")))
            else:
                break
        if len(nums) >= 5:
            return label_text, nums[:5]
    return None, None


def extract(pdf):
    out = subprocess.run([PDFTOTEXT, "-layout", "-f", "1", "-l", "1", str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    # Some PDFs emit a stray "\u00ac" glyph at the start of table lines.
    lines = [ln.replace("\u00ac", " ") for ln in out.splitlines()]
    out = "\n".join(lines)
    tm = TITLE_RE.search(out)
    title_month = None
    if tm and tm.group(1).lower() in MONTHS_PT:
        title_month = (int(tm.group(2)), MONTHS_PT[tm.group(1).lower()])
    la, a = parse_row(lines, re.compile(r"^\s*A\)|^\s*a\)"))
    lb, b = parse_row(lines, re.compile(r"^\s*B\)|^\s*b\)"))
    _, ab = parse_row(lines, re.compile(r"^\s*(?:A\+B\b|\(a\s*\+\s*b\))", re.I))
    if a is None or b is None or ab is None:
        raise ValueError("missing row(s): A=%s B=%s A+B=%s" % (a is not None, b is not None, ab is not None))
    return title_month, la, lb, a, b, ab


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    rows, labels, notes = [], defaultdict(set), []
    for pdf in sorted(src.glob("*.pdf")):
        fm = FILE_RE.match(pdf.name)
        fmonth = (int(fm.group(1)), int(fm.group(2))) if fm else None
        try:
            month, la, lb, a, b, ab = extract(pdf)
            status = "ok"
            if month is None:  # garbled title font: fall back to the file name
                month = fmonth
                notes.append("%s: title unreadable, month taken from file name" % pdf.name)
            elif fmonth and fmonth != month:
                # e.g. 2023_02_3.pdf is the March 2023 edition; the title is authoritative
                notes.append("%s: file name month %04d-%02d != title month %04d-%02d (title used)"
                             % ((pdf.name,) + fmonth + month))
            labels[month[0]].add((la, lb))
            rows.append(dict(month="%04d-%02d-01" % month, source_file=pdf.name,
                             autos_month=a[0], light_commercial_month=b[0],
                             autos_plus_lc_month=ab[0], autos_prev_month=a[1],
                             light_commercial_prev_month=b[1], autos_ytd=a[2],
                             light_commercial_ytd=b[2], parse_status=status))
        except Exception as e:  # noqa: BLE001 - recorded in CSV
            m = "%04d-%02d-01" % fmonth if fmonth else ""
            rows.append(dict(month=m, source_file=pdf.name, parse_status="error:%s" % e))
    rows.sort(key=lambda r: (r["month"], r["source_file"]))
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["parse_status"] == "ok"]
    print("files: %d, ok: %d" % (len(rows), len(ok)))
    print("notes:")
    for n in notes:
        print("  " + n)
    # (5) parse errors
    errs = [r for r in rows if r["parse_status"] != "ok"]
    print("\n(5) parse errors: %d" % len(errs))
    for r in errs:
        print("  %s %s %s" % (r["month"], r["source_file"], r["parse_status"]))
    # (4) coverage
    by_month = defaultdict(list)
    for r in ok:
        by_month[r["month"]].append(r["source_file"])
    expected = ["%04d-%02d-01" % (y, m) for y in range(2003, 2027) for m in range(1, 13)
                if (y, m) <= (2026, 1)]
    missing = [m for m in expected if m not in by_month]
    dups = {m: f for m, f in by_month.items() if len(f) > 1}
    extra = [m for m in by_month if m not in expected]
    print("\n(4) months expected %d, present %d; missing=%s; duplicates=%s; extra=%s"
          % (len(expected), len(by_month), missing, dups, extra))
    # (1) A + B == A+B
    bad1 = [r for r in ok if r["autos_month"] + r["light_commercial_month"] != r["autos_plus_lc_month"]]
    print("\n(1) autos+lc == A+B: %d/%d ok, mismatches=%d" % (len(ok) - len(bad1), len(ok), len(bad1)))
    for r in bad1:
        print("  %s %s autos=%d lc=%d a+b=%d" % (r["month"], r["source_file"], r["autos_month"],
              r["light_commercial_month"], r["autos_plus_lc_month"]))
    # (2) prev-month column vs previous month's col A
    idx = {r["month"]: r for r in ok}
    exact = checked = 0
    mism = []
    for m, r in sorted(idx.items()):
        y, mo = int(m[:4]), int(m[5:7])
        pm = "%04d-%02d-01" % ((y, mo - 1) if mo > 1 else (y - 1, 12))
        if pm not in idx:
            continue
        p = idx[pm]
        for name, cur, prev in (("autos", "autos_prev_month", "autos_month"),
                                ("light_commercial", "light_commercial_prev_month", "light_commercial_month")):
            checked += 1
            if r[cur] == p[prev]:
                exact += 1
            else:
                mism.append("  %s %s: col B=%d vs %s col A=%d (diff %+d)" % (
                    m[:7], name, r[cur], pm[:7], p[prev], r[cur] - p[prev]))
    print("\n(2) prev-month col B vs prior month col A: checked=%d exact=%d mismatches=%d"
          % (checked, exact, len(mism)))
    print("\n".join(mism))
    # (3) YTD
    ytd_checked = 0
    ytd_bad = []
    for m, r in sorted(idx.items()):
        y, mo = int(m[:4]), int(m[5:7])
        months = ["%04d-%02d-01" % (y, k) for k in range(1, mo + 1)]
        if any(k not in idx for k in months):
            ytd_bad.append("  %s: cannot check (missing months in year)" % m[:7])
            continue
        for name, ytd, mcol in (("autos", "autos_ytd", "autos_month"),
                                ("light_commercial", "light_commercial_ytd", "light_commercial_month")):
            ytd_checked += 1
            s = sum(idx[k][mcol] for k in months)
            if s != r[ytd]:
                ytd_bad.append("  %s %s: col C=%d vs sum Jan..m col A=%d (diff %+d)" % (
                    m[:7], name, r[ytd], s, r[ytd] - s))
    print("\n(3) YTD col C vs sum of col A: checked=%d mismatches=%d" % (ytd_checked, len(ytd_bad)))
    print("\n".join(ytd_bad))
    print("\nlabel variants (A row label, B row label) by year:")
    for y in sorted(labels):
        print("  %d: %s" % (y, sorted(labels[y])))


if __name__ == "__main__":
    main()
