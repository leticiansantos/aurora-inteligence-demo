"""Mask real brand names in evidence files (ADR D6): BRAND -> BRAND_<first 6 hex of sha256(BRAND)>.

Counts, months, ranks, units and shares are untouched. 'AURORA MOTORS' (fictional) and the residual
'OUTRAS (NAO PUBLICADAS)' are kept. A brand is replaced only as a whole token (not inside a longer
alphanumeric word), longest names first, so a composite name like 'X/Y' is masked before 'X'.

Usage: python3 -I mask_brands.py <brands.txt> <file>...   (brands.txt: one brand per line; files rewritten in place)
Exit 1 if, after masking, any brand from the list is still present in a file.
"""
import hashlib
import re
import sys
from pathlib import Path

KEEP = {"AURORA MOTORS", "OUTRAS (NAO PUBLICADAS)"}
# Never treat these as brands even if a parser emitted them: they are words of the evidence format itself.
RESERVED = {"PASS", "FAIL", "ERROR", "INFO", "REPORT", "MISSING", "SELECT", "FROM", "WHERE", "AND", "OR", "NOT",
            "AS", "ON", "IN", "IS", "NULL", "TRUE", "FALSE", "UNION", "ALL", "GROUP", "BY", "ORDER", "WITH", "JOIN"}


def token(brand: str) -> str:
    return "BRAND_" + hashlib.sha256(brand.encode("utf-8")).hexdigest()[:6]


def pattern_for(brand: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(brand) + r"(?![A-Za-z0-9])")


def main() -> int:
    brands = {b.strip().strip('"') for b in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()}
    brands = sorted((b for b in brands if b and b not in KEEP and b not in RESERVED and b != "brand"),
                    key=len, reverse=True)
    pats = [(pattern_for(b), token(b)) for b in brands]
    leaks = 0
    for name in sys.argv[2:]:
        p = Path(name)
        text = p.read_text(encoding="utf-8")
        for pat, tok in pats:
            text = pat.sub(tok, text)
        p.write_text(text, encoding="utf-8")
        for pat, _ in pats:
            if pat.search(text):
                leaks += 1
                print(f"LEAK {p}: {pat.pattern}", file=sys.stderr)
    print(f"masked {len(brands)} brand names in {len(sys.argv) - 2} files; leaks={leaks}")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
