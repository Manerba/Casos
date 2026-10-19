"""Content-level FTS regressions on disposable Casos Issue databases."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from dashboard import auth, database, search_service as search
from dashboard.errors import ApplicationError
from dashboard.app import app


class IssueSearchTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='casos-issue-search-');self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        for module,name,value in ((database,'DB_DIR',root),(database,'DB_PATH',root/'casos.db'),(auth,'SECRET_KEY_PATH',root/'secret.key')):
            patcher=patch.object(module,name,value);patcher.start();self.addCleanup(patcher.stop)
        database.init_db()
        self.db=database.get_db();self.addCleanup(self.db.close)
        for name in ('reader','writer'):
            self.db.execute('INSERT INTO users(username,password_hash) VALUES(?,?)',(name,'unused'))
        self.db.commit()
        self.user={'id':2};self.admin={'id':1}

    def issue(self,title='Container',description='',**fields):
        data={'title':title,'description':description,'created_by':3,**fields}
        return self.db.execute('INSERT INTO issues ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values())).lastrowid

    def update(self,issue_id,content,**fields):
        data={'issue_id':issue_id,'content':content,'user_id':3,**fields}
        return self.db.execute('INSERT INTO issue_updates ('+','.join(data)+') VALUES ('+','.join('?' for _ in data)+')',list(data.values())).lastrowid

    def find(self,query,**options):return search.search_content(self.db,self.user,query,**options)

    def test_and_phrase_and_controlled_literal_punctuation(self):
        target=self.issue('Proxy','Freigabe Domain')
        self.issue('Proxy','Domain')
        self.assertEqual([r['id'] for r in self.find('Proxy Freigabe Domain')['items']],[target])
        phrase=self.issue(description='Alpha Beta')
        apart=self.issue(description='Beta something Alpha')
        self.assertEqual({r['id'] for r in self.find('Alpha-Beta')['items']},{phrase,apart})
        self.assertEqual([r['id'] for r in self.find('"Alpha Beta"')['items']],[phrase])
        self.assertEqual(self.find('Alpha OR Beta')['total'],0)
        with self.assertRaises(ApplicationError):self.find('title:Alpha')

    def test_unicode_case_accents_prefix_and_no_infix(self):
        issue=self.issue(description='ÄNDERUNGEN an Fenstern Київ ПРИВІТ')
        self.issue(description='Zeitfenster')
        for query in ('anderungen','a\u0308nderungen','änderungen','fenster*','київ','привіт'):
            with self.subTest(query=query):self.assertEqual([r['id'] for r in self.find(query)['items']],[issue])
        self.assertEqual(self.find('fenster')['total'],0)
        with self.assertRaises(ApplicationError):self.find('*fenster')

    def test_one_corpus_ranks_concise_update_over_noisy_issues(self):
        for index in range(25):issue=self.issue(description='needle '+'background '*150)
        update=self.update(issue,'needle needle needle')
        hit=self.find('needle',limit=1)['items'][0]
        self.assertEqual((hit['type'],hit['update_id'],hit['issue_id']),('update',update,issue))
        self.assertEqual(hit['url'],f'/issues/{issue}?update={update}')
        self.assertNotIn('score',hit)
        self.assertNotIn('project_id',hit)
        self.assertNotIn('handoff_id',hit)

    def test_safe_bounded_snippets_include_late_match(self):
        issue=self.issue()
        self.update(issue,'Einleitung '*200+'<script>alert(1)</script> Schreibschicht "& Ende')
        hit=self.find('Schreibschicht')['items'][0]
        self.assertIn('<mark>Schreibschicht</mark>',hit['snippet_html'])
        self.assertNotIn('<script>',hit['snippet_html'])
        self.assertIn('&lt;script&gt;',hit['snippet_html'])
        self.assertLessEqual(len(hit['snippet']),322)
        self.db.execute('UPDATE issue_updates SET content=?',('&'*10000+' Schreibschicht '+'x'*10000,))
        hit=self.find('Schreibschicht')['items'][0]
        self.assertIn('<mark>Schreibschicht</mark>',hit['snippet_html'])
        self.assertLessEqual(len(hit['snippet']),322)
        self.assertLess(len(hit['snippet_html']),2000)

    def test_types_issue_filter_and_timezone_inclusive_updated_at(self):
        issue=self.issue(description='needle',created_at='2026-01-01 00:00:00',updated_at='2026-02-01 11:00:00')
        update=self.update(issue,'needle',created_at='2026-01-01 00:00:00',updated_at='2026-02-01 11:00:00')
        self.update(issue,'needle old',updated_at='2026-02-01 10:59:59')
        self.update(self.issue(),'needle other',updated_at='2026-02-01 11:00:00')
        result=self.find('needle',issue_id=issue,types=['update'],since='2026-02-01T12:00:00+01:00')
        self.assertEqual([r['update_id'] for r in result['items']],[update])
        self.assertEqual(result['items'][0]['updated_at'],'2026-02-01T11:00:00Z')
        self.assertEqual(result['items'][0]['created_at'],'2026-01-01T00:00:00Z')
        self.assertEqual(self.find('needle',issue_id=issue,since='2026-02-01T11:00:00Z')['total'],2)
        self.assertEqual(self.find('needle',issue_id=issue,since='2026-02-01T11:00:00.000001Z')['total'],0)
        for bad in ('2026-02-01','2026-02-01T11:00:00','tomorrow'):
            with self.subTest(since=bad),self.assertRaises(ApplicationError):self.find('needle',since=bad)

    def test_pagination_has_stable_ties_and_no_duplicate_rows(self):
        ids=[self.issue(description='needle',updated_at='2026-01-01 00:00:00') for _ in range(7)]
        collected=[];offset=0
        while offset is not None:
            page=self.find('needle',offset=offset,limit=2)
            self.assertEqual(page['total'],7)
            collected.extend(row['id'] for row in page['items'])
            offset=page['next_offset']
        self.assertEqual(collected,list(reversed(ids)))
        self.assertIsNone(self.find('needle',offset=100)['next_offset'])
        self.assertEqual(self.find('needle',offset=100)['total'],7)

    def test_since_preserves_microsecond_boundaries_for_both_sources_and_zones(self):
        parent=self.issue()
        zones=(timezone.utc,timezone(timedelta(hours=5,minutes=30)),timezone(timedelta(hours=-7)))
        for index,microsecond in enumerate((0,123000,123456,999999)):
            pivot=datetime(2026,2,1,23,59,59,microsecond,tzinfo=timezone.utc)
            query=f'microboundary{index}'
            records=[]
            for delta in (-1,0,1):
                instant=pivot+timedelta(microseconds=delta)
                # Mix legacy naive seconds and zoned fractional sources,
                # including offsets that change the local calendar day.
                stamp=(instant.strftime('%Y-%m-%d %H:%M:%S') if instant.microsecond==0
                       else instant.astimezone(zones[delta+1]).isoformat())
                iid=self.issue(query,created_at=stamp,updated_at=stamp)
                uid=self.update(parent,query,created_at=stamp,updated_at=stamp)
                records.extend(((instant,'issue',iid),(instant,'update',uid)))
            for delta in (-1,0,1):
                lower=pivot+timedelta(microseconds=delta)
                expected={(kind,rid) for instant,kind,rid in records if instant>=lower}
                for zone in zones:
                    since=lower.astimezone(zone).isoformat()
                    with self.subTest(microsecond=microsecond,delta=delta,since=since):
                        page=self.find(query,since=since)
                        self.assertEqual(page['total'],len(expected))
                        self.assertEqual({(row['type'],row['id']) for row in page['items']},expected)
                        for row in page['items']:
                            instant=next(moment for moment,kind,rid in records if (kind,rid)==(row['type'],row['id']))
                            exact=instant.isoformat().replace('+00:00','Z')
                            self.assertEqual(row['created_at'],exact)
                            self.assertEqual(row['updated_at'],exact)

    def test_microsecond_ranking_ties_sort_mixed_sources_before_pagination(self):
        parent=self.issue()
        newest=self.update(parent,'chronologicalneedle',updated_at='2026-03-02T00:00:00.123457Z')
        equal_issue=self.issue('chronologicalneedle',updated_at='2026-03-01T17:00:00.123456-07:00')
        legacy=self.issue('chronologicalneedle',updated_at='2026-03-02 00:00:00')
        equal_update=self.update(parent,'chronologicalneedle',updated_at='2026-03-02T05:30:00.123456+05:30')
        later_issue_id=self.issue('chronologicalneedle',updated_at='2026-03-02 00:00:00.123456')
        older_update=self.update(parent,'chronologicalneedle',updated_at='2026-03-02 00:00:00.123455')
        malformed=self.issue('chronologicalneedle',updated_at='invalid timestamp')
        expected=[('update',newest),('issue',later_issue_id),('issue',equal_issue),('update',equal_update),('update',older_update),('issue',legacy),('issue',malformed)]
        actual=[];offset=0
        while offset is not None:
            page=self.find('chronologicalneedle',offset=offset,limit=2)
            self.assertEqual(page['total'],len(expected))
            actual.extend((row['type'],row['id']) for row in page['items'])
            offset=page['next_offset']
        self.assertEqual(actual,expected)
        self.assertEqual(self.find('chronologicalneedle',since='2026-03-02T00:00:00.123456Z')['total'],4)
        self.assertIsNone(self.find('chronologicalneedle')['items'][-1]['updated_at'])

    def test_since_rejects_precision_loss_and_preserves_latest_supported_instant(self):
        iid=self.issue('lastinstant',created_at='9999-12-31 23:59:59.999999',updated_at='9999-12-31 23:59:59.999999')
        result=self.find('lastinstant',since='9999-12-31T23:59:59.999999Z')
        self.assertEqual([row['id'] for row in result['items']],[iid])
        self.assertEqual(result['items'][0]['updated_at'],'9999-12-31T23:59:59.999999Z')
        for since in ('2026-01-01T00:00:00.1234567Z','2026-01-01T00:00:00,1234567Z','0001-01-01T00:00:00+14:00'):
            with self.subTest(since=since),self.assertRaises(ApplicationError) as caught:
                self.find('lastinstant',since=since)
            self.assertEqual(caught.exception.code,'invalid_search_since')

    def test_insert_update_delete_and_issue_cascade_update_index(self):
        issue=self.issue('Oldword','oldword')
        update=self.update(issue,'oldword')
        self.assertEqual({row['type'] for row in self.find('oldword')['items']},{'issue','update'})
        self.db.execute("UPDATE issues SET title='newword',description='newword' WHERE id=?",(issue,))
        self.db.execute("UPDATE issue_updates SET content='newword' WHERE id=?",(update,))
        self.assertEqual(self.find('oldword')['total'],0)
        self.assertEqual(self.find('newword')['total'],2)
        self.db.execute('DELETE FROM issue_updates WHERE id=?',(update,))
        self.assertEqual(self.find('newword')['total'],1)
        self.update(issue,'newword')
        self.db.execute('DELETE FROM issues WHERE id=?',(issue,))
        self.assertEqual(self.find('newword')['total'],0)
        self.db.execute("INSERT INTO search_fts(search_fts,rank) VALUES('integrity-check',1)")
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_runtime_metadata_joins_do_not_index_parent_title_as_update(self):
        issue=self.issue('SecretParentTitle')
        update=self.update(issue,'needle')
        self.assertEqual(self.find('SecretParentTitle',types=['update'])['total'],0)
        self.db.execute("UPDATE issues SET title='Renamed' WHERE id=?",(issue,))
        self.db.execute("UPDATE users SET username='renamed-author' WHERE id=3")
        hit=self.find('needle')['items'][0]
        self.assertEqual((hit['title'],hit['user']),('Renamed','renamed-author'))
        self.db.execute('DELETE FROM users WHERE id=3')
        self.assertIsNone(self.find('needle')['items'][0]['user_id'])
        self.assertEqual(self.find('needle')['items'][0]['update_id'],update)

    def test_every_active_user_reads_and_stale_activity_is_rejected_even_for_empty_query(self):
        self.issue(description='needle')
        self.assertEqual(search.search_content(self.db,self.admin,'needle'),self.find('needle'))
        self.db.execute('UPDATE users SET is_active=0 WHERE id=2')
        for query in ('needle',''):
            with self.subTest(query=query),self.assertRaises(ApplicationError) as caught:
                self.find(query)
            self.assertEqual(caught.exception.status_code,401)
        with self.assertRaises(ApplicationError):search.search_content(self.db,{'id':True},'needle')

    def test_current_mcp_token_and_kill_switch_apply_to_common_service(self):
        self.issue(description='needle');self.db.commit()
        plain,token_id=auth.create_mcp_token('Search identity',1)
        current=auth.validate_mcp_bearer(plain)
        self.assertEqual(search.search_content(self.db,current,'needle')['total'],1)
        self.assertEqual(search.search_content(self.db,current,'needle'),self.find('needle'))
        self.db.execute('UPDATE mcp_config SET enabled=0 WHERE id=1');self.db.commit()
        with self.assertRaises(ApplicationError):search.search_content(self.db,current,'needle')
        self.db.execute('UPDATE mcp_config SET enabled=1 WHERE id=1');self.db.commit()
        auth.revoke_mcp_token(token_id)
        with self.assertRaises(ApplicationError):search.search_content(self.db,current,'')

    def test_backfill_missing_trigger_repair_and_transaction_rollback(self):
        self.db.execute('DROP TRIGGER search_issues_ai')
        issue=self.issue(description='backfilled')
        self.assertEqual(self.find('backfilled')['total'],0)
        search.initialize_search_index(self.db)
        self.assertEqual(self.find('backfilled')['total'],1)
        self.issue(description='newindexed')
        self.assertEqual(self.find('newindexed')['total'],1)
        self.db.commit()
        self.db.execute("UPDATE issues SET description='rollbackword' WHERE id=?",(issue,))
        search.rebuild_search_index(self.db)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.find('rollbackword')['total'],1)
        self.db.rollback()
        self.assertEqual(self.find('rollbackword')['total'],0)
        self.assertEqual(self.find('backfilled')['total'],1)
        search.rebuild_search_index(self.db)
        self.assertEqual(self.find('backfilled')['total'],1)

    def test_initialization_idempotent_and_does_not_index_attachment_names(self):
        issue=self.issue(description='needle');self.update(issue,'needle')
        self.db.execute("INSERT INTO attachments(issue_id,storage_name,original_name,media_type,size,uploader_id) VALUES(?, 'unique','attachmentonlyword.msg','application/octet-stream',0,1)",(issue,))
        self.db.commit()
        database.init_db();database.init_db()
        self.assertEqual(self.find('needle')['total'],2)
        self.assertEqual(self.find('attachmentonlyword')['total'],0)
        self.assertEqual(self.db.execute('SELECT version FROM search_index_meta').fetchone()[0],2)

    def test_invalid_filters_and_queries_return_structured_errors(self):
        cases=[({'limit':0},'invalid_search_limit'),({'limit':True},'invalid_search_limit'),({'limit':201},'invalid_search_limit'),({'offset':-1},'invalid_search_offset'),({'offset':2**64},'invalid_search_offset'),({'issue_id':2**64},'invalid_issue_id'),({'issue_id':True},'invalid_issue_id'),({'types':['handoff']},'invalid_search_types'),({'types':'issue'},'invalid_search_types')]
        for options,code in cases:
            with self.subTest(options=options),self.assertRaises(ApplicationError) as caught:self.find('needle',**options)
            self.assertEqual(caught.exception.code,code)
        for query in ('"unterminated','needle\x00','a'*1001,'(needle)','**'):
            with self.subTest(query=query[:20]),self.assertRaises(ApplicationError) as caught:self.find(query)
            self.assertEqual(caught.exception.code,'invalid_search_query')
        self.assertEqual(self.find('')['total'],0)
        self.assertEqual(self.find('needle',types=[])['total'],0)

    def test_missing_fts_is_explicit_and_failed_reinitialization_rolls_back(self):
        self.issue(description='preservedneedle');self.db.commit()
        self.db.execute('DROP TRIGGER search_issues_ai');self.db.commit()
        connection=self.db
        class MissingFts:
            def execute(self,sql,*args):
                if sql.startswith('CREATE VIRTUAL TABLE'):
                    raise sqlite3.OperationalError('no such module: fts5')
                return connection.execute(sql,*args)
        with self.assertRaisesRegex(RuntimeError,'FTS5'):
            search.initialize_search_index(MissingFts())
        self.assertEqual(self.find('preservedneedle')['total'],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM issues').fetchone()[0],1)
        search.initialize_search_index(self.db)
        self.db.execute('DROP TABLE search_fts')
        with self.assertRaises(ApplicationError) as caught:self.find('preservedneedle')
        self.assertEqual((caught.exception.status_code,caught.exception.code),(503,'search_unavailable'))

    def test_real_rest_auth_filters_and_service_parity(self):
        issue=self.issue(description='Sharedneedle')
        update=self.update(issue,'Sharedneedle',updated_at='2026-10-19 14:30:00.123456')
        self.update(issue,'Sharedneedle',updated_at='2026-10-19 14:30:00.123455')
        since='2026-10-19T16:30:00.123456+02:00'
        self.db.commit()
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/search?query=Sharedneedle').status_code,401)
            client.cookies.set(auth.COOKIE_NAME,auth.sign_token(auth.create_session(2)))
            response=client.get('/api/search',params={'query':'Sharedneedle','types':'update','issue_id':issue,'limit':1,'since':since})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json(),self.find('Sharedneedle',types=['update'],issue_id=issue,limit=1,since=since))
            self.assertEqual(response.json()['items'][0]['update_id'],update)
            self.assertEqual(response.json()['total'],1)
            self.assertEqual(response.json()['items'][0]['updated_at'],'2026-10-19T14:30:00.123456Z')
            error=client.get('/api/search',params={'query':'needle','types':'subtask'}).json()
            self.assertEqual(error['code'],'invalid_search_types')


if __name__=='__main__':unittest.main()
