"""Pure, deterministic aftersales generator (stdlib only; no pyspark import).

The job task (main.py) reads market_synthetic_registrations with Spark and hands plain Python data to this
module, so everything here is unit-testable without a workspace. Same (seed, version, fleet) -> same rows.
"""
import hashlib
import math
from datetime import date, timedelta

from aftersales_config import CATEGORIES, DEALERS, DEFAULT_CONFIG, PARTS, SEASONALITY, AftersalesConfig

DEALER_IDS = [d[0] for d in DEALERS]
PART_IDS = [f"P{i + 1:03d}" for i in range(len(PARTS))]
PART_CATEGORY = [p[1] for p in PARTS]


def _noise(seed: int, *tags) -> float:
    """Deterministic uniform value in [-1, 1] from (seed, tags); order independent."""
    key = "|".join([str(seed), *map(str, tags)]).encode()
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") / (2**64 - 1) * 2 - 1


def _erfinv(x: float) -> float:
    a = 0.147
    ln = math.log(1 - x * x)
    t = 2 / (math.pi * a) + ln / 2
    return math.copysign(math.sqrt(math.sqrt(t * t - ln / a) - t), x)


def _normal(seed: int, *tags) -> float:
    u = min(max(_noise(seed, *tags), -1 + 1e-9), 1 - 1e-9)
    return math.sqrt(2) * _erfinv(u)


def _poisson(lam: float, u: float) -> int:
    """Inverse-CDF Poisson from a uniform u in [0, 1)."""
    if lam <= 0:
        return 0
    if lam > 40:  # normal approximation
        z = math.sqrt(2) * _erfinv(2 * min(max(u, 1e-9), 1 - 1e-9) - 1)
        return max(0, int(round(lam + math.sqrt(lam) * z)))
    p = math.exp(-lam)
    cdf, k = p, 0
    while u > cdf and k < 400:
        k += 1
        p *= lam / k
        cdf += p
    return k


# ---- static entities -------------------------------------------------------------------------------------


def dealers_rows():
    return [(d[0], f"Aurora Motors {d[1]}", d[1], d[2], d[3], d[4], d[5] / 1000.0) for d in DEALERS]


def parts_rows():
    return [
        (PART_IDS[i], p[0], p[1], CATEGORIES[p[1]], p[2], round(p[2] * p[3], 2), "true" if p[5] else "false")
        for i, p in enumerate(PARTS)
    ]


def lead_time_days(dealer_idx: int, part_idx: int, cfg: AftersalesConfig = DEFAULT_CONFIG) -> int:
    """Contractual supplier lead time (3..30 days); critical parts are imported, so they take longer."""
    critical = PARTS[part_idx][5]
    base = 18 if critical else 6
    spread = 8 if critical else 3
    region_extra = {"Sudeste": 0, "Sul": 1, "Centro-Oeste": 2, "Nordeste": 3}[DEALERS[dealer_idx][3]]
    n = _noise(cfg.seed, "lt", dealer_idx, part_idx)
    return int(min(30, max(3, round(base + spread * n + region_extra))))


def lead_times_rows(cfg: AftersalesConfig = DEFAULT_CONFIG):
    return [
        (DEALER_IDS[d], PART_IDS[p], lead_time_days(d, p, cfg))
        for d in range(len(DEALERS))
        for p in range(len(PARTS))
    ]


# ---- fleet -----------------------------------------------------------------------------------------------


def fleet_by_dealer_month(registrations: dict, cfg: AftersalesConfig = DEFAULT_CONFIG) -> dict:
    """{(dealer_idx, first_of_month): active fleet (float)} summed over models, cumulative, no rounding.

    registrations: {(first_of_month, model): units}. Months after cfg.fleet_last_month reuse the last fleet.
    """
    months = sorted({m for (m, _) in registrations})
    expected = [date(2019 + i // 12, i % 12 + 1, 1) for i in range((cfg.fleet_last_month.year - 2019) * 12 + cfg.fleet_last_month.month)]
    missing = [m for m in expected if m not in set(months)]
    if missing:
        raise ValueError(f"registrations miss {len(missing)} months, first {missing[0]}")
    cum, out = {}, {}
    for m in months:
        for (mm, model), units in registrations.items():
            if mm == m:
                cum[model] = cum.get(model, 0.0) + units
        total = sum(cum.values())
        for di, d in enumerate(DEALERS):
            out[(di, m)] = total * d[5] / 1000.0
    return out


def _fleet_lookup(fleet: dict, di: int, d: date, cfg: AftersalesConfig) -> float:
    m = min(date(d.year, d.month, 1), cfg.fleet_last_month)
    return fleet[(di, m)]  # KeyError on a gap instead of silently zeroing demand


def effective_fleet(fleet: dict, di: int, d: date, cfg: AftersalesConfig = DEFAULT_CONFIG) -> float:
    """Vehicles older than 12 months count fully, newer ones at cfg.new_vehicle_wear (fleet-age factor)."""
    now = _fleet_lookup(fleet, di, d, cfg)
    y, m = d.year - 1, d.month
    old = _fleet_lookup(fleet, di, date(y, m, 1), cfg) if date(y, m, 1) >= date(2019, 1, 1) else 0.0
    return old + cfg.new_vehicle_wear * (now - old)


# ---- demand ----------------------------------------------------------------------------------------------


def expected_daily_rate(eff_fleet: float, part_idx: int, d: date, cfg: AftersalesConfig = DEFAULT_CONFIG) -> float:
    """Expected units demanded on day d at one dealer for one part (before dispersion)."""
    nominal = PARTS[part_idx][4]
    season = SEASONALITY[PART_CATEGORY[part_idx]][d.month - 1]
    wd = cfg.weekday_factors[d.weekday()]
    # nominal is per 1,000 vehicles per year; normalise the weekday pattern to ~5.45 open-day-equivalents/week
    return eff_fleet / 1000.0 * nominal / 365.25 * season * wd * 7.0 / sum(cfg.weekday_factors)


def demand_units(rate: float, di: int, pi: int, d: date, cfg: AftersalesConfig = DEFAULT_CONFIG) -> int:
    if rate <= 0:
        return 0
    mult = math.exp(cfg.overdispersion * _normal(cfg.seed, "ovd", di, pi, d.isoformat()) - cfg.overdispersion**2 / 2)
    u = (_noise(cfg.seed, "dem", di, pi, d.isoformat()) + 1) / 2
    return _poisson(rate * mult, min(u, 1 - 1e-12))


# ---- stock simulation ------------------------------------------------------------------------------------


class SeriesState:
    """One dealer x part stock series: (s, S) policy with a per-dealer cover factor, pipeline of open orders."""

    def __init__(self, di: int, pi: int, cfg: AftersalesConfig):
        self.di, self.pi, self.cfg = di, pi, cfg
        self.lead = lead_time_days(di, pi, cfg)
        self.cover = DEALERS[di][6] * (1 + 0.25 * _noise(cfg.seed, "cover", di, pi))
        self.stock = None
        self.pipeline = []  # list of (due_date, qty)

    def on_order(self) -> int:
        return sum(q for _, q in self.pipeline)

    def step(self, fleet: dict, d: date):
        """Advance one day. Returns (demand, sold, lost)."""
        cfg, di, pi = self.cfg, self.di, self.pi
        eff = effective_fleet(fleet, di, d, cfg)
        # planning rate: season-aware average daily demand (what a dealer system would forecast)
        plan = max(expected_daily_rate(eff, pi, d.replace(day=15), cfg) * sum(cfg.weekday_factors) / 7.0, 0.0)
        s_level = math.ceil(self.cover * plan * (self.lead + cfg.reorder_buffer_days))
        big_s = s_level + math.ceil(self.cover * plan * cfg.cover_days_after_lead)
        if self.stock is None:
            self.stock = big_s
        # receipts
        due = [q for (t, q) in self.pipeline if t <= d]
        if due:
            self.stock += sum(due)
            self.pipeline = [(t, q) for (t, q) in self.pipeline if t > d]
        dem = demand_units(expected_daily_rate(eff, pi, d, cfg), di, pi, d, cfg)
        sold = min(self.stock, dem)
        self.stock -= sold
        # periodic review
        if d.toordinal() % cfg.review_days == 0:
            position = self.stock + self.on_order()
            if position <= s_level and big_s > position:
                lt = self.lead * (1 + cfg.lead_time_jitter * _noise(cfg.seed, "ltj", di, pi, d.isoformat()))
                if _noise(cfg.seed, "delay", di, pi, d.isoformat()) > 1 - 2 * cfg.delay_probability:
                    lt *= cfg.delay_multiplier
                if cfg.disruption_start <= d <= cfg.disruption_end and PART_CATEGORY[pi] in cfg.disruption_categories:
                    lt += cfg.disruption_extra_days
                self.pipeline.append((d + timedelta(days=max(1, int(round(lt)))), big_s - position))
        if (d == cfg.writeoff_date and PARTS[pi][5] and self.lead >= cfg.writeoff_min_lead_days
                and not self.pipeline
                and (_noise(cfg.seed, "writeoff", di, pi) + 1) / 2 < cfg.writeoff_probability):
            self.stock = int(self.stock * cfg.writeoff_keep_share)
        return dem, sold, dem - sold


def iter_days(cfg: AftersalesConfig = DEFAULT_CONFIG):
    d = cfg.history_start
    while d <= cfg.history_end:
        yield d
        d += timedelta(days=1)


def simulate(fleet: dict, cfg: AftersalesConfig = DEFAULT_CONFIG):
    """Yield, day by day: (date, sales_rows, snapshot_rows).

    sales_rows: list of (sale_date, dealer_id, part_id, demand, sold, lost) for all dealer x part pairs (dense).
    snapshot_rows: only on Sundays, end-of-day (snapshot_date, dealer_id, part_id, on_hand, on_order).
    """
    states = [[SeriesState(di, pi, cfg) for pi in range(len(PARTS))] for di in range(len(DEALERS))]
    for d in iter_days(cfg):
        sales, snaps = [], []
        for di, row in enumerate(states):
            for pi, st in enumerate(row):
                dem, sold, lost = st.step(fleet, d)
                sales.append((d.isoformat(), DEALER_IDS[di], PART_IDS[pi], dem, sold, lost))
                if d.weekday() == 6:
                    snaps.append((d.isoformat(), DEALER_IDS[di], PART_IDS[pi], st.stock, st.on_order()))
        yield d, sales, snaps
