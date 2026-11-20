"""Versioned configuration for the fictional automaker "Aurora Motors"."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AuroraConfig:
    version: str = "aurora-gen-1.0.0"
    seed: int = 20190101
    brand: str = "AURORA MOTORS"
    segment: str = "automoveis"
    launch_date: date = date(2019, 1, 1)
    # model -> base split (renormalized after noise)
    models: tuple = (("IPE", 0.45), ("JATOBA", 0.35), ("AROEIRA", 0.20))
    split_noise: float = 0.05  # +/- relative noise on each model weight
    # share curve
    ramp_months: int = 36  # 2019-01 -> 2022-01
    ramp_end_share: float = 0.03
    hold_share: float = 0.033
    seasonality_amplitude: float = 0.0035
    share_noise: float = 0.0015  # +/- absolute noise
    # clamps
    max_share: float = 0.04
    min_share_after_ramp: float = 0.03
    min_share_during_ramp: float = 0.0


DEFAULT_CONFIG = AuroraConfig()
