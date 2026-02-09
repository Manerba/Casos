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

    # Default-Bereiche einfuegen (nur wenn Tabelle leer)
    cursor = conn.execute("SELECT COUNT(*) FROM areas")
    if cursor.fetchone()[0] == 0:
        for area in DEFAULT_AREAS:
            conn.execute("INSERT INTO areas (name) VALUES (?)", (area,))

    conn.commit()
    conn.close()
