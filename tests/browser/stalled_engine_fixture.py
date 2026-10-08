"""A real scan with one deliberately stuck generated-file decoder and child."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/app')
from engine import cli, scan

original = scan.process_file_task
original_discovery = scan.discover_source_files

def ordered_discovery(*args, **kwargs):
    return sorted(original_discovery(*args, **kwargs))

scan.discover_source_files = ordered_discovery


def blocked_task(*args, **kwargs):
    # Browser harness's first file, or the API fixture's explicitly named file.
    if Path(args[0]).name in ('photo-000.jpg', 'z-blocked.jpg'):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])
        base = Path(sys.argv[sys.argv.index('--base') + 1])
        (base / 'stalled-worker.json').write_text(json.dumps({'worker': os.getpid(), 'decoder': child.pid}))
        time.sleep(600)
    return original(*args, **kwargs)


scan.process_file_task = blocked_task
if __name__ == '__main__':
    cli.main()
