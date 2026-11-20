import re
from pathlib import Path

import pandas as pd

from aftersales.ml.tables import PK, TABLES, column_names, to_records

DOC = Path(__file__).resolve().parents[3] / "docs" / "data-model" / "aftersales.md"


def doc_columns(table):
    text = DOC.read_text()
    m = re.search(rf"\*\*`{table}`\*\*[^\n]*\n`([^`]+)`", text)
    assert m, table
    cols = []
    for part in re.split(r",\s*(?![^()]*\))", m.group(1)):
        cols.append(part.strip().split(" ")[0])
    return cols


def test_columns_match_frozen_contract():
    for t in TABLES:
        assert column_names(t) == doc_columns(t), t


def test_pk_columns_exist():
    for t, pk in PK.items():
        assert set(pk) <= set(column_names(t))


def test_to_records_types():
    cols = column_names("aftersales_model_metrics")
    row = dict(model_name="m", model_version="3", run_id="r", cutoff_date=pd.Timestamp("2026-08-16"),
               forecast_date=pd.Timestamp("2026-11-16"), holdout_weeks=13, n_series=720, wape=0.2,
               baseline_wape=float("nan"), bias=0.0, baseline_bias=0.0, is_champion=True,
               logged_at=pd.Timestamp("2026-11-20 10:00"))
    rec = to_records(pd.DataFrame([row]), "aftersales_model_metrics")[0]
    assert rec[3].isoformat() == "2026-08-16" and rec[8] is None and rec[9] == 0.0 and rec[11] is True
    assert len(rec) == len(cols)
