from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from plzdo_local_code_adapter import codec
from plzdo_local_code_adapter.cli import configure
from tests.adapter.fixtures import fixture, formalization, save_formalization, seal, write_json

CORE = Path(os.environ.get('PLZDO_ADAPTER_TEST_CORE_ROOT', str(Path(__file__).resolve().parents[2])))


@unittest.skipUnless((CORE / 'bin' / 'plzdo_entry.py').is_file(), 'public core source fixture not supplied')
class RealCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='adapter-real-process-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.envelope, self.config = fixture(self.root, CORE)
        self.request = self.envelope['request']

    def call(self):
        verifier = self.request['verifier']
        return subprocess.run([verifier['python']['path'], '-I', '-B', '-S', verifier['entrypoint']['path'],
                               '--config', str(self.config)], input=codec.canonical(self.envelope),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/', timeout=15,
                              env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})

    def assert_rejected(self):
        result = self.call()
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'plzdo-local-code-adapter: parent verification rejected\n')

    def test_real_core_absence_and_approval_snapshot_no_writes(self):
        state = Path(self.request['parentReference']['state']['path'])
        before = {str(path): codec.file_pin(path) for path in state.rglob('*') if path.is_file()}
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'absent')
        self.assertEqual(before, {str(path): codec.file_pin(path) for path in state.rglob('*') if path.is_file()})
        record = formalization(self.request)
        path = save_formalization(self.request, record)
        pin = codec.file_pin(path)
        self.envelope['operation'] = 'verify'
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['status'], 'verified')
        self.assertEqual(output['parentApprovalHash'], record['approval']['approvalHash'])
        self.assertEqual(output['parentCreatedAt'], self.request['preparedAt'])
        self.assertEqual(pin, codec.file_pin(path))
        self.assertFalse(list(state.rglob('*.lock')))
        self.assertFalse(list(state.rglob('__pycache__')))

    def test_real_core_draft_replay_and_no_approve(self):
        record = formalization(self.request, status='draft')
        save_formalization(self.request, record)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'prepared')
        self.envelope['operation'] = 'verify'
        self.assert_rejected()

    def test_runtime_style_utc_suffix_and_fractional_expiry(self):
        self.request['preparedAt'] = self.request['preparedAt'].replace('Z', '+00:00')
        self.request['expiresAt'] = self.request['expiresAt'].replace('Z', '.500000+00:00')
        seal(self.request)
        record = formalization(self.request)
        for key in ('createdAt', 'updatedAt'):
            record[key] = record[key].replace('+00:00', 'Z')
        record['approval']['approvedAt'] = record['approval']['approvedAt'].replace('+00:00', 'Z')
        save_formalization(self.request, record)
        self.envelope['operation'] = 'verify'
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'verified')

    def test_real_core_markerless_existing_draft(self):
        save_formalization(self.request, formalization(self.request, status='draft', marker=False))
        self.assert_rejected()

    def test_real_core_malformed_other_record_not_absence(self):
        state = Path(self.request['parentReference']['state']['path'])
        write_json(state / 'formalizations' / 'other-goal.json', {'bad': 'fixture'})
        self.assert_rejected()

    def test_real_core_project_mutation(self):
        state = Path(self.request['parentReference']['state']['path'])
        registry_path = state / 'registry' / 'registry.json'
        registry = json.loads(registry_path.read_text())
        other = self.root / 'other-project'
        other.mkdir()
        registry['projects'][0]['path'] = str(other)
        write_json(registry_path, registry)
        self.assert_rejected()

    def test_real_core_identity_mutation_same_approval_hash(self):
        record = formalization(self.request)
        record['id'] = 'other-goal'
        save_formalization(self.request, record)
        self.assert_rejected()

    def test_real_core_completed_and_superseded(self):
        for state in ('completed', 'superseded'):
            record = formalization(self.request)
            record['status'] = state
            if state == 'completed':
                record['completion'] = {'evidenceReference': 'fixture-evidence', 'evidenceSha256': 'a' * 64,
                                        'completedAt': record['updatedAt']}
            else:
                record['supersession'] = {'reason': 'Fixture revocation', 'supersededAt': record['updatedAt']}
            save_formalization(self.request, record)
            with self.subTest(state=state):
                self.assert_rejected()

    def test_request_or_config_drift(self):
        self.request['packet']['id'] = 'altered'
        self.assert_rejected()
        seal(self.request)
        config = json.loads(self.config.read_text())
        config['coreVersion'] = '9.9.9'
        write_json(self.config, config)
        self.assert_rejected()

    def test_v1_wire_and_mixed_legacy_marker_rejected(self):
        original = copy.deepcopy(self.envelope)
        for where, key, value in ((self.envelope, 'protocol', 'local-coding.parent-verifier-input.v1'),
                                  (self.request, 'schemaVersion', 'local-coding.parent-request.v1')):
            previous = where[key]
            where[key] = value
            seal(self.request)
            self.assert_rejected()
            where[key] = previous
        self.envelope = original
        self.request = original['request']
        record = formalization(self.request)
        record['evidenceContract'].append('local-code-delegation:v1:' + self.request['requestSha256'])
        record['approval']['approvalHash'] = codec.digest({key: record[key] for key in codec.GOVERNED_FIELDS})
        save_formalization(self.request, record)
        self.assert_rejected()

    def test_execution_is_opaque_canonical_json(self):
        self.request['execution'] = {'engine': {'privateRole': 'example'},
                                     'opaque': ['caller-owned', {'limit': 7}]}
        seal(self.request)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'absent')

    def test_state_replacement_and_symlink_rejected(self):
        state = Path(self.request['parentReference']['state']['path'])
        state.rename(self.root / 'old-state')
        state.symlink_to(self.root / 'old-state', target_is_directory=True)
        self.assert_rejected()

    def test_registry_and_goal_symlink_rejected(self):
        state = Path(self.request['parentReference']['state']['path'])
        path = save_formalization(self.request, formalization(self.request))
        path.rename(self.root / 'outside.json')
        path.symlink_to(self.root / 'outside.json')
        self.assert_rejected()

    def test_no_runtime_or_core_import_in_adapter(self):
        script = "import sys; import plzdo_local_code_adapter.cli; assert not any(x == 'local_coding' or x.startswith('local_coding.') or x == 'plzdo_local' or x.startswith('plzdo_local.') for x in sys.modules)"
        result = subprocess.run([sys.executable, '-B', '-S', '-c', script], cwd=Path(__file__).parents[2], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unpinned_core_root_shadow_cannot_execute(self):
        # Copy only the public source into owned scratch; never edit real core.
        copied = self.root / 'copied-core'
        copied.mkdir()
        for directory in codec.core_roots(CORE):
            shutil.copytree(directory, copied / directory.name,
                            ignore=shutil.ignore_patterns('__pycache__'))
        (copied / 'bin').mkdir()
        shutil.copyfile(CORE / 'bin' / 'plzdo_entry.py', copied / 'bin' / 'plzdo_entry.py')
        shutil.copyfile(CORE / 'VERSION', copied / 'VERSION')
        scratch = self.root / 'shadow-test'
        scratch.mkdir()
        envelope, config_path = fixture(scratch, copied)
        sentinel = scratch / 'shadow-executed'
        (copied / 'json.py').write_text('from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
        config = codec.validate_config(json.loads(config_path.read_text()))
        result = codec.core_command(config, envelope['request']['parentReference'], 'version')
        self.assertEqual(result['version'], '0.3.0')
        self.assertFalse(sentinel.exists())

    def test_unpinned_adapter_parent_shadow_cannot_execute(self):
        copied_parent = self.root / 'installed'
        copied_parent.mkdir()
        copied_package = copied_parent / 'plzdo_local_code_adapter'
        shutil.copytree(Path(codec.__file__).parent, copied_package)
        sentinel = self.root / 'adapter-shadow-executed'
        (copied_parent / 'json.py').write_text('from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n')
        request = self.envelope['request']
        verifier = request['verifier']
        original = str(Path(codec.__file__).parent)
        verifier['codeFiles'] = sorted([p for p in verifier['codeFiles'] if not Path(p['path']).is_relative_to(original)]
                                       + [codec.file_pin(p) for p in codec.closure(copied_package)], key=lambda p: p['path'])
        verifier['codeRoots'] = sorted([p for p in verifier['codeRoots'] if p['path'] != original]
                                       + [codec.root_pin(copied_package)], key=lambda p: p['path'])
        verifier['entrypoint'] = codec.file_pin(copied_package / 'verify_parent.py')
        seal(request)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'absent')
        self.assertFalse(sentinel.exists())


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='adapter-config-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.core = self.root / 'fake-core'
        for name in ('plzdo_local', 'bin', 'schemas', 'templates', 'resources'):
            (self.core / name).mkdir(parents=True)
        (self.core / 'plzdo_local' / '__init__.py').write_text('')
        (self.core / 'bin' / 'plzdo_entry.py').write_text('raise SystemExit(2)\n')
        (self.core / 'VERSION').write_text('0.3.0\n')
        (self.core / 'schemas' / 'test.json').write_text('{}\n')
        self.envelope, self.config = fixture(self.root, self.core)

    def test_configure_never_invokes_core_or_runtime(self):
        with patch.object(codec, 'bounded_process', side_effect=AssertionError('process invoked')):
            configure(core_root=self.core, core_python=self.root / 'fixture-python', verifier_python=self.root / 'fixture-python',
                      state_root=self.root / 'core-state', project_root=self.root / 'project',
                      project_id='fixture-project', formalization_id='other-goal', output=self.root / 'new-pins')

    def test_repeated_configuration_cannot_overwrite(self):
        original = self.config.read_bytes()
        with self.assertRaises(codec.AdapterError):
            configure(core_root=self.core, core_python=self.root / 'fixture-python', verifier_python=self.root / 'fixture-python',
                      state_root=self.root / 'core-state', project_root=self.root / 'project',
                      project_id='fixture-project', formalization_id='fixture-goal', output=self.root / 'pins')
        self.assertEqual(original, self.config.read_bytes())

    def test_added_importable_native_or_python_file_rejected(self):
        for filename in ('surprise.py', 'module.so', 'module.pyc'):
            path = self.core / 'plzdo_local' / filename
            path.write_bytes(b'fixture')
            with self.subTest(filename=filename), self.assertRaises(codec.AdapterError):
                codec.validate_config(json.loads(self.config.read_text()))
            path.unlink()

    def test_changed_core_code_or_schema(self):
        for relative in ('plzdo_local/__init__.py', 'schemas/test.json', 'VERSION', 'bin/plzdo_entry.py'):
            path = self.core / relative
            old = path.read_bytes()
            path.write_bytes(old + b' ')
            with self.subTest(relative=relative), self.assertRaises(codec.AdapterError):
                codec.validate_config(json.loads(self.config.read_text()))
            path.write_bytes(old)

    def test_no_unknown_config_options(self):
        config = json.loads(self.config.read_text())
        config['command'] = ['/bin/sh', '-c', 'true']
        with self.assertRaises(codec.AdapterError):
            codec.validate_config(config)

    def test_v1_config_and_write_command_rejected(self):
        config = json.loads(self.config.read_text())
        config['schemaVersion'] = 'plzdo-local-code-adapter.config.v1'
        with self.assertRaises(codec.AdapterError):
            codec.validate_config(config)
        with patch.object(codec, 'bounded_process', side_effect=AssertionError('process invoked')):
            with self.assertRaises(codec.AdapterError):
                codec.core_command(config, self.envelope['request']['parentReference'], 'approve')

    def test_bundled_resource_closure_drift_rejected(self):
        added = self.core / 'resources' / 'injected.txt'
        added.write_text('changed bundled bytes')
        with self.assertRaises(codec.AdapterError):
            codec.validate_config(json.loads(self.config.read_text()))

    def test_extra_pinned_file_or_root_is_not_a_supported_closure(self):
        extra = self.root / 'extra'
        extra.mkdir()
        file = extra / 'unrelated.py'
        file.write_text('unused = True\n')
        for with_root in (False, True):
            envelope = copy.deepcopy(self.envelope)
            verifier = envelope['request']['verifier']
            verifier['codeFiles'].append(codec.file_pin(file))
            verifier['codeFiles'].sort(key=lambda item: item['path'])
            if with_root:
                verifier['codeRoots'].append(codec.root_pin(extra))
                verifier['codeRoots'].sort(key=lambda item: item['path'])
            seal(envelope['request'])
            with self.subTest(with_root=with_root), self.assertRaises(codec.AdapterError):
                codec.verify(envelope, self.config)

    def test_missing_core_code_in_request_rejected(self):
        self.envelope['request']['verifier']['codeFiles'] = [p for p in self.envelope['request']['verifier']['codeFiles'] if not p['path'].endswith('/VERSION')]
        seal(self.envelope['request'])
        with self.assertRaises(codec.AdapterError):
            codec.verify(self.envelope, self.config)

    def test_changed_code_during_snapshot_rejected(self):
        request = self.envelope['request']
        parent = request['parentReference']
        version = {'schemaVersion': 'plzdo-local.version-status.v1', 'status': 'ok', 'version': '0.3.0'}
        state = {'schemaVersion': 'plzdo-local.state-root-status.v1', 'status': 'configured',
                 'path': parent['state']['path'], 'exists': True, 'isSymlink': False}
        project = {'schemaVersion': 'plzdo-local.project-show.v1', 'status': 'ok', 'project': {
            'id': parent['projectId'], 'aliases': [], 'domain': 'software', 'area': 'tooling',
            'path': parent['project']['path'], 'state': 'active', 'repositoryId': None}}
        def command(_config, _parent, key):
            if key == 'formalization':
                (self.core / 'plzdo_local' / '__init__.py').write_text('changed = True\n')
                return None
            return {'version': version, 'state': state, 'project': project}[key]
        with patch.object(codec, 'core_command', side_effect=command), self.assertRaises(codec.AdapterError):
            codec.verify(self.envelope, self.config)

    def test_outer_session_cancellation_reaches_running_core(self):
        # A synthetic CLI waits long enough to inspect process-group ownership.
        # It is installed/pinned before launch; no real core source is edited.
        started = self.root / 'core-started.json'
        sentinel = self.root / 'core-escaped'
        cli = self.core / 'plzdo_local' / 'cli.py'
        cli.write_text('import os,json,time\nfrom pathlib import Path\n'
                       'def main(args):\n'
                       '    Path(' + repr(str(started)) + ').write_text(json.dumps({"pid":os.getpid(),"group":os.getpgrp()}))\n'
                       '    time.sleep(10)\n'
                       '    Path(' + repr(str(sentinel)) + ').touch()\n'
                       '    return 0\n')
        config = json.loads(self.config.read_text())
        config['coreCodeFiles'] = [codec.file_pin(path) for path in codec.core_files(self.core)]
        write_json(self.config, config)
        parent = self.envelope['request']['parentReference']
        parent_path = self.root / 'session-parent.json'
        write_json(parent_path, parent)
        harness = self.root / 'session-harness.py'
        harness.write_text('import importlib.util,json\nfrom pathlib import Path\n'
                           'spec=importlib.util.spec_from_file_location("fixed_codec",' + repr(str(Path(codec.__file__))) + ')\n'
                           'module=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n'
                           'module.core_command(json.loads(Path(' + repr(str(self.config)) + ').read_text()),'
                           'json.loads(Path(' + repr(str(parent_path)) + ').read_text()),"version")\n')
        child = subprocess.Popen([str(self.root / 'fixture-python'), '-I', '-B', '-S', str(harness)],
                                 start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 2
            while not started.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(started.exists(), 'synthetic core did not start')
            identity = json.loads(started.read_text())
            self.assertEqual(identity['group'], child.pid, 'core escaped the runtime-owned group')
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
            self.assertFalse(sentinel.exists())
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
            child.stdout.close()
            child.stderr.close()


if __name__ == '__main__':
    unittest.main()
