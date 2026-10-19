"""Casos issue schema. Legacy Tareas databases require an explicit migration."""
import fcntl
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

DB_DIR = Path(os.environ.get('CASOS_DATA_DIR', Path(__file__).parent.parent / 'data'))
DB_PATH = DB_DIR / 'casos.db'
SCHEMA_VERSION = 2


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
        if version not in ([(1,)], [(SCHEMA_VERSION,)]):
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
        _migrate_event_names(conn)
        # Preserve schema1 notification opt-outs under the Issue event name.
        conn.execute("INSERT OR IGNORE INTO user_mail_preferences(user_id,event_type,enabled,days_before) "
                     "SELECT user_id,'issue_assigned',enabled,days_before FROM user_mail_preferences "
                     "WHERE event_type='task_assigned'")
        conn.execute('UPDATE schema_info SET version = ?', (SCHEMA_VERSION,))
        from dashboard.search_service import initialize_search_index
        initialize_search_index(conn)
        if not conn.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            import bcrypt
            hashed = bcrypt.hashpw(b'admin', bcrypt.gensalt()).decode()
            conn.execute("INSERT INTO users(username,password_hash,vorname,is_admin) VALUES('admin',?,'Administrator',1)", (hashed,))
        _default_templates(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate_event_names(conn):
    """Schema1 ->2 preserves IDs/content and snapshots still-resolvable names."""
    columns = {row[1] for row in conn.execute('PRAGMA table_info(issue_events)')}
    missing = {'actor_name', 'old_label', 'new_label'} - columns
    if not missing:
        return
    for name, declaration in (('actor_name', "TEXT NOT NULL DEFAULT ''"), ('old_label', 'TEXT'), ('new_label', 'TEXT')):
        if name in missing:
            conn.execute(f'ALTER TABLE issue_events ADD COLUMN {name} {declaration}')
    names = {row[0]: ' '.join(filter(None, (row[2], row[3]))).strip() or row[1]
             for row in conn.execute('SELECT id,username,vorname,nachname FROM users')}

    def label(value):
        try:
            uid = json.loads(value) if value is not None else None
            return (names.get(uid, f'#{uid}') if type(uid) is int else '')
        except (ValueError, TypeError):
            return ''

    for eid, actor, kind, old, new in conn.execute('SELECT id,actor_id,event_type,old_value,new_value FROM issue_events').fetchall():
        conn.execute('UPDATE issue_events SET actor_name=?,old_label=?,new_label=? WHERE id=?',
                     (names.get(actor, f'#{actor}' if actor else ''), label(old) if kind == 'assignment' else None,
                      label(new) if kind == 'assignment' else None, eid))


def _default_templates(conn):
    templates = [
        ('issue_assigned', 'Zuweisung geändert: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat die Zuweisung des Issues "{issue_title}" von {old_assignee} auf {new_assignee} geändert.\nFälligkeit: {deadline}\nPriorität: {priority}\n\n{issue_url}'),
        ('status_change', 'Status geändert: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat den Status von "{issue_title}" auf {new_status} geändert.\n\n{issue_url}'),
        ('new_update', 'Neues Update: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat ein Update zu "{issue_title}" geschrieben.\n\n{update_url}'),
        ('deadline_reached', 'Heute fällig: {issue_title}', 'Hallo {recipient_name},\n\nDas Issue "{issue_title}" ist heute fällig.\n\n{issue_url}'),
        ('deadline_warning', 'Bald fällig: {issue_title}', 'Hallo {recipient_name},\n\nDas Issue "{issue_title}" ist in {days_before} Tagen fällig.\n\n{issue_url}'),
        ('invite', 'Einladung zu Casos', 'Hallo {recipient_name},\n\nBenutzername: {username}\nURL: {app_url}\n\nBitte melde dich an und ändere dein Passwort.'),
        ('test', 'Testmail von Casos', 'Dies ist eine Testmail von Casos.'),
    ]
    conn.executemany('INSERT OR IGNORE INTO mail_templates(event_type,subject,body_text) VALUES(?,?,?)', templates)
    # Only replace exact former defaults; administrator customizations survive.
    previous = {
        'issue_assigned': ('Issue zugewiesen: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat dir das Issue "{issue_title}" zugewiesen.\nFälligkeit: {deadline}\nPriorität: {priority}\n\n{issue_url}'),
        'new_update': ('Neues Update: {issue_title}', 'Hallo {recipient_name},\n\n{actor_name} hat ein Update zu "{issue_title}" geschrieben.\n\n{issue_url}'),
    }
    for event, subject, body in templates:
        if event in previous:
            old_subject, old_body = previous[event]
            conn.execute('UPDATE mail_templates SET subject=?,body_text=? WHERE event_type=? AND subject=? AND body_text=?',
                         (subject, body, event, old_subject, old_body))
