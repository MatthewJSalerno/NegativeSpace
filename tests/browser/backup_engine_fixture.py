"""Generated fixtures only: hold, fail or interrupt an actual catalog snapshot.

Control lives in this harness's disposable appdata, never in production or photos.
Without a control file the normal engine runs unchanged.
"""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, '/app')
from engine import cli, ns_db

original = ns_db._snapshot
control = Path('/appdata/backup-test.json')

def settings():
    return json.loads(control.read_text()) if control.exists() else {}

def snapshot(*args, **kwargs):
    action = settings()
    deadline = time.monotonic() + 120
    while settings().get('hold') and time.monotonic() < deadline:
        time.sleep(.05)
    if action.get('delay'):
        time.sleep(min(float(action['delay']), 30))
    if action.get('interrupt'):
        os._exit(90)
    run_mode = args[0].execute('SELECT r.mode FROM backup_attempts a LEFT JOIN runs r ON r.id=a.related_run_id WHERE a.attempt_id=?', (args[1],)).fetchone()[0]
    if action.get('failure') and (not action.get('only_mode') or action['only_mode'] == run_mode):
        if action.get('once'):
            remaining = dict(action)
            remaining.pop('failure')
            control.write_text(json.dumps(remaining))
        raise ns_db.BackupFailed(action['failure'], 'Generated backup storage failure')
    return original(*args, **kwargs)

ns_db._snapshot = snapshot
if __name__ == '__main__':
    cli.main()
