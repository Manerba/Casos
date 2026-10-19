"""Retained security semantics from retired project/file tests, on flat Issues."""
import asyncio
import json
import unittest
from contextlib import closing, contextmanager
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError, ValidationError as FastMCPValidationError

from dashboard import api_auth, auth, database, issue_service, update_service
from dashboard.app import app as main_app
from dashboard.mcp_app import app as dedicated_app
from dashboard.errors import ApplicationError
from dashboard.mcp_errors import StructuredToolErrors
from tests.attachment_test_helpers import AttachmentTestCase


class SecurityRegressions(AttachmentTestCase):
    def assert_security_headers(self, response, dedicated=False):
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')
        self.assertIn(response.headers['referrer-policy'], ('same-origin', 'no-referrer'))
        policy = response.headers['content-security-policy']
        self.assertIn("frame-ancestors 'none'", policy)
        if dedicated:
            self.assertIn("default-src 'none'", policy)
        else:
            self.assertIn("script-src 'self'", policy)
            self.assertNotIn("'unsafe-eval'", policy)
            self.assertIn("object-src 'none'", policy)
            self.assertIn("frame-src 'none'", policy)
            self.assertIn("connect-src 'self'", policy)

    def test_authentication_csrf_and_security_headers_on_real_apps(self):
        with TestClient(main_app) as client:
            for path, status in (('/login',200), ('/',302), (f'/issues/{self.issue_id}',302),
                                 ('/api/issues',401), (f'/api/issues/{self.issue_id}/history',401)):
                with self.subTest(path=path):
                    response=client.get(path,follow_redirects=False)
                    self.assertEqual(response.status_code,status)
                    self.assert_security_headers(response)
            for path in ('/',f'/issues/{self.issue_id}','/api/issues',f'/api/issues/{self.issue_id}/history'):
                response=client.get(path,headers=self.headers('reader'))
                self.assertEqual(response.status_code,200,response.text[:200])
                self.assert_security_headers(response)
                if path.startswith('/api/'):
                    self.assertEqual(response.headers['cache-control'],'no-store')
            # A Bearer is accepted only by attachment REST and the MCP transport.
            self.assertEqual(client.get('/api/issues',headers=self.headers('agent')).status_code,401)
            self.assertEqual(client.get('/api/admin/users',headers=self.headers('reader')).status_code,403)
            self.assertEqual(client.get('/api/admin/users',headers=self.headers('admin')).status_code,200)
            for method,path,body in (
                ('POST','/api/issues',{'title':'Blocked'}),
                ('PUT',f'/api/issues/{self.issue_id}',{'title':'Blocked'}),
                ('PATCH',f'/api/issues/{self.issue_id}/description',{}),
                ('DELETE',f'/api/issues/{self.issue_id}',None),
                ('PUT','/api/user/mail/preferences',{'preferences':[]}),
            ):
                response=client.request(method,path,json=body,headers=self.headers('owner',csrf=False))
                self.assertEqual(response.status_code,403,response.text)
        with TestClient(dedicated_app) as client:
            for path in ('/login','/',f'/issues/{self.issue_id}','/static/js/app_core.js','/api/admin/users','/api/issues'):
                response=client.get(path,headers=self.headers('agent'))
                self.assertEqual(response.status_code,404,path)
                self.assert_security_headers(response,dedicated=True)
            bootstrap=client.get('/.well-known/casos-agent.json')
            self.assertEqual(bootstrap.status_code,200)
            self.assert_security_headers(bootstrap,dedicated=True)
            self.assertEqual(client.get(self.url,headers=self.headers('owner')).status_code,401)
            self.assertEqual(client.get(self.url,headers=self.headers('agent')).status_code,200)

    def test_signed_cookie_security_flags_logout_and_current_session(self):
        api_auth._rate_limits.clear(); self.addCleanup(api_auth._rate_limits.clear)
        with TestClient(main_app,base_url='https://casos.test') as client, \
                patch('dashboard.tls_utils.get_tls_config',return_value={'enabled':True}):
            response=client.post('/api/auth/login',json={'username':'admin','password':'admin'},
                                 headers={'X-Requested-With':'XMLHttpRequest'})
            self.assertEqual(response.status_code,200,response.text)
            cookie=response.headers['set-cookie'].lower()
            for fragment in ('httponly','secure','samesite=lax','path=/'):
                self.assertIn(fragment,cookie)
            signed=client.cookies.get(auth.COOKIE_NAME)
            self.assertIsNotNone(auth.validate_session(auth.unsign_token(signed)))
            self.assertEqual(client.get('/api/issues').status_code,200)
            self.assertEqual(client.post('/api/auth/logout',headers={'X-Requested-With':'XMLHttpRequest'}).status_code,200)
            self.assertIsNone(auth.validate_session(auth.unsign_token(signed)))
            self.assertEqual(client.get('/api/issues').status_code,401)
            self.assertEqual(client.get('/api/issues',headers={'Cookie':auth.COOKIE_NAME+'='+signed+'tamper'}).status_code,401)

    def test_exact_markdown_roundtrip_between_rest_and_mcp(self):
        from tests import test_issue_mcp as mcp_tests
        self.rpc=mcp_tests.IssueMCPTests.rpc.__get__(self)
        self.call=mcp_tests.IssueMCPTests.call.__get__(self)
        source='# Größe 🧪\r\n\r\n<p>Literal HTML</p>\r\n\r\n| A | B |\r\n|---|---|\r\n| 1 | 2 |\r\n\r\n```html\r\n<script>example</script>\r\n```\r\n'
        with mcp_tests.TestClient(main_app) as client:
            h=mcp_tests.IssueMCPTests.initialize(self,client)
            created=client.post('/api/issues',json={'title':'Roundtrip','description':source,'assigned_to':self.users['agent']['id']},headers=self.headers('owner'))
            self.assertEqual(created.status_code,201,created.text)
            iid=created.json()['id']
            detail=self.call(client,h,'issue.get',{'issue_id':iid})
            self.assertEqual(detail['description'],source)
            self.assertEqual(detail['description_format'],'markdown')
            entry=self.call(client,h,'update.add',{'issue_id':iid,'content':source})
            rest=client.get(f'/api/issues/{iid}/updates/{entry["update_id"]}',headers=self.headers('reader')).json()
            self.assertEqual(rest['content'],source)
            self.assertEqual(rest['content_format'],'markdown')
            changed=source+'\r\nMCP addition'
            self.call(client,h,'issue.update',{'issue_id':iid,'changes':{'description':changed,'description_revision':detail['description_revision']}})
            self.assertEqual(client.get(f'/api/issues/{iid}',headers=self.headers('reader')).json()['description'],changed)

    def test_reason_unicode_length_empty_and_audit_separation(self):
        iid=self.issue_id
        for reason in ('\ud800','\udfff','x'*1001,' '*1001,False,123):
            for action in (
                lambda:issue_service.update_issue(iid,{'title':'Must not persist'},self.users['owner'],reason=reason),
                lambda:update_service.create_update(iid,'Must not persist',self.users['owner'],reason=reason),
            ):
                before=len(self.rows('audit_log'))
                with self.subTest(reason=repr(reason)),self.assertRaises(ApplicationError) as caught:action()
                self.assertEqual(caught.exception.code,'invalid_reason')
                self.assertEqual(len(self.rows('audit_log')),before)
        self.assertEqual(issue_service.get_issue(iid,self.users['owner'])['title'],'Attachments')
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issue_updates').fetchone()[0],0)
        reason='🧪'*1000
        issue_service.update_issue(iid,{'priority':71},self.users['owner'],reason=reason)
        audit=self.rows('audit_log')[-1]
        self.assertEqual(audit['reason'],reason)
        self.assertNotIn('reason',json.loads(audit['changes_json']))
        issue_service.update_issue(iid,{'priority':72},self.users['owner'],reason=' \n\t ')
        self.assertIsNone(self.rows('audit_log')[-1]['reason'])
        with TestClient(main_app) as client:
            result=client.get('/api/admin/mcp/audit',headers=self.headers('admin')).json()
            self.assertTrue(any(row['reason']==reason for row in result['items']))
            self.assertEqual(client.get('/api/admin/mcp/audit',headers=self.headers('reader')).status_code,403)

    def test_list_total_and_items_share_one_snapshot_under_concurrent_delete(self):
        second=issue_service.create_issue({'title':'Concurrent'},self.users['owner'])['id']
        factory=issue_service.db_query
        changed=[]
        class ConcurrentConnection:
            def __init__(self,db):self.db=db
            def execute(self,sql,parameters=()):
                cursor=self.db.execute(sql,parameters)
                if sql.startswith('SELECT COUNT(*) FROM issues'):
                    with closing(database.get_db()) as writer,writer:
                        writer.execute('DELETE FROM issues WHERE id=?',(second,))
                    changed.append(second)
                return cursor
        @contextmanager
        def concurrent_query():
            with factory() as db:yield ConcurrentConnection(db)
        with patch.object(issue_service,'db_query',concurrent_query):
            result=issue_service.list_issues(self.users['reader'])
        self.assertEqual(changed,[second])
        self.assertEqual(result['total'],2)
        self.assertEqual({item['id'] for item in result['items']},{self.issue_id,second})
        self.assertEqual(issue_service.list_issues(self.users['reader'])['total'],1)


class StructuredErrorRegressions(unittest.TestCase):
    def test_unknown_errors_never_expose_details_and_success_schema_survives(self):
        server=FastMCP('isolated-errors-test',middleware=[StructuredToolErrors()],strict_input_validation=False)
        @server.tool
        def fail(kind:str)->list[dict]:
            errors={
                'runtime':RuntimeError('/private/path bearer-secret'),
                'tool':ToolError('/private/path bearer-secret'),
                'http':HTTPException(500,'database credentials bearer-secret'),
                'framework':FastMCPValidationError('private input bearer-secret'),
                'typed':ApplicationError(409,'Concurrent change',code='revision_conflict',field='revision'),
            }
            raise errors[kind]
        @server.tool
        def success()->list[dict]:return [{'id':1}]
        async def run():
            async with Client(server) as client:
                for kind,code in (('runtime','internal_error'),('tool','internal_error'),('http','internal_error'),
                                  ('framework','invalid_arguments'),('typed','revision_conflict')):
                    with self.subTest(kind=kind):
                        result=await client.call_tool('fail',{'kind':kind},raise_on_error=False)
                        self.assertTrue(result.is_error)
                        self.assertEqual(result.structured_content['code'],code)
                        self.assertEqual(json.loads(result.content[0].text),result.structured_content)
                        for private in ('private','bearer-secret','credentials'):
                            self.assertNotIn(private,json.dumps(result.structured_content))
                missing=await client.call_tool('missing_tool',{},raise_on_error=False)
                self.assertTrue(missing.is_error)
                self.assertEqual(missing.structured_content['code'],'unknown_tool')
                result=await client.call_tool('success',{})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content,{'result':[{'id':1}]})
        with self.assertLogs('fastmcp.server.server',level='WARNING') as records:
            asyncio.run(run())
        log=' '.join(records.output)
        self.assertNotIn('bearer-secret',log)
        self.assertNotIn('/private/path',log)


if __name__=='__main__':unittest.main()
