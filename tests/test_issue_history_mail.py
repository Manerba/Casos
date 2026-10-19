"""Issue timeline/mail parity, commit boundaries, recipients and deadline preferences."""
import sqlite3
import unittest
from contextlib import closing
from datetime import date
from unittest.mock import patch

from dashboard import api_admin, api_issue_history, api_mail, api_updates, auth, database
from dashboard import issue_service, update_service, mail_service
from dashboard.issue_history_service import list_history
from dashboard.errors import ApplicationError
from tests import test_issues


class IssueHistoryMailTests(unittest.TestCase):
    setUpBase = test_issues.IssueTests.setUp
    create = test_issues.IssueTests.create
    rows = test_issues.IssueTests.rows

    def setUp(self):
        self.setUpBase()
        for router in (api_issue_history.router, api_updates.router, api_mail.mail_user_router, api_admin.router):
            self.client.app.include_router(router)
        self.client.app.dependency_overrides[auth.get_admin_user] = lambda: self.admin
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO mail_config(id,smtp_server,from_address) VALUES(1,'invalid.example','casos@example.invalid')")
            for name, user in self.users.items():
                db.execute('UPDATE users SET email=?,vorname=? WHERE id=?', (name+'@example.invalid', name.title(), user['id']))
        self.sent = []
        def fake_mail(to_email, subject, html_body, text_body):
            self.sent.append({'to': to_email, 'subject': subject, 'html': html_body, 'text': text_body})
        mocked = patch.object(mail_service, 'send_mail', side_effect=fake_mail)
        mocked.start(); self.addCleanup(mocked.stop)
        guard = patch.object(mail_service, '_create_smtp_connection', side_effect=AssertionError('Real SMTP forbidden'))
        guard.start(); self.addCleanup(guard.stop)

    def preference(self, name, event, enabled=1, days=2):
        with closing(database.get_db()) as db, db:
            db.execute('INSERT OR REPLACE INTO user_mail_preferences(user_id,event_type,enabled,days_before) VALUES(?,?,?,?)',
                       (self.users[name]['id'], event, enabled, days))

    def test_events_before_after_reopen_actor_and_history_pagination(self):
        issue = self.create(assigned_to=self.users['bob']['id'])
        iid = issue['id']
        self.assertEqual([m['to'] for m in self.sent], ['bob@example.invalid'])
        self.sent.clear()
        self.user = self.users['bob']
        for status in ('erledigt', 'offen'):
            self.assertEqual(self.client.put(f'/api/issues/{iid}', json={'status':status}).status_code, 200)
        update_service.create_update(iid, '# Human update', self.users['bob'])
        page = list_history(iid, self.users['agent'], limit=2)
        self.assertEqual(page['total'], 4)
        self.assertEqual(page['next_offset'], 2)
        items = page['items'] + list_history(iid, self.users['agent'], offset=2, limit=2)['items']
        events = sorted([item for item in items if item['kind']=='event'], key=lambda item:item['id'])
        self.assertEqual([(e['event_type'], e['old_value'], e['new_value']) for e in events],
                         [('assignment', None, self.users['bob']['id']), ('status','offen','erledigt'), ('status','erledigt','offen')])
        self.assertEqual([e['actor_name'] for e in events], ['Alice','Bob','Bob'])
        self.assertEqual(events[0]['new_label'], 'Bob')
        self.assertEqual([m['to'] for m in self.sent], ['alice@example.invalid']*3)
        self.assertIn('?update=', self.sent[-1]['text'])
        before = len(self.rows('issue_events'))
        issue_service.update_issue(iid, {'status':'offen'}, self.users['bob'])
        self.assertEqual(len(self.rows('issue_events')), before)
        self.assertEqual(len(self.sent), 3)

    def test_new_updates_only_current_creator_assignee_not_actor_or_readers(self):
        iid = self.create(assigned_to=self.users['bob']['id'])['id']
        grants = issue_service.get_editors(iid, self.users['alice'])
        issue_service.set_editors(iid, [self.users['agent']['id']], self.users['alice'], revision=grants['revision'])
        self.sent.clear()
        entry = update_service.create_update(iid, 'Update with <img src=x onerror=alert(1)>', self.users['agent'])
        self.assertEqual({m['to'] for m in self.sent}, {'alice@example.invalid','bob@example.invalid'})
        update_service.edit_update(iid, entry['id'], 'Corrected', self.users['agent'], entry['revision'])
        update_service.get_update(iid, entry['id'], self.admin)
        self.assertEqual(len(self.sent), 2)
        self.preference('bob','new_update',enabled=0)
        self.sent.clear()
        update_service.create_update(iid, 'Second', self.users['agent'])
        self.assertEqual([m['to'] for m in self.sent], ['alice@example.invalid'])
        with closing(database.get_db()) as db, db:
            db.execute('UPDATE users SET is_active=0 WHERE id=?',(self.users['alice']['id'],))
        self.sent.clear()
        update_service.create_update(iid,'Third', self.users['agent'])
        self.assertEqual(self.sent, [])

    def test_duplicate_addresses_and_actor_mailbox_are_excluded(self):
        iid = self.create(assigned_to=self.users['bob']['id'])['id']
        with closing(database.get_db()) as db, db:
            db.execute('UPDATE users SET email=? WHERE id=?',('ALICE@example.invalid',self.users['bob']['id']))
        self.sent.clear()
        update_service.create_update(iid, 'By admin', self.admin)
        self.assertEqual(len(self.sent),1)
        self.sent.clear()
        update_service.create_update(iid, 'By Alice', self.users['alice'])
        self.assertEqual(self.sent,[])

    def test_commit_before_mail_and_mail_failures_do_not_lose_mutations(self):
        iid = self.create(assigned_to=self.users['bob']['id'])['id']
        observed=[]
        def inspect_commit(*args):
            with closing(database.get_db()) as db:
                observed.append((db.execute('SELECT status FROM issues WHERE id=?',(iid,)).fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM issue_events WHERE issue_id=? AND event_type='status'",(iid,)).fetchone()[0]))
            raise RuntimeError('Deliberate transport failure')
        with patch.object(mail_service,'send_mail',side_effect=inspect_commit):
            result=issue_service.update_issue(iid,{'status':'erledigt'},self.users['bob'])
        self.assertEqual(result['status'],'erledigt')
        self.assertEqual(observed,[('erledigt',1)])
        with patch.object(mail_service,'send_mail',return_value='SMTP unavailable'):
            entry=update_service.create_update(iid,'Saved despite SMTP failure',self.users['bob'])
        self.assertEqual(update_service.get_update(iid,entry['id'],self.admin)['content'],'Saved despite SMTP failure')

    def test_failed_audit_and_commit_send_no_mail_and_leave_no_events(self):
        iid=self.create(assigned_to=self.users['bob']['id'])['id']
        self.sent.clear()
        with closing(database.get_db()) as db,db:
            db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_log BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        for operation in (lambda: issue_service.update_issue(iid,{'status':'erledigt'},self.users['bob']),
                          lambda: update_service.create_update(iid,'Must rollback',self.users['bob']),
                          lambda: self.create(assigned_to=self.users['bob']['id'])):
            with self.assertRaises(sqlite3.IntegrityError):operation()
        self.assertEqual(self.sent,[])
        self.assertEqual(len(self.rows('issue_events')),1)
        self.assertEqual(self.rows('issue_updates'),[])
        self.assertEqual(issue_service.get_issue(iid,self.admin)['status'],'offen')
        with closing(database.get_db()) as db,db:
            db.execute('DROP TRIGGER fail_audit')
        original=database.get_db
        class FailingCommit:
            def __init__(self):self.db=original()
            def __getattr__(self,key):return getattr(self.db,key)
            def commit(self):raise sqlite3.OperationalError('commit failed')
        with patch('dashboard.db_utils.get_db',side_effect=FailingCommit):
            with self.assertRaises(sqlite3.OperationalError):
                update_service.create_update(iid,'Commit rollback',self.users['bob'])
        self.assertEqual(self.sent,[])
        self.assertEqual(self.rows('issue_updates'),[])

    def test_deleted_assignee_preserves_event_names_and_real_admin_actor(self):
        iid=self.create(assigned_to=self.users['bob']['id'])['id']
        self.sent.clear()
        response=self.client.delete('/api/admin/users/'+str(self.users['bob']['id']))
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(issue_service.get_issue(iid,self.admin)['assigned_to'])
        items=list_history(iid,self.admin)['items']
        self.assertEqual(items[0]['old_value'],self.users['bob']['id'])
        self.assertEqual(items[0]['new_value'],None)
        self.assertEqual(items[0]['old_label'],'Bob')
        self.assertEqual(items[0]['actor_id'],1)
        self.assertEqual(items[0]['actor_name'],'Administrator')
        self.assertEqual(items[1]['new_label'],'Bob')
        self.assertEqual([m['to'] for m in self.sent],['alice@example.invalid'])
        # The historical actor name also survives account deletion.
        self.client.delete('/api/admin/users/'+str(self.users['alice']['id']))
        self.assertIsNone(issue_service.get_issue(iid,self.admin)['created_by'])
        self.assertEqual(list_history(iid,self.admin)['items'][1]['actor_name'],'Alice')

    def test_preferences_defaults_validation_and_html_escaping(self):
        response=self.client.get('/api/user/mail/preferences')
        self.assertEqual(response.status_code,200)
        self.assertEqual({p['event_type'] for p in response.json()['preferences']},set(mail_service.ISSUE_MAIL_EVENTS))
        for bad in ({'event_type':'task_assigned','enabled':True}, {'event_type':'new_update','enabled':True,'days_before':0},
                    {'event_type':'new_update','enabled':True,'days_before':True}, {'event_type':'deadline_warning','enabled':True,'days_before':366}):
            self.assertEqual(self.client.put('/api/user/mail/preferences',json={'preferences':[bad]}).status_code,422)
        good={'event_type':'new_update','enabled':False,'days_before':2}
        self.assertEqual(self.client.put('/api/user/mail/preferences',json={'preferences':[good,good]}).status_code,422)
        self.assertEqual(self.client.put('/api/user/mail/preferences',json={'preferences':[good]}).status_code,200)
        iid=self.create(title='<img src=x onerror=alert(1)> {actor_name}',assigned_to=self.users['bob']['id'])['id']
        message=self.sent[-1]
        self.assertNotIn('<img',message['html'])
        self.assertIn('&lt;img',message['html'])
        self.assertIn('{actor_name}',message['text'])
        self.assertIn(f'/issues/{iid}',message['text'])

    def test_deadlines_default_individual_warning_terminal_inactive_and_dedup(self):
        for status in ('offen','in_arbeit','erledigt','abgebrochen'):
            self.create(title=status,deadline='2026-11-10',status=status,assigned_to=self.users['bob']['id'])
        self.create(title='Default warning',deadline='2026-11-12',assigned_to=self.users['bob']['id'])
        self.create(title='Individual warning',deadline='2026-11-13',assigned_to=self.users['bob']['id'])
        self.create(title='Past',deadline='2026-11-09',assigned_to=self.users['bob']['id'])
        self.preference('bob','deadline_warning',days=3)
        self.preference('bob','deadline_reached',enabled=0)
        self.sent.clear()
        counts=mail_service.notify_due_issues(date(2026,11,10))
        self.assertEqual(counts,{'deadline_reached':2,'deadline_warning':2})
        self.assertEqual([m['to'] for m in self.sent],['alice@example.invalid','alice@example.invalid','alice@example.invalid','bob@example.invalid'])
        self.assertIn('Default warning',self.sent[2]['subject'])
        self.assertIn('Individual warning',self.sent[3]['subject'])
        with closing(database.get_db()) as db,db:
            db.execute('UPDATE users SET is_active=0 WHERE id=?',(self.users['alice']['id'],))
        self.sent.clear()
        self.assertEqual(mail_service.notify_due_issues(date(2026,11,10)),{'deadline_reached':0,'deadline_warning':1})
        with closing(database.get_db()) as db,db:
            db.execute('UPDATE users SET is_active=1 WHERE id=?',(self.users['alice']['id'],))
            db.execute('UPDATE users SET email=? WHERE id=?',('ALICE@example.invalid',self.users['bob']['id']))
        self.preference('bob','deadline_warning',days=2)
        self.sent.clear()
        self.assertEqual(mail_service.notify_due_issues(date(2026,11,10)),{'deadline_reached':2,'deadline_warning':1})

    def test_history_active_rights_and_strict_pagination(self):
        iid=self.create()['id']
        for offset,limit in ((True,50),(0,False),(-1,50),(0,501)):
            with self.assertRaises(ApplicationError):list_history(iid,self.user,offset,limit)
        with closing(database.get_db()) as db,db:
            db.execute('UPDATE users SET is_active=0 WHERE id=?',(self.user['id'],))
        self.assertEqual(self.client.get(f'/api/issues/{iid}/history').status_code,401)

    def test_real_mcp_and_rest_share_history_notifications_and_current_identity(self):
        from tests.test_issue_mcp import IssueMCPTests, TestClient
        from dashboard.app import app
        token,_=auth.create_mcp_token('History agent',1)
        identity=auth.validate_mcp_bearer(token)
        iid=self.create(assigned_to=identity['id'])['id']
        self.sent.clear()
        self.rpc=IssueMCPTests.rpc.__get__(self)
        self.call=IssueMCPTests.call.__get__(self)
        with TestClient(app) as client:
            headers=IssueMCPTests.initialize(self,client,token)
            self.call(client,headers,'issue.update',{'issue_id':iid,'changes':{'status':'erledigt'}})
            self.call(client,headers,'issue.update',{'issue_id':iid,'changes':{'status':'offen'}})
            created=self.call(client,headers,'update.add',{'issue_id':iid,'content':'MCP timeline'})
            remote=self.call(client,headers,'issue.history',{'issue_id':iid})
            client.cookies.set('casos_session',auth.sign_token(auth.create_session(self.users['alice']['id'])))
            rest=client.get(f'/api/issues/{iid}/history').json()
            self.assertEqual(remote,rest)
            self.assertEqual(rest['total'],4)
            self.assertEqual({item['actor_id'] for item in rest['items']}, {self.users['alice']['id'],identity['id']})
            self.assertEqual([m['to'] for m in self.sent],['alice@example.invalid']*3)
            self.assertIn(f'?update={created["update_id"]}',self.sent[-1]['text'])
            auth.set_mcp_enabled(False)
            self.assertEqual(client.post('/mcp/',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'issue.history','arguments':{'issue_id':iid}}}).status_code,401)
            auth.set_mcp_enabled(True)


if __name__=='__main__':unittest.main()
