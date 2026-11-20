#!/usr/bin/env python3
"""Ask the benchmark questions to the market Genie Agent and print a text transcript (question, status,
generated SQL, Genie's text answer, first result rows). Read-only. Usage: ask_benchmarks.py SPACE_ID [PROFILE]"""
import json, subprocess, sys, time, importlib.util, pathlib

SPACE, PROFILE = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "classic-stable-new")
here = pathlib.Path(__file__).parent
spec = importlib.util.spec_from_file_location("b", here / "build_space.py")
sys.argv = [sys.argv[0]]
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)

def cli(*a):
    r = subprocess.run(["databricks", *a, "--profile", PROFILE, "-o", "json"], capture_output=True, text=True)
    if r.returncode: raise RuntimeError(r.stderr.strip()[:400])
    return json.loads(r.stdout)

for q in b.BENCH_QUESTIONS:
    start = cli("genie", "start-conversation", "--no-wait", SPACE, q)
    conv, msg = start["conversation_id"], start["message_id"]
    t0 = time.time()
    while True:
        m = cli("genie", "get-message", SPACE, conv, msg)
        if m.get("status") in ("COMPLETED", "FAILED", "CANCELLED") or time.time() - t0 > 300: break
        time.sleep(4)
    print("=" * 100); print("PERGUNTA:", q); print("STATUS:", m.get("status"), f"({time.time()-t0:.0f}s)")
    if m.get("error"): print("ERRO:", m["error"])
    for a in m.get("attachments", []) or []:
        if a.get("text"): print("RESPOSTA:", a["text"].get("content", "").strip())
        if a.get("query"):
            print("SQL GERADO:\n" + a["query"].get("query", "").strip())
            if a["query"].get("description"): print("DESCRIÇÃO:", a["query"]["description"])
            try:
                r = cli("genie", "get-message-attachment-query-result", SPACE, conv, msg, a["attachment_id"])
                sr = r.get("statement_response", {})
                cols = [c["name"] for c in sr.get("manifest", {}).get("schema", {}).get("columns", [])]
                rows = sr.get("result", {}).get("data_array", []) or []
                print(f"RESULTADO ({len(rows)} linhas): " + " | ".join(cols))
                for row in rows[:12]: print("  " + " | ".join(str(v) for v in row))
            except Exception as e:
                print("RESULTADO: indisponível:", e)
