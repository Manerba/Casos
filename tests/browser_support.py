"""Local, isolated real-HTTP browser fixture. Never uses repo runtime data."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[1]


@contextmanager
def browser_server():
    with tempfile.TemporaryDirectory(prefix='casos-browser-') as directory:
        root = Path(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'CASOS_DATA_DIR': str(root / 'data'),
               'CASOS_LOG_FILE': str(root / 'security.log'), 'CASOS_TEST_PORT': str(port)}
        with (root / 'server.log').open('w+') as log:
            process = subprocess.Popen([sys.executable, str(REPO / 'tests/serve_browser_fixture.py')],
                                       cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                base = f'http://127.0.0.1:{port}'
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        with urlopen(base + '/login', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise TimeoutError('Isolated browser server did not start')
                identities = json.loads((root / 'data/test-identities.json').read_text())
                yield {'url': base, 'root': root, 'identities': identities}
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def browser_login(page, base, username='alice', password='Browser77!'):
    response = page.request.post(base + '/api/auth/login',
                                 data={'username': username, 'password': password},
                                 headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.ok, response.text()
    page.goto(base)
