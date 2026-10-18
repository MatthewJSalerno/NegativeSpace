"""Generated Git histories prove docs-only routing cannot hide application changes."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from tools import ci_scope


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write('README.md', '# Fixture\n')
        self.write('engine/example.py', 'value = 1\n')
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo,
                                       stderr=subprocess.PIPE).decode().strip()

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'Generated fixture')
        return self.git('rev-parse', 'HEAD')

    def scope(self, head, event='pull_request', base=None):
        base = base or self.base
        body = ({'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}}
                if event == 'pull_request' else {'before': base, 'after': head})
        return ci_scope.select_scope(event, body, self.repo)[0]

    def test_prose_changes_use_docs_for_pr_and_push(self):
        for name in ('README.md', 'TODO.md', 'tests/README.md', 'docs/nested/spec.md',
                     'docs/images/example.png', 'AGENTS.md', 'CLAUDE.md'):
            self.write(name, 'Updated documentation\n')
        head = self.commit()
        self.assertEqual(self.scope(head), 'docs')
        self.assertEqual(self.scope(head, 'push'), 'docs')

    def test_mixed_and_unknown_paths_require_full(self):
        for name in ('engine/example.py', 'webui/frontend/src/App.tsx', 'tests/fixture.json',
                     'requirements.txt', 'docker/app.Dockerfile', '.github/workflows/test.yml',
                     'tools/check-specs.py', 'docs/script.py', 'VERSION', 'unknown.md'):
            with self.subTest(name=name):
                self.git('reset', '--hard', self.base)
                self.write('README.md', 'Docs changed\n')
                self.write(name, 'Changed\n')
                self.assertEqual(self.scope(self.commit()), 'full')

    def test_code_renamed_into_docs_requires_full(self):
        (self.repo / 'docs').mkdir()
        self.git('mv', 'engine/example.py', 'docs/example.md')
        self.assertEqual(self.scope(self.commit()), 'full')

    def test_code_deleted_requires_full(self):
        (self.repo / 'engine/example.py').unlink()
        self.assertEqual(self.scope(self.commit()), 'full')

    def test_docs_rename_and_delete_remain_docs(self):
        self.git('mv', 'README.md', 'TODO.md')
        head = self.commit()
        self.assertEqual(self.scope(head), 'docs')
        (self.repo / 'TODO.md').unlink()
        self.assertEqual(self.scope(self.commit(), base=head), 'docs')

    def test_spaces_newlines_and_large_diff_do_not_hide_code(self):
        for n in range(350):
            self.write(f'docs/page {n}\nextra.md', '# Generated\n')
        self.write('webui/zz.py', 'changed = True\n')
        self.assertEqual(self.scope(self.commit()), 'full')

    def test_push_checks_every_commit_in_range(self):
        self.write('engine/example.py', 'value = 2\n')
        self.commit()
        self.write('README.md', 'Docs last\n')
        self.assertEqual(self.scope(self.commit(), 'push'), 'full')

    def test_pr_uses_merge_base_not_unrelated_base_branch_changes(self):
        self.write('README.md', 'PR docs\n')
        head = self.commit()
        self.git('checkout', '--detach', self.base)
        self.write('engine/example.py', 'value = 2\n')
        other = self.commit()
        self.assertEqual(self.scope(head, base=other), 'docs')
        self.assertEqual(self.scope(head, 'push', base=other), 'full')

    def test_manual_unknown_empty_and_unavailable_ranges_use_full(self):
        self.assertEqual(self.scope(self.base), 'full')
        self.assertEqual(self.scope('f' * 40), 'full')
        self.assertEqual(self.scope(self.base, 'push', base='0' * 40), 'full')
        for event, body in [('workflow_dispatch', {}), ('schedule', {}),
                            ('pull_request', {}), ('push', None),
                            ('push', {'before': '--help', 'after': self.base})]:
            with self.subTest(event=event, body=body):
                self.assertEqual(ci_scope.select_scope(event, body, self.repo)[0], 'full')

    def test_cli_outputs_scope_and_falls_back_when_event_is_unreadable(self):
        self.write('README.md', 'Documentation change\n')
        head = self.commit()
        event = self.repo / 'event.json'
        event.write_text(json.dumps({'before': self.base, 'after': self.base}))
        output = self.repo / 'output'
        env = dict(os.environ, GITHUB_EVENT_NAME='push', GITHUB_EVENT_PATH=str(event),
                   GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(self.repo / 'summary'))
        tool = str(Path(ci_scope.__file__).resolve())
        for content in ('{', event.read_text(), json.dumps({'before': self.base, 'after': head})):
            event.write_text(content)
            subprocess.run(['python3', tool, 'select'], cwd=self.repo, env=env,
                           check=True, capture_output=True)
        self.assertEqual(output.read_text(), 'scope=full\nscope=full\nscope=docs\n')


class GateTests(unittest.TestCase):
    def results(self, scope):
        return {'changes': {'result': 'success', 'outputs': {'scope': scope}},
                'docs': {'result': 'success'},
                **{name: {'result': 'skipped' if scope == 'docs' else 'success'}
                   for name in ci_scope.APP_JOBS}}

    def test_full_requires_every_suite_success(self):
        ci_scope.require_success(self.results('full'))
        for name in ci_scope.APP_JOBS:
            for state in ('failure', 'cancelled', 'skipped', 'pending'):
                result = self.results('full')
                result[name]['result'] = state
                with self.subTest(job=name, state=state), self.assertRaises(ValueError):
                    ci_scope.require_success(result)

    def test_docs_accepts_only_intentional_skips(self):
        ci_scope.require_success(self.results('docs'))
        for name in ci_scope.APP_JOBS:
            for state in ('failure', 'cancelled', 'success'):
                result = self.results('docs')
                result[name]['result'] = state
                with self.subTest(job=name, state=state), self.assertRaises(ValueError):
                    ci_scope.require_success(result)

    def test_classification_and_docs_must_pass_for_both_modes(self):
        for scope in ('docs', 'full'):
            for name in ('changes', 'docs'):
                for state in ('failure', 'cancelled', 'skipped'):
                    result = self.results(scope)
                    result[name]['result'] = state
                    with self.subTest(scope=scope, job=name, state=state), self.assertRaises(ValueError):
                        ci_scope.require_success(result)

    def test_missing_results_or_scope_cannot_pass(self):
        original = self.results('docs')
        cases = [{}, {**original, 'unexpected': {'result': 'success'}}]
        for name in original:
            cases.append({k: v for k, v in original.items() if k != name})
        for scope in ('', 'true', 'other', None):
            case = copy.deepcopy(original)
            case['changes']['outputs']['scope'] = scope
            cases.append(case)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                ci_scope.require_success(case)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / '.github/workflows/engine-tests.yml'
        self.workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.jobs = self.workflow['jobs']

    def test_workflow_runs_for_docs_and_gate_requires_every_job(self):
        self.assertEqual(set(self.workflow['on']), {'pull_request', 'push', 'workflow_dispatch'})
        self.assertEqual(self.workflow['on']['pull_request'], '')
        self.assertEqual(self.workflow['on']['push'], {'branches': ['main']})
        gate = self.jobs['smoke']
        self.assertEqual(gate['name'], 'Smoke suite (in container)')
        self.assertEqual(gate['if'], '${{ always() }}')
        self.assertEqual(set(gate['needs']), set(self.jobs) - {'smoke'})
        step = next(step for step in gate['steps'] if 'run' in step)
        self.assertEqual(step['run'].strip(), 'python3 tools/ci_scope.py gate')
        self.assertEqual(step['env']['RESULTS'], '${{ toJSON(needs) }}')

    def test_scope_controls_all_application_jobs_but_not_docs(self):
        for name in ci_scope.APP_JOBS:
            with self.subTest(job=name):
                self.assertEqual(self.jobs[name]['needs'], 'changes')
                self.assertEqual(self.jobs[name]['if'], "${{ needs.changes.outputs.scope == 'full' }}")
        self.assertNotIn('if', self.jobs['docs'])
        checks = [step['run'] for step in self.jobs['docs']['steps'] if 'run' in step]
        for name in ('check-specs.py', 'check-schema-drift.py', 'check-api-spec.py'):
            self.assertTrue(any(f'tools/{name}' in command for command in checks), name)
        changes = self.jobs['changes']
        self.assertEqual(changes['outputs']['scope'], '${{ steps.scope.outputs.scope }}')
        checkout = next(step for step in changes['steps'] if 'uses' in step)
        self.assertEqual(checkout['with']['fetch-depth'], '0')
        scope = next(step for step in changes['steps'] if step.get('id') == 'scope')
        self.assertEqual(scope['run'], 'python3 tools/ci_scope.py select')


if __name__ == '__main__':
    unittest.main()
