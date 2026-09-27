"""Real engine with Copy acceptance delayed before file work, for browser tests."""
import importlib
import sys
import time

sys.path.insert(0, '/app')
engine = importlib.import_module('ns-engine')
original_start = engine.start_run

def start(*args, **kwargs):
    result = original_start(*args, **kwargs)
    if args[1] == 'COPY':
        time.sleep(3)
    return result

engine.start_run = start
if __name__ == '__main__':
    engine.main()
