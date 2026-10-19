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


class IssueInitializationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='casos-issue-init-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for key, value in {'DB_DIR': self.root, 'DB_PATH': self.root / 'casos.db'}.items():
            p = patch.object(database, key, value)
            p.start()
            self.addCleanup(p.stop)

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


if __name__ == '__main__':
    unittest.main()
