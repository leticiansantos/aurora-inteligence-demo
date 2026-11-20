"""Pure planning logic for the Fenabrave downloader: URL candidates and what to (re)probe.

No I/O and no Spark here, so everything is unit-testable.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Iterable

BASE_URL = "https://www.fenabrave.org.br/portal/files/"
# Unprefixed variants probed for every new month (ADR D1); all are probed, none short-circuits.
VARIANTS = ("02", "2", "3")
TERMINAL_STATUSES = {"downloaded", "duplicate", "not_found"}
REPROBE_WINDOW_MONTHS = 3

_URL_MONTH_RE = re.compile(r"(?:^|/)(?:\d+_)?(\d{4})_(\d{2})_[0-9A-Za-z]+\.pdf$")


def url_month(url: str) -> date:
    """First day of the month encoded in the URL file name (a plain label, not the reference month)."""
    m = _URL_MONTH_RE.search(url)
    if not m:
        raise ValueError(f"Cannot read year/month from URL: {url}")
    return date(int(m.group(1)), int(m.group(2)), 1)


def basename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def load_seed(path: Path | None = None) -> list[str]:
    path = path or Path(__file__).with_name("seed_urls.json")
    return list(json.loads(path.read_text())["urls"])


def add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def month_range(start: date, end: date) -> list[date]:
    """Inclusive list of first-of-month dates."""
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def discovery_candidates(last_seed_month: date, today: date) -> list[str]:
    """All unprefixed variants for every month after the last seed month, up to today's month."""
    urls: list[str] = []
    for m in month_range(add_months(last_seed_month, 1), today):
        for v in VARIANTS:
            urls.append(f"{BASE_URL}{m.year}_{m.month:02d}_{v}.pdf")
    return urls


def build_candidates(seed: Iterable[str], today: date) -> list[tuple[str, str]]:
    """(url, origin) for seed and discovery URLs, ordered by url_month then URL (deterministic)."""
    seed = list(seed)
    last_seed = max(url_month(u) for u in seed)
    pairs = [(u, "seed") for u in seed] + [(u, "discovery") for u in discovery_candidates(last_seed, today)]
    return sorted(pairs, key=lambda p: (url_month(p[0]), p[0]))


def select_to_probe(candidates: list[tuple[str, str]], existing: dict[str, str], today: date) -> list[tuple[str, str]]:
    """Pick the candidates that need an HTTP probe in this run.

    existing maps source_url -> last status. Terminal statuses are never retried, except
    `not_found` for the most recent REPROBE_WINDOW_MONTHS url months (late publication).
    `failed` (transient) and unknown URLs are always (re)tried.
    """
    window_start = add_months(date(today.year, today.month, 1), -(REPROBE_WINDOW_MONTHS - 1))
    todo = []
    for url, origin in candidates:
        status = existing.get(url)
        if status is None or status not in TERMINAL_STATUSES:
            todo.append((url, origin))
        elif status == "not_found" and url_month(url) >= window_start:
            todo.append((url, origin))
    return todo
