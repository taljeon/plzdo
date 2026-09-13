"""Joined real CLI flow. No live approvals, providers, model or browser calls."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from plzdo_local_code_adapter import codec
from tests.adapter.fixtures import fixture, formalization, save_formalization, write_json

ROOT = Path(__file__).resolve().parents[2]
CORE = Path(os.environ.get('PLZDO_ADAPTER_TEST_CORE_ROOT', str(ROOT)))
RUNTIME = Path(os.environ.get('PLZDO_ADAPTER_TEST_RUNTIME_ROOT', str(ROOT / 'runtime-public')))
AVAILABLE = ((CORE / 'bin' / 'plzdo_entry.py').is_file()
             and (RUNTIME / 'local_coding' / '_engine' / 'parent_authority.py').is_file()
             and importlib.util.find_spec('jsonschema') is not None and platform.system() == 'Darwin')


@unittest.skipUnless(AVAILABLE, 'joined public core/runtime macOS fixture and runtime dependency not supplied')
class RuntimeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='adapter-runtime-bridge-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.envelope, self.config = fixture(self.root, CORE, configure_cli=True)
        self.state = self.root / 'runtime-state'
        self.verifier = self.envelope['request']['verifier']

    def cli(self, *args):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('LOCAL_CODING_', 'PLZDO_'))}
        env.update(PYTHONPATH=str(RUNTIME), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-m', 'local_coding',
                                 '--state-root', str(self.state), *args], cwd=RUNTIME, env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stderr, '', result.stderr)
        return result, json.loads(result.stdout)

    def trust(self):
        fingerprint = codec.digest(self.verifier)
        result, data = self.cli('delegation', 'trust-verifier', '--verifier', str(self.root / 'pins' / 'verifier.json'),
                                '--expected-sha256', fingerprint,
                                '--confirm', 'TRUST PARENT VERIFIER ' + fingerprint)
        self.assertEqual(result.returncode, 0, data)

    def prepare(self, *, compute=False):
        packet = ({'kind': 'compute-analysis', 'id': 'fixture-compute', 'objective': 'Synthetic tool handoff',
                   'inputs': {'value': 42}, 'external_ai_allowed': True}
                  if compute else
                  {'kind': 'artifact-create', 'id': 'fixture-packet', 'objective': 'Create fixture text',
                   'allowed_paths': ['result.txt'], 'external_ai_allowed': True,
                   'generation_profile': 'huihui-qwen38-q6kl-v1', 'task_category': 'product-development',
                   'validation_packs': [{'type': 'text', 'path': 'result.txt', 'required': ['fixture']}]})
        write_json(self.root / 'packet.json', packet)
        args = ['delegation', 'prepare', '--packet', str(self.root / 'packet.json'),
                '--parent-reference', str(self.root / 'pins' / 'parent-reference.json'),
                '--verifier', str(self.root / 'pins' / 'verifier.json'),
                '--expires-at', self.envelope['request']['expiresAt'], '--max-calls', '0' if compute else '8',
                '--max-runs', '2']
        if not compute:
            for provider in ('local', 'codex', 'claude', 'grok'):
                args.extend(['--provider', provider])
        result, data = self.cli(*args)
        self.assertEqual(result.returncode, 0, data)
        prepared = data['result']
        self.assertIs(prepared['execution_authorized'], False)
        self.assertEqual(prepared['provider_calls'], 0)
        self.assertEqual(prepared['marker'], codec.MARKER_PREFIX + prepared['request']['requestSha256'])
        return prepared['request'], args

    def adopt(self, request):
        result, data = self.cli('delegation', 'adopt', '--id', request['id'], '--expected-sha256', request['requestSha256'])
        self.assertEqual(result.returncode, 0, data)
        self.assertEqual(data['result']['document']['status'], 'delegated')
        self.assertNotIn('approvedBy', data['result']['document'])
        return data['result']['document']

    def test_new_parent_scope_cli_admits_children_without_standalone_approval(self):
        self.trust()
        template = {'kind': 'artifact-create', 'id': 'template-text', 'objective': 'Create fixture text',
            'allowed_paths': ['result.txt'], 'external_ai_allowed': True,
            'generation_profile': 'huihui-qwen38-q6kl-v1', 'task_category': 'product-development',
            'validation_packs': [{'type': 'text', 'path': 'result.txt', 'required': ['fixture']}]}
        scope = {'schemaVersion': 'local-coding.task-scope.v1',
            'templates': {'text': {'packet': template, 'basePolicy': {'mode': 'exact'}}}}
        write_json(self.root / 'scope.json', scope)
        result, data = self.cli('delegation', 'prepare-scope', '--scope', str(self.root / 'scope.json'),
            '--parent-reference', str(self.root / 'pins/parent-reference.json'),
            '--verifier', str(self.root / 'pins/verifier.json'),
            '--expires-at', self.envelope['request']['expiresAt'], '--max-calls', '2',
            '--max-total-runs', '2', '--max-children', '2', '--provider', 'local')
        self.assertEqual(result.returncode, 0, data)
        request = data['result']['request']
        self.assertEqual(data['result']['marker'], codec.SCOPE_MARKER_PREFIX + request['requestSha256'])
        self.assertNotIn('packet', request)
        write_json(self.root / 'child.json', {**template, 'id': 'child-one'})
        rejected, _ = self.cli('scope', 'admit', '--id', request['id'], '--template', 'text',
                               '--packet', str(self.root / 'child.json'))
        self.assertNotEqual(rejected.returncode, 0)
        save_formalization(request, formalization(request))
        document = self.adopt(request)
        self.assertEqual(document['schemaVersion'], 'parent-scoped-contract.v1')
        root_path = self.state / 'contracts' / (request['id'] + '.json')
        original = root_path.read_bytes()
        for child_id in ('child-one', 'child-two'):
            write_json(self.root / 'child.json', {**template, 'id': child_id})
            result, data = self.cli('scope', 'admit', '--id', request['id'], '--template', 'text',
                                   '--packet', str(self.root / 'child.json'))
            self.assertEqual(result.returncode, 0, data)
            self.assertIs(data['result']['new_operator_approval'], False)
            self.assertEqual(data['result']['child']['packet']['hn_formalization'], request['id'])
        self.assertEqual(root_path.read_bytes(), original)
        self.assertEqual(len(list((self.state / 'contracts').glob('*.json'))), 1)
        self.assertEqual(len(list((self.state / 'ledgers').glob('*.json'))), 1)
        self.adopt(request)  # Re-adoption after children never resets the catalog.
        write_json(self.root / 'child.json', {**template, 'id': 'child-three'})
        rejected, _ = self.cli('scope', 'admit', '--id', request['id'], '--template', 'text',
                               '--packet', str(self.root / 'child.json'))
        self.assertNotEqual(rejected.returncode, 0)
        save_formalization(request, formalization(request, status='draft'))
        write_json(self.root / 'child.json', {**template, 'id': 'child-one'})
        rejected, _ = self.cli('scope', 'admit', '--id', request['id'], '--template', 'text',
                               '--packet', str(self.root / 'child.json'))
        self.assertNotEqual(rejected.returncode, 0)

    def test_cli_prepare_adopt_compute_handoff_then_revocation(self):
        self.trust()
        request, args = self.prepare(compute=True)
        request_file = self.state / 'parent-requests' / (request['id'] + '.json')
        request_bytes = request_file.read_bytes()
        self.assertFalse((self.state / 'contracts').exists())
        self.assertFalse((self.state / 'ledgers').exists())
        # Simulated data stands in for the operator's normal first draft/approval.
        draft = formalization(request, status='draft')
        path = save_formalization(request, draft)
        repeated, data = self.cli(*args)
        self.assertEqual(repeated.returncode, 0, data)
        self.assertEqual(request_file.read_bytes(), request_bytes)
        rejected, data = self.cli('delegation', 'adopt', '--id', request['id'], '--expected-sha256', request['requestSha256'])
        self.assertNotEqual(rejected.returncode, 0, data)
        approved = formalization(request)
        save_formalization(request, approved)
        document = self.adopt(request)
        ledger_path = self.state / 'ledgers' / (request['id'] + '.json')
        ledger_bytes = ledger_path.read_bytes()
        self.assertEqual(self.adopt(request), document)
        self.assertEqual(ledger_path.read_bytes(), ledger_bytes)
        write_json(self.root / 'normalized-packet.json', request['packet'])
        result, data = self.cli('run', '--packet', str(self.root / 'normalized-packet.json'), '--name', 'fixture-compute-first')
        self.assertEqual(result.returncode, 2, data)
        self.assertEqual(data['state'], 'handoff_required')
        self.assertIs(data['result']['computed'], False)
        self.assertEqual(data['result']['provider_calls'], 0)
        self.assertEqual(data['apply_status'], 'not_applied')
        ledger_after_run = ledger_path.read_bytes()
        ledger = json.loads(ledger_after_run)
        self.assertEqual(len(ledger['records']), 1)
        self.assertEqual(ledger['records'][0]['kind'], 'run')
        approved['status'] = 'completed'
        approved['completion'] = {'evidenceReference': 'fixture-evidence', 'evidenceSha256': 'a' * 64,
                                  'completedAt': approved['updatedAt']}
        save_formalization(request, approved)
        result, data = self.cli('run', '--packet', str(self.root / 'normalized-packet.json'), '--name', 'fixture-compute-revoked')
        self.assertNotEqual(result.returncode, 0, data)
        self.assertNotEqual(data['state'], 'handoff_required')
        self.assertEqual(ledger_path.read_bytes(), ledger_after_run)

    def test_cli_missing_trust_never_prepares_or_executes(self):
        packet = {'kind': 'compute-analysis', 'id': 'untrusted-compute', 'objective': 'Synthetic handoff',
                  'inputs': {}, 'external_ai_allowed': True}
        write_json(self.root / 'packet.json', packet)
        result, data = self.cli('delegation', 'prepare', '--packet', str(self.root / 'packet.json'),
                                '--parent-reference', str(self.root / 'pins' / 'parent-reference.json'),
                                '--verifier', str(self.root / 'pins' / 'verifier.json'),
                                '--expires-at', self.envelope['request']['expiresAt'], '--max-calls', '0')
        self.assertNotEqual(result.returncode, 0, data)
        self.assertFalse(list((self.state / 'parent-requests').glob('*.json')))
        self.assertFalse((self.state / 'contracts').exists())

    def test_real_adapter_blocks_each_reservation_after_parent_change(self):
        self.trust()
        request, _ = self.prepare()
        approved = formalization(request)
        save_formalization(request, approved)
        document = self.adopt(request)
        with patch.object(sys, 'path', [str(RUNTIME), *sys.path]):
            from local_coding.cli import _engine_module
            contracts = _engine_module('contracts')
            ledger = _engine_module('ledger')
            StateError = _engine_module('state_io').StateError
        engine_path = str(RUNTIME / 'local_coding' / '_engine')
        sys.path.insert(0, engine_path)
        self.addCleanup(sys.path.remove, engine_path)
        binding = document['execution']['taskBindings'][request['packet']['id']]
        current = contracts.approved_contract(request['packet'], self.state)
        self.assertEqual(current, (document, binding))
        parent_reservation = ledger.reserve(self.state, document, binding, request['packet'], 'provider', 'grok')
        ledger_path = self.state / 'ledgers' / (request['id'] + '.json')
        before = ledger_path.read_bytes()
        changed = formalization(request)
        changed['id'] = 'different-goal'
        # ID is not part of core approvalHash: the core record remains valid,
        # but the adapter's parent identity check must reject all reservations.
        self.assertEqual(changed['approval']['approvalHash'], approved['approval']['approvalHash'])
        save_formalization(request, changed)
        for provider in ('local', 'codex', 'claude', 'grok'):
            with self.subTest(provider=provider), self.assertRaises(StateError):
                ledger.reserve(self.state, document, binding, request['packet'], 'provider', provider)
            self.assertEqual(ledger_path.read_bytes(), before)
        with self.assertRaises(StateError):
            ledger.reserve(self.state, document, binding, request['packet'], 'run')
        with self.assertRaises(StateError):
            ledger.claim_child_send(self.state, document, binding, request['packet'],
                                    parent_reservation_id=parent_reservation['reservation_id'], child_id='b' * 64)
        self.assertEqual(ledger_path.read_bytes(), before)
        self.assertEqual(len(json.loads(before)['records']), 1)

    def test_cli_reference_reuses_fixed_verifier_for_next_goal(self):
        self.trust()
        descriptor = (self.root / 'pins' / 'verifier.json').read_bytes()
        output = self.root / 'next-reference.json'
        command = [sys.executable, '-I', '-S', '-B', str(CORE / 'bin' / 'plzdo_adapter_entry.py'), 'reference',
                   '--state-root', str(self.root / 'core-state'), '--project-root', str(self.root / 'project'),
                   '--project-id', 'fixture-project', '--formalization-id', 'fixture-next-goal',
                   '--output', str(output)]
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_bytes())['formalizationId'], 'fixture-next-goal')
        repeat = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15)
        self.assertEqual(repeat.returncode, 2)
        self.assertEqual((self.root / 'pins' / 'verifier.json').read_bytes(), descriptor)


if __name__ == '__main__':
    unittest.main()
