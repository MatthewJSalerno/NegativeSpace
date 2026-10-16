"""Generated browser fixture: pause a Copy after its settings snapshot commits."""
import sys
import time
from pathlib import Path
sys.path.insert(0, '/app')
from engine import cli, store

original_start = store.start_run

def start(*args, **kwargs):
    result = original_start(*args, **kwargs)
    gate = Path('/data/source/.hold-settings-job')
    if args[1] == 'COPY':
        deadline = time.monotonic() + 120
        while gate.exists() and time.monotonic() < deadline:
            time.sleep(.05)
    return result

store.start_run = start
if __name__ == '__main__':
    cli.main()
