"""AD transport fixtures exercise filters, binary SIDs and real Issue transactions."""
import sqlite3
from contextlib import closing
from unittest.mock import Mock, patch

from ldap3 import Connection, MOCK_SYNC, NONE, Server

from dashboard import ad_directory as directory, api_issues, database, issue_service
from dashboard.crypto_utils import encrypt
from dashboard.errors import ApplicationError
from dashboard.issue_history_service import list_history
from tests.attachment_test_helpers import AttachmentTestCase

SID = 'S-1-5-21-111-222-333-1001'
OTHER_SID = 'S-1-5-21-111-222-333-1002'
PERSON = {'sid': SID, 'username': 'emeyer', 'full_name': 'Eva Meyer'}


class ADPeopleTests(AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.app.include_router(api_issues.router)
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO ldap_config(id,server,bind_dn,bind_password,search_base,group_dn) VALUES(1,'ad.example.invalid','service',?,'OU=Login,DC=example,DC=invalid','CN=Casos,OU=Login,DC=example,DC=invalid')", (encrypt('fixture-only'),))
            db.execute('INSERT INTO tls_verify_config(id,verify_ldap) VALUES(1,1)')
        self.entries = [
            {'sid': SID, 'sAMAccountName': 'emeyer', 'givenName': 'Eva', 'sn': 'Meyer', 'displayName': 'Eva Meyer'},
            {'sid': OTHER_SID, 'sAMAccountName': 'max', 'givenName': 'Max', 'sn': 'Muster', 'displayName': ''},
        ]
        self.connections = []
        self.server = Mock(side_effect=lambda *a, **kw: Server('ad.example.invalid', get_info=NONE))
        self.bind = Mock(side_effect=self.connection)
        self.patch(directory, '_create_server', self.server)
        self.patch(directory, '_bind_connection', self.bind)

    def connection(self, server, *args, **kwargs):
        conn = Connection(server, client_strategy=MOCK_SYNC)
        for entry in self.entries:
            attributes = {key: value for key, value in entry.items() if key not in ('sid', 'kind') and value}
            attributes.update(objectSid=directory.sid_bytes(entry['sid']),
                              objectClass=['top', 'person', entry.get('kind', 'user')],
                              objectCategory='person' if entry.get('kind') != 'computer' else 'computer')
            conn.strategy.add_entry(f"CN={entry['sid']},OU=People,DC=example,DC=invalid", attributes)
        conn.bind()
        self.connections.append(conn)
        return conn

    def test_search_first_last_login_and_full_name_outside_login_group(self):
        for query in ('eva', 'MEYER', 'emey', 'Eva Meyer'):
            with self.subTest(query=query):
                self.assertEqual(directory.search_people(query, self.users['reader'])['items'], [PERSON])
        self.assertEqual(directory.search_people('Muster', self.users['reader'])['items'][0]['full_name'], 'Max Muster')
        self.assertTrue(self.server.call_args.kwargs['verify_cert'])
        self.assertEqual(self.bind.call_args.args[2], 'fixture-only')
        self.assertTrue(all(not conn.bound for conn in self.connections))
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ad_people').fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT id FROM users WHERE username='emeyer'").fetchone())

    def test_search_excludes_contacts_computers_and_escapes_wildcards(self):
        self.entries.extend([
            {'sid': SID[:-1]+'3', 'sAMAccountName': 'evacomputer', 'givenName': 'Eva', 'kind': 'computer'},
            {'sid': SID[:-1]+'4', 'sAMAccountName': 'evacontact', 'givenName': 'Eva', 'kind': 'contact'},
        ])
        self.assertEqual(directory.search_people('Eva', self.users['reader'])['items'], [PERSON])
        # ldap3 MOCK_SYNC reconstructs escaped parentheses as filter syntax.
        # Inspect the outgoing assertion instead of relying on that mock bug.
        with patch.object(directory, '_lookup', return_value={'items':[]}) as lookup:
            directory.search_people('*)(objectClass=*)', self.users['reader'])
            search_filter = lookup.call_args.args[1]
            self.assertNotIn('(objectClass=*)', search_filter)
            self.assertIn(r'(givenName=*\2a\29\28objectClass=\2a\29*)', search_filter)
            directory.search_people('*', self.users['reader'])
            self.assertIn(r'(sAMAccountName=*\2a*)', lookup.call_args.args[1])

    def test_binary_sid_roundtrip_and_invalid_values(self):
        self.assertEqual(directory._sid_text(directory.sid_bytes(SID)), SID)
        self.assertEqual(directory.resolve_person(SID, self.users['reader']), PERSON)
        for value in (True, 7, '', 's-1-5-21', 'S-1-05-21', 'S-1-5-4294967296', 'S-1-281474976710656-1', SID+'*)(x=y)'):
            with self.subTest(value=value), self.assertRaises(ApplicationError):
                directory.sid_bytes(value)
        with self.assertRaises(ApplicationError) as error:
            directory.resolve_person(SID[:-1]+'9', self.users['reader'])
        self.assertEqual(error.exception.code, 'ad_person_not_found')

    def test_no_configuration_and_invalid_input_do_not_contact_directory(self):
        for query in ('', ' ', 'x'*201, '\ud800', '\x00'):
            with self.subTest(query=repr(query)), self.assertRaises(ApplicationError):
                directory.search_people(query, self.users['reader'])
        for offset, limit in ((-1,50), (True,50), (0,101), (0,False)):
            with self.assertRaises(ApplicationError):
                directory.search_people('Eva', self.users['reader'], offset, limit)
        with closing(database.get_db()) as db, db:
            db.execute('DELETE FROM ldap_config')
        with self.assertRaises(ApplicationError) as error:
            directory.search_people('Eva', self.users['reader'])
        self.assertEqual(error.exception.code, 'ad_not_configured')
        self.bind.assert_not_called()

    def test_pagination_passes_ad_page_boundaries_without_losing_matches(self):
        self.entries = [{'sid': f'S-1-5-21-111-222-333-{i+1000}', 'sAMAccountName': f'match{i}'} for i in range(207)]
        offset, collected = 0, []
        while offset is not None:
            result = directory.search_people('match', self.users['reader'], offset, 50)
            collected.extend(item['sid'] for item in result['items'])
            offset = result['next_offset']
        self.assertEqual(len(collected), 207)
        self.assertEqual(len(set(collected)), 207)

    def test_errors_never_leak_ldap_details_and_recheck_active_user(self):
        self.bind.side_effect = RuntimeError('secret-password ldap://private-host CN=Private')
        with self.assertRaises(ApplicationError) as error:
            directory.search_people('Eva', self.users['reader'])
        self.assertEqual(error.exception.detail, 'adPeople.unavailable')
        self.bind.side_effect = self.connection
        def deactivate(*args):
            with closing(database.get_db()) as db, db:
                db.execute('UPDATE users SET is_active=0 WHERE id=?', (self.users['reader']['id'],))
            return {'items': [PERSON]}
        with patch.object(directory, '_lookup', side_effect=deactivate), self.assertRaises(ApplicationError) as error:
            directory.search_people('Eva', self.users['reader'])
        self.assertEqual(error.exception.status_code, 401)

    def test_rest_requires_auth_and_csrf_and_does_not_trust_client_names(self):
        self.assertEqual(self.client.get('/api/ad/people?query=Eva').status_code, 401)
        self.bind.assert_not_called()
        headers = self.headers('owner')
        response = self.client.get('/api/ad/people?query=Eva', headers=headers)
        self.assertEqual(response.json()['items'], [PERSON])
        self.assertEqual(self.client.post('/api/issues', headers=self.headers('owner', csrf=False), json={'title':'Denied', 'affected_person_sid':SID}).status_code, 403)
        response = self.client.post('/api/issues', headers=headers, json={'title':'With contact', 'affected_person_sid':SID})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['affected_person'], PERSON)
        response = self.client.put(f'/api/issues/{self.issue_id}', headers=headers,
                                   json={'affected_person_sid':SID, 'affected_person':{'username':'forged'}})
        self.assertEqual(response.status_code, 422)

    def test_cache_survives_offline_reads_and_never_creates_accounts_or_rights(self):
        with closing(database.get_db()) as db:
            before_users = [tuple(row) for row in db.execute('SELECT * FROM users')]
        result = issue_service.update_issue(self.issue_id, {'affected_person_sid':SID}, self.users['editor'])
        self.assertEqual(result['affected_person'], PERSON)
        self.assertEqual(result['assigned_to'], self.users['assignee']['id'])
        self.bind.reset_mock(); self.bind.side_effect = AssertionError('Reads must never use LDAP')
        with closing(database.get_db()) as db, db:
            db.execute('DELETE FROM ldap_config')
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM users')], before_users)
        read = issue_service.get_issue(self.issue_id, self.users['reader'])
        self.assertEqual(read['affected_person'], PERSON)
        self.assertFalse(read['permissions']['can_edit'])
        self.assertEqual(issue_service.list_issues(self.users['reader'])['items'][0]['affected_person'], PERSON)
        updated = issue_service.update_issue(self.issue_id, {'title':'Offline'}, self.users['editor'])
        self.assertEqual(updated['affected_person'], PERSON)
        cleared = issue_service.update_issue(self.issue_id, {'affected_person_sid':None}, self.users['editor'])
        self.assertIsNone(cleared['affected_person'])
        self.bind.assert_not_called()

    def test_sid_identifies_renames_and_identical_names_remain_distinct(self):
        first = issue_service.create_issue({'title':'First', 'affected_person_sid':SID}, self.users['owner'])
        self.entries[0].update(sAMAccountName='renamed', displayName='Eva Renamed')
        second = issue_service.create_issue({'title':'Second', 'affected_person_sid':SID}, self.users['owner'])
        self.assertEqual(issue_service.get_issue(first['id'], self.users['reader'])['affected_person'], second['affected_person'])
        self.entries[0].update(displayName='Eva Renamed Again')
        refreshed = issue_service.update_issue(first['id'], {'affected_person_sid':SID}, self.users['owner'])
        self.assertEqual(refreshed['affected_person']['full_name'], 'Eva Renamed Again')
        with closing(database.get_db()) as db:
            self.assertIn('affected_person_cache', db.execute('SELECT changes_json FROM audit_log ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.entries[1].update(sAMAccountName='renamed', displayName='Eva Renamed')
        issue_service.update_issue(first['id'], {'affected_person_sid':OTHER_SID}, self.users['owner'])
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ad_people').fetchone()[0], 2)
        history = list_history(first['id'], self.users['reader'])['items']
        self.assertEqual(history[-1]['new_label'], 'Eva Meyer (emeyer)')
        self.assertEqual(history[0]['old_value'], SID)
        self.assertEqual(history[0]['new_value'], OTHER_SID)

    def test_lookup_failure_and_lost_edit_rights_leave_issue_and_cache_untouched(self):
        with self.assertRaises(ApplicationError):
            issue_service.update_issue(self.issue_id, {'title':'Lost', 'affected_person_sid':SID}, self.users['reader'])
        self.bind.assert_not_called()
        def revoke(*args):
            with closing(database.get_db()) as db, db:
                db.execute('DELETE FROM issue_editors WHERE issue_id=?', (self.issue_id,))
            return PERSON
        with patch.object(directory, 'resolve_person', side_effect=revoke), self.assertRaises(ApplicationError):
            issue_service.update_issue(self.issue_id, {'title':'Lost', 'affected_person_sid':SID}, self.users['editor'])
        self.bind.side_effect = RuntimeError('offline')
        with self.assertRaises(ApplicationError):
            issue_service.update_issue(self.issue_id, {'title':'Lost', 'affected_person_sid':SID}, self.users['owner'])
        self.assertEqual(issue_service.get_issue(self.issue_id, self.users['owner'])['title'], 'Attachments')
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ad_people').fetchone()[0], 0)

    def test_schema_two_upgrade_is_atomic_and_preserves_data(self):
        with closing(database.get_db()) as db, db:
            db.execute('ALTER TABLE issues DROP COLUMN affected_person_sid')
            db.execute('DROP TABLE ad_people')
            db.execute('UPDATE schema_info SET version=2')
        with closing(database.get_db()) as db, closing(sqlite3.connect(self.root/'before-upgrade.db')) as backup:
            db.backup(backup)
        with patch('dashboard.search_service.initialize_search_index', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                database.init_db()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0], 2)
            self.assertNotIn('affected_person_sid', [row[1] for row in db.execute('PRAGMA table_info(issues)')])
        database.init_db(); database.init_db()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0], 3)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(issue_service.get_issue(self.issue_id, self.users['owner'])['assigned_to'], self.issue['assigned_to'])
        self.assertIsNone(issue_service.get_issue(self.issue_id, self.users['owner'])['affected_person'])
