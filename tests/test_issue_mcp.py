"""Actual MCP HTTP sessions on both app mounts, shared REST rights and isolated data."""
import base64
import json
from contextlib import closing
from unittest.mock import patch

from fastapi.testclient import TestClient as BaseTestClient

from tests.attachment_test_helpers import AttachmentTestCase
from dashboard import auth, database, issue_service, mcp_server, update_service
from dashboard.api_admin_mcp import MCP_TOOLS
from dashboard.app import app as main_app
from dashboard.mcp_app import app as dedicated_app
from dashboard.agent_guide import build_agent_metadata, build_agent_guide_markdown


class TestClient(BaseTestClient):
    """Terminate HTTP transport sessions as a normal MCP SDK client does."""
    def __exit__(self, *args):
        for headers in getattr(self, '_mcp_sessions', []):
            self.delete('/mcp/', headers=headers)
        return super().__exit__(*args)


class IssueMCPTests(AttachmentTestCase):
    def setUp(self):
        super().setUp()
        self.reader_token, self.reader_token_id = auth.create_mcp_token('Read all', 1)
        self.reader = auth.validate_mcp_bearer(self.reader_token)
        with closing(database.get_db()) as db, db:
            db.execute("INSERT OR REPLACE INTO app_config(id,server_address) VALUES(1,'casos.test:8514')")

    def rpc(self, client, method, params, headers):
        response = client.post('/mcp/', headers=headers, json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
        self.assertEqual(response.status_code, 200, response.text[:500])
        payload = (next(json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: '))
                   if response.headers['content-type'].startswith('text/event-stream') else response.json())
        self.assertNotIn('error', payload, payload)
        return response, payload['result']

    def initialize(self, client, token=None):
        headers = {'Authorization':'Bearer '+(token or self.token), 'Accept':'application/json, text/event-stream'}
        response, result = self.rpc(client,'initialize',{'protocolVersion':'2025-11-25','capabilities':{},
                                                        'clientInfo':{'name':'casos-issue-test','version':'1'}},headers)
        headers.update({'Mcp-Session-Id':response.headers['mcp-session-id'],'MCP-Protocol-Version':result['protocolVersion']})
        ready=client.post('/mcp/',headers=headers,json={'jsonrpc':'2.0','method':'notifications/initialized'})
        self.assertEqual(ready.status_code,202,ready.text)
        if not hasattr(client,'_mcp_sessions'):client._mcp_sessions=[]
        client._mcp_sessions.append(headers.copy())
        return headers

    def call(self, client, headers, tool, arguments=None, error=None):
        _, result=self.rpc(client,'tools/call',{'name':tool,'arguments':arguments or {}},headers)
        self.assertEqual(bool(result.get('isError')),error is not None,result)
        payload=result.get('structuredContent') or json.loads(result['content'][0]['text'])
        if error:
            self.assertEqual(payload['code'],error,payload)
        return payload

    def test_both_mounts_catalog_lifecycle_and_compact_writes(self):
        for app,port in ((main_app,8514),(dedicated_app,8516)):
            with self.subTest(port=port),TestClient(app,base_url=f'http://casos.test:{port}') as client:
                h=self.initialize(client)
                _, catalog=self.rpc(client,'tools/list',{},h)
                self.assertEqual({t['name'] for t in catalog['tools']},set(MCP_TOOLS))
                serialized=json.dumps(catalog)
                for legacy in ('project_id','subtask_id','nextcloud','file_storage_type','status_percent','handoff.'):
                    self.assertNotIn(legacy,serialized)
                self.assertEqual(self.call(client,h,'whoami')['id'],self.users['agent']['id'])
                created=self.call(client,h,'issue.create',{'title':f'MCP {port}','description':'Original','assigned_to':self.users['assignee']['id']})
                self.assertEqual(set(created),{'ok','issue_id'})
                iid=created['issue_id']
                listing=self.call(client,h,'issue.list',{'limit':1})
                self.assertEqual(listing['items'][0]['issue_id'],iid)
                self.assertNotIn('description',listing['items'][0])
                self.assertIsNotNone(listing['next_offset'])
                current=self.call(client,h,'issue.get',{'issue_id':iid})
                self.assertEqual(current['description'],'Original')
                result=self.call(client,h,'issue.update',{'issue_id':iid,'changes':{'status':'erledigt','assigned_to':None,'deadline':None},'reason':'verified'})
                self.assertEqual(result,{'ok':True})
                self.call(client,h,'issue.update',{'issue_id':iid,'changes':{'status':'offen'}})
                history=self.call(client,h,'issue.history',{'issue_id':iid,'limit':2})
                self.assertEqual(history['total'],4)
                self.assertEqual(history['items'][0]['new_value'],'offen')
                self.assertEqual(history['next_offset'],2)
                if port==8514:
                    rest_history=client.get(f'/api/issues/{iid}/history?limit=2',headers=self.headers('reader'))
                    self.assertEqual(rest_history.status_code,200)
                    self.assertEqual(rest_history.json(),history)
                patched=self.call(client,h,'issue.patch_description',{'issue_id':iid,'revision':current['description_revision'],'operation':'append','text':' more'})
                self.assertIn('description_revision',patched)
                self.call(client,h,'issue.patch_description',{'issue_id':iid,'revision':current['description_revision'],'operation':'append','text':' lost'},error='revision_conflict')
                rest=issue_service.get_issue(iid,self.users['reader'])
                self.assertEqual(rest['status'],'offen');self.assertIsNone(rest['assigned_to'])
                self.assertEqual(rest['description'],'Original more')
                self.assertEqual(self.call(client,h,'issue.delete',{'issue_id':iid})['ok'],True)
                self.call(client,h,'issue.get',{'issue_id':iid},error='issue_not_found')

    def test_global_read_rights_grants_and_update_revisions(self):
        with TestClient(main_app,base_url='http://casos.test:8514') as client:
            h=self.initialize(client);rh=self.initialize(client,self.reader_token)
            iid=self.issue_id
            read=self.call(client,rh,'issue.get',{'issue_id':iid})
            self.assertFalse(read['permissions']['can_edit'])
            self.call(client,rh,'update.add',{'issue_id':iid,'content':'denied'},error='permission_denied')
            self.call(client,rh,'issue.update',{'issue_id':iid,'changes':{'status':'erledigt'}},error='permission_denied')
            self.call(client,h,'issue.update',{'issue_id':iid,'changes':{'assigned_to':self.users['agent']['id']}},error='permission_denied')
            created=self.call(client,h,'update.add',{'issue_id':iid,'content':'**Entry**'})
            entry=self.call(client,rh,'update.get',{'issue_id':iid,'update_id':created['update_id']})
            self.assertEqual(entry['content'],'**Entry**');self.assertFalse(entry['can_write'])
            revised=self.call(client,h,'update.edit',{'issue_id':iid,'update_id':entry['update_id'],'content':'Corrected','revision':entry['revision']})
            self.call(client,h,'update.edit',{'issue_id':iid,'update_id':entry['update_id'],'content':'Lost','revision':entry['revision']},error='revision_conflict')
            self.call(client,h,'update.delete',{'issue_id':iid,'update_id':entry['update_id']},error='permission_denied')
            with closing(database.get_db()) as db,db:
                db.execute('UPDATE users SET is_admin=1 WHERE id=?',(self.users['agent']['id'],))
                db.execute("UPDATE issue_updates SET created_at=datetime('now','-1 day') WHERE id=?",(entry['update_id'],))
            self.assertTrue(self.call(client,h,'whoami')['is_admin'])
            self.call(client,h,'update.edit',{'issue_id':iid,'update_id':entry['update_id'],'content':'Admin','revision':revised['revision']})
            grants=self.call(client,h,'issue.editors.get',{'issue_id':iid})
            self.call(client,h,'issue.editors.set',{'issue_id':iid,'user_ids':[self.reader['id']],'revision':grants['revision']})
            self.assertTrue(self.call(client,rh,'issue.get',{'issue_id':iid})['permissions']['can_edit'])
            self.call(client,rh,'update.add',{'issue_id':iid,'content':'Allowed by grant'})
            self.call(client,h,'update.delete',{'issue_id':iid,'update_id':entry['update_id']})
            self.call(client,rh,'update.get',{'issue_id':iid,'update_id':entry['update_id']},error='update_not_found')

    def test_attachments_binary_duplicates_bounds_and_rest_parity(self):
        for app,port in ((main_app,8514),(dedicated_app,8516)):
            with self.subTest(port=port),TestClient(app,base_url=f'http://casos.test:{port}') as client:
                h=self.initialize(client);rh=self.initialize(client,self.reader_token)
                data=b'\x00\xff\x01binary'
                a=self.call(client,h,'attachment.add',{'issue_id':self.issue_id,'original_name':'same.bin','content':base64.b64encode(data).decode()})
                b=self.call(client,h,'attachment.add',{'issue_id':self.issue_id,'original_name':'same.bin','content':'Other','encoding':'utf-8'})
                self.assertNotEqual(a['attachment_id'],b['attachment_id'])
                read=self.call(client,rh,'attachment.read',{'issue_id':self.issue_id,'attachment_id':a['attachment_id']})
                self.assertEqual(base64.b64decode(read['content']),data)
                self.assertEqual(client.get(read['download_url'],headers=rh).content,data)
                self.call(client,rh,'attachment.delete',{'issue_id':self.issue_id,'attachment_id':a['attachment_id']},error='permission_denied')
                self.call(client,h,'attachment.read',{'issue_id':self.issue_id,'attachment_id':a['attachment_id'],'encoding':'utf-8'},error='invalid_encoding')
                rest=client.post(self.url,headers={**h,'X-Requested-With':'XMLHttpRequest'},files={'file':('big.bin',b'0'*33,'application/octet-stream')})
                self.assertEqual(rest.status_code,201,rest.text)
                with patch.object(mcp_server,'MCP_ATTACHMENT_MAX_BYTES',32):
                    self.call(client,h,'attachment.add',{'issue_id':self.issue_id,'original_name':'limit','content':'é'*17,'encoding':'utf-8'},error='attachment_too_large')
                    self.call(client,h,'attachment.read',{'issue_id':self.issue_id,'attachment_id':rest.json()['id']},error='attachment_too_large')
                self.call(client,h,'attachment.add',{'issue_id':self.issue_id,'original_name':'bad','content':'%%%not-base64'},error='invalid_encoding')
                self.call(client,h,'attachment.delete',{'issue_id':self.issue_id,'attachment_id':a['attachment_id']})
                self.assertEqual(client.get(read['download_url'],headers=rh).status_code,404)

    def test_existing_sessions_refresh_roles_revocation_and_kill_switch(self):
        for app,port in ((main_app,8514),(dedicated_app,8516)):
            with self.subTest(port=port),TestClient(app,base_url=f'http://casos.test:{port}') as client:
                token,tid=auth.create_mcp_token('Dynamic',1);u=auth.validate_mcp_bearer(token)
                h=self.initialize(client,token)
                self.call(client,h,'issue.delete',{'issue_id':self.issue_id},error='permission_denied')
                with closing(database.get_db()) as db,db:
                    db.execute('UPDATE users SET is_admin=1 WHERE id=?',(u['id'],))
                self.assertTrue(self.call(client,h,'issue.get',{'issue_id':self.issue_id})['permissions']['can_manage'])
                with closing(database.get_db()) as db,db:
                    db.execute('UPDATE users SET is_admin=0 WHERE id=?',(u['id'],))
                self.call(client,h,'issue.delete',{'issue_id':self.issue_id},error='permission_denied')
                auth.set_mcp_enabled(False)
                response=client.post('/mcp/',headers=h,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
                self.assertEqual(response.status_code,401)
                self.assertEqual(client.get(self.url,headers=h).status_code,403)
                auth.set_mcp_enabled(True)
                self.call(client,h,'issue.get',{'issue_id':self.issue_id})
                auth.revoke_mcp_token(tid)
                self.assertEqual(client.post('/mcp/',headers=h,json={'jsonrpc':'2.0','id':3,'method':'tools/list','params':{}}).status_code,401)
                self.assertEqual(client.get(self.url,headers=h).status_code,401)

    def test_session_id_never_transfers_identity_or_write_rights_between_tokens(self):
        for app in (main_app, dedicated_app):
            with self.subTest(app=app.title), TestClient(app) as client:
                writer = self.initialize(client)
                reader = self.initialize(client, self.reader_token)
                self.assertEqual(self.call(client, writer, 'whoami')['id'], self.users['agent']['id'])
                self.assertEqual(self.call(client, reader, 'whoami')['id'], self.reader['id'])
                changed = {**writer, 'Authorization': 'Bearer ' + self.reader_token}
                response = client.post('/mcp/', headers=changed, json={'jsonrpc':'2.0', 'id':2,
                    'method':'tools/call', 'params':{'name':'whoami','arguments':{}}})
                if response.status_code == 200:
                    self.assertEqual(self.call(client, changed, 'whoami')['id'], self.reader['id'])
                    self.call(client, changed, 'issue.update', {'issue_id':self.issue_id,
                        'changes':{'title':'Must not inherit writer access'}}, error='permission_denied')
                else:
                    self.assertIn(response.status_code, (403, 404))
                self.assertEqual(self.call(client, writer, 'whoami')['id'], self.users['agent']['id'])
                self.assertEqual(self.call(client, reader, 'whoami')['id'], self.reader['id'])
                self.assertEqual(issue_service.get_issue(self.issue_id, self.users['owner'])['title'], 'Attachments')

    def test_errors_are_structured_and_no_partial_writes(self):
        with TestClient(main_app) as client:
            h=self.initialize(client)
            before=issue_service.get_issue(self.issue_id,self.users['owner'])
            errors=[('issue.list',{'limit':501},'invalid_pagination'),
                    ('issue.get',{},'missing_argument'),
                    ('issue.create',{'title':'SECRET','status':'SECRET'},'invalid_status'),
                    ('issue.update',{'issue_id':self.issue_id,'changes':{'title':'SECRET','unexpected':'SECRET'}},'unknown_argument'),
                    ('issue.update',{'issue_id':self.issue_id,'changes':{'description':'SECRET'}},'revision_required'),
                    ('issue.update',{'issue_id':self.issue_id,'changes':{'title':'SECRET'},'reason':'x'*1001},'invalid_reason'),
                    ('attachment.add',{'issue_id':self.issue_id,'original_name':'safe','content':'SECRET','encoding':'SECRET'},'invalid_encoding')]
            with self.assertLogs('fastmcp.server.server', level='WARNING') as records:
                for name,args,code in errors:
                    with self.subTest(tool=name,code=code):
                        result=self.call(client,h,name,args,error=code)
                        self.assertNotIn('SECRET',json.dumps(result))
            self.assertNotIn('SECRET',' '.join(records.output))
            after=issue_service.get_issue(self.issue_id,self.users['owner'])
            self.assertEqual(after,before)

    def test_guides_bootstrap_search_and_current_identity(self):
        update_service.create_update(self.issue_id,'Unique searchable Unicode Größe',self.users['owner'])
        for app,port in ((main_app,8514),(dedicated_app,8516)):
            with self.subTest(port=port),TestClient(app,base_url=f'http://casos.test:{port}') as client:
                h=self.initialize(client,self.reader_token)
                metadata=client.get('/.well-known/casos-agent.json').json()
                self.assertEqual(metadata['mcp']['token_admin_url'],'http://casos.test:8514/?settings=mcp')
                guide=client.get('/agent-guide.md').text
                self.assertIn(f'http://casos.test:{port}/api/issues/',guide)
                self.assertIn('issue.update',guide);self.assertNotIn('8515',guide)
                self.assertNotIn('list_projects',guide)
                self.assertIn('changes',guide)
                remote=self.call(client,h,'get_agent_guide')
                self.assertEqual(remote['metadata']['attachment_api_base_url'],f'http://casos.test:{port}')
                found=self.call(client,h,'search',{'query':'"Unicode Größe"','types':['update']})
                self.assertEqual(found['total'],1);self.assertEqual(found['items'][0]['issue_id'],self.issue_id)
                self.assertIn('?update=',found['items'][0]['url'])
                if port==8514:
                    rest=client.get('/api/search',params={'query':'"Unicode Größe"','types':'update'},headers=self.headers('reader')).json()
                    self.assertEqual(rest['items'],found['items'])
                    anonymous=client.get('/api/issues');self.assertEqual(anonymous.status_code,401)
                else:
                    self.assertEqual(client.get('/api/issues',headers=h).status_code,404)
                    self.assertEqual(client.get('/api/admin/mcp/config',headers=h).status_code,404)
        with closing(database.get_db()) as db,db:
            db.execute('UPDATE users SET is_active=0 WHERE id=?',(self.reader['id'],))
        with TestClient(dedicated_app) as client:
            self.assertEqual(client.post('/mcp/',headers={'Authorization':'Bearer '+self.reader_token},json={}).status_code,401)
