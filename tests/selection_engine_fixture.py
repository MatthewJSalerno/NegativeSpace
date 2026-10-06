"""Pause a real engine before selection parsing, for process-ownership tests."""
import json
import os
from pathlib import Path
import sys
import time


if __name__ == '__main__':
    base = Path(sys.argv[sys.argv.index('--base') + 1])
    (base / 'selection-fixture-ready.json').write_text(json.dumps({'pid': os.getpid()}))
    deadline = time.monotonic() + 30
    while not (base / 'selection-fixture-release').exists():
        if time.monotonic() > deadline:
            raise SystemExit('Selection fixture was not released')
        time.sleep(.02)
    os.chdir(Path(__file__).resolve().parents[1])
    os.execv(sys.executable, [sys.executable, '-m', 'engine', *sys.argv[1:]])
