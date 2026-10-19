"""Issue routes through the real app, session validation and CSRF middleware."""
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from dashboard import auth, database, mcp_transport
from dashboard.app import app


class IssueHTTPTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='casos-issue-http-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for module, key, value in (
            (database, 'DB_DIR', root), (database, 'DB_PATH', root / 'casos.db'),
            (auth, 'SECRET_KEY_PATH', root / 'secret.key'),
            (mcp_transport, 'setup_security_logger', lambda: None),
        ):
            p = patch.object(module, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self):
        response = self.client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'},
                                    headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(response.status_code, 200, response.text)

    def test_real_session_csrf_and_description_conflict(self):
        self.assertEqual(self.client.get('/api/issues').status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/issues', json={'title': 'Denied'}).status_code, 403)
        self.client.headers['X-Requested-With'] = 'XMLHttpRequest'
        response = self.client.post('/api/issues', json={'title': 'HTTP', 'description': 'original'})
        self.assertEqual(response.status_code, 201, response.text)
        issue = response.json()
        url = f'/api/issues/{issue["id"]}'
        first = self.client.put(url, json={'description': 'winner', 'description_revision': issue['description_revision']})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.put(url, json={'description': 'loser', 'description_revision': issue['description_revision']})
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(second.json()['code'], 'revision_conflict')
        self.assertEqual(self.client.get(url).json()['description'], 'winner')
        self.assertIn("object-src 'none'", response.headers['Content-Security-Policy'])

    def test_deactivation_revokes_existing_browser_session(self):
        self.login()
        with closing(database.get_db()) as db, db:
            db.execute('UPDATE users SET is_active=0 WHERE id=1')
        self.assertEqual(self.client.get('/api/issues').status_code, 401)
        self.assertEqual(self.client.get('/', follow_redirects=False).status_code, 302)

    def test_removed_endpoints_do_not_fall_through_to_spa(self):
        self.login()
        for path in ('/api/tasks', '/api/areas', '/editor', '/text-editor', '/handoff', '/aufgaben'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == '__main__':
    unittest.main()
