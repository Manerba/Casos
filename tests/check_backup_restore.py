"""Real loopback, offline backup/restore of a completely isolated Casos instance.

Run: venv/bin/python tests/check_backup_restore.py
Both production ASGI apps run in child processes. Only SMTP connection/send is
replaced by a recording test transport. No systemd, real mail, runtime data or
external integrations are used. The complete data directory is copied only
with both writers stopped, then restored to a new empty directory.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import shlex
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
FAKE_PASSWORD = 'BackupCheck-FakeOnly-77!'
CSRF = {'X-Requested-With': 'XMLHttpRequest'}
BINARY_FILES = (b'\x00\xffCasos restore first\r\n\x80' * 113,
                bytes(range(256)) * 19 + b'\x00restore second')


def serve(kind):
    """Child-only adapter around the real main functions and test SMTP transport."""
    data = Path(os.environ['CASOS_DATA_DIR']).resolve()
    sandbox = Path(os.environ['CASOS_BACKUP_TEST_ROOT']).resolve()
    if sandbox not in data.parents or not sandbox.name.startswith('casos-backup-check-'):
        raise RuntimeError('Backup fixture requires its own temporary data directory')
    if os.environ.get('CASOS_HOST') != '127.0.0.1':
        raise RuntimeError('Backup fixture must bind only to loopback')
    from dashboard import mail_service

    def record(event, **values):
        with Path(os.environ['CASOS_BACKUP_TEST_MAIL_LOG']).open('a') as output:
            output.write(json.dumps({'event': event, **values}) + '\n')

    def connection(config):
        if config['password'] != FAKE_PASSWORD:
            return 'Test credential was not decrypted correctly'
        record('connection', decrypted=True)
        return None

    def send_mail(to_email, subject, html_body, text_body):
        config = mail_service.get_smtp_config()
        if config is None or config['password'] != FAKE_PASSWORD:
            return 'Test credential did not survive restore'
        record('send', decrypted=True, recipient=to_email)
        return None

    # Install before routers import these functions. Unexpected SMTP calls fail
    # instead of opening a connection, including in the dedicated MCP process.
    mail_service.test_smtp_connection = connection
    mail_service.send_mail = send_mail
    def forbid_smtp(*args, **kwargs):
        raise AssertionError('Real SMTP is forbidden in the backup fixture')
    import smtplib
    smtplib.SMTP = forbid_smtp
    smtplib.SMTP_SSL = forbid_smtp
    if kind == 'main':
        from dashboard.app import main
    else:
        from dashboard.mcp_app import main
    main()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            result.update(block)
    return result.hexdigest()


def tree_manifest(root):
    result = {'.': {'type': 'dir', 'mode': stat.S_IMODE(root.stat().st_mode)}}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink(), 'Unexpected symlink in isolated fixture'
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            result[str(path.relative_to(root))] = {'type': 'dir', 'mode': mode}
        else:
            assert path.is_file(), 'Unexpected special file in isolated fixture'
            result[str(path.relative_to(root))] = {'type': 'file', 'size': path.stat().st_size,
                                                  'mode': mode, 'sha256': digest(path)}
    return result


def assert_database(path):
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        return {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                for name in ('issues', 'issue_updates', 'attachments', 'audit_log')}


class Apps:
    def __init__(self, sandbox, data, phase):
        self.sandbox, self.data, self.phase = sandbox, data, phase
        self.processes = []
        self.logs = []
        self.returncodes = []
        self.graceful = []
        self.main = f'http://127.0.0.1:{free_port()}'
        self.dedicated = f'http://127.0.0.1:{free_port()}'
        while self.dedicated == self.main:
            self.dedicated = f'http://127.0.0.1:{free_port()}'
        self.mail_log = sandbox / (phase + '-mail.jsonl')

    def __enter__(self):
        import httpx
        try:
            for kind, base in [('main', self.main), ('mcp', self.dedicated)]:
                log = (self.sandbox / f'{self.phase}-{kind}.log').open('w+')
                self.logs.append(log)
                env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONUNBUFFERED': '1',
                       'CASOS_DATA_DIR': str(self.data), 'CASOS_HOST': '127.0.0.1',
                       'CASOS_PORT': base.rsplit(':', 1)[1], 'CASOS_MCP_PORT': base.rsplit(':', 1)[1],
                       'CASOS_LOG_FILE': str(self.sandbox / f'{self.phase}-{kind}-security.log'),
                       'CASOS_BACKUP_TEST_ROOT': str(self.sandbox),
                       'CASOS_BACKUP_TEST_MAIL_LOG': str(self.mail_log)}
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', kind],
                                           cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
                self.processes.append(process)
            # Launch both before readiness: exercise concurrent first startup,
            # the shared initialization lock and concurrent restart migrations.
            for (kind, base), process, log in zip([('main', self.main), ('mcp', self.dedicated)], self.processes, self.logs):
                deadline = time.monotonic() + 30
                ready_path = '/login' if kind == 'main' else '/.well-known/casos-agent.json'
                with httpx.Client(trust_env=False, timeout=1) as client:
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            log.seek(0)
                            raise RuntimeError('Isolated app exited: ' + log.read())
                        try:
                            if client.get(base + ready_path).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    else:
                        raise TimeoutError('Isolated ' + kind + ' app did not start')
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        # All clients/transport sessions close before this outer context exits.
        # Both processes are stopped before the caller can create a backup.
        problem = None
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
        for process, log in zip(self.processes, self.logs):
            try:
                result = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                problem = 'App did not stop gracefully; no backup may be taken'
                result = process.returncode
            self.returncodes.append(result)
            log.seek(0)
            completed = 'Application shutdown complete.' in log.read()
            # Uvicorn deliberately re-raises SIGTERM after graceful shutdown.
            graceful = result in (0, -signal.SIGTERM) and completed
            self.graceful.append(graceful)
            if not graceful:
                problem = problem or f'App did not confirm graceful shutdown (exit {result})'
        for log in self.logs:
            log.close()
        if problem and exc_type is None:
            raise AssertionError(problem)


def response_json(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


async def call(client, name, args=None, error=None):
    result = await client.call_tool(name, args or {}, raise_on_error=False)
    if error:
        assert result.is_error and result.structured_content['code'] == error, result
    else:
        assert not result.is_error, result
    return result.structured_content


async def populate(apps, http):
    from fastmcp import Client
    token = response_json(http.post('/api/admin/mcp/tokens', json={'display_name': 'Restore fixture agent'}))
    state = {'token': token['token'], 'token_id': token['id']}
    async with Client(apps.main + '/mcp/', auth=state['token'], timeout=15) as main, Client(apps.dedicated + '/mcp/', auth=state['token'], timeout=15) as dedicated:
        state['identity'] = await call(main, 'whoami')
        created = await call(main, 'issue.create', {'title': 'Offline restore ü ✓', 'description': 'restoreissuenovember original Markdown **source**'})
        state['issue_id'] = created['issue_id']
        update = await call(dedicated, 'update.add', {'issue_id': state['issue_id'], 'content': 'restoreupdatenovember chronological update ü ✓'})
        state['update_id'] = update['update_id']
        first = response_json(http.post(f'/api/issues/{state["issue_id"]}/attachments',
            files={'file': ('same-name.bin', BINARY_FILES[0], 'application/octet-stream')}), 201)
        second = await call(dedicated, 'attachment.add', {'issue_id': state['issue_id'], 'original_name': 'same-name.bin',
            'content': base64.b64encode(BINARY_FILES[1]).decode()})
        state['attachment_ids'] = [first['id'], second['attachment_id']]
        state['issue'] = await call(main, 'issue.get', {'issue_id': state['issue_id']})
        state['update'] = await call(dedicated, 'update.get', {'issue_id': state['issue_id'], 'update_id': state['update_id']})
        assert (await call(main, 'search', {'query': 'restoreupdatenovember'}))['total'] == 1
    return state


def setup_mail(http):
    config = {'smtp_server': 'smtp-backup.example.invalid', 'smtp_port': 587, 'encryption': 'starttls',
              'auth_enabled': True, 'username': 'backup-test-only', 'password': FAKE_PASSWORD,
              'from_address': 'casos-backup@example.invalid', 'from_name': 'Backup fixture'}
    response_json(http.post('/api/admin/mail/config', json=config))
    assert response_json(http.get('/api/admin/mail/config'))['config']['password'] == '********'
    response_json(http.post('/api/admin/mail/test', json={'to_email': 'nobody@example.invalid'}))
    response_json(http.put('/api/user/mail/preferences', json={'preferences': [
        {'event_type': 'new_update', 'enabled': False, 'days_before': 2}]}))


def read_credential(data):
    with closing(sqlite3.connect(data / 'casos.db')) as db:
        encrypted = db.execute('SELECT password FROM mail_config WHERE id=1').fetchone()[0]
    assert encrypted.startswith('gAAAAA') and encrypted != FAKE_PASSWORD
    # Use the same Fernet derivation; also verify through production decrypt in
    # the restarted process's get_smtp_config + fake test-mail transport below.
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256((data / 'secret.key').read_text().strip().encode()).digest())
    assert Fernet(key).decrypt(encrypted.encode()).decode() == FAKE_PASSWORD
    return encrypted


async def verify_snapshot(apps, http, state):
    from fastmcp import Client
    issue_id = state['issue_id']
    issue = response_json(http.get(f'/api/issues/{issue_id}'))
    for key in ('title', 'description', 'description_revision', 'status', 'created_by'):
        assert issue[key] == state['issue'][key], key
    update = response_json(http.get(f'/api/issues/{issue_id}/updates/{state["update_id"]}'))
    for key in ('content', 'revision', 'created_at', 'user_id'):
        assert update[key] == state['update'][key], key
    assert response_json(http.get('/api/search', params={'query': 'restoreissuenovember'}))['total'] == 1
    assert response_json(http.get('/api/search', params={'query': 'restoreupdatenovember'}))['total'] == 1
    items = response_json(http.get(f'/api/issues/{issue_id}/attachments'))['items']
    assert len(items) == 2 and {x['original_name'] for x in items} == {'same-name.bin'}
    async with Client(apps.main + '/mcp/', auth=state['token'], timeout=15) as main, Client(apps.dedicated + '/mcp/', auth=state['token'], timeout=15) as dedicated:
        for client in (main, dedicated):
            assert (await call(client, 'whoami'))['id'] == state['identity']['id']
            got = await call(client, 'issue.get', {'issue_id': issue_id})
            assert got['description_revision'] == state['issue']['description_revision']
            got_update = await call(client, 'update.get', {'issue_id': issue_id, 'update_id': state['update_id']})
            assert got_update['revision'] == state['update']['revision']
            assert (await call(client, 'search', {'query': 'restoreupdatenovember'}))['total'] == 1
            for index, attachment_id in enumerate(state['attachment_ids']):
                downloaded = await call(client, 'attachment.read', {'issue_id': issue_id, 'attachment_id': attachment_id})
                assert base64.b64decode(downloaded['content']) == BINARY_FILES[index]
        for base in (apps.main, apps.dedicated):
            for index, attachment_id in enumerate(state['attachment_ids']):
                response = http.get(base + f'/api/issues/{issue_id}/attachments/{attachment_id}/download',
                                    headers={'Authorization': 'Bearer ' + state['token']})
                assert response.status_code == 200 and response.content == BINARY_FILES[index]
    response_json(http.post('/api/admin/mail/test', json={'to_email': 'restored@example.invalid'}))
    assert response_json(http.get('/api/admin/mail/config'))['config']['password'] == '********'
    prefs = response_json(http.get('/api/user/mail/preferences'))['preferences']
    assert next(x for x in prefs if x['event_type'] == 'new_update')['enabled'] == 0


async def write_after_restore(apps, http, state):
    from fastmcp import Client
    issue_id = state['issue_id']
    old_revision = state['issue']['description_revision']
    response_json(http.put(f'/api/issues/{issue_id}', json={'description': 'restorenewwrite HTTP revision', 'description_revision': old_revision}))
    conflict = http.put(f'/api/issues/{issue_id}', json={'description': 'must not overwrite', 'description_revision': old_revision})
    assert conflict.status_code == 409 and conflict.json()['code'] == 'revision_conflict'
    current = response_json(http.get(f'/api/issues/{issue_id}'))
    async with Client(apps.dedicated + '/mcp/', auth=state['token'], timeout=15) as client:
        await call(client, 'issue.patch_description', {'issue_id': issue_id, 'revision': current['description_revision'],
            'operation': 'append', 'text': '\nMCP write after offline restore'})
        args = {'issue_id': issue_id, 'update_id': state['update_id'], 'content': 'restoreeditedupdate changed after restore', 'revision': state['update']['revision']}
        await call(client, 'update.edit', args)
        await call(client, 'update.edit', args, error='revision_conflict')
        created = await call(client, 'issue.create', {'title': 'New issue after restore', 'description': 'New records remain writable'})
        state['new_issue_id'] = created['issue_id']
    new = response_json(http.post(f'/api/issues/{issue_id}/attachments',
        files={'file': ('same-name.bin', b'new after restore\x00\xfe', 'application/octet-stream')}), 201)
    state['new_attachment_id'] = new['id']
    state['new_issue'] = response_json(http.get(f'/api/issues/{issue_id}'))
    assert 'MCP write after offline restore' in state['new_issue']['description']
    state['new_update'] = response_json(http.get(f'/api/issues/{issue_id}/updates/{state["update_id"]}'))
    assert state['new_issue']['description_revision'] != old_revision
    assert state['new_update']['revision'] != state['update']['revision']
    assert response_json(http.get('/api/search', params={'query': 'restoreeditedupdate'}))['total'] == 1
    assert response_json(http.get('/api/search', params={'query': 'restoreupdatenovember'}))['total'] == 0


async def verify_second_restart(apps, http, state):
    from fastmcp import Client
    issue_id = state['issue_id']
    assert response_json(http.get(f'/api/issues/{issue_id}'))['description_revision'] == state['new_issue']['description_revision']
    assert response_json(http.get(f'/api/issues/{issue_id}/updates/{state["update_id"]}'))['revision'] == state['new_update']['revision']
    response_json(http.get(f'/api/issues/{state["new_issue_id"]}'))
    for base in (apps.main, apps.dedicated):
        async with Client(base + '/mcp/', auth=state['token'], timeout=15) as client:
            result = await call(client, 'attachment.read', {'issue_id': issue_id, 'attachment_id': state['new_attachment_id']})
            assert base64.b64decode(result['content']) == b'new after restore\x00\xfe'
            assert (await call(client, 'search', {'query': 'restoreeditedupdate'}))['total'] == 1
    response_json(http.delete(f'/api/admin/mcp/tokens/{state["token_id"]}'))
    for base in (apps.main, apps.dedicated):
        bearer = {'Authorization': 'Bearer ' + state['token']}
        assert http.get(base + f'/api/issues/{issue_id}/attachments/{state["attachment_ids"][0]}/download', headers=bearer).status_code == 401
        assert http.get(base + '/mcp/', headers=bearer).status_code == 401


def main(evidence_path=None):
    import httpx
    started = datetime.now(timezone.utc)
    checked_worktree_dirty = bool(subprocess.check_output(
        ['git', 'status', '--porcelain'], cwd=REPO, text=True).strip())
    with tempfile.TemporaryDirectory(prefix='casos-backup-check-') as directory:
        sandbox = Path(directory)
        data = sandbox / 'original-data'
        data.mkdir(mode=0o700)
        assert not list(data.iterdir())
        with Apps(sandbox, data, 'fresh') as original:
            with httpx.Client(base_url=original.main, headers=CSRF, trust_env=False, timeout=20) as http:
                response_json(http.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'}))
                assert response_json(http.get('/api/issues'))['total'] == 0
                state = asyncio.run(populate(original, http))
                setup_mail(http)
                cookie = http.cookies.get('casos_session')
                assert cookie
        assert original.graceful == [True, True]
        assert all(process.poll() is not None for process in original.processes)
        before_counts = assert_database(data / 'casos.db')
        encrypted = read_credential(data)
        assert stat.S_IMODE((data / 'secret.key').stat().st_mode) == 0o600
        source_manifest = tree_manifest(data)
        assert 'casos.db' in source_manifest and 'secret.key' in source_manifest
        attachment_files = [p for p in source_manifest if p.startswith('attachments/') and len(Path(p).name) == 32]
        assert len(attachment_files) == 2
        backup = sandbox / 'offline-backup'
        shutil.copytree(data, backup, copy_function=shutil.copy2)
        assert tree_manifest(backup) == source_manifest
        restored = sandbox / 'restored-data'
        restored.mkdir(mode=0o700)
        assert not list(restored.iterdir())
        shutil.copytree(backup, restored, dirs_exist_ok=True, copy_function=shutil.copy2)
        assert tree_manifest(restored) == source_manifest
        assert read_credential(restored) == encrypted
        assert assert_database(restored / 'casos.db') == before_counts
        with Apps(sandbox, restored, 'restored') as apps:
            with httpx.Client(base_url=apps.main, headers=CSRF, cookies={'casos_session': cookie}, trust_env=False, timeout=20) as http:
                # Saved signed browser session demonstrates secret.key continuity.
                assert response_json(http.get('/api/auth/me'))['user']['id'] == 1
                asyncio.run(verify_snapshot(apps, http, state))
                asyncio.run(write_after_restore(apps, http, state))
        assert apps.graceful == [True, True]
        after_counts = assert_database(restored / 'casos.db')
        assert after_counts['issues'] == before_counts['issues'] + 1
        assert after_counts['attachments'] == before_counts['attachments'] + 1
        assert after_counts['audit_log'] > before_counts['audit_log']
        with Apps(sandbox, restored, 'second-restart') as restarted:
            with httpx.Client(base_url=restarted.main, headers=CSRF, cookies={'casos_session': cookie}, trust_env=False, timeout=20) as http:
                # Also exercise a fresh login after restoring password hashes.
                response_json(http.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'}))
                asyncio.run(verify_second_restart(restarted, http, state))
        assert restarted.graceful == [True, True]
        assert_database(restored / 'casos.db')
        source_mail = [json.loads(line) for line in original.mail_log.read_text().splitlines()]
        restored_mail = [json.loads(line) for line in apps.mail_log.read_text().splitlines()]
        assert any(x['event'] == 'connection' and x['decrypted'] for x in source_mail)
        assert any(x['event'] == 'send' and x['decrypted'] for x in restored_mail)
        evidence = {
            'project_id': 77, 'subtask_id': 399, 'result': 'passed',
            'started_utc': started.isoformat(), 'completed_utc': datetime.now(timezone.utc).isoformat(),
            'command': 'venv/bin/python tests/check_backup_restore.py' + (
                ' --evidence ' + shlex.quote(str(evidence_path)) if evidence_path is not None else ''),
            'checked_worktree_dirty': checked_worktree_dirty,
            'checked_worktree_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
            'checked_worktree_version': (REPO / 'version.txt').read_text().strip(),
            'processes': {'apps': ['dashboard.app', 'dashboard.mcp_app'], 'binding': '127.0.0.1 only', 'startup': 'Both processes launched before either readiness check, in all three phases',
                          'fresh_shutdown': original.returncodes, 'restored_shutdown': apps.returncodes,
                          'second_restart_shutdown': restarted.returncodes, 'all_shutdowns_confirmed_in_logs': all(original.graceful + apps.graceful + restarted.graceful)},
            'backup': {'method': 'Complete offline copy after both app processes exited cleanly; restore into new empty directory',
                       'full_manifest_equal_before_start': True, 'copied_file_count': sum(x['type'] == 'file' for x in source_manifest.values()),
                       'sqlite_snapshot_sha256': source_manifest['casos.db']['sha256'],
                       'wal_shm_files_present_in_snapshot': [p for p in source_manifest if p.endswith(('-wal', '-shm'))],
                       'secret_file_equal': True, 'secret_mode': '0600', 'directory_modes_preserved': True,
                       'encrypted_fake_smtp_credential_equal_and_decryptable': True},
            'checks': ['parallel fresh initialization and restarts of both real apps', 'SQLite integrity_check and foreign_key_check before/after restore and after second restart',
                       'two same-name binary attachments with distinct IDs and exact bytes over both HTTP services and both MCP mounts',
                       'Issue/update content, authors, IDs and revisions preserved', 'FTS Issue/update hits preserved and updated after new writes',
                       'saved signed cookie and fresh login after restore', 'MCP identity and token preserved across both restarts',
                       'encrypted fake SMTP credential works through production get_smtp_config/decrypt after restore',
                       'mail preference opt-out preserved', 'REST and MCP revision conflicts still reject stale writes',
                       'new Issue/update changes/attachment/audit persist through second restart', 'token revocation blocks both services after restore'],
            'fixture_attachment_sha256': [hashlib.sha256(raw).hexdigest() for raw in BINARY_FILES],
            'rows_before_backup': before_counts, 'rows_after_restored_writes': after_counts,
            'isolation': {'temporary_data_only': True, 'real_smtp': False, 'systemd_or_production_services_used': False,
                          'mail_transport': 'in-process recording fake; unexpected smtplib calls raise',
                          'temporary_data_removed_after_check': True},
            'not_executed': ['production service stop/start', 'real SMTP/LDAP network traffic', 'external TLS key/certificate backup',
                             'cross-host OS account ownership migration', 'live concurrent-writer backup']}
    destination = (evidence_path or REPO / 'docs/project77-backup-evidence.json').expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'result': 'passed', 'evidence': str(destination), 'copied_files': evidence['backup']['copied_file_count'],
                      'checks': len(evidence['checks'])}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', choices=['main', 'mcp'], help=argparse.SUPPRESS)
    parser.add_argument('--evidence', type=Path, help='Write evidence JSON here instead of docs/project77-backup-evidence.json')
    arguments = parser.parse_args()
    if arguments.serve:
        serve(arguments.serve)
    else:
        main(arguments.evidence)
