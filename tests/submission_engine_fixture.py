"""Real engine with Copy acceptance delayed before file work, for browser tests."""
import sys
import time

sys.path.insert(0, '/app')
from engine import cli, store  # noqa: E402

original_start = store.start_run

def start(*args, **kwargs):
    result = original_start(*args, **kwargs)
    if args[1] == 'COPY':
        time.sleep(3)
    return result

store.start_run = start
if __name__ == '__main__':
    cli.main()
