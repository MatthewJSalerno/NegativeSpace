"""Browser-fixture engine: real jobs, synthetic network filesystem detection."""
import sys

sys.path.insert(0, '/app')
from engine import cli, transfer  # noqa: E402

transfer.filesystem_type = lambda path: 'nfs'
if __name__ == '__main__':
    cli.main()
