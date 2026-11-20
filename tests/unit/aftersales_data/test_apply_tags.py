import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/aftersales/governance"))
import apply_tags as at  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = (ROOT / "docs/data-model/aftersales.md").read_text()


class Fake:
    def __init__(self, tables, columns=None, models=(), fail=(), no_tag_effect=False):
        self.tagged, self.no_tag_effect = {}, no_tag_effect
        self.tables, self.models, self.fail = tables, models, fail
        self.columns = columns or {}
        self.executed = []

    def execute(self, sql):
        if any(f in sql for f in self.fail):
            raise RuntimeError("boom")
        self.executed.append(sql)
        m = re.match(r"ALTER (?:TABLE|MATERIALIZED VIEW|STREAMING TABLE) `\w+`\.`\w+`\.`(\w+)` SET TAGS", sql)
        if m and not self.no_tag_effect:
            self.tagged[m.group(1)] = {"synthetic", "aid_domain", "layer"}

    def query(self, sql):
        if "information_schema.tables" in sql:
            return [{"table_name": n, "table_type": t} for n, t in self.tables.items()]
        if "information_schema.columns" in sql:
            t = re.search(r"table_name = '(\w+)'", sql).group(1)
            return [{"column_name": c} for c in self.columns.get(t, [])]
        if "information_schema.table_tags" in sql:
            return [{"table_name": t, "tag_name": k} for t, ks in self.tagged.items() for k in ks]
        raise AssertionError(sql)


def contract_tables():
    return set(re.findall(r"\*\*`(aftersales_\w+)`\*\*", CONTRACT))


def test_set_tags_statement():
    sql = at.set_tags_sql("TABLE", "`c`.`s`.`t`", at.tags_for("aftersales_demand_weekly"))
    assert sql == ("ALTER TABLE `c`.`s`.`t` SET TAGS ('synthetic' = 'true', 'aid_domain' = 'aftersales', "
                   "'layer' = 'gold')")


def test_layer_map_covers_contract_tables():
    ct = contract_tables()
    assert ct, "no tables parsed from contract"
    assert ct <= set(at.TABLE_LAYER)
    assert len(at.TABLE_LAYER) == 16


def test_ml_column_comments_match_contract():
    for table, cols in at.COLUMN_COMMENTS.items():
        block = CONTRACT.split(f"**`{table}`**")[1].split("\n\n")[0]
        line = block.split("\n")[1].strip("`")
        decl = re.findall(r"(?:^|, )(\w+) [A-Z]", line)
        assert set(cols) == set(decl), table


def test_lit_escapes_quotes():
    assert at.lit("it's") == "'it\\'s'"


def test_skips_missing_and_reports_unknown():
    f = Fake({"aftersales_dealers": "MATERIALIZED_VIEW", "aftersales_mystery": "MANAGED"})
    logs = []
    assert at.govern(f.execute, f.query, "c", "s", logs.append) == []
    assert any("aftersales_demand_weekly not found" in m for m in logs)
    assert any("unknown aftersales table aftersales_mystery" in m for m in logs)
    assert len([s for s in f.executed if "SET TAGS" in s]) == 1
    assert "'layer' = 'silver'" in f.executed[0]


def test_ml_comments_only_existing_columns():
    f = Fake({"aftersales_model_metrics": "MANAGED"},
             columns={"aftersales_model_metrics": ["model_version", "wape", "extra"]})
    assert at.govern(f.execute, f.query, "c", "s", lambda m: None) == []
    cols = [s for s in f.executed if "ALTER COLUMN" in s]
    assert len(cols) == 2 and not any("extra" in s for s in cols)
    assert any(s.startswith("COMMENT ON TABLE") for s in f.executed)


def test_fallback_form_and_real_failure():
    f = Fake({"aftersales_dealers": "MATERIALIZED_VIEW"}, fail=("ALTER TABLE",))
    logs = []
    assert at.govern(f.execute, f.query, "c", "s", logs.append) == []
    assert f.executed[0].startswith("ALTER MATERIALIZED VIEW")  # tried first, per table type
    assert any("via ALTER MATERIALIZED VIEW" in m for m in logs)
    f = Fake({"aftersales_dealers": "MANAGED"}, fail=("SET TAGS",))
    assert len(at.govern(f.execute, f.query, "c", "s", lambda m: None)) == 1


def test_govern_never_touches_models():
    f = Fake({"aftersales_dealers": "MANAGED"})
    logs = []
    assert at.govern(f.execute, f.query, "c", "s", logs.append) == []
    assert not any("REGISTERED MODEL" in x or "SHOW MODELS" in x for x in f.executed)
    assert not any("MODEL TAGGING" in m for m in logs)


def test_idempotent_same_statements():
    t = {"aftersales_stockout_risk": "MANAGED"}
    a, b = Fake(t, {"aftersales_stockout_risk": ["action"]}), Fake(t, {"aftersales_stockout_risk": ["action"]})
    at.govern(a.execute, a.query, "c", "s", lambda m: None)
    at.govern(b.execute, b.query, "c", "s", lambda m: None)
    assert a.executed == b.executed


def test_streaming_table_form_first():
    f = Fake({"aftersales_raw_dealers": "STREAMING_TABLE"})
    at.govern(f.execute, f.query, "c", "s", lambda m: None)
    assert f.executed[0].startswith("ALTER STREAMING TABLE")


def test_verification_fails_when_tags_missing():
    f = Fake({"aftersales_dealers": "MANAGED"}, no_tag_effect=True)
    failures = at.govern(f.execute, f.query, "c", "s", lambda m: None)
    assert any(x.startswith("verify aftersales_dealers") for x in failures)
    ok = Fake({"aftersales_dealers": "MANAGED"})
    assert at.govern(ok.execute, ok.query, "c", "s", lambda m: None) == []


def test_missing_tables_only_warn():
    f = Fake({})
    assert at.govern(f.execute, f.query, "c", "s", lambda m: None) == []


def _run_as_main(monkeypatch, fake):
    import types

    class Row:
        def __init__(self, d):
            self.d = d

        def asDict(self):
            return self.d

    class DF:
        def __init__(self, rows):
            self.rows = rows

        def collect(self):
            return [Row(r) for r in self.rows]

    class Spark:
        def sql(self, s):
            return DF(fake.query(s)) if s.lstrip().upper().startswith("SELECT") else (fake.execute(s), DF([]))[1]

    builder = types.SimpleNamespace(getOrCreate=lambda: Spark())
    sql_mod = types.ModuleType("pyspark.sql")
    sql_mod.SparkSession = types.SimpleNamespace(builder=builder)
    monkeypatch.setitem(sys.modules, "pyspark", types.ModuleType("pyspark"))
    monkeypatch.setitem(sys.modules, "pyspark.sql", sql_mod)
    monkeypatch.setattr(sys, "argv", ["apply_tags.py", "--catalog", "c", "--schema", "s"])
    src = (ROOT / "src/aftersales/governance/apply_tags.py").read_text()
    exec(compile(src, "apply_tags", "exec"), {"__name__": "__main__"})


def test_main_block_success_path_does_not_exit_or_raise(monkeypatch):
    _run_as_main(monkeypatch, Fake({"aftersales_dealers": "MANAGED"}))  # a SystemExit would fail this test


def test_main_block_raises_runtime_error_on_failure(monkeypatch):
    import pytest
    with pytest.raises(RuntimeError):
        _run_as_main(monkeypatch, Fake({"aftersales_dealers": "MANAGED"}, no_tag_effect=True))
