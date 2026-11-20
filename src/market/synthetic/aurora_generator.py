"""Pure, deterministic Aurora Motors generator (no pyspark import).

`generate_rows` is the reference implementation (and unit-test oracle); the pipeline reproduces the
same math lazily in Spark from `curve_rows` (see market_synthetic_registrations.py).
"""
import hashlib
import math
from datetime import date

from aurora_config import DEFAULT_CONFIG, AuroraConfig


def _noise(seed: int, ref_month: date, tag: str) -> float:
    """Deterministic uniform value in [-1, 1] from (seed, month, tag); order independent."""
    digest = hashlib.blake2b(f"{seed}|{ref_month.isoformat()}|{tag}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / (2**64 - 1) * 2 - 1


def _months_since_launch(ref_month: date, launch: date) -> int:
    return (ref_month.year - launch.year) * 12 + (ref_month.month - launch.month)


def target_share(ref_month: date, cfg: AuroraConfig) -> float:
    t = _months_since_launch(ref_month, cfg.launch_date)
    frac = min(max(t, 0) / cfg.ramp_months, 1.0)
    base = cfg.ramp_end_share * frac if t < cfg.ramp_months else cfg.hold_share
    seasonal = cfg.seasonality_amplitude * math.sin(2 * math.pi * (ref_month.month - 1) / 12) * frac
    noise = cfg.share_noise * _noise(cfg.seed, ref_month, "share") * frac
    lo = cfg.min_share_during_ramp if t < cfg.ramp_months else cfg.min_share_after_ramp
    return min(max(base + seasonal + noise, lo), cfg.max_share)


def normalized_weights(ref_month: date, cfg: AuroraConfig) -> list:
    """Per-model split weights for a month (seeded noise, renormalized to sum to 1)."""
    weights = [w * (1 + cfg.split_noise * _noise(cfg.seed, ref_month, f"model:{m}")) for m, w in cfg.models]
    s = sum(weights)
    return [w / s for w in weights]


def _split(total: int, ref_month: date, cfg: AuroraConfig) -> list:
    raw = [total * w for w in normalized_weights(ref_month, cfg)]
    units = [int(math.floor(r)) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - units[i]), i))
    for i in order[: total - sum(units)]:
        units[i] += 1
    return units


def curve_rows(cfg: AuroraConfig = DEFAULT_CONFIG, end_year: int = 2050) -> list:
    """Static (ref_month, model, tie_idx, target_share, weight) curve from launch to end_year-12.

    Everything noisy depends only on (seed, month, tag), so it can be precomputed at pipeline
    definition time. The pipeline joins it lazily with the real totals (no Spark action needed).
    """
    out, y, m = [], cfg.launch_date.year, cfg.launch_date.month
    while y <= end_year:
        ref = date(y, m, 1)
        share, weights = target_share(ref, cfg), normalized_weights(ref, cfg)
        for i, ((model, _), w) in enumerate(zip(cfg.models, weights)):
            out.append((ref, model, i, share, w))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def generate_rows(totals, cfg: AuroraConfig = DEFAULT_CONFIG) -> list:
    """totals: iterable of (ref_month: date, total_real_units: int) for the automoveis segment."""
    rows = []
    for ref_month, total_real in sorted(totals, key=lambda x: x[0]):
        if ref_month < cfg.launch_date or total_real is None or total_real < 0:
            continue
        share = target_share(ref_month, cfg)
        aurora_total = int(round(share * total_real / (1 - share)))
        for (model, _), units in zip(cfg.models, _split(aurora_total, ref_month, cfg)):
            rows.append(
                {
                    "ref_month": ref_month,
                    "segment": cfg.segment,
                    "brand": cfg.brand,
                    "model": model,
                    "units": units,
                    "target_share": share,
                    "is_synthetic": True,
                    "generator_version": cfg.version,
                    "seed": cfg.seed,
                }
            )
    return rows
