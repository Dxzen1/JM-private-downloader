import subprocess
import sys

import pytest


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux resource limit")
def test_task_memory_limit_rejects_oversized_allocation():
    # A disposable interpreter exercises the real OS limit without fetching data.
    script = """
from types import SimpleNamespace
from app import worker
worker.process_task = lambda *args: bytearray(1024 * 1024 * 1024)
try:
    worker._task_child('unused.sqlite3', SimpleNamespace(task_memory_mb=128), {})
except MemoryError:
    print('allocation-bounded')
else:
    raise SystemExit('memory limit was not enforced')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert "allocation-bounded" in result.stdout
