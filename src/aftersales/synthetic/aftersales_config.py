"""Versioned configuration for the synthetic aftersales domain of the fictional automaker "Aurora Motors".

Everything here is invented: fictional dealers (real Brazilian cities are allowed), generic part names, no real
brand or part codes. Contract: docs/data-model/aftersales.md. Changing anything that affects the output requires
bumping `version` (and a full refresh of the pipeline, see src/aftersales/pipeline/README.md).
"""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AftersalesConfig:
    version: str = "aftersales-gen-1.0.0"
    seed: int = 20261120
    history_start: date = date(2019, 1, 1)
    history_end: date = date(2026, 11, 15)  # a Sunday; AS_OF / forecast_date = 2026-11-16
    fleet_last_month: date = date(2026, 9, 1)  # registrations stop here; later months reuse this fleet
    weekday_factors: tuple = (1.0, 1.0, 1.0, 1.0, 1.05, 0.45, 0.0)  # Mon..Sun (Sunday closed)
    overdispersion: float = 0.30  # sd of the log-normal demand multiplier (gamma-Poisson like)
    new_vehicle_wear: float = 0.30  # vehicles younger than 12 months use 30% of the nominal parts
    lead_time_jitter: float = 0.30  # actual supplier lead time varies +/-30% around the contract
    delay_probability: float = 0.10  # share of orders hit by a supplier delay
    delay_multiplier: float = 2.2
    # Supplier disruption (a documented demo event): orders placed in the window for these categories arrive late.
    disruption_start: date = date(2026, 8, 15)
    disruption_end: date = date(2026, 10, 31)
    disruption_categories: tuple = ("filters", "engine", "lighting")
    disruption_extra_days: int = 45
    # Inventory-count write-off (a documented demo event) on the last day: long-lead critical parts with nothing on
    # order lose most of their stock, which creates genuinely critical stockout risk at forecast time.
    writeoff_date: date = date(2026, 11, 15)
    writeoff_min_lead_days: int = 14
    writeoff_probability: float = 0.12
    writeoff_keep_share: float = 0.15
    review_days: int = 3  # the dealer reviews the reorder point every 3 days (Mon/Thu style)
    reorder_buffer_days: int = 30  # reorder point = cover x demand over (lead time + this buffer)
    cover_days_after_lead: int = 30  # order-up-to level = reorder point + cover x this many days of demand


DEFAULT_CONFIG = AftersalesConfig()

# (dealer_id, city, state, region, opened_on, weight/1000, stock_cover); every dealer opened before the first sale
# stock_cover scales the reorder point: <1 = under-stocked store (stockouts), >1 = over-stocked (transfer donor).
DEALERS = (
    ("D001", "São Paulo", "SP", "Sudeste", "2018-03-01", 150, 1.05),
    ("D002", "Campinas", "SP", "Sudeste", "2018-03-01", 90, 1.70),
    ("D003", "Rio de Janeiro", "RJ", "Sudeste", "2018-04-01", 120, 1.05),
    ("D004", "Belo Horizonte", "MG", "Sudeste", "2018-05-01", 100, 1.60),
    ("D005", "Curitiba", "PR", "Sul", "2018-03-01", 90, 1.25),
    ("D006", "Porto Alegre", "RS", "Sul", "2018-06-01", 80, 1.1),
    ("D007", "Florianópolis", "SC", "Sul", "2018-08-01", 60, 1.60),
    ("D008", "Salvador", "BA", "Nordeste", "2018-07-01", 80, 1.0),
    ("D009", "Recife", "PE", "Nordeste", "2018-09-01", 70, 1.60),
    ("D010", "Fortaleza", "CE", "Nordeste", "2018-10-01", 60, 1.05),
    ("D011", "Brasília", "DF", "Centro-Oeste", "2018-06-01", 70, 1.00),
    ("D012", "Goiânia", "GO", "Centro-Oeste", "2018-11-01", 30, 1.50),
)

CATEGORIES = {
    "brakes": "Freios",
    "filters": "Filtros",
    "suspension": "Suspensão",
    "electrical": "Elétrica",
    "engine": "Motor",
    "cooling": "Arrefecimento",
    "lighting": "Iluminação",
    "air_conditioning": "Ar-condicionado",
}

# Monthly seasonality multipliers Jan..Dec (mean ~1) per category.
SEASONALITY = {
    "brakes": (1.15, 1.10, 1.10, 1.00, 0.90, 0.85, 0.90, 0.90, 0.95, 1.00, 1.05, 1.20),
    "filters": (1.25, 0.95, 0.90, 1.00, 0.95, 0.90, 1.25, 0.95, 0.95, 1.00, 0.95, 0.95),  # revisions peak Jan/Jul
    "suspension": (1.10, 1.15, 1.10, 1.00, 0.90, 0.85, 0.90, 0.90, 0.95, 1.00, 1.05, 1.10),
    "electrical": (0.90, 0.85, 0.90, 0.95, 1.05, 1.25, 1.25, 1.10, 0.95, 0.90, 0.90, 0.90),  # winter batteries
    "engine": (1.10, 0.95, 0.95, 1.00, 1.00, 1.00, 1.10, 1.00, 1.00, 1.00, 0.95, 1.00),
    "cooling": (1.20, 1.15, 1.05, 0.95, 0.85, 0.80, 0.85, 0.95, 1.05, 1.10, 1.15, 1.20),
    "lighting": (1.15, 1.10, 1.10, 1.00, 0.95, 0.90, 0.90, 0.90, 0.95, 1.00, 1.00, 1.15),
    "air_conditioning": (1.35, 1.30, 1.15, 0.95, 0.75, 0.65, 0.70, 0.85, 1.00, 1.15, 1.25, 1.35),  # summer peak
}

# (name, category_id, unit_price_brl, unit_cost_ratio, nominal parts per 1,000 active vehicles per year, is_critical)
# Critical parts immobilize the vehicle; they are imported (longer lead time).
PARTS = (
    ("Pastilha de freio dianteira", "brakes", 189.90, 0.55, 95, True),
    ("Pastilha de freio traseira", "brakes", 159.90, 0.55, 60, True),
    ("Disco de freio dianteiro", "brakes", 349.90, 0.58, 30, True),
    ("Disco de freio traseiro", "brakes", 289.90, 0.58, 18, False),
    ("Fluido de freio", "brakes", 34.90, 0.50, 70, False),
    ("Cilindro mestre de freio", "brakes", 429.90, 0.60, 4, True),
    ("Cabo de freio de estacionamento", "brakes", 79.90, 0.52, 12, False),
    ("Sapata de freio traseira", "brakes", 139.90, 0.54, 10, False),
    ("Filtro de óleo", "filters", 39.90, 0.48, 190, False),
    ("Filtro de ar do motor", "filters", 59.90, 0.50, 110, False),
    ("Filtro de cabine", "filters", 49.90, 0.48, 95, False),
    ("Filtro de combustível", "filters", 79.90, 0.50, 55, False),
    ("Elemento filtrante de ar", "filters", 64.90, 0.50, 30, False),
    ("Amortecedor dianteiro", "suspension", 459.90, 0.60, 24, True),
    ("Amortecedor traseiro", "suspension", 389.90, 0.60, 22, False),
    ("Pivô de suspensão", "suspension", 119.90, 0.52, 28, False),
    ("Bieleta da barra estabilizadora", "suspension", 69.90, 0.50, 34, False),
    ("Bucha da bandeja", "suspension", 54.90, 0.48, 40, False),
    ("Mola helicoidal dianteira", "suspension", 329.90, 0.58, 6, True),
    ("Terminal de direção", "suspension", 89.90, 0.50, 26, False),
    ("Bateria 60Ah", "electrical", 589.90, 0.62, 48, True),
    ("Alternador", "electrical", 899.90, 0.64, 5, True),
    ("Motor de partida", "electrical", 749.90, 0.64, 5, True),
    ("Vela de ignição", "electrical", 42.90, 0.48, 120, False),
    ("Bobina de ignição", "electrical", 289.90, 0.58, 14, True),
    ("Sensor de oxigênio", "electrical", 249.90, 0.58, 10, False),
    ("Fusível (kit)", "electrical", 19.90, 0.40, 45, False),
    ("Correia dentada", "engine", 219.90, 0.55, 18, True),
    ("Correia do alternador", "engine", 89.90, 0.50, 32, False),
    ("Tensor da correia", "engine", 159.90, 0.52, 14, False),
    ("Kit de embreagem", "engine", 849.90, 0.62, 9, True),
    ("Junta do cabeçote", "engine", 199.90, 0.55, 5, True),
    ("Óleo de motor 5W30 (litro)", "engine", 54.90, 0.50, 380, False),
    ("Coxim do motor", "engine", 189.90, 0.55, 10, False),
    ("Bomba de combustível", "engine", 379.90, 0.58, 7, True),
    ("Bomba d'água", "cooling", 329.90, 0.58, 12, True),
    ("Radiador", "cooling", 689.90, 0.62, 6, True),
    ("Válvula termostática", "cooling", 99.90, 0.50, 16, False),
    ("Mangueira do radiador", "cooling", 69.90, 0.48, 28, False),
    ("Aditivo de radiador (litro)", "cooling", 29.90, 0.45, 85, False),
    ("Ventoinha do radiador", "cooling", 459.90, 0.58, 5, False),
    ("Tampa do reservatório", "cooling", 34.90, 0.45, 12, False),
    ("Reservatório de expansão", "cooling", 119.90, 0.52, 7, False),
    ("Lâmpada de farol", "lighting", 24.90, 0.42, 130, False),
    ("Lâmpada de lanterna", "lighting", 12.90, 0.40, 110, False),
    ("Farol dianteiro (unidade)", "lighting", 549.90, 0.60, 6, True),
    ("Lanterna traseira (unidade)", "lighting", 319.90, 0.58, 8, False),
    ("Farol de neblina", "lighting", 169.90, 0.52, 9, False),
    ("Palheta do limpador", "lighting", 44.90, 0.46, 140, False),
    ("Reator de xenônio", "lighting", 389.90, 0.58, 3, False),
    ("Interruptor de luz de freio", "lighting", 39.90, 0.46, 20, False),
    ("Compressor do ar-condicionado", "air_conditioning", 1199.90, 0.64, 4, True),
    ("Condensador", "air_conditioning", 649.90, 0.60, 5, False),
    ("Gás refrigerante (kit)", "air_conditioning", 89.90, 0.48, 60, False),
    ("Filtro secador", "air_conditioning", 79.90, 0.50, 24, False),
    ("Válvula de expansão", "air_conditioning", 189.90, 0.54, 8, False),
    ("Correia do compressor", "air_conditioning", 74.90, 0.48, 14, False),
    ("Evaporador", "air_conditioning", 599.90, 0.60, 3, False),
    ("Motor do ventilador interno", "air_conditioning", 259.90, 0.56, 9, False),
    ("Resistor do ventilador", "air_conditioning", 59.90, 0.48, 18, False),
)
