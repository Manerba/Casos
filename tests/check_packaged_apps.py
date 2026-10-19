"""Build/extract a real DEB and start both packaged apps without installation.

Run: venv/bin/python tests/check_packaged_apps.py [--package /path/to/casos.deb]
Uses the existing Python interpreter/dependencies, NOT a fresh dependency
installation. No maintainer hook, apt, pip, systemd or production data is used.
"""
import argparse
import asyncio
import base64
import hashlib
import importlib.metadata
import io
import json
import os
import signal
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
CSRF = {'X-Requested-With': 'XMLHttpRequest'}
EXPECTED_TOOLS = {
    'whoami', 'get_agent_guide', 'issue.list', 'issue.get', 'issue.create', 'issue.update',
    'issue.delete', 'issue.patch_description', 'issue.editors.get', 'issue.editors.set',
    'issue.history', 'update.list', 'update.get', 'update.add', 'update.edit', 'update.delete',
    'attachment.list', 'attachment.add', 'attachment.read', 'attachment.delete', 'users.list', 'search',
}
BINARIES = (b'\x00\xffpackaged first\r\n\x80' * 137, bytes(range(256)) * 9 + b'packaged second\x00')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StaticAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {'src', 'href'} and value and value.startswith('/static/'):
                self.urls.add(value)


def json_response(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


@contextmanager
def packaged_apps(app_dir, sandbox, lifecycle):
    import httpx
    first, second = free_port(), free_port()
    while first == second:
        second = free_port()
    endpoints = {'main': f'http://127.0.0.1:{first}', 'mcp': f'http://127.0.0.1:{second}'}
    processes, logs = [], []
    data = sandbox / 'runtime-data'
    data.mkdir(mode=0o700)
    assert not list(data.iterdir())
    try:
        for kind, script in [('main', 'app.py'), ('mcp', 'mcp_app.py')]:
            log = (sandbox / f'{kind}.log').open('w+')
            logs.append(log)
            env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONUNBUFFERED': '1',
                   'CASOS_DATA_DIR': str(data), 'CASOS_HOST': '127.0.0.1',
                   'CASOS_PORT': str(first), 'CASOS_MCP_PORT': str(second),
                   'CASOS_LOG_FILE': str(sandbox / f'{kind}-security.log')}
            # Absolute extracted script + extracted cwd. No repository PYTHONPATH.
            command = [sys.executable, '-B', str(app_dir / 'dashboard' / script)]
            process = subprocess.Popen(command, cwd=app_dir, env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
        # Both writers are launched before readiness: concurrent fresh init.
        for (kind, base), process, log in zip(endpoints.items(), processes, logs):
            deadline = time.monotonic() + 30
            path = '/login' if kind == 'main' else '/.well-known/casos-agent.json'
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError('Packaged process exited: ' + log.read())
                    try:
                        if client.get(base + path).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.1)
                else:
                    raise TimeoutError('Packaged app did not become ready')
        lifecycle['parallel_start'] = True
        lifecycle['fresh_data_created'] = (data / 'casos.db').is_file()
        yield endpoints, data
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        lifecycle['returncodes'], lifecycle['graceful_shutdown'] = [], []
        for process, log in zip(processes, logs):
            try:
                code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait(timeout=5)
            log.seek(0)
            graceful = code in (0, -signal.SIGTERM) and 'Application shutdown complete.' in log.read()
            lifecycle['returncodes'].append(code)
            lifecycle['graceful_shutdown'].append(graceful)
            log.close()


async def call(client, tool, args=None):
    result = await client.call_tool(tool, args or {}, raise_on_error=False)
    assert not result.is_error, result
    return result.structured_content


async def exercise(endpoints, app_dir, version):
    import httpx
    from fastmcp import Client
    from PIL import Image
    main_url, mcp_url = endpoints['main'], endpoints['mcp']
    with httpx.Client(base_url=main_url, headers=CSRF, trust_env=False, timeout=20) as http:
        assert http.get('/api/issues').status_code == 401
        json_response(http.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'}))
        assert json_response(http.get('/api/auth/me'))['user']['id'] == 1
        assert json_response(http.get('/api/issues'))['total'] == 0
        assert json_response(http.get('/api/dashboard/info'))['version'] == version
        assert json_response(http.get('/api/admin/mail/config'))['config'] is None
        page = http.get('/')
        assert page.status_code == 200
        assets = StaticAssets()
        assets.feed(page.text)
        assert len(assets.urls) >= 8
        for url in assets.urls:
            response = http.get(url)
            assert response.status_code == 200, url
            file = app_dir / 'dashboard' / urlsplit(url).path.lstrip('/')
            assert file.read_bytes() == response.content, url
        token = json_response(http.post('/api/admin/mcp/tokens', json={'display_name': 'Packaged fixture agent'}))
        bearer = {'Authorization': 'Bearer ' + token['token']}
        async with Client(main_url + '/mcp/', auth=token['token'], timeout=15) as main, Client(mcp_url + '/mcp/', auth=token['token'], timeout=15) as dedicated:
            catalogs = [{tool.name for tool in await client.list_tools()} for client in (main, dedicated)]
            assert catalogs[0] == catalogs[1] == EXPECTED_TOOLS and len(catalogs[0]) == 22
            assert (await call(main, 'whoami'))['id'] == (await call(dedicated, 'whoami'))['id']
            created = await call(main, 'issue.create', {'title': 'Paketstart ü ✓', 'description': 'packagedissuenovember **Markdown**'})
            issue_id = created['issue_id']
            issue_path = f'/api/issues/{issue_id}'
            assert json_response(http.get(issue_path))['description'] == 'packagedissuenovember **Markdown**'
            update = await call(dedicated, 'update.add', {'issue_id': issue_id, 'content': 'packagedupdatenovember Unicode ü ✓'})
            assert (await call(main, 'update.get', {'issue_id': issue_id, 'update_id': update['update_id']}))['content'] == 'packagedupdatenovember Unicode ü ✓'
            first = await call(main, 'attachment.add', {'issue_id': issue_id, 'original_name': 'same.bin',
                'content': base64.b64encode(BINARIES[0]).decode()})
            second = json_response(http.post(mcp_url + issue_path + '/attachments', headers=bearer,
                files={'file': ('same.bin', BINARIES[1], 'application/octet-stream')}), 201)
            attachment_ids = [first['attachment_id'], second['id']]
            assert len(set(attachment_ids)) == 2
            for client in (main, dedicated):
                assert (await call(client, 'search', {'query': 'packagedissuenovember'}))['total'] == 1
                assert (await call(client, 'search', {'query': 'packagedupdatenovember'}))['total'] == 1
                listing = await call(client, 'attachment.list', {'issue_id': issue_id})
                assert listing['total'] == 2
                assert {item['original_name'] for item in listing['items']} == {'same.bin'}
                for index, attachment_id in enumerate(attachment_ids):
                    result = await call(client, 'attachment.read', {'issue_id': issue_id, 'attachment_id': attachment_id})
                    assert base64.b64decode(result['content']) == BINARIES[index]
            for base in (main_url, mcp_url):
                for index, attachment_id in enumerate(attachment_ids):
                    response = http.get(base + issue_path + f'/attachments/{attachment_id}/download', headers=bearer)
                    assert response.status_code == 200 and response.content == BINARIES[index]
            assert json_response(http.get('/api/search', params={'query': 'packagedupdatenovember'}))['total'] == 1
            # Actual preview subprocess must find the extracted worker and Pillow.
            picture = io.BytesIO()
            Image.new('RGB', (17, 11), '#216b80').save(picture, format='PNG')
            png = picture.getvalue()
            attached = json_response(http.post(issue_path + '/attachments', files={'file': ('package.png', png, 'image/png')}), 201)
            preview_path = issue_path + f'/attachments/{attached["id"]}/preview'
            assert json_response(http.get(preview_path))['kind'] == 'image'
            for base in (main_url, mcp_url):
                metadata = json_response(http.get(base + preview_path, headers=bearer))
                assert (metadata['width'], metadata['height']) == (17, 11)
                response = http.get(base + preview_path + '/image', headers=bearer)
                assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
                with Image.open(io.BytesIO(response.content)) as decoded:
                    assert decoded.size == (17, 11) and decoded.getpixel((0, 0)) == (33, 107, 128)
            # Dedicated service offers no web/admin/general REST surfaces.
            for path in ('/', '/login', '/api/issues', '/api/admin/mcp/config', '/static/js/app_core.js'):
                assert http.get(mcp_url + path).status_code == 404, path
            download_path = issue_path + f'/attachments/{attachment_ids[0]}/download'
            assert http.get(mcp_url + download_path).status_code == 401  # Browser cookie is insufficient.
            assert http.get(mcp_url + preview_path).status_code == 401
            assert http.get(download_path, headers={'Authorization': 'Bearer invalid'}).status_code == 401
            with httpx.Client(trust_env=False, timeout=10) as anonymous:
                assert anonymous.get(main_url + download_path).status_code == 401
                assert anonymous.get(main_url + issue_path, headers=bearer).status_code == 401
                assert anonymous.get(main_url + '/mcp/', cookies=http.cookies).status_code == 401
                for base in (main_url, mcp_url):
                    # Bearer writes still need the CSRF header, even on MCP REST.
                    response = anonymous.post(base + issue_path + '/attachments', headers=bearer,
                                              files={'file': ('rejected.bin', b'x', 'application/octet-stream')})
                    assert response.status_code == 403
        json_response(http.delete(f'/api/admin/mcp/tokens/{token["id"]}'))
        for base in (main_url, mcp_url):
            assert http.get(base + download_path, headers=bearer).status_code == 401
            assert http.get(base + '/mcp/', headers=bearer).status_code == 401
        assert json_response(http.get('/api/admin/mail/config'))['config'] is None
        return {'tool_count': len(EXPECTED_TOOLS), 'identical_catalogs': True, 'static_asset_count': len(assets.urls),
                'binary_sha256': [hashlib.sha256(raw).hexdigest() for raw in BINARIES],
                'png_dimensions': [17, 11], 'smtp_remained_unconfigured': True,
                'checks': ['parallel fresh startup of both extracted production scripts', 'HTTP login and exact packaged version/assets',
                           '22-tool catalogs and current identity on both real MCP mounts', 'cross-service Issue and Unicode Update',
                           'FTS Issue and Update search over REST and both MCP mounts', 'same-name binary attachments via MCP and dedicated REST, exact bytes on both services',
                           'actual extracted image preview worker on both services', 'cookie/Bearer/anonymous/CSRF restrictions and dedicated route isolation',
                           'token revocation on both services']}


def main(package=None, evidence_path=None):
    started = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix='casos-packaged-check-') as directory:
        sandbox = Path(directory)
        built_here = package is None
        if built_here:
            output = sandbox / 'artifacts'
            with (sandbox / 'build.log').open('w+') as log:
                result = subprocess.run([str(REPO / 'publish.sh'), '--build', str(output)], cwd=REPO,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=120)
                if result.returncode:
                    log.seek(0)
                    raise RuntimeError(log.read())
            packages = list(output.glob('casos_*.deb'))
            assert len(packages) == 1
            package = packages[0]
        else:
            package = Path(package).expanduser().resolve(strict=True)
            assert package.is_file()
        name = subprocess.check_output(['dpkg-deb', '--field', str(package), 'Package'], text=True).strip()
        version = subprocess.check_output(['dpkg-deb', '--field', str(package), 'Version'], text=True).strip()
        assert name == 'casos'
        package_hash = sha256(package)
        extracted = sandbox / 'extracted'
        subprocess.run(['dpkg-deb', '-x', str(package), str(extracted)], check=True, timeout=30)
        app_dir = extracted / 'opt/casos'
        assert (app_dir / 'version.txt').read_text().strip() == version
        assert not (app_dir / 'data').exists()
        assert not (app_dir / 'dashboard/admin_app.py').exists()
        assert not (app_dir / 'venv').exists()
        payload_before = {str(path.relative_to(extracted)): sha256(path) for path in extracted.rglob('*') if path.is_file()}
        lifecycle = {}
        with packaged_apps(app_dir, sandbox, lifecycle) as (endpoints, data):
            results = asyncio.run(exercise(endpoints, app_dir, version))
            assert (data / 'casos.db').is_file() and (data / 'secret.key').is_file()
        assert lifecycle['graceful_shutdown'] == [True, True], lifecycle
        payload_after = {str(path.relative_to(extracted)): sha256(path) for path in extracted.rglob('*') if path.is_file()}
        assert payload_after == payload_before, 'Packaged payload unexpectedly changed at runtime'
        evidence = {'project_id': 77, 'subtasks': [399, 400], 'result': 'passed',
                    'started_utc': started.isoformat(), 'completed_utc': datetime.now(timezone.utc).isoformat(),
                    'command': 'venv/bin/python tests/check_packaged_apps.py' + (' --package <existing-deb>' if not built_here else '') + (
                        ' --evidence ' + shlex.quote(str(evidence_path)) if evidence_path is not None else ''),
                    'package': {'name': name, 'version': version, 'sha256': package_hash, 'built_by_check': built_here,
                                'build_command': './publish.sh --build <temporary-artifact-directory>' if built_here else None,
                                'extraction': 'dpkg-deb -x into temporary directory; no installation/hooks',
                                'payload_file_count': len(payload_before), 'payload_unchanged_after_runtime': True},
                    'python': {'interpreter': sys.executable, 'version': sys.version.split()[0],
                               'dependencies': 'Existing repository venv; no fresh dependency installation was performed',
                               'selected_versions': {name: importlib.metadata.version(name) for name in ('fastapi', 'fastmcp', 'Pillow', 'extract-msg', 'striprtf')}},
                    'processes': {'source': 'Extracted /opt/casos/dashboard/app.py and mcp_app.py, executed directly',
                                  'cwd': 'Extracted /opt/casos', 'pythonpath_from_repository': False,
                                  'loopback_only': True, **lifecycle},
                    'results': results,
                    'isolation': {'temporary_data_only': True, 'real_mail_sent': False, 'smtp_configuration': None,
                                  'systemd_apt_pip_or_maintainer_hooks_executed': False, 'temporary_data_removed_after_check': True},
                    'not_executed': ['root installation of the DEB', 'maintainer hooks and real service activation',
                                     'fresh Python dependency download/install', 'upgrade/removal on a real host', 'real LDAP/SMTP/TLS integrations']}
    destination = (evidence_path or REPO / 'docs/project77-packaged-apps-evidence.json').expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'result': 'passed', 'package_version': version, 'package_sha256': package_hash,
                      'tool_count': results['tool_count'], 'evidence': str(destination)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, help='Use an existing DEB instead of building a temporary artifact')
    parser.add_argument('--evidence', type=Path, help='Write evidence JSON here instead of docs/project77-packaged-apps-evidence.json')
    arguments = parser.parse_args()
    main(arguments.package, arguments.evidence)
