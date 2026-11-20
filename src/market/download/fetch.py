"""HTTP probing and safe landing of PDFs (stdlib only, no third-party dependency)."""
from __future__ import annotations

import hashlib
import os
import shutil
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

from planning import basename, url_month

USER_AGENT = "aurora-demo-market-ingest/1.0"  # generic on purpose: no personal data
TIMEOUT_S = 30
MAX_ATTEMPTS = 3
MAX_WORKERS = 4
SLEEP_S = 0.2
PDF_MAGIC = b"%PDF"
CHUNK = 1024 * 1024


@dataclass
class Probe:
    """Result of probing one candidate URL (before dedupe / landing)."""
    url: str
    origin: str
    status: str                      # downloaded|not_found|failed (pre-dedupe)
    http_status: Optional[int] = None
    tmp_path: Optional[str] = None
    sha256: Optional[str] = None
    bytes: Optional[int] = None
    last_modified: Optional[datetime] = None
    error: Optional[str] = None


def _request(url: str, method: str):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=TIMEOUT_S)


def _with_retries(fn: Callable, sleep: Callable[[float], None] = time.sleep):
    """Run fn up to MAX_ATTEMPTS times with exponential backoff on network/5xx errors.

    A 404 (and other 4xx) is a definitive answer and is re-raised immediately.
    """
    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
        if attempt < MAX_ATTEMPTS - 1:
            sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def _parse_last_modified(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def probe_url(url: str, origin: str, tmp_dir: str, opener: Callable = _request,
              sleep: Callable[[float], None] = time.sleep) -> Probe:
    """HEAD the URL; GET only when it is a 200 application/pdf; verify %PDF magic and hash it."""
    try:
        sleep(SLEEP_S)
        with _with_retries(lambda: opener(url, "HEAD"), sleep) as head:
            ctype = (head.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            last_mod = _parse_last_modified(head.headers.get("Last-Modified"))
            code = head.status
        if ctype != "application/pdf":
            return Probe(url, origin, "not_found", code, last_modified=last_mod,
                         error=f"unexpected content-type {ctype!r}")
        sleep(SLEEP_S)
        tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}.part")
        with _with_retries(lambda: opener(url, "GET"), sleep) as resp:
            h, size, first = hashlib.sha256(), 0, b""
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    if not first:
                        first = chunk[:4]
                    h.update(chunk)
                    f.write(chunk)
                    size += len(chunk)
            code = resp.status
        if first != PDF_MAGIC:
            os.remove(tmp_path)
            return Probe(url, origin, "failed", code, error="missing %PDF magic bytes")
        return Probe(url, origin, "downloaded", code, tmp_path, h.hexdigest(), size, last_mod)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return Probe(url, origin, "not_found", 404)
        return Probe(url, origin, "failed", e.code, error=f"HTTP {e.code}")
    except Exception as e:  # network errors after retries
        return Probe(url, origin, "failed", None, error=f"{type(e).__name__}: {e}")


def probe_all(todo: list[tuple[str, str]], tmp_dir: str, **kw) -> list[Probe]:
    os.makedirs(tmp_dir, exist_ok=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(lambda uo: probe_url(uo[0], uo[1], tmp_dir, **kw), todo))


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def finalize(probes: list[Probe], known_hashes: dict[str, str], landing_dir: str,
             now: Optional[datetime] = None) -> list[dict]:
    """Sequentially (deterministic order) dedupe by sha256 and move new PDFs into the landing dir.

    known_hashes: sha256 -> source_url of files already landed (mutated). Existing files are never
    overwritten. Returns manifest rows (dicts) for every probe.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for p in sorted(probes, key=lambda x: (url_month(x.url), x.url)):
        row = {"source_url": p.url, "url_month": url_month(p.url), "file_path": None, "bytes": p.bytes,
               "sha256": p.sha256, "status": p.status, "duplicate_of": None, "http_status": p.http_status,
               "origin": p.origin, "source_last_modified": p.last_modified, "attempted_at": now,
               "downloaded_at": None}
        if p.status == "downloaded":
            if p.sha256 in known_hashes:
                row["status"], row["duplicate_of"] = "duplicate", known_hashes[p.sha256]
                os.remove(p.tmp_path)
            else:
                dest_dir = os.path.join(landing_dir, str(url_month(p.url).year))
                dest = os.path.join(dest_dir, basename(p.url))
                os.makedirs(dest_dir, exist_ok=True)
                if os.path.exists(dest):  # never overwrite
                    existing_sha = _file_sha256(dest)
                    os.remove(p.tmp_path)
                    if existing_sha != p.sha256:  # keep the old file; retried (and reported) every run
                        row["status"] = "failed"
                        row["conflict"] = f"{dest} exists with sha256={existing_sha}, remote sha256={p.sha256}"
                        rows.append(row)
                        continue  # else: adopt the identical file already there
                else:
                    shutil.move(p.tmp_path, dest)
                row["file_path"], row["downloaded_at"] = dest, now
                known_hashes[p.sha256] = p.url
        rows.append(row)
    return rows
