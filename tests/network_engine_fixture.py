"""Browser-fixture engine: real jobs, synthetic network filesystem detection."""
import importlib
import sys

sys.path.insert(0, '/app')
engine = importlib.import_module('ns-engine')
engine.filesystem_type = lambda path: 'nfs'
if __name__ == '__main__':
    engine.main()
