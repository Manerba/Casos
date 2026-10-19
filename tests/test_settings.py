"""Settings on the real main app, with isolated DB/secrets and fake transports."""
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from dashboard import auth, database, tls_utils
from dashboard.app import app
from dashboard import api_ldap, api_mail, issue_service


class SettingsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='casos-settings-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for module, name, value in ((database,'DB_DIR',self.root), (database,'DB_PATH',self.root/'casos.db'), (auth,'SECRET_KEY_PATH',self.root/'secret.key')):
            patcher=patch.object(module,name,value);patcher.start();self.addCleanup(patcher.stop)
        database.init_db()
        with closing(database.get_db()) as db, db:
            self.reader=db.execute("INSERT INTO users(username,password_hash) VALUES('reader','')").lastrowid
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.headers={'X-Requested-With':'XMLHttpRequest'}
        self.sign_in(1)

    def sign_in(self, uid):
        self.client.cookies.clear()
        self.client.cookies.set(auth.COOKIE_NAME,auth.sign_token(auth.create_session(uid)))

    def test_all_admin_sections_are_session_and_admin_protected(self):
        endpoints=['/api/admin/users','/api/admin/app/config','/api/admin/ldap/config','/api/admin/mail/config','/api/admin/mail/templates','/api/admin/tls/config','/api/admin/tls/verify','/api/admin/mcp/config','/api/admin/mcp/tokens','/api/admin/mcp/audit']
        for endpoint in endpoints:
            with self.subTest(admin=endpoint): self.assertEqual(self.client.get(endpoint).status_code,200)
        self.sign_in(self.reader)
        for endpoint in endpoints:
            with self.subTest(reader=endpoint): self.assertEqual(self.client.get(endpoint).status_code,403)
        self.assertEqual(self.client.get('/api/user/mail/preferences').status_code,200)
        self.client.cookies.clear()
        for endpoint in endpoints:
            with self.subTest(anonymous=endpoint): self.assertEqual(self.client.get(endpoint).status_code,401)

    def test_csrf_on_admin_writes_and_restart_without_service_execution(self):
        operations=[('POST','/api/admin/users',{}),('POST','/api/admin/app/config',{}),('POST','/api/admin/ldap/config',{}),('POST','/api/admin/mail/config',{}),('POST','/api/admin/tls/verify',{}),('POST','/api/admin/mcp/tokens',{}),('POST','/api/dashboard/restart',{})]
        with patch('dashboard.app.subprocess.Popen') as process:
            for method,url,body in operations:
                with self.subTest(url=url): self.assertEqual(self.client.request(method,url,json=body).status_code,403)
            process.assert_not_called()
            self.assertEqual(self.client.post('/api/dashboard/restart',headers=self.headers).status_code,200)
            self.assertEqual(process.call_args.args[0],['systemctl','restart','casos.service','casos-mcp.service'])

    def test_current_admin_and_active_state_apply_to_existing_session(self):
        with closing(database.get_db()) as db, db: db.execute('UPDATE users SET is_admin=0 WHERE id=1')
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        with closing(database.get_db()) as db, db: db.execute('UPDATE users SET is_admin=1,is_active=0 WHERE id=1')
        self.assertEqual(self.client.get('/api/admin/users').status_code,401)

    def test_app_configuration_is_immediately_visible_and_audited(self):
        response=self.client.post('/api/admin/app/config',headers=self.headers,json={'server_address':'https://casos.example.invalid/'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/admin/app/config').json()['config']['server_address'],'casos.example.invalid')
        self.assertEqual(self.client.post('/api/admin/app/config',headers=self.headers,json={'server_address':'   '}).status_code,400)
        with closing(database.get_db()) as db:
            audit=db.execute("SELECT actor_user_id,entity_type FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(tuple(audit),(1,'app_config'))

    def test_ldap_secret_masking_retains_secret_and_delete_deactivates(self):
        config={'server':'ldap.example.invalid','port':636,'use_ssl':1,'bind_dn':'cn=bind','bind_password':'secret-do-not-audit','search_base':'dc=example','sync_interval_minutes':30}
        with patch.object(api_ldap,'test_connection',return_value=(True,None)) as transport:
            response=self.client.post('/api/admin/ldap/config',headers=self.headers,json=config)
            self.assertEqual(response.status_code,200,response.text)
            returned=self.client.get('/api/admin/ldap/config').json()['config']
            self.assertEqual(returned['bind_password'],'********')
            config['bind_password']='********'
            self.assertEqual(self.client.post('/api/admin/ldap/config',headers=self.headers,json=config).status_code,200)
            self.assertEqual(transport.call_args.args[4],'secret-do-not-audit')
        with closing(database.get_db()) as db, db:
            stored=db.execute('SELECT bind_password FROM ldap_config').fetchone()[0]
            self.assertTrue(stored.startswith('gAAAAA'))
            self.assertNotIn('secret-do-not-audit',' '.join(r[0] or '' for r in db.execute('SELECT changes_json FROM audit_log')))
            db.execute("UPDATE users SET auth_source='ldap' WHERE id=?",(self.reader,))
        self.assertEqual(self.client.delete('/api/admin/ldap/config',headers=self.headers).status_code,200)
        with closing(database.get_db()) as db: self.assertEqual(db.execute('SELECT is_active FROM users WHERE id=?',(self.reader,)).fetchone()[0],0)

    def test_mail_secret_and_preferences_with_fake_transport(self):
        config={'smtp_server':'smtp.example.invalid','from_address':'test@example.invalid','username':'tester','password':'mail-secret'}
        with patch.object(api_mail,'test_smtp_connection',return_value=None):
            self.assertEqual(self.client.post('/api/admin/mail/config',headers=self.headers,json=config).status_code,200)
            self.assertEqual(self.client.get('/api/admin/mail/config').json()['config']['password'],'********')
        self.sign_in(self.reader)
        response=self.client.put('/api/user/mail/preferences',headers=self.headers,json={'preferences':[{'event_type':'new_update','enabled':False,'days_before':2}]})
        self.assertEqual(response.status_code,200,response.text)
        prefs=self.client.get('/api/user/mail/preferences').json()['preferences']
        self.assertFalse(next(p['enabled'] for p in prefs if p['event_type']=='new_update'))

    def test_tls_options_and_current_database_path(self):
        self.assertEqual(tls_utils.get_tls_verify_config(),{'verify_smtp':False,'verify_ldap':False})
        response=self.client.post('/api/admin/tls/verify',headers=self.headers,json={'verify_smtp':1,'verify_ldap':1})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(tls_utils.get_tls_verify_config(),{'verify_smtp':True,'verify_ldap':True})
        self.assertEqual(self.client.post('/api/admin/tls/verify',headers=self.headers,json={'verify_nextcloud':1}).status_code,422)
        cert=self.root/'bad.pem';key=self.root/'bad.key'
        cert.write_text('-----BEGIN CERTIFICATE-----\nnot-a-certificate');key.write_text('-----BEGIN PRIVATE KEY-----\nbad')
        result=self.client.post('/api/admin/tls/validate',headers=self.headers,json={'cert_path':str(cert),'key_path':str(key)}).json()
        self.assertFalse(result['valid'])
        self.assertIsNone(tls_utils.get_tls_config())

    def test_user_management_preserves_issue_and_cannot_expose_password(self):
        response=self.client.post('/api/admin/users',headers=self.headers,json={'username':'writer','password':'four-or-more'})
        self.assertEqual(response.status_code,200,response.text)
        uid=response.json()['id']
        issue=issue_service.create_issue({'title':'Keep issue after deleting user'}, {'id':uid})
        token=auth.sign_token(auth.create_session(uid))
        response=self.client.put(f'/api/admin/users/{uid}',headers=self.headers,json={'is_active':0})
        self.assertEqual(response.status_code,200,response.text)
        with TestClient(app) as inactive:
            inactive.cookies.set(auth.COOKIE_NAME,token)
            self.assertEqual(inactive.get('/api/issues').status_code,401)
        self.assertEqual(self.client.delete(f'/api/admin/users/{uid}',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get(f'/api/issues/{issue["id"]}').status_code,200)
        with closing(database.get_db()) as db:
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertNotIn('four-or-more',' '.join(r[0] or '' for r in db.execute('SELECT changes_json FROM audit_log')))


if __name__=='__main__': unittest.main()
