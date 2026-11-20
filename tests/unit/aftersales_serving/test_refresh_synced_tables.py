import importlib.util
import pathlib

_path = pathlib.Path(__file__).parents[3] / "src/aftersales/serving/refresh_synced_tables.py"
_spec = importlib.util.spec_from_file_location("refresh_synced_tables", _path)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class FakeClient:
    def __init__(self, existing, states):
        self.existing, self.states, self.calls = existing, states, []

    def do(self, method, path, body=None):
        self.calls.append((method, path))
        if path.startswith("/api/2.0/postgres/synced_tables/"):
            name = path.rsplit("/", 1)[1]
            if name not in self.existing:
                raise RuntimeError("TABLE_DOES_NOT_EXIST")
            return {"status": {"detailed": {"pipeline_id": "pl-" + name[-4:]}}}
        if method == "POST":
            return {"update_id": "u1"}
        return {"update": {"state": self.states.pop(0)}}


def test_find_pipeline_id_nested_and_missing():
    assert mod.find_pipeline_id({"a": [{"b": {"pipeline_id": "p1"}}]}) == "p1"
    assert mod.find_pipeline_id({"a": {"pipeline_id": ""}}) is None


def test_refresh_skips_missing_and_waits_for_terminal_state():
    name = mod.synced_table_name("c", "s", "dealers")
    client = FakeClient({name}, ["RUNNING", "COMPLETED"])
    mod.wait_for_update.__defaults__  # keep signature stable
    orig = mod.time.sleep
    mod.time.sleep = lambda _s: None
    try:
        out = mod.refresh(client, "c", "s", 60)
    finally:
        mod.time.sleep = orig
    assert out[name] == "COMPLETED"
    assert out[mod.synced_table_name("c", "s", "parts")].startswith("skipped")


def test_wait_times_out():
    ticks = iter([0, 5, 100])
    try:
        mod.wait_for_update(lambda: {"update": {"state": "RUNNING"}}, 10, sleep=lambda _s: None, now=lambda: next(ticks))
    except TimeoutError:
        return
    raise AssertionError("expected TimeoutError")


def _run_as_script(monkeypatch, rc):
    """Execute the module's `__main__` block the way spark_python_task does (exec in a fresh namespace)."""
    source = _path.read_text()
    namespace = {"__name__": "__main__", "__file__": str(_path)}
    # Replace main() with a stub returning `rc`, keeping the real `__main__` guard code under test.
    head, guard = source.split('if __name__ == "__main__":')
    code = head + "\ndef main(argv=None):\n    return %d\n\nif __name__ == \"__main__\":" % rc + guard
    exec(compile(code, str(_path), "exec"), namespace)  # noqa: S102 - test-only


def test_script_success_does_not_raise_systemexit(monkeypatch):
    # exec() must return normally: a SystemExit (even code 0) would mark the serverless task FAILED.
    _run_as_script(monkeypatch, 0)


def test_script_failure_raises_runtimeerror(monkeypatch):
    import pytest

    with pytest.raises(RuntimeError, match=r"sync failed \(rc=1\)"):
        _run_as_script(monkeypatch, 1)
