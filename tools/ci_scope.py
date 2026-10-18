#!/usr/bin/env python3
"""Select CI from the complete Git diff and validate its required merge gate."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

DOC_FILES = frozenset({'README.md', 'CHANGELOG.md', 'TODO.md', 'AGENTS.md',
                       'CLAUDE.md', 'tests/README.md'})
APP_JOBS = ('engine', 'metadata', 'contracts', 'browsers')


def documentation_path(name):
    """Only known prose and documentation images may skip application tests."""
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        return False
    return (name in DOC_FILES
            or (path.parts[0:1] == ('docs',) and path.suffix == '.md')
            or (path.parts[0:2] == ('docs', 'images')
                and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}))


def select_scope(event_name, event, repo=Path('.')):
    """Missing/uncertain history, manual runs and unknown paths use the full suite."""
    try:
        if event_name == 'pull_request':
            base = event['pull_request']['base']['sha']
            head = event['pull_request']['head']['sha']
            separator = '...'
        elif event_name == 'push':
            base, head = event['before'], event['after']
            separator = '..'
        else:
            return 'full', 'Manual or unrecognized event'
        if any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
               or sha == '0' * 40 for sha in (base, head)):
            return 'full', 'Missing or invalid comparison commits'
        if event_name == 'push':
            subprocess.run(['git', 'merge-base', '--is-ancestor', base, head],
                           cwd=repo, check=True, capture_output=True)
        # Disable rename detection so moving code into docs cannot hide its deletion.
        # NUL separation handles spaces/newlines; local Git has no API path-count limit.
        diff = subprocess.check_output(
            ['git', 'diff', '--name-only', '-z', '--no-renames',
             base + separator + head, '--'], cwd=repo, stderr=subprocess.PIPE)
        paths = [os.fsdecode(name) for name in diff.split(b'\0') if name]
        if paths and all(documentation_path(name) for name in paths):
            return 'docs', 'Only documentation changed'
        return 'full', 'Application, unknown paths, or empty diff'
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return 'full', 'Comparison unavailable; full validation required'


def require_success(results):
    """Only a successful docs classification permits intentionally skipped suites."""
    expected = {'changes', 'docs', *APP_JOBS}
    if not isinstance(results, dict) or set(results) != expected:
        raise ValueError('Missing or unexpected CI job results')
    for job in ('changes', 'docs'):
        if results[job].get('result') != 'success':
            raise ValueError(f'{job} must pass')
    scope = results['changes'].get('outputs', {}).get('scope')
    if scope not in ('docs', 'full'):
        raise ValueError('Missing or invalid CI scope')
    wanted = 'skipped' if scope == 'docs' else 'success'
    for job in APP_JOBS:
        if results[job].get('result') != wanted:
            raise ValueError(f'{job} must be {wanted} for {scope} changes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('select', 'gate'))
    args = parser.parse_args()
    if args.command == 'gate':
        try:
            require_success(json.loads(os.environ['RESULTS']))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise SystemExit(f'CI gate refused: {exc}') from exc
        print('Required checks passed for the selected CI scope')
        return
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    except (KeyError, OSError, ValueError):
        event = {}
    scope, reason = select_scope(os.environ.get('GITHUB_EVENT_NAME', ''), event)
    print(f'CI scope: {scope} ({reason})')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write(f'scope={scope}\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(f'CI scope: **{scope}**. {reason}.\n')


if __name__ == '__main__':
    main()
