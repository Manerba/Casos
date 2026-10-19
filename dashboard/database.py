"""Casos issue schema. Legacy Tareas databases require an explicit migration."""
import fcntl
import os
import sqlite3
from contextlib import closing
from pathlib import Path

DB_DIR = Path(os.environ.get('CASOS_DATA_DIR', Path(__file__).parent.parent / 'data'))
DB_PATH = DB_DIR / 'casos.db'
SCHEMA_VERSION = 1


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with DB_PATH.with_suffix('.db.init.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with closing(sqlite3.connect(str(DB_PATH), timeout=30)) as conn:
            _initialize_db(conn)


def _initialize_db(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables and ('schema_info' not in tables or 'issues' not in tables):
        raise RuntimeError('Existing database is not a Casos issue database. Back up database, secret and files; use a fresh CASOS_DATA_DIR. No data was deleted or migrated.')
    if tables:
        version = conn.execute('SELECT version FROM schema_info').fetchall()
        if version != [(SCHEMA_VERSION,)]:
            raise RuntimeError('Unsupported Casos database schema version; back up before upgrading.')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    # DDL and bootstrap are one transaction, so a failed first start can retry.
    schema = Path(__file__).with_name('issue_schema.sql').read_text()
    conn.execute('BEGIN IMMEDIATE')
    try:
        for statement in schema.split(';'):
            if statement.strip():
                conn.execute(statement)
        if not tables:
            conn.execute('INSERT INTO schema_info(version) VALUES (?)', (SCHEMA_VERSION,))
        if not conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            import bcrypt
            hashed = bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode()
            conn.execute("INSERT INTO users(username,password_hash,vorname,is_admin) VALUES('admin',?,'Administrator',1)", (hashed,))
        _default_templates(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _default_templates(conn):
    templates = [
        ('issue_assigned', 'Issue zugewiesen: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat dir das Issue "{issue_title}" zugewiesen.\nFälligkeit: {deadline}\nPriorität: {priority}\n\n{issue_url}'),
        ('status_change', 'Status geändert: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat den Status von "{issue_title}" auf {new_status} geändert.\n\n{issue_url}'),
        ('new_update', 'Neues Update: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat ein Update zu "{issue_title}" geschrieben.\n\n{issue_url}'),
        ('deadline_reached', 'Heute fällig: {issue_title}', 'Hallo {recipient_name},\n\nDas Issue "{issue_title}" ist heute fällig.\n\n{issue_url}'),
        ('deadline_warning', 'Bald fällig: {issue_title}', 'Hallo {recipient_name},\n\nDas Issue "{issue_title}" ist in {days_before} Tagen fällig.\n\n{issue_url}'),
        ('invite', 'Einladung zu Casos', 'Hallo {recipient_name},\n\nBenutzername: {username}\nURL: {app_url}\n\nBitte melde dich an und ändere dein Passwort.'),
        ('test', 'Testmail von Casos', 'Dies ist eine Testmail von Casos.'),
    ]
    conn.executemany('INSERT OR IGNORE INTO mail_templates(event_type,subject,body_text) VALUES(?,?,?)', templates)
