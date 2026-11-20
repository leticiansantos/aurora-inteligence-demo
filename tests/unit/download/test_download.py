import io
import json
import os
import sys
import urllib.error
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src" / "market" / "download"))

import fetch  # noqa: E402
import planning  # noqa: E402

PDF = b"%PDF-1.6\n" + b"x" * 100


class FakeResp:
    def __init__(self, status, headers, body=b""):
        self.status, self.headers, self._b = status, headers, io.BytesIO(body)

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_opener(site, calls=None):
    """site: url -> (content_type, body). Missing -> 404."""
    def opener(url, method):
        if calls is not None:
            calls.append((method, url))
        if url not in site:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        ctype, body = site[url]
        h = {"Content-Type": ctype, "Last-Modified": "Thu, 01 Oct 2026 12:51:54 GMT"}
        return FakeResp(200, h, body if method == "GET" else b"")
    return opener


nosleep = lambda s: None  # noqa: E731
U = planning.BASE_URL


# ---- planning
def test_seed_has_277_unique_urls_and_months_parse():
    seed = planning.load_seed()
    assert len(seed) == len(set(seed)) == 277
    months = {planning.url_month(u) for u in seed}
    assert min(months) == date(2003, 1, 1) and max(months) == date(2026, 1, 1)


@pytest.mark.parametrize("url,expected", [
    (U + "2_2012_06_2.pdf", date(2012, 6, 1)),
    (U + "2023_02_3.pdf", date(2023, 2, 1)),
    (U + "2026_09_02.pdf", date(2026, 9, 1)),
])
def test_url_month(url, expected):
    assert planning.url_month(url) == expected


def test_discovery_probes_all_variants_after_last_seed_month():
    c = planning.discovery_candidates(date(2026, 1, 1), date(2026, 3, 15))
    assert c == [f"{U}2026_{m:02d}_{v}.pdf" for m in (2, 3) for v in ("02", "2", "3")]


def test_select_to_probe_idempotent_and_reprobe_window():
    today = date(2026, 11, 20)
    cands = planning.build_candidates(planning.load_seed(), today)
    first = planning.select_to_probe(cands, {}, today)
    assert len(first) == len(cands)
    # everything terminal -> only not_found within the last 3 url months is re-probed
    existing = {u: "downloaded" for u, o in cands if o == "seed"}
    for u, o in cands:
        if o == "discovery":
            existing[u] = "not_found"
    again = planning.select_to_probe(cands, existing, today)
    months = {planning.url_month(u) for u, _ in again}
    assert months == {date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)}
    assert all(o == "discovery" for _, o in again)
    # failed is never terminal
    existing[cands[0][0]] = "failed"
    assert cands[0] in planning.select_to_probe(cands, existing, today)


# ---- fetch
def test_probe_404_not_found_and_no_file(tmp_path):
    p = fetch.probe_url(U + "2026_10_02.pdf", "discovery", str(tmp_path), make_opener({}), nosleep)
    assert (p.status, p.http_status, p.tmp_path) == ("not_found", 404, None)
    assert os.listdir(tmp_path) == []


def test_probe_html_200_is_not_a_pdf(tmp_path):
    site = {U + "x_2026_01_2.pdf": ("text/html", b"<html>")}
    p = fetch.probe_url(U + "x_2026_01_2.pdf", "seed", str(tmp_path), make_opener(site), nosleep)
    assert p.status == "not_found" and os.listdir(tmp_path) == []


def test_probe_bad_magic_fails_and_cleans(tmp_path):
    site = {U + "2026_01_02.pdf": ("application/pdf", b"<html>not a pdf")}
    p = fetch.probe_url(U + "2026_01_02.pdf", "seed", str(tmp_path), make_opener(site), nosleep)
    assert p.status == "failed" and "magic" in p.error and os.listdir(tmp_path) == []


def test_probe_ok_hash_and_get_only_after_head(tmp_path):
    calls = []
    site = {U + "2026_09_02.pdf": ("application/pdf", PDF)}
    p = fetch.probe_url(U + "2026_09_02.pdf", "discovery", str(tmp_path), make_opener(site, calls), nosleep)
    assert p.status == "downloaded" and p.bytes == len(PDF) and len(p.sha256) == 64
    assert [m for m, _ in calls] == ["HEAD", "GET"]
    assert p.last_modified == datetime(2026, 10, 1, 12, 51, 54)


def test_retry_on_5xx_then_success(tmp_path):
    state = {"n": 0}

    def flaky(url, method):
        state["n"] += 1
        if state["n"] < 3:
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        return FakeResp(200, {"Content-Type": "application/pdf"}, PDF)

    p = fetch.probe_url(U + "2026_09_02.pdf", "seed", str(tmp_path), flaky, nosleep)
    assert p.status == "downloaded"


def test_persistent_failure_is_failed_not_terminal(tmp_path):
    def down(url, method):
        raise urllib.error.URLError("boom")

    p = fetch.probe_url(U + "2026_09_02.pdf", "seed", str(tmp_path), down, nosleep)
    assert p.status == "failed" and "URLError" in p.error


def run_finalize(site, urls, tmp_path, hashes=None):
    tmp, land = tmp_path / "tmp", tmp_path / "land"
    probes = fetch.probe_all([(u, "discovery") for u in urls], str(tmp), opener=make_opener(site), sleep=nosleep)
    rows = fetch.finalize(probes, {} if hashes is None else hashes, str(land), datetime(2026, 11, 20))
    return rows, tmp, land


def test_finalize_dedupes_identical_variants_and_lands_once(tmp_path):
    a, b, c = (U + f"2026_09_{v}.pdf" for v in ("02", "2", "3"))
    site = {a: ("application/pdf", PDF), b: ("application/pdf", PDF)}
    rows, tmp, land = run_finalize(site, [a, b, c], tmp_path)
    by = {r["source_url"]: r for r in rows}
    assert by[a]["status"] == "downloaded" and by[a]["file_path"].endswith("/2026/2026_09_02.pdf")
    assert by[b]["status"] == "duplicate" and by[b]["duplicate_of"] == a and by[b]["file_path"] is None
    assert by[c]["status"] == "not_found"
    assert (land / "2026" / "2026_09_02.pdf").read_bytes() == PDF
    assert not (land / "2026" / "2026_09_2.pdf").exists()
    assert list(tmp.iterdir()) == []  # nothing left in the tmp dir


def test_finalize_duplicate_of_previous_run(tmp_path):
    a = U + "2026_09_02.pdf"
    sha = fetch.hashlib.sha256(PDF).hexdigest()
    rows, _, land = run_finalize({a: ("application/pdf", PDF)}, [a], tmp_path, {sha: U + "2026_08_02.pdf"})
    assert rows[0]["status"] == "duplicate" and rows[0]["duplicate_of"] == U + "2026_08_02.pdf"
    assert not land.exists() or list(land.rglob("*.pdf")) == []


def test_never_overwrites_existing_file(tmp_path):
    a = U + "2026_09_02.pdf"
    dest = tmp_path / "land" / "2026" / "2026_09_02.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"%PDF-OTHER")
    rows, _, _ = run_finalize({a: ("application/pdf", PDF)}, [a], tmp_path)
    assert rows[0]["status"] == "failed"
    assert "sha256=" in rows[0]["conflict"] and "remote sha256=" in rows[0]["conflict"]
    assert dest.read_bytes() == b"%PDF-OTHER"


def test_adopts_identical_existing_file(tmp_path):
    a = U + "2026_09_02.pdf"
    dest = tmp_path / "land" / "2026" / "2026_09_02.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(PDF)
    rows, tmp, _ = run_finalize({a: ("application/pdf", PDF)}, [a], tmp_path)
    assert rows[0]["status"] == "downloaded" and dest.read_bytes() == PDF and list(tmp.iterdir()) == []


def test_manifest_row_contract_columns(tmp_path):
    a = U + "2026_09_02.pdf"
    rows, _, _ = run_finalize({a: ("application/pdf", PDF)}, [a], tmp_path)
    assert set(rows[0]) == {"source_url", "url_month", "file_path", "bytes", "sha256", "status", "duplicate_of",
                            "http_status", "origin", "source_last_modified", "attempted_at", "downloaded_at"}


def test_second_run_is_noop_for_terminal_urls():
    today = date(2026, 11, 20)
    cands = planning.build_candidates(planning.load_seed(), today)
    existing = {u: "downloaded" if o == "seed" else "duplicate" for u, o in cands}
    assert planning.select_to_probe(cands, existing, today) == []
