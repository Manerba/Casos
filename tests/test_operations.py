"""Real DEB build and prefixed lifecycle hooks; no host service/user/pip actions."""
import configparser
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
UNITS = {'casos.service', 'casos-mcp.service', 'casos-ldap-sync.service',
         'casos-ldap-sync.timer', 'casos-mail-scheduler.service', 'casos-mail-scheduler.timer'}
STUBS = ('id', 'useradd', 'userdel', 'chown', 'python3', 'venv-python', 'systemctl')
STUB_SOURCE = '''#!/usr/bin/python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['CASOS_PACKAGE_ROOT'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root/'hook-calls.jsonl').open('a') as log:
    log.write(json.dumps([name, *args])+'\\n')
marker = root/'stub-user-exists'
if name == 'id':
    if args == ['-u']: print('0')
    elif not marker.exists(): sys.exit(1)
elif name == 'useradd': marker.touch()
elif name == 'userdel': marker.unlink(missing_ok=True)
elif name == 'python3':
    assert args[:2] == ['-m', 'venv'], args
    target = pathlib.Path(args[2])/'bin'/'python'
    assert target.is_relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('#!/bin/sh\\nexit 99\\n')
    target.chmod(0o755)
elif name == 'venv-python' and (root/'fail-pip').exists(): sys.exit(1)
'''


class OperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not shutil.which('dpkg-deb') or not shutil.which('rsync'):
            raise unittest.SkipTest('Package checks need dpkg-deb and rsync; not executed')
        cls.temporary = tempfile.TemporaryDirectory(prefix='casos-operations-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        cls.output = cls.work/'artifacts with spaces'
        result = subprocess.run(['bash', str(ROOT/'publish.sh'), '--build', str(cls.output)],
                                cwd=ROOT, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.package = next(cls.output.glob('casos_*.deb'))
        cls.build_output = result.stdout
        cls.control = cls.work/'control'
        subprocess.run(['dpkg-deb', '--control', str(cls.package), str(cls.control)], check=True, capture_output=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='lifecycle-', dir=self.work)
        self.addCleanup(tmp.cleanup)
        self.stage = Path(tmp.name)
        subprocess.run(['dpkg-deb', '--extract', str(self.package), str(self.stage)], check=True, capture_output=True)
        self.app = self.stage/'opt/casos'
        self.env = {**os.environ, 'CASOS_PACKAGE_ROOT': str(self.stage)}
        self.stubdir = self.stage/'.casos-hook-stubs'
        self.stubdir.mkdir()
        for name in STUBS:
            path = self.stubdir/name
            path.write_text(STUB_SOURCE)
            path.chmod(0o755)

    def hook(self, name, argument, *, success=True):
        result = subprocess.run(['bash', str(self.control/name), argument],
                                env=self.env, text=True, capture_output=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def calls(self):
        path = self.stage/'hook-calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def clear_calls(self):
        (self.stage/'hook-calls.jsonl').unlink(missing_ok=True)

    def seed_data(self):
        data = self.app/'data'
        (data/'attachments').mkdir(parents=True, exist_ok=True)
        for relative, content in {'casos.db': b'isolated database sentinel', 'secret.key': b'test-only-key',
                                  'attachments/opaque-storage-name': bytes(range(256))}.items():
            (data/relative).write_bytes(content)
        return self.data_bytes()

    def data_bytes(self):
        return {str(p.relative_to(self.app/'data')): p.read_bytes()
                for p in (self.app/'data').rglob('*') if p.is_file()}

    def test_shell_syntax_and_explicit_local_build_mode(self):
        for path in [ROOT/'publish.sh', ROOT/'packaging/install.sh', *(ROOT/'packaging/DEBIAN'/n for n in ('postinst', 'prerm', 'postrm'))]:
            with self.subTest(path=path):
                result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
        for arguments in ([], ['--setup'], ['--github'], ['--github-init'], ['--invalid']):
            result = subprocess.run(['bash', str(ROOT/'publish.sh'), *arguments], cwd=self.stage,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
        self.assertTrue(self.package.is_file(), 'The completed build must retain its DEB')
        self.assertIn(str(self.package), self.build_output)
        self.assertEqual(list(self.output.glob('.casos*')), [])

    def test_actual_package_inventory_dependencies_and_safe_modes(self):
        payload = subprocess.run(['dpkg-deb', '--fsys-tarfile', str(self.package)], capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            members = archive.getmembers()
        names = {entry.name.removeprefix('./') for entry in members}
        for entry in members:
            self.assertEqual((entry.uid, entry.gid), (0, 0), entry.name)
            if entry.isdir(): self.assertEqual(entry.mode & 0o777, 0o755, entry.name)
            elif entry.isfile(): self.assertEqual(entry.mode & 0o777, 0o644, entry.name)
            else: self.fail('Unexpected archive link/special entry: '+entry.name)
        required = {'opt/casos/dashboard/app.py', 'opt/casos/dashboard/mcp_app.py',
                    'opt/casos/dashboard/preview_worker.py', 'opt/casos/dashboard/issue_schema.sql',
                    'opt/casos/dashboard/static/js/markdown_editor.js',
                    'opt/casos/dashboard/static/js/vendor/marked.LICENSE',
                    'usr/share/doc/casos/README.Debian', 'usr/share/doc/casos/operations.md', 'usr/share/doc/casos/DEPENDENCIES.md',
                    'usr/share/doc/casos/licenses/extract-msg-LICENSE.txt',
                    'usr/share/doc/casos/licenses/Pillow-LICENSE.txt',
                    'usr/share/doc/casos/licenses/striprtf-LICENSE.txt'}
        self.assertTrue(required <= names, required-names)
        for name in names:
            for forbidden in ('__pycache__', '.pyc', '/data/', '/venv/', 'secret.key', '/tests/', '/fixtures/',
                              'project77-', 'admin_app.py', 'casos-admin', 'onlyoffice', 'webdav.py',
                              'api_nextcloud.py', 'file_browser.', 'text_file_editor.', 'turndown', 'vis-network'):
                self.assertNotIn(forbidden, name)
        scripts = {p.name for p in (self.app/'scripts').iterdir()}
        self.assertEqual(scripts, UNITS | {'ldap_sync_cron.py', 'mail_scheduler.py'})
        info = subprocess.run(['dpkg-deb', '--field', str(self.package)], capture_output=True, text=True, check=True).stdout
        self.assertIn('Version: '+(ROOT/'version.txt').read_text().strip(), info)
        self.assertNotIn('docker', info.lower())
        self.assertNotIn('8515', info)
        for name in ('postinst', 'prerm', 'postrm'):
            self.assertEqual((self.control/name).stat().st_mode & 0o777, 0o755)

    def test_units_keep_hardening_paths_and_both_timers(self):
        for unit in UNITS:
            target = self.app/'scripts'/unit
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read(target)
            if unit.endswith('.service'):
                self.assertEqual(config['Service']['User'], 'casos')
                self.assertEqual(config['Service']['Group'], 'casos')
                self.assertEqual(config['Service']['WorkingDirectory'], '/opt/casos')
                self.assertEqual(config['Service']['ProtectSystem'], 'strict')
                for key in ('NoNewPrivileges', 'PrivateTmp', 'ProtectHome', 'ProtectKernelTunables', 'ProtectControlGroups'):
                    self.assertIn(config['Service'][key], ('true', 'yes'))
                self.assertIn('/opt/casos/data', config['Service']['ReadWritePaths'])
                command = config['Service']['ExecStart'].split()
                self.assertEqual(command[0], '/opt/casos/venv/bin/python')
                self.assertTrue((self.app/command[1]).is_file(), command)
            else:
                self.assertTrue((self.app/'scripts'/unit.replace('.timer', '.service')).is_file())
            self.assertNotIn('8515', target.read_text())
        mail = configparser.ConfigParser();mail.read(self.app/'scripts/casos-mail-scheduler.timer')
        self.assertEqual(mail['Timer']['OnCalendar'], '*-*-* 00:01:00')
        ldap = configparser.ConfigParser();ldap.read(self.app/'scripts/casos-ldap-sync.timer')
        self.assertEqual(ldap['Timer']['OnBootSec'], '5min')
        self.assertEqual(ldap['Timer']['OnUnitActiveSec'], '15min')

    def test_configure_creates_runtime_and_all_units_without_mutating_source(self):
        code = self.app/'dashboard/app.py'
        before = code.read_bytes()
        self.hook('postinst', 'configure')
        self.assertEqual((self.app/'data').stat().st_mode & 0o777, 0o700)
        self.assertEqual({p.name for p in (self.stage/'etc/systemd/system').iterdir()}, UNITS)
        self.assertEqual(code.read_bytes(), before)
        self.assertEqual(code.stat().st_mode & 0o777, 0o644)
        calls = self.calls()
        self.assertEqual(len([c for c in calls if c[0]=='useradd']), 1)
        self.assertEqual(len([c for c in calls if c[0]=='python3']), 1)
        self.assertIn(['chown', '-R', 'casos:casos', str(self.app/'data')], calls)
        restart = next(c for c in calls if c[:2]==['systemctl', 'restart'])
        self.assertEqual(set(restart[2:]), {'casos.service', 'casos-mcp.service', 'casos-ldap-sync.timer', 'casos-mail-scheduler.timer'})
        self.hook('postinst', 'configure')
        self.assertEqual(len([c for c in self.calls() if c[0]=='useradd']), 1)
        self.assertEqual(len([c for c in self.calls() if c[0]=='python3']), 1)

    def test_upgrade_and_remove_preserve_runtime_purge_only_default_data(self):
        expected = self.seed_data()
        neighbor = self.stage/'unrelated-data';neighbor.mkdir();(neighbor/'keep').write_text('untouched')
        self.hook('postinst', 'configure');self.clear_calls()
        self.hook('prerm', 'upgrade');self.hook('postrm', 'upgrade')
        self.assertEqual(self.data_bytes(), expected)
        self.assertFalse(any(c[:2]==['systemctl','disable'] for c in self.calls()))
        self.assertEqual({p.name for p in (self.stage/'etc/systemd/system').iterdir()}, UNITS)
        self.hook('postinst', 'configure')
        self.assertEqual(self.data_bytes(), expected)
        self.hook('prerm', 'remove');self.hook('postrm', 'remove')
        self.assertEqual(self.data_bytes(), expected)
        self.assertTrue((self.app/'venv').exists())
        self.assertEqual(list((self.stage/'etc/systemd/system').iterdir()), [])
        self.assertTrue(any(c[:2]==['systemctl','disable'] for c in self.calls()))
        self.hook('postrm', 'purge')
        self.assertFalse((self.app/'data').exists());self.assertFalse((self.app/'venv').exists())
        self.assertEqual((neighbor/'keep').read_text(), 'untouched')
        self.assertTrue(any(c[0]=='userdel' for c in self.calls()))

    def test_failed_dependencies_do_not_start_services_or_drop_existing_data(self):
        expected = self.seed_data()
        (self.stage/'fail-pip').touch()
        self.hook('postinst', 'configure', success=False)
        self.assertEqual(self.data_bytes(), expected)
        self.assertFalse(any(c[0]=='systemctl' for c in self.calls()))
        self.assertFalse((self.stage/'etc/systemd/system').exists())

    def test_isolated_hooks_require_stubs_before_any_system_action(self):
        shutil.rmtree(self.stubdir)
        for name, argument in (('postinst','configure'), ('prerm','remove'), ('postrm','purge')):
            with self.subTest(hook=name):
                result = self.hook(name, argument, success=False)
                self.assertIn('Missing isolated hook stub', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.app/'data').exists())
        self.assertFalse((self.stage/'etc').exists())

    def test_local_installer_passes_only_validated_package_to_stub_apt(self):
        apt = self.stubdir/'apt-get'
        apt.write_text('#!/usr/bin/python3\nimport json,os,pathlib,sys\npathlib.Path(os.environ["APT_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))\n')
        apt.chmod(0o755)
        capture = self.stage/'apt-call.json'
        env = {**self.env, 'PATH':str(self.stubdir)+os.pathsep+os.environ['PATH'], 'APT_CAPTURE':str(capture)}
        result = subprocess.run(['bash',str(ROOT/'packaging/install.sh'),str(self.package)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(capture.read_text()), ['install','--',str(self.package)])
        capture.unlink()
        result = subprocess.run(['bash',str(ROOT/'packaging/install.sh')],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertFalse(capture.exists())


if __name__ == '__main__':
    unittest.main()
