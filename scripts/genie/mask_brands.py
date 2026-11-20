#!/usr/bin/env python3
"""Mask real brand names in a text transcript (stdin → stdout) with stable tokens BRAND_<sha6>, so committed
evidence carries no real brand names. The brand list is read from a file (one per line, not committed).
Aurora Motors (fictional) is kept. Usage: mask_brands.py BRANDS_FILE < in.txt > out.txt"""
import hashlib, re, sys
brands = sorted({b.strip() for b in open(sys.argv[1]) if b.strip() and b.strip() != "AURORA MOTORS"},
                key=len, reverse=True)
text = sys.stdin.read()
for b in brands:
    tok = "BRAND_" + hashlib.sha1(b.encode()).hexdigest()[:6]
    text = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(b) + r"(?![A-Za-z0-9_])", tok, text, flags=re.IGNORECASE)
sys.stdout.write(text)
