"""Worker de Cloudflare (cloudflare/worker.js): pre-mercado con respuestas simuladas de Yahoo y Nasdaq."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js no disponible")


def test_worker_premarket_endpoints(tmp_path):
    mod = tmp_path / "worker.mjs"       # Node necesita la extensión .mjs para cargarlo como módulo
    mod.write_text((ROOT / "cloudflare" / "worker.js").read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tests" / "worker_harness.mjs"), str(mod)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "worker ok" in r.stdout, r.stdout + r.stderr
