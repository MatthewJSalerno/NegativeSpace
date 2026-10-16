"""Generated-only harness: fail the first XMP publication for each original mode."""
import sys
import os
from pathlib import Path
sys.path.insert(0, '/app')
from engine import cli, durable

original = durable.copy_verify_delete
mode = 'move' if '--move' in sys.argv else 'copy'
# Optional generated-demo cycle keeps previous markers and operation history intact.
cycle = os.environ.get('NS_PAIR_FAILURE_VERSION', '')
marker = Path('/appdata') / ('pair-failure-' + mode + ('-' + cycle if cycle else ''))

def publish(source, destination, **kwargs):
    if source.endswith('.xmp') and not marker.exists():
        marker.write_text('generated failure already injected')
        return False, 'Generated XMP publication failure; retry can now finish.'
    return original(source, destination, **kwargs)

durable.copy_verify_delete = publish
if __name__ == '__main__':
    cli.main()
