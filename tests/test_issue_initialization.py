"""Fresh issue schema, restart, concurrency and preservation of unknown databases."""
import multiprocessing
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from dashboard import database


def initialize_worker(directory):
    database.DB_DIR = Path(directory)
    database.DB_PATH = Path(directory) / 'casos.db'
    database.init_db()


def paused_initializer(directory, ready, results, pause_prefix=None, paused=None, resume=None, connected=None):
    """Real separate process; pauses SQL while the initialization flock is held."""
    database.DB_DIR = Path(directory)
    database.DB_PATH = Path(directory) / 'casos.db'
    connect = sqlite3.connect

    class PausingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if pause_prefix and sql.strip().startswith(pause_prefix):
                paused.set()
                if not resume.wait(15):
                    raise TimeoutError('Paused initializer was not released')
            return super().execute(sql, *args, **kwargs)

    def connection(*args, **kwargs):
        if connected is not None:
            connected.set()
        return connect(*args, factory=PausingConnection, **kwargs)

    ready.set()
    try:
        with patch.object(database.sqlite3, 'connect', connection):
            database.init_db()
    except Exception as error:
        results.put(f'{type(error).__name__}: {error}')
    else:
        results.put(None)


class IssueInitializationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='casos-issue-init-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for key, value in {'DB_DIR': self.root, 'DB_PATH': self.root / 'casos.db'}.items():
            p = patch.object(database, key, value)
            p.start()
            self.addCleanup(p.stop)

    def _start_initializer(self, context, results, **options):
        ready = context.Event()
        process = context.Process(target=paused_initializer, args=(str(self.root), ready, results), kwargs=options)
        process.start()
        def cleanup():
            if process.is_alive():
                process.kill()
            process.join(5)
            process.close()
        self.addCleanup(cleanup)
        self.assertTrue(ready.wait(10), 'Initializer did not start')
        return process

    def test_second_initializer_waits_before_wal_setup(self):
        context = multiprocessing.get_context('spawn')
        results = context.Queue(); self.addCleanup(results.close)
        paused, resume = context.Event(), context.Event()
        first = self._start_initializer(context, results, pause_prefix='PRAGMA journal_mode=WAL', paused=paused, resume=resume)
        self.assertTrue(paused.wait(10))
        second = self._start_initializer(context, results)
        try:
            second.join(1)
            self.assertTrue(second.is_alive(), 'Second initializer bypassed the lock before WAL')
        finally:
            resume.set()
        for worker in (first, second):
            worker.join(15)
            self.assertEqual(worker.exitcode, 0)
            self.assertIsNone(results.get(timeout=2))
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_process_death_releases_lock_and_rolls_back_partial_schema(self):
        context = multiprocessing.get_context('spawn')
        results = context.Queue(); self.addCleanup(results.close)
        paused = context.Event()
        first = self._start_initializer(context, results, pause_prefix='CREATE TABLE IF NOT EXISTS issue_updates',
                                        paused=paused, resume=context.Event())
        self.assertTrue(paused.wait(10), 'Initializer did not enter schema transaction')
        first.kill(); first.join(5)
        second = self._start_initializer(context, results)
        second.join(15)
        self.assertEqual(second.exitcode, 0)
        self.assertIsNone(results.get(timeout=2))
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0], database.SCHEMA_VERSION)

    def test_initialization_error_propagates_closes_connection_and_allows_retry(self):
        connect, connections = sqlite3.connect, []
        def observed_connection(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection
        with patch.object(database.sqlite3, 'connect', observed_connection), \
                patch.object(database, '_default_templates', side_effect=sqlite3.OperationalError('injected init error')):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'injected init error'):
                database.init_db()
        self.assertEqual(len(connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute('SELECT 1')
        database.init_db()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_fresh_restart_and_foreign_keys(self):
        database.init_db()
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO issues(title,created_by) VALUES('Preserve',1)")
            db.execute("INSERT INTO issue_updates(issue_id,user_id,content) VALUES(1,1,'Keep')")
        database.init_db()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT title FROM issues').fetchone()[0], 'Preserve')
            self.assertEqual(db.execute('SELECT content FROM issue_updates').fetchone()[0], 'Keep')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(tables & {'tasks','sub_tasks','project_members','nextcloud_config','onlyoffice_config','areas'})
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO issue_updates(issue_id,content) VALUES(999,'orphan')")

    def test_legacy_and_unknown_data_are_not_changed(self):
        with closing(sqlite3.connect(database.DB_PATH)) as db, db:
            db.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,name TEXT)')
            db.execute("INSERT INTO tasks VALUES(7,'Do not delete')")
        before = database.DB_PATH.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'No data was deleted'):
            database.init_db()
        self.assertEqual(database.DB_PATH.read_bytes(), before)

    def test_parallel_first_start_and_restart(self):
        ctx = multiprocessing.get_context('spawn')
        for _ in range(2):
            workers = [ctx.Process(target=initialize_worker, args=(str(self.root),)) for _ in range(3)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(20)
                if worker.is_alive():
                    worker.kill()
                    worker.join()
                self.assertEqual(worker.exitcode, 0)
                worker.close()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM schema_info').fetchone()[0], 1)

    def test_failed_initialization_rolls_back_schema(self):
        with closing(sqlite3.connect(database.DB_PATH)) as db:
            with patch.object(database, '_default_templates', side_effect=RuntimeError('injected')):
                with self.assertRaisesRegex(RuntimeError, 'injected'):
                    database._initialize_db(db)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
        database.init_db()

    def _schema_one_with_events(self):
        database.init_db()
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO users(id,username,password_hash,vorname) VALUES(2,'alice','','Alice')")
            db.execute("INSERT INTO issues(id,title,created_by,assigned_to) VALUES(7,'Preserve event',1,2)")
            db.execute("INSERT INTO issue_updates(issue_id,user_id,content) VALUES(7,2,'Keep original markdown')")
            db.execute("INSERT INTO issue_events(id,issue_id,actor_id,event_type,old_value,new_value) VALUES(9,7,1,'assignment','null','2')")
            for name in ('actor_name','old_label','new_label'):
                db.execute('ALTER TABLE issue_events DROP COLUMN ' + name)
            db.execute('UPDATE schema_info SET version=1')
            db.execute("UPDATE mail_templates SET body_text='Custom template' WHERE event_type='issue_assigned'")
            db.execute("INSERT INTO user_mail_preferences(user_id,event_type,enabled,days_before) VALUES(1,'task_assigned',0,7),(2,'task_assigned',0,5),(2,'issue_assigned',1,3)")

    def test_schema_one_upgrade_preserves_data_and_custom_templates(self):
        self._schema_one_with_events()
        database.init_db()
        database.init_db()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0],2)
            event=db.execute('SELECT * FROM issue_events WHERE id=9').fetchone()
            self.assertEqual((event['issue_id'],event['actor_id'],event['old_value'],event['new_value']),(7,1,'null','2'))
            self.assertEqual((event['actor_name'],event['old_label'],event['new_label']),('Administrator','','Alice'))
            self.assertEqual(db.execute('SELECT content FROM issue_updates').fetchone()[0],'Keep original markdown')
            self.assertEqual(db.execute("SELECT body_text FROM mail_templates WHERE event_type='issue_assigned'").fetchone()[0],'Custom template')
            self.assertEqual([tuple(row) for row in db.execute("SELECT user_id,enabled,days_before FROM user_mail_preferences WHERE event_type='issue_assigned' ORDER BY user_id")],[(1,0,7),(2,1,3)])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_concurrent_schema_one_upgrade_waits_and_preserves_data_and_snapshots(self):
        self._schema_one_with_events()
        with closing(database.get_db()) as db:
            before = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                      for table in ('issues', 'issue_updates', 'users')}
            event_before = tuple(db.execute('SELECT * FROM issue_events WHERE id=9').fetchone())
        context = multiprocessing.get_context('spawn')
        results = context.Queue()
        def close_results():
            results.close()
            results.join_thread()
        self.addCleanup(close_results)
        paused, resume, second_connected = context.Event(), context.Event(), context.Event()
        # actor_name has already been added inside the uncommitted upgrade;
        # pausing the next ALTER exercises the migration's in-flight schema.
        first = self._start_initializer(context, results,
                                        pause_prefix='ALTER TABLE issue_events ADD COLUMN old_label',
                                        paused=paused, resume=resume)
        self.assertTrue(paused.wait(10), 'First process did not enter the schema-1 upgrade')
        try:
            with closing(database.get_db()) as db:
                self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0], 1)
                self.assertNotIn('actor_name', {row[1] for row in db.execute('PRAGMA table_info(issue_events)')})
                self.assertEqual(tuple(db.execute('SELECT * FROM issue_events WHERE id=9').fetchone()), event_before)
            second = self._start_initializer(context, results, connected=second_connected)
            second.join(1)
            self.assertTrue(second.is_alive(), 'Second initializer bypassed the pending schema upgrade')
            self.assertFalse(second_connected.is_set(), 'Second initializer opened SQLite before acquiring the process lock')
        finally:
            resume.set()
        for worker in (first, second):
            worker.join(15)
            self.assertEqual(worker.exitcode, 0, 'Concurrent schema upgrade failed or hung')
            self.assertIsNone(results.get(timeout=2))
        self.assertTrue(second_connected.is_set())
        with closing(database.get_db()) as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT version FROM schema_info')], [(2,)])
            for table, rows in before.items():
                self.assertEqual([tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')], rows)
            event = db.execute('SELECT * FROM issue_events WHERE id=9').fetchone()
            self.assertEqual(tuple(event)[:len(event_before)], event_before)
            self.assertEqual((event['actor_name'], event['old_label'], event['new_label']), ('Administrator', '', 'Alice'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issue_events').fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT body_text FROM mail_templates WHERE event_type='issue_assigned'").fetchone()[0], 'Custom template')
            self.assertEqual([tuple(row) for row in db.execute("SELECT user_id,enabled,days_before FROM user_mail_preferences WHERE event_type='issue_assigned' ORDER BY user_id")], [(1, 0, 7), (2, 1, 3)])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_schema_upgrade_failure_rolls_back_columns_version_and_content(self):
        self._schema_one_with_events()
        with patch('dashboard.search_service.initialize_search_index',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                database.init_db()
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone()[0],1)
            self.assertNotIn('actor_name',{r[1] for r in db.execute('PRAGMA table_info(issue_events)')})
            self.assertEqual(db.execute('SELECT new_value FROM issue_events WHERE id=9').fetchone()[0],'2')
        database.init_db()

    def test_future_schema_version_is_rejected_without_changes(self):
        database.init_db()
        with closing(database.get_db()) as db,db:
            db.execute('UPDATE schema_info SET version=900')
        before=database.DB_PATH.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'Unsupported'):
            database.init_db()
        self.assertEqual(database.DB_PATH.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
