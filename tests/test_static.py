"""The online showcase finds a sequence by a key that Python (export) and JavaScript (page) must
build identically."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("export_static", ROOT / "scripts" / "export_static.py")
export_static = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_static)

REQUESTS = [  # as precache.jobs(tour_zooms=True) asks, and as explore.js posts them
    {"ra": 95.60007, "dec": 25.04644, "zoom": "hours", "wave": 1.31, "n": 48, "t_min": 60948.3,
     "t_max": 60948.45, "tol": None},
    {"ra": 304.1695, "dec": -23.61185, "zoom": "days", "wave": 1.15, "n": 64, "t_min": 60942.0,
     "t_max": 60962.0, "tol": 0.12},
    {"ra": 180.0, "dec": 0.0, "zoom": "months", "wave": None},
]


def test_python_key_format():
    assert export_static.request_key(180, 0, "days") == "180.00000,0.00000,days,,48,,,"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_javascript_builds_the_same_keys(tmp_path):
    shutil.copy(ROOT / "web" / "js" / "static.js", tmp_path / "static.mjs")
    # JSON turns 180.0 into 180 and 60942.0 into 60942, just as the browser holds them.
    script = (f"import {{ requestKey }} from './static.mjs';"
              f"console.log(JSON.stringify({json.dumps(REQUESTS)}.map(requestKey)));")
    (tmp_path / "check.mjs").write_text(script)
    out = subprocess.run(["node", "check.mjs"], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [export_static.request_key(**r) for r in REQUESTS]
