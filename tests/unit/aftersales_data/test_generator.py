import hashlib
import sys
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/aftersales/synthetic"))
from aftersales_config import DEALERS, DEFAULT_CONFIG, PARTS, CATEGORIES  # noqa: E402
from aftersales_generator import (  # noqa: E402
    dealers_rows, fleet_by_dealer_month, lead_times_rows, parts_rows, simulate,
)
from aftersales_writer import write_all  # noqa: E402

SMALL = replace(DEFAULT_CONFIG, history_start=date(2025, 12, 1), history_end=date(2026, 1, 31))


def _regs():
    out = {}
    for y in range(2019, 2027):
        for m in range(1, 13):
            if (y, m) > (2026, 9):
                continue
            for model, u in (("IPE", 450), ("JATOBA", 350), ("AROEIRA", 200)):
                out[(date(y, m, 1), model)] = float(u + m)
    return out


REGS = _regs()
FLEET = fleet_by_dealer_month(REGS)


def test_dealers_and_parts_contract():
    d = dealers_rows()
    assert len(d) == 12 and [r[0] for r in d] == [f"D{i:03d}" for i in range(1, 13)]
    assert abs(sum(r[6] for r in d) - 1.0) < 1e-9
    regions = [r[4] for r in d]
    assert set(regions) == {"Sudeste", "Sul", "Nordeste", "Centro-Oeste"}
    assert all(regions.count(r) >= 2 for r in set(regions))
    p = parts_rows()
    assert len(p) == 60 and len({r[1] for r in p}) == 60 and {r[2] for r in p} == set(CATEGORIES)
    assert all(0 < r[5] < r[4] for r in p)
    assert any(r[6] == "true" for r in p)


def _banned_words():
    """Read the git-ignored local denylist (tests/.brand-denylist.local); the public repo lists no brands."""
    import pathlib, re
    f = pathlib.Path(__file__).resolve().parents[2] / ".brand-denylist.local"
    if not f.exists():
        return []
    m = re.search(r"^BANNED_NAME_WORDS='([^']*)'", f.read_text(), re.M)
    return m.group(1).split() if m else []


def test_no_real_brand_markers_in_names():
    import pytest
    banned = _banned_words()
    if not banned:
        pytest.skip("local brand denylist not found")
    text = " ".join([r[1] for r in dealers_rows()] + [r[1] for r in parts_rows()]).lower()
    for word in banned:
        assert word not in text


def test_lead_times():
    lt = lead_times_rows()
    assert len(lt) == 720 and all(3 <= r[2] <= 30 for r in lt)
    crit = {r[0] for r in parts_rows() if r[6] == "true"}
    avg = lambda rows: sum(r[2] for r in rows) / len(rows)  # noqa: E731
    assert avg([r for r in lt if r[1] in crit]) > avg([r for r in lt if r[1] not in crit])


def test_fleet_oracle_matches_source():
    # sum over dealers of the monthly registrations == source registrations (fleet_share sums to 1)
    for model, total in (("IPE", sum(v for (m, mo), v in REGS.items() if mo == "IPE")),):
        assert total > 0
    last = date(2026, 9, 1)
    fleet_total_last = sum(FLEET[(di, last)] for di in range(12))
    assert abs(fleet_total_last - sum(REGS.values())) < 1e-6


def test_simulation_invariants_and_determinism():
    a = [(d, s, n) for d, s, n in simulate(FLEET, SMALL)]
    b = [(d, s, n) for d, s, n in simulate(FLEET, SMALL)]
    assert a == b
    assert len(a) == 62
    for d, sales, snaps in a:
        assert len(sales) == 720
        assert all(r[5] == r[3] - r[4] >= 0 and r[4] >= 0 for r in sales)
        if d.weekday() == 6:
            assert len(snaps) == 720 and all(s[3] >= 0 and s[4] >= 0 for s in snaps)
            assert all(r[3] == 0 for r in sales)  # Sunday closed
        else:
            assert snaps == []


def test_csv_files_byte_identical():
    def digest(root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}

    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        c1 = write_all(t1, FLEET, SMALL)
        write_all(t2, FLEET, SMALL)
        assert digest(t1) == digest(t2)
        assert c1["daily_sales"] == 62 * 720 and c1["dealers"] == 12 and c1["parts"] == 60
        assert (Path(t1) / "daily_sales" / "daily_sales_2025-12.csv").exists()
        assert (Path(t1) / "_manifest" / "manifest.json").exists()


def test_calendar_and_frozen_fleet():
    assert DEFAULT_CONFIG.history_start == date(2019, 1, 1) and DEFAULT_CONFIG.history_end == date(2026, 11, 15)
    assert DEFAULT_CONFIG.history_end.weekday() == 6
    from aftersales_generator import _fleet_lookup
    # after 2026-09 the active fleet is the frozen 2026-09 value
    assert _fleet_lookup(FLEET, 0, date(2026, 11, 10), DEFAULT_CONFIG) == FLEET[(0, date(2026, 9, 1))]


def test_dealer_names_and_opening():
    for r in dealers_rows():
        assert r[1] == f"Aurora Motors {r[2]}"
        assert date.fromisoformat(r[5]) <= DEFAULT_CONFIG.history_start


def test_missing_registration_month_raises():
    import pytest
    bad = {k: v for k, v in REGS.items() if k[0] != date(2022, 5, 1)}
    with pytest.raises(ValueError):
        fleet_by_dealer_month(bad)


def test_writeoff_event_only_on_its_date_and_never_negative():
    cfg = replace(SMALL, history_start=date(2026, 1, 1), history_end=date(2026, 1, 31), writeoff_date=date(2026, 1, 31),
                  writeoff_probability=1.0)
    rows = list(simulate(FLEET, cfg))
    last = rows[-1][2]
    assert rows[-1][0] == date(2026, 1, 31) and all(r[3] >= 0 for r in last)


def test_main_imports_resolve_without___file__(monkeypatch):
    synth = Path(__file__).resolve().parents[3] / "src/aftersales/synthetic"
    src = (synth / "main.py").read_text()
    monkeypatch.chdir(synth)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p or ".").resolve() != synth])
    for mod in ("aftersales_config", "aftersales_generator", "aftersales_writer"):
        sys.modules.pop(mod, None)
    ns = {"__name__": "not_main"}  # no __file__, like the serverless task runner
    exec(compile(src, "main", "exec"), ns)
    assert callable(ns["main"]) and "write_all" in ns
