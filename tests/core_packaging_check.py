"""Focused source and staged-install checks; no wheel build or package install."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_support import bundled_inputs, stage_resources
CORE_ONLY = sys.argv[1:] == ['--core-only']


class PackagingBoundaryTests(unittest.TestCase):
    def test_distribution_boundary(self):
        import tomllib

        config = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        project = config['project']
        self.assertEqual((project['name'], project['version'], project['requires-python']),
                         ('plzdo', '0.3.0', '>=3.9'))
        self.assertEqual(project['dependencies'], [])
        self.assertEqual(project['optional-dependencies'], {'local': ['plzdo-local-runtime==0.3.0']})
        self.assertNotIn('scripts', project, 'console_scripts runs site before an entrypoint can reject it')
        self.assertEqual(config['tool']['setuptools']['packages'], ['plzdo_local', 'plzdo_local_code_adapter'])
        self.assertNotIn('license', project, 'consolidated licensing is a separate operator decision')

    def test_staged_install_resources_and_isolated_entries(self):
        with tempfile.TemporaryDirectory(prefix='plzdo-core-install-') as temporary:
            owned = Path(temporary).resolve()
            prefix = owned / 'venv'
            venv.EnvBuilder(with_pip=False).create(prefix)
            purelib = Path(sysconfig.get_path('purelib', scheme='posix_prefix',
                                             vars={'base': str(prefix), 'platbase': str(prefix)}))
            self.assertTrue(purelib.is_relative_to(prefix), 'fixture package path escaped its owned prefix')
            purelib.mkdir(parents=True, exist_ok=True)
            for package in ('plzdo_local', 'plzdo_local_code_adapter'):
                shutil.copytree(ROOT / package, purelib / package, ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('plzdo', 'plzdo-local-code-adapter', 'plzdo_entry.py', 'plzdo_adapter_entry.py'):
                shutil.copy2(ROOT / 'bin' / name, prefix / 'bin' / name)
            outputs = stage_resources(ROOT, purelib)
            for source, target in zip(bundled_inputs(ROOT), outputs):
                self.assertEqual(source.read_bytes(), Path(target).read_bytes())
                self.assertTrue(Path(target).is_relative_to(purelib / 'plzdo_local' / '_bundled'))
            self.assertTrue((purelib / 'plzdo_local' / '_bundled' / 'resources' / 'public-skills' / 'ponytail' / 'SKILL.md').is_file())

            sentinel = owned / 'unsafe-startup'
            poison = 'from pathlib import Path; Path(' + repr(str(sentinel)) + ').touch()\n'
            (purelib / 'startup.pth').write_text('import pathlib; pathlib.Path(' + repr(str(sentinel)) + ').touch()\n')
            for name in ('sitecustomize.py', 'usercustomize.py', 'json.py'):
                (purelib / name).write_text(poison)
            if CORE_ONLY:
                (purelib / 'plzdo_local_code_adapter' / '__init__.py').write_text(poison)
                (purelib / 'local_coding.py').write_text(poison)
            untrusted = owned / 'untrusted'
            untrusted.mkdir()
            (untrusted / 'sitecustomize.py').write_text(poison)
            (untrusted / 'json.py').write_text(poison)
            env = {**os.environ, 'PYTHONPATH': str(untrusted), 'PYTHONUSERBASE': str(untrusted),
                   'PLZDO_HOME': str(owned / 'control-state')}

            def launch(name, *args):
                result = subprocess.run([str(prefix / 'bin' / name), *args], cwd=untrusted, env=env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertFalse(sentinel.exists(), 'site/.pth or an unpinned sibling ran')
                return result.stdout

            self.assertEqual(json.loads(launch('plzdo', 'version', '--json'))['version'], '0.3.0')
            self.assertIn('ponytail', json.loads(launch('plzdo', 'skills', 'list', '--json'))['items'])
            launch('plzdo', 'sources', 'list', '--json')
            launch('plzdo', 'init', str(owned / 'new-project'), '--id', 'fixture-project', '--json')
            self.assertFalse((purelib / 'local_coding').exists())

            if not CORE_ONLY:
                from plzdo_local_code_adapter import codec
                from tests.adapter.fixtures import fixture, formalization, save_formalization, seal

                self.assertEqual(launch('plzdo-local-code-adapter', '--version').strip(), '0.3.0')
                # Configure/verify the staged installed adapter and installed core.
                state = owned / 'fixture'
                state.mkdir()
                envelope, _ = fixture(state, purelib / 'plzdo_local')
                output = state / 'installed-pins'
                launch('plzdo-local-code-adapter', 'configure', '--core-root', str(purelib / 'plzdo_local'),
                    '--core-python', str(state / 'fixture-python'), '--verifier-python', str(state / 'fixture-python'),
                    '--state-root', str(state / 'core-state'), '--project-root', str(state / 'project'),
                    '--project-id', 'fixture-project', '--formalization-id', 'fixture-goal', '--output', str(output))
                request = envelope['request']
                request['verifier'] = json.loads((output / 'verifier.json').read_text())
                seal(request)
                save_formalization(request, formalization(request))
                envelope['operation'] = 'verify'
                verifier = request['verifier']
                result = subprocess.run([verifier['python']['path'], '-I', '-S', '-B', verifier['entrypoint']['path'],
                                         '--config', str(output / 'adapter-config.json')],
                                        input=codec.canonical(envelope), capture_output=True, cwd=untrusted, env=env, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'verified')
                self.assertFalse(sentinel.exists())
                self.assertNotIn(str(purelib), [pin['path'] for pin in verifier['codeRoots']])
                self.assertTrue(all(Path(pin['path']).is_relative_to(purelib / 'plzdo_local') or
                                    Path(pin['path']).is_relative_to(purelib / 'plzdo_local_code_adapter')
                                    for pin in verifier['codeFiles']))

            # Positive control: the fixture really would run during ordinary site startup.
            control = subprocess.run([str(prefix / 'bin' / 'python3'), '-I', '-B', '-c', 'pass'],
                                     capture_output=True, timeout=10)
            self.assertEqual(control.returncode, 0, control.stderr)
            self.assertTrue(sentinel.exists())

    def test_direct_nonisolated_entry_refuses_before_cli(self):
        for relative in ('bin/plzdo_entry.py', 'bin/plzdo_adapter_entry.py',
                         'plzdo_local_code_adapter/verify_parent.py', 'plzdo_local_code_adapter/core_entry.py'):
            with self.subTest(entry=relative):
                result = subprocess.run([sys.executable, '-B', '-S', str(ROOT / relative), '--help'],
                                        capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')

    def test_python39_rejects_optional_entries(self):
        self.assertEqual(sys.version_info[:2], (3, 9))
        for relative in ('bin/plzdo_adapter_entry.py', 'plzdo_local_code_adapter/verify_parent.py',
                         'plzdo_local_code_adapter/core_entry.py'):
            with self.subTest(entry=relative):
                result = subprocess.run([sys.executable, '-I', '-S', '-B', str(ROOT / relative), '--help'],
                                        capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')
                expected = (b'plzdo-local-code-adapter: use the isolated launcher'
                            if relative == 'bin/plzdo_adapter_entry.py' else b'Python 3.11+')
                self.assertIn(expected, result.stderr)


if __name__ == '__main__':
    if sys.argv[1:] not in ([], ['--core-only']):
        raise SystemExit('usage: core_packaging_check.py [--core-only]')
    if not CORE_ONLY and sys.version_info < (3, 11):
        raise SystemExit('full package/adapter checks require Python 3.11+; use --core-only for core compatibility')
    print('package verification interpreter:', sys.executable, sys.version.split()[0], flush=True)
    names = ['test_staged_install_resources_and_isolated_entries', 'test_direct_nonisolated_entry_refuses_before_cli']
    if not CORE_ONLY:
        names.append('test_distribution_boundary')
    if sys.version_info[:2] == (3, 9):
        names.append('test_python39_rejects_optional_entries')
    suite = unittest.TestSuite(PackagingBoundaryTests(name) for name in names)
    runner = unittest.TextTestRunner()
    result = runner.run(suite)
    raise SystemExit(not result.wasSuccessful())
