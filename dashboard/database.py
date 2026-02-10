"""
Tareas - SQLite Datenbank
Schema, Initialisierung und Verbindungsmanagement.
"""

import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DB_DIR / "tareas.db"

DEFAULT_AREAS = ["Entwicklung", "Design", "Planung", "Testing", "Allgemein"]


def get_db() -> sqlite3.Connection:
    """Liefert eine SQLite-Verbindung mit Row-Factory und Foreign Keys."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Erstellt Tabellen und Default-Daten beim App-Startup."""
    DB_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS areas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            deadline TEXT,
            priority INTEGER DEFAULT 50,
            task_type TEXT DEFAULT 'aufgabe',
            status TEXT DEFAULT 'offen',
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sub_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            area_id INTEGER REFERENCES areas(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT (datetime('now')),
            deadline TEXT,
            priority INTEGER DEFAULT 50,
            status_percent INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sub_task_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_task_id INTEGER NOT NULL REFERENCES sub_tasks(id) ON DELETE CASCADE,
            depends_on_id INTEGER NOT NULL REFERENCES sub_tasks(id) ON DELETE CASCADE,
            UNIQUE(sub_task_id, depends_on_id)
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            vorname TEXT DEFAULT '',
            nachname TEXT DEFAULT '',
            email TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );
    """)

    # Migrationen: Spalten hinzufuegen falls nicht vorhanden
    cols = [r[1] for r in conn.execute("PRAGMA table_info(sub_tasks)").fetchall()]

    if "description" not in cols:
        conn.execute("ALTER TABLE sub_tasks ADD COLUMN description TEXT DEFAULT ''")

    if "position_number" not in cols:
        conn.execute("ALTER TABLE sub_tasks ADD COLUMN position_number INTEGER")
        # Bestehende SubTasks nachtraeglich nummerieren (pro Projekt)
        projects = conn.execute(
            "SELECT DISTINCT project_id FROM sub_tasks"
        ).fetchall()
        for (pid,) in projects:
            rows = conn.execute(
                "SELECT id FROM sub_tasks WHERE project_id = ? ORDER BY created_at ASC, id ASC",
                (pid,),
            ).fetchall()
            for i, (sid,) in enumerate(rows, start=1):
                conn.execute(
                    "UPDATE sub_tasks SET position_number = ? WHERE id = ?", (i, sid)
                )

    # Migration: created_by fuer tasks
    task_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "created_by" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN created_by INTEGER REFERENCES users(id)")

    # Migration: assigned_to fuer tasks
    if "assigned_to" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_to INTEGER REFERENCES users(id)")

    # Migration: created_by und assigned_to fuer sub_tasks
    sub_cols = [r[1] for r in conn.execute("PRAGMA table_info(sub_tasks)").fetchall()]
    if "created_by" not in sub_cols:
        conn.execute("ALTER TABLE sub_tasks ADD COLUMN created_by INTEGER REFERENCES users(id)")
    if "assigned_to" not in sub_cols:
        conn.execute("ALTER TABLE sub_tasks ADD COLUMN assigned_to INTEGER REFERENCES users(id)")

    # Migration: Notes-Tabellen
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS task_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(task_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS sub_task_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_task_id INTEGER NOT NULL REFERENCES sub_tasks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(sub_task_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS project_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            can_read INTEGER DEFAULT 1,
            can_edit INTEGER DEFAULT 0,
            can_create INTEGER DEFAULT 0,
            added_at TEXT DEFAULT (datetime('now')),
            UNIQUE(project_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS subtask_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_task_id INTEGER NOT NULL REFERENCES sub_tasks(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            can_read INTEGER DEFAULT 1,
            can_edit INTEGER DEFAULT 0,
            added_at TEXT DEFAULT (datetime('now')),
            UNIQUE(sub_task_id, user_id)
        );
    """)

    # Default-Bereiche einfuegen (nur wenn Tabelle leer)
    cursor = conn.execute("SELECT COUNT(*) FROM areas")
    if cursor.fetchone()[0] == 0:
        for area in DEFAULT_AREAS:
            conn.execute("INSERT INTO areas (name) VALUES (?)", (area,))

    # Default-Admin anlegen (nur wenn keine User vorhanden)
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        import bcrypt
        hashed = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password_hash, vorname, nachname, is_admin) VALUES (?, ?, ?, ?, ?)",
            ("admin", hashed, "Administrator", "", 1),
        )

    conn.commit()
    conn.close()
