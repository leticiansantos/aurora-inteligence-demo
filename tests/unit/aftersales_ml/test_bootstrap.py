"""train.py / score.py must resolve `aftersales.ml` with no __file__ and no cwd help, given only --src."""
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src"


@pytest.mark.parametrize("name", ["train", "score"])
def test_exec_without_file_resolves_imports_via_src_arg(name, tmp_path):
    script = SRC / "aftersales" / "ml" / f"{name}.py"
    code = (
        "import sys\n"
        f"sys.argv = ['{name}.py', '--src', {str(SRC)!r}]\n"
        f"g = {{'__name__': 'serverless_exec'}}\n"          # no __file__
        f"exec(compile(open({str(script)!r}).read(), '{name}.py', 'exec'), g)\n"
        "assert 'aftersales.ml.forecast' in sys.modules\n"
        "assert sys.path[0] == " + repr(str(SRC)) + "\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
