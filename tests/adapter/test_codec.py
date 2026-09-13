from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from plzdo_local_code_adapter import codec
from tests.adapter.fixtures import formalization, seal


class DecoderTests(unittest.TestCase):
    def test_single_document(self):
        self.assertEqual(codec.decode(b' {"x": 1}\n', 100), {"x": 1})

    def test_ambiguous_or_noncanonical_json(self):
        for raw in (b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}', b'{} {}',
                    b'[]', b'null', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e1000}',
                    b'\xef\xbb\xbf{}', b'{"x":"\\ud800"}', b'\xff', b'{}trailing', b''):
            with self.subTest(raw=raw), self.assertRaises(codec.AdapterError):
                codec.decode(raw, 100)

    def test_oversize(self):
        with self.assertRaises(codec.AdapterError):
            codec.decode(b'{}', 1)

    def test_deeply_nested_input_rejects(self):
        with self.assertRaises(codec.AdapterError):
            codec.decode(b'{"x":' + b'[' * 10000 + b'0' + b']' * 10000 + b'}', 100000)

    def test_timestamp_exact_seconds(self):
        for value in ('2026-09-12T12:00:00+00:00', '2026-09-12T12:00:00.1Z',
                      '2026-13-12T12:00:00Z', '2026-09-12', True):
            with self.subTest(value=value), self.assertRaises(codec.AdapterError):
                codec.timestamp(value, 'test')

    def test_runtime_request_accepts_both_explicit_utc_forms(self):
        self.assertEqual(codec.request_timestamp('2026-09-12T12:00:00Z', 'preparedAt'),
                         codec.request_timestamp('2026-09-12T12:00:00+00:00', 'preparedAt'))
        self.assertEqual(codec.request_timestamp('2026-09-12T12:00:00.123456+00:00', 'expiresAt').microsecond,
                         123456)
        for value in ('2026-09-12T12:00:00', '2026-09-12T12:00:00+01:00'):
            with self.assertRaises(codec.AdapterError):
                codec.request_timestamp(value, 'expiresAt')
        with self.assertRaises(codec.AdapterError):
            codec.request_timestamp('2026-09-12T12:00:00.1Z', 'preparedAt')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.request = {"schemaVersion": codec.REQUEST_SCHEMA,
                        "preparedAt": "2026-09-12T12:00:00Z", "expiresAt": "2026-09-12T13:00:00Z",
                        "requestSha256": "a" * 64,
                        "parentReference": {"formalizationId": "fixture-goal", "projectId": "fixture-project"}}
        self.now = "2026-09-12T12:00:00Z"

    def check(self, record, operation='verify'):
        return codec.decode_snapshot(record, self.request, operation, self.now)

    def test_same_second_approved_snapshot(self):
        record = formalization(self.request)
        result = self.check(record)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['parentCreatedAt'], self.now)
        self.assertEqual(result['parentApprovedAt'], self.now)
        self.assertIs(result['atomicLease'], False)
        self.assertEqual(result['authorizationBasis'], 'operator-owned-local-record-snapshot')

    def test_scope_marker_is_distinct_and_cannot_reuse_exact_or_mixed_marker(self):
        old_record = formalization(self.request)
        self.request['schemaVersion'] = codec.SCOPE_REQUEST_SCHEMA
        self.assertEqual(self.check(formalization(self.request))['status'], 'verified')
        with self.assertRaisesRegex(codec.AdapterError, 'marker'):
            self.check(old_record)
        mixed = formalization(self.request)
        mixed['evidenceContract'].append(codec.MARKER_PREFIX + self.request['requestSha256'])
        mixed['approval']['approvalHash'] = codec.digest({key: mixed[key] for key in codec.GOVERNED_FIELDS})
        with self.assertRaisesRegex(codec.AdapterError, 'marker'):
            self.check(mixed)

    def test_absent_and_matching_draft_only_during_prepare(self):
        self.assertEqual(self.check(None, 'prepare')['status'], 'absent')
        record = formalization(self.request, status='draft')
        self.assertEqual(self.check(record, 'prepare')['status'], 'prepared')
        for value in (None, record):
            with self.assertRaises(codec.AdapterError):
                self.check(value)

    def test_markerless_existing_draft_rejected(self):
        with self.assertRaisesRegex(codec.AdapterError, 'marker'):
            self.check(formalization(self.request, status='draft', marker=False), 'prepare')

    def test_governed_hash_does_not_mask_identity_mutation(self):
        for field, value in (('id', 'other-goal'), ('projectId', 'other-project'),
                             ('createdAt', '2026-09-12T11:59:59Z'), ('status', 'completed')):
            record = formalization(self.request)
            old_hash = record['approval']['approvalHash']
            record[field] = value
            self.assertEqual(old_hash, codec.digest({key: record[key] for key in codec.GOVERNED_FIELDS}))
            with self.subTest(field=field), self.assertRaises(codec.AdapterError):
                self.check(record)

    def test_payload_mutation_without_reapproval_rejected(self):
        record = formalization(self.request)
        record['objective'] = 'Altered objective'
        with self.assertRaisesRegex(codec.AdapterError, 'payload hash'):
            self.check(record)

    def test_marker_requires_exact_unique_evidence_item(self):
        marker = codec.MARKER_PREFIX + self.request['requestSha256']
        for evidence in ([marker, marker], ['prefix ' + marker], [marker + '-suffix'],
                         [marker, codec.MARKER_PREFIX + 'b' * 64], [], [None]):
            record = formalization(self.request)
            record['evidenceContract'] = evidence
            with self.subTest(evidence=evidence), self.assertRaises(codec.AdapterError):
                self.check(record)

    def test_future_and_invalid_approval_times(self):
        for field in ('createdAt', 'updatedAt', 'approvedAt'):
            record = formalization(self.request)
            if field == 'approvedAt':
                record['approval'][field] = '2026-09-12T12:00:01Z'
            else:
                record[field] = '2026-09-12T12:00:01Z'
            with self.subTest(field=field), self.assertRaises(codec.AdapterError):
                self.check(record)

    def test_unconfirmed_terminal_bad_shape(self):
        changes = [lambda r: r.update(supersession={}), lambda r: r.update(extra=True),
                   lambda r: r.update(schemaVersion='unsupported'),
                   lambda r: r['approval'].update(operatorConfirmed=1),
                   lambda r: r['approval'].update(approvalHash='b' * 64),
                   lambda r: r['route']['projectDecision'].update(projectId='other-project')]
        for change in changes:
            record = formalization(self.request)
            change(record)
            with self.subTest(change=change), self.assertRaises(codec.AdapterError):
                self.check(record)

    def test_expiry_exact_boundary_rejected(self):
        self.now = self.request['expiresAt']
        with self.assertRaises(codec.AdapterError):
            self.check(formalization(self.request))


class CoreCommandTests(unittest.TestCase):
    def setUp(self):
        self.config = {'corePython': {'path': '/fixture/python'}, 'coreRoot': {'path': '/fixture/core'}}
        self.parent = {'projectId': 'fixture-project', 'formalizationId': 'fixture-goal',
                       'state': {'path': '/fixture/state'}}

    def test_only_exact_missing_is_absence(self):
        exact = b'plzdo: DurableCommandError: formalization not found: fixture-goal\n'
        with patch.object(codec, 'bounded_process', return_value=(2, b'', exact)):
            self.assertIsNone(codec.core_command(self.config, self.parent, 'formalization'))
        for result in ((2, b'', b''), (2, b'', b'permission denied\n'), (1, b'', exact),
                       (2, b'{}', exact), (2, b'', exact.rstrip()),
                       (2, b'', exact.replace(b'fixture-goal', b'other-goal')),
                       (2, b'', b'prefix\n' + exact), (2, b'', exact + b'\n')):
            with self.subTest(result=result), patch.object(codec, 'bounded_process', return_value=result), self.assertRaises(codec.AdapterError):
                codec.core_command(self.config, self.parent, 'formalization')

    def test_fixed_argv_and_sanitized_environment(self):
        with patch.dict(os.environ, {'PYTHONPATH': '/untrusted', 'PLZDO_HOME': '/wrong', 'SECRET_EXAMPLE': 'not-a-secret'}), patch.object(codec, 'bounded_process', return_value=(0, b'{}', b'')) as run:
            codec.core_command(self.config, self.parent, 'project')
        argv, env = run.call_args.args
        self.assertEqual(argv, ['/fixture/python', '-I', '-B', '-S', str(Path(codec.__file__).parent / 'core_entry.py'),
                                '--core-root', '/fixture/core',
                                'project', 'show', 'fixture-project', '--json'])
        self.assertEqual(set(env), {'PATH', 'LANG', 'LC_ALL', 'PYTHONDONTWRITEBYTECODE', 'PLZDO_HOME'})
        self.assertEqual(env['PLZDO_HOME'], '/fixture/state')

    def test_no_arbitrary_command_or_argument_injection(self):
        with patch.object(codec, 'bounded_process') as run:
            for command in ('approve', 'draft', 'shell', 'version; true'):
                with self.assertRaises(codec.AdapterError):
                    codec.core_command(self.config, self.parent, command)
            for identifier in ('--json', 'ok; touch /tmp/should-not-exist', '../parent', 'x\nwhoami', 'x'):
                with self.assertRaises(codec.AdapterError):
                    codec.core_command(self.config, {**self.parent, 'formalizationId': identifier}, 'formalization')
            run.assert_not_called()

    def test_stderr_or_ambiguous_stdout_rejected(self):
        for result in ((0, b'{}', b'warning'), (0, b'{}{}', b''), (0, b'{"x":1,"x":2}', b''), (2, b'{}', b'')):
            with self.subTest(result=result), patch.object(codec, 'bounded_process', return_value=result), self.assertRaises(codec.AdapterError):
                codec.core_command(self.config, self.parent, 'version')


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='adapter-boundary-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.file = self.root / 'file.py'
        self.file.write_text('pass\n')

    def test_pin_detects_content_and_inode_change(self):
        pin = codec.file_pin(self.file)
        self.file.write_text('changed\n')
        with self.assertRaises(codec.AdapterError):
            codec.validate_pin(pin)
        self.file.write_text('pass\n')
        self.file.rename(self.root / 'old.py')
        self.file.write_text('pass\n')
        with self.assertRaises(codec.AdapterError):
            codec.validate_pin(pin)

    def test_symlink_file_directory_and_nonregular_rejected(self):
        link = self.root / 'link.py'
        link.symlink_to(self.file)
        with self.assertRaises(codec.AdapterError):
            codec.file_pin(link)
        with self.assertRaises(codec.AdapterError):
            codec.closure(self.root)
        link.unlink()
        fifo = self.root / 'pipe'
        os.mkfifo(fifo)
        with self.assertRaises(codec.AdapterError):
            codec.file_pin(fifo)

    def test_writable_file_rejected(self):
        self.file.chmod(0o666)
        with self.assertRaises(codec.AdapterError):
            codec.file_pin(self.file)

    def test_pin_type_boolean_rejected(self):
        pin = codec.file_pin(self.file)
        pin['device'] = True
        with self.assertRaises(codec.AdapterError):
            codec.validate_pin(pin)

    def test_root_replacement_detected(self):
        directory = self.root / 'state'
        directory.mkdir()
        pin = codec.root_pin(directory)
        directory.rename(self.root / 'old-state')
        directory.mkdir()
        with self.assertRaises(codec.AdapterError):
            codec.validate_pin(pin, directory=True)


class ProcessTests(unittest.TestCase):
    def invoke(self, source, **kwargs):
        # This private test helper exercises bounded_process; the public adapter
        # constructs only its four literal core commands.
        return codec.bounded_process([str(Path(sys.executable).resolve()), '-I', '-B', '-S', '-c', source],
                                     {'PATH': '/usr/bin:/bin'}, **kwargs)

    def test_success_and_nonzero(self):
        self.assertEqual(self.invoke('print("ok")'), (0, b'ok\n', b''))
        self.assertEqual(self.invoke('raise SystemExit(2)')[0], 2)

    def test_deadline_and_output_bounds(self):
        for source, kwargs in (('import time; time.sleep(5)', {'timeout': .1}),
                               ('print("x" * 10000)', {'stdout_limit': 100}),
                               ('import sys; sys.stderr.write("x" * 10000)', {'stderr_limit': 100})):
            with self.subTest(source=source), self.assertRaises(codec.AdapterError):
                self.invoke(source, **kwargs)

    def test_parent_exits_but_descendant_holds_output_open(self):
        source = 'import os,time\nif os.fork() == 0: time.sleep(5)\nelse: os._exit(0)'
        started = time.monotonic()
        with self.assertRaises(codec.AdapterError):
            self.invoke(source, timeout=.2)
        self.assertLess(time.monotonic() - started, 2)


if __name__ == '__main__':
    unittest.main()
