"""
Tareas - MCP-Server (Model Context Protocol)

Exponiert Tareas-Funktionen als MCP-Tools fuer remote Claude-Code-Instanzen.
Mountet sich an /mcp/ in app.py via FastMCP.http_app().

Authentifizierung: Bearer-Token (Middleware in app.py setzt current_mcp_user
ContextVar). Jeder MCP-User ist ein eigener Eintrag in der users-Tabelle mit
auth_source='mcp'.

Persistenz: direkter Zugriff auf SQLite (selbe DB wie REST-API), Schreib-Ops
laufen via audit_log.log_change(...) ins Audit.
"""

import logging
from contextvars import ContextVar

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from dashboard.agent_guide import build_agent_guide_markdown, build_agent_metadata
from dashboard.audit_log import log_change, diff_fields
from dashboard.db_utils import db_query, db_transaction
from dashboard.task_types import normalize_task_type

logger = logging.getLogger(__name__)

# Wird von der MCP-Auth-Middleware in app.py pro Request gesetzt.
current_mcp_user: ContextVar[dict | None] = ContextVar("current_mcp_user", default=None)


def _user() -> dict:
    """Aktuellen MCP-User aus dem Request-Kontext holen."""
    u = current_mcp_user.get()
    if not u:
        raise ToolError("MCP-User-Kontext fehlt (Bearer-Token nicht akzeptiert?)")
    return u


# ============================================================
# Row-Serialisierung
# ============================================================

def _task_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "status": row["status"],
        "priority": row["priority"],
        "task_type": row["task_type"],
        "deadline": row["deadline"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "assigned_to": row["assigned_to"],
        "nextcloud_path": row["nextcloud_path"] if "nextcloud_path" in row.keys() else None,
    }


def _subtask_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "description": row["description"] or "",
        "area_id": row["area_id"],
        "deadline": row["deadline"],
        "priority": row["priority"],
        "status_percent": row["status_percent"],
        "position_number": row["position_number"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "assigned_to": row["assigned_to"],
        "depends_on_project": bool(row["depends_on_project"]) if row["depends_on_project"] is not None else False,
    }


def _ordered_subtask_rows(db, project_id: int) -> list:
    return db.execute(
        """SELECT id, position_number FROM sub_tasks
           WHERE project_id = ?
           ORDER BY
               CASE WHEN position_number IS NULL THEN 1 ELSE 0 END,
               position_number ASC,
               created_at ASC,
               id ASC""",
        (project_id,),
    ).fetchall()


def _renumber_project_subtasks(db, ordered_ids: list[int]) -> dict[int, int]:
    new_positions: dict[int, int] = {}
    for pos, sid in enumerate(ordered_ids, start=1):
        db.execute("UPDATE sub_tasks SET position_number = ? WHERE id = ?", (pos, sid))
        new_positions[sid] = pos
    return new_positions


def _subtask_with_predecessors(db, subtask_id: int) -> dict:
    row = db.execute("SELECT * FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
    if not row:
        raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")
    preds = db.execute(
        "SELECT depends_on_id FROM sub_task_dependencies WHERE sub_task_id = ?",
        (subtask_id,),
    ).fetchall()
    result = _subtask_to_dict(row)
    result["predecessor_ids"] = [p["depends_on_id"] for p in preds]
    return result


# ============================================================
# FastMCP-Instanz
# ============================================================

mcp = FastMCP(
    name="Tareas",
    instructions=(
        "Tareas-Aufgabenverwaltung. Du bist als eigener MCP-User in der DB "
        "registriert; alle Aenderungen werden im Audit-Log protokolliert. "
        "Aufgaben (Projekte) haben Teilaufgaben (Subtasks) mit optionalen "
        "Abhaengigkeiten. Felder: description = Spec/Anforderung, notes = "
        "aktuelle User-Notiz, note_entries = chronologische Handoffs/Findings."
    ),
)


@mcp.tool
def get_agent_guide() -> dict:
    """Liefert die tokenfreie Tareas-Nutzungsanleitung inkl. URLs und AGENTS.md-Snippet."""
    metadata = build_agent_metadata()
    return {
        "metadata": metadata,
        "markdown": build_agent_guide_markdown(metadata),
    }


# ============================================================
# Projekte (Tasks)
# ============================================================

@mcp.tool
def list_projects(status: str | None = None) -> list[dict]:
    """Listet alle Projekte (Top-Level-Aufgaben). Optionaler Statusfilter (z.B. 'offen', 'erledigt')."""
    with db_query() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY priority DESC, created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM tasks ORDER BY priority DESC, created_at DESC"
            ).fetchall()
        return [_task_to_dict(r) for r in rows]


@mcp.tool
def get_project(project_id: int) -> dict:
    """Holt ein Projekt inkl. aller Subtasks und ihrer Abhaengigkeiten in einem Call."""
    with db_query() as db:
        task = db.execute("SELECT * FROM tasks WHERE id = ?", (project_id,)).fetchone()
        if not task:
            raise ToolError(f"Projekt {project_id} nicht gefunden")
        subs = db.execute(
            "SELECT * FROM sub_tasks WHERE project_id = ? ORDER BY position_number ASC, id ASC",
            (project_id,),
        ).fetchall()
        deps = db.execute(
            """SELECT sub_task_id, depends_on_id FROM sub_task_dependencies
               WHERE sub_task_id IN (SELECT id FROM sub_tasks WHERE project_id = ?)""",
            (project_id,),
        ).fetchall()
        dep_map: dict[int, list[int]] = {}
        for d in deps:
            dep_map.setdefault(d["sub_task_id"], []).append(d["depends_on_id"])

        result = _task_to_dict(task)
        result["subtasks"] = []
        for s in subs:
            st = _subtask_to_dict(s)
            st["predecessor_ids"] = dep_map.get(s["id"], [])
            result["subtasks"].append(st)
        return result


@mcp.tool
def create_project(
    name: str,
    description: str = "",
    deadline: str | None = None,
    priority: int = 50,
    status: str = "offen",
    task_type: str = "projekt",
) -> dict:
    """Legt ein neues Projekt an. Gibt das angelegte Projekt-Dict (mit id) zurueck."""
    user = _user()
    if not name.strip():
        raise ToolError("name darf nicht leer sein")
    try:
        task_type = normalize_task_type(task_type)
    except ValueError as exc:
        raise ToolError(str(exc))
    with db_transaction() as db:
        cursor = db.execute(
            """INSERT INTO tasks (name, description, deadline, priority, status, task_type, created_by, assigned_to)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name.strip(), description, deadline, priority, status, task_type, user["id"], user["id"]),
        )
        task_id = cursor.lastrowid
        row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    log_change(user, "task", task_id, "create", {
        "name": name, "description": description, "priority": priority,
        "status": status, "task_type": task_type, "deadline": deadline,
    })
    return _task_to_dict(row)


@mcp.tool
def update_project(
    project_id: int,
    name: str | None = None,
    description: str | None = None,
    deadline: str | None = None,
    priority: int | None = None,
    status: str | None = None,
    assigned_to: int | None = None,
) -> dict:
    """Aktualisiert ein Projekt. Nur uebergebene Felder werden geaendert."""
    user = _user()
    with db_transaction() as db:
        before = db.execute("SELECT * FROM tasks WHERE id = ?", (project_id,)).fetchone()
        if not before:
            raise ToolError(f"Projekt {project_id} nicht gefunden")
        updates, values = [], []
        new_vals = {}
        if name is not None:
            updates.append("name = ?"); values.append(name); new_vals["name"] = name
        if description is not None:
            updates.append("description = ?"); values.append(description); new_vals["description"] = description
        if deadline is not None:
            updates.append("deadline = ?"); values.append(deadline); new_vals["deadline"] = deadline
        if priority is not None:
            updates.append("priority = ?"); values.append(priority); new_vals["priority"] = priority
        if status is not None:
            updates.append("status = ?"); values.append(status); new_vals["status"] = status
        if assigned_to is not None:
            if assigned_to == 0:
                updates.append("assigned_to = NULL"); new_vals["assigned_to"] = None
            else:
                updates.append("assigned_to = ?"); values.append(assigned_to); new_vals["assigned_to"] = assigned_to
        if not updates:
            raise ToolError("Keine Felder zum Aktualisieren angegeben")
        values.append(project_id)
        db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)
        after = db.execute("SELECT * FROM tasks WHERE id = ?", (project_id,)).fetchone()
    changes = diff_fields(dict(before), {**dict(before), **new_vals}, list(new_vals.keys()))
    log_change(user, "task", project_id, "update", changes)
    return _task_to_dict(after)


@mcp.tool
def delete_project(project_id: int) -> dict:
    """Loescht ein Projekt inkl. aller Subtasks (CASCADE)."""
    user = _user()
    with db_transaction() as db:
        row = db.execute("SELECT id, name FROM tasks WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise ToolError(f"Projekt {project_id} nicht gefunden")
        db.execute("DELETE FROM tasks WHERE id = ?", (project_id,))
    log_change(user, "task", project_id, "delete", {"name": row["name"]})
    return {"deleted": True, "id": project_id}


# ============================================================
# Teilaufgaben (SubTasks)
# ============================================================

@mcp.tool
def list_subtasks(project_id: int) -> list[dict]:
    """Listet alle Teilaufgaben eines Projekts inkl. predecessor_ids."""
    with db_query() as db:
        if not db.execute("SELECT id FROM tasks WHERE id = ?", (project_id,)).fetchone():
            raise ToolError(f"Projekt {project_id} nicht gefunden")
        subs = db.execute(
            "SELECT * FROM sub_tasks WHERE project_id = ? ORDER BY position_number ASC, id ASC",
            (project_id,),
        ).fetchall()
        deps = db.execute(
            """SELECT sub_task_id, depends_on_id FROM sub_task_dependencies
               WHERE sub_task_id IN (SELECT id FROM sub_tasks WHERE project_id = ?)""",
            (project_id,),
        ).fetchall()
        dep_map: dict[int, list[int]] = {}
        for d in deps:
            dep_map.setdefault(d["sub_task_id"], []).append(d["depends_on_id"])
        result = []
        for s in subs:
            st = _subtask_to_dict(s)
            st["predecessor_ids"] = dep_map.get(s["id"], [])
            result.append(st)
        return result


@mcp.tool
def get_subtask(subtask_id: int) -> dict:
    """Holt eine einzelne Teilaufgabe inkl. predecessor_ids."""
    with db_query() as db:
        row = db.execute("SELECT * FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
        if not row:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")
        preds = db.execute(
            "SELECT depends_on_id FROM sub_task_dependencies WHERE sub_task_id = ?",
            (subtask_id,),
        ).fetchall()
        st = _subtask_to_dict(row)
        st["predecessor_ids"] = [p["depends_on_id"] for p in preds]
        return st


@mcp.tool
def create_subtask(
    project_id: int,
    name: str,
    description: str = "",
    area_id: int | None = None,
    deadline: str | None = None,
    priority: int = 50,
    status_percent: int = 0,
    predecessor_ids: list[int] | None = None,
    assigned_to: int | None = None,
    depends_on_project: bool = False,
) -> dict:
    """Legt eine Teilaufgabe an. predecessor_ids = Liste der Vorgaenger-Subtask-IDs."""
    user = _user()
    if not name.strip():
        raise ToolError("name darf nicht leer sein")
    predecessor_ids = predecessor_ids or []
    with db_transaction() as db:
        if not db.execute("SELECT id FROM tasks WHERE id = ?", (project_id,)).fetchone():
            raise ToolError(f"Projekt {project_id} nicht gefunden")
        # naechste position_number ermitteln
        next_pos = db.execute(
            "SELECT COALESCE(MAX(position_number), 0) + 1 AS p FROM sub_tasks WHERE project_id = ?",
            (project_id,),
        ).fetchone()["p"]
        assigned = assigned_to if assigned_to is not None else user["id"]
        cursor = db.execute(
            """INSERT INTO sub_tasks
               (project_id, name, description, area_id, deadline, priority, status_percent,
                position_number, created_by, assigned_to, depends_on_project)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, name.strip(), description, area_id, deadline, priority, status_percent,
             next_pos, user["id"], assigned, 1 if depends_on_project else 0),
        )
        subtask_id = cursor.lastrowid
        for pid in predecessor_ids:
            if pid == 0:
                continue
            db.execute(
                "INSERT OR IGNORE INTO sub_task_dependencies (sub_task_id, depends_on_id) VALUES (?, ?)",
                (subtask_id, pid),
            )
        row = db.execute("SELECT * FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
    log_change(user, "sub_task", subtask_id, "create", {
        "project_id": project_id, "name": name, "description": description,
        "priority": priority, "deadline": deadline,
        "predecessor_ids": predecessor_ids, "assigned_to": assigned,
    })
    result = _subtask_to_dict(row)
    result["predecessor_ids"] = predecessor_ids
    return result


@mcp.tool
def update_subtask(
    subtask_id: int,
    name: str | None = None,
    description: str | None = None,
    area_id: int | None = None,
    deadline: str | None = None,
    priority: int | None = None,
    status_percent: int | None = None,
    assigned_to: int | None = None,
    predecessor_ids: list[int] | None = None,
) -> dict:
    """Aktualisiert eine Teilaufgabe. Nur uebergebene Felder werden geaendert.
    predecessor_ids ersetzt KOMPLETT die bestehenden Vorgaenger."""
    user = _user()
    with db_transaction() as db:
        before = db.execute("SELECT * FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
        if not before:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")
        updates, values = [], []
        new_vals: dict = {}
        if name is not None:
            updates.append("name = ?"); values.append(name); new_vals["name"] = name
        if description is not None:
            updates.append("description = ?"); values.append(description); new_vals["description"] = description
        if area_id is not None:
            updates.append("area_id = ?"); values.append(area_id); new_vals["area_id"] = area_id
        if deadline is not None:
            updates.append("deadline = ?"); values.append(deadline); new_vals["deadline"] = deadline
        if priority is not None:
            updates.append("priority = ?"); values.append(priority); new_vals["priority"] = priority
        if status_percent is not None:
            updates.append("status_percent = ?"); values.append(status_percent); new_vals["status_percent"] = status_percent
        if assigned_to is not None:
            if assigned_to == 0:
                updates.append("assigned_to = NULL"); new_vals["assigned_to"] = None
            else:
                updates.append("assigned_to = ?"); values.append(assigned_to); new_vals["assigned_to"] = assigned_to
        if updates:
            values.append(subtask_id)
            db.execute(f"UPDATE sub_tasks SET {', '.join(updates)} WHERE id = ?", values)
        if predecessor_ids is not None:
            db.execute("DELETE FROM sub_task_dependencies WHERE sub_task_id = ?", (subtask_id,))
            has_project_dep = 0 in predecessor_ids
            db.execute(
                "UPDATE sub_tasks SET depends_on_project = ? WHERE id = ?",
                (1 if has_project_dep else 0, subtask_id),
            )
            for pid in predecessor_ids:
                if pid == 0:
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO sub_task_dependencies (sub_task_id, depends_on_id) VALUES (?, ?)",
                    (subtask_id, pid),
                )
            new_vals["predecessor_ids"] = predecessor_ids
        after = db.execute("SELECT * FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
        preds = db.execute(
            "SELECT depends_on_id FROM sub_task_dependencies WHERE sub_task_id = ?",
            (subtask_id,),
        ).fetchall()
    changes = {k: {"old": before[k] if k in before.keys() else None, "new": v} for k, v in new_vals.items()}
    log_change(user, "sub_task", subtask_id, "update", changes)
    result = _subtask_to_dict(after)
    result["predecessor_ids"] = [p["depends_on_id"] for p in preds]
    return result


@mcp.tool
def delete_subtask(subtask_id: int) -> dict:
    """Loescht eine Teilaufgabe."""
    user = _user()
    with db_transaction() as db:
        row = db.execute("SELECT id, name, project_id FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
        if not row:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")
        db.execute("DELETE FROM sub_tasks WHERE id = ?", (subtask_id,))
    log_change(user, "sub_task", subtask_id, "delete", {
        "name": row["name"], "project_id": row["project_id"],
    })
    return {"deleted": True, "id": subtask_id}


@mcp.tool
def move_subtask(subtask_id: int, direction: str) -> dict:
    """Verschiebt eine Teilaufgabe um eine Position. direction muss 'up' oder 'down' sein.
    Abhaengigkeiten bleiben dabei unveraendert."""
    user = _user()
    direction = (direction or "").strip().lower()
    if direction not in {"up", "down"}:
        raise ToolError("direction muss 'up' oder 'down' sein")

    with db_transaction() as db:
        current = db.execute(
            "SELECT id, project_id, position_number FROM sub_tasks WHERE id = ?",
            (subtask_id,),
        ).fetchone()
        if not current:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")

        rows = _ordered_subtask_rows(db, current["project_id"])
        ordered_ids = [row["id"] for row in rows]
        try:
            old_index = ordered_ids.index(subtask_id)
        except ValueError:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")

        target_index = old_index - 1 if direction == "up" else old_index + 1
        if target_index < 0 or target_index >= len(ordered_ids):
            result = _subtask_with_predecessors(db, subtask_id)
            return {
                "moved": False,
                "message": "Bereits am Rand",
                "subtask": result,
                "old_position": old_index + 1,
                "new_position": old_index + 1,
                "new_positions": {row["id"]: row["position_number"] for row in rows},
                "removed_dependencies": [],
            }

        swapped_with = ordered_ids[target_index]
        ordered_ids[old_index], ordered_ids[target_index] = ordered_ids[target_index], ordered_ids[old_index]
        new_positions = _renumber_project_subtasks(db, ordered_ids)
        result = _subtask_with_predecessors(db, subtask_id)

    log_change(user, "sub_task", subtask_id, "move", {
        "direction": direction,
        "old_position": old_index + 1,
        "new_position": target_index + 1,
        "old_position_number": current["position_number"],
        "swapped_with": swapped_with,
        "new_positions": new_positions,
        "dependencies_preserved": True,
    })
    return {
        "moved": True,
        "message": "Position geaendert",
        "subtask": result,
        "swapped_with": swapped_with,
        "old_position": old_index + 1,
        "new_position": target_index + 1,
        "new_positions": new_positions,
        "removed_dependencies": [],
        "dependencies_preserved": True,
    }


@mcp.tool
def set_subtask_position(subtask_id: int, position_number: int) -> dict:
    """Setzt eine Teilaufgabe auf eine absolute 1-basierte Position innerhalb ihres Projekts.
    Zu grosse Positionswerte werden auf die letzte Position geklemmt. Abhaengigkeiten bleiben unveraendert."""
    user = _user()
    if position_number is None or position_number < 1:
        raise ToolError("position_number muss groesser oder gleich 1 sein")

    with db_transaction() as db:
        current = db.execute(
            "SELECT id, project_id, position_number FROM sub_tasks WHERE id = ?",
            (subtask_id,),
        ).fetchone()
        if not current:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")

        rows = _ordered_subtask_rows(db, current["project_id"])
        ordered_ids = [row["id"] for row in rows]
        try:
            old_index = ordered_ids.index(subtask_id)
        except ValueError:
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")

        ordered_ids.pop(old_index)
        target_index = min(position_number, len(rows)) - 1
        ordered_ids.insert(target_index, subtask_id)
        new_positions = _renumber_project_subtasks(db, ordered_ids)
        result = _subtask_with_predecessors(db, subtask_id)

    new_position = new_positions[subtask_id]
    moved = old_index + 1 != new_position or current["position_number"] != new_position
    log_change(user, "sub_task", subtask_id, "move", {
        "requested_position": position_number,
        "old_position": old_index + 1,
        "new_position": new_position,
        "old_position_number": current["position_number"],
        "new_positions": new_positions,
        "dependencies_preserved": True,
    })
    return {
        "moved": moved,
        "message": "Position geaendert",
        "subtask": result,
        "requested_position": position_number,
        "old_position": old_index + 1,
        "new_position": new_position,
        "new_positions": new_positions,
        "removed_dependencies": [],
        "dependencies_preserved": True,
    }


# ============================================================
# Abhaengigkeiten
# ============================================================

@mcp.tool
def add_dependency(subtask_id: int, depends_on_id: int) -> dict:
    """Fuegt eine Abhaengigkeit hinzu: subtask_id wartet auf depends_on_id.
    depends_on_id=0 bedeutet 'haengt vom Projektknoten ab'."""
    user = _user()
    with db_transaction() as db:
        if not db.execute("SELECT id FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone():
            raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")
        if depends_on_id == 0:
            db.execute(
                "UPDATE sub_tasks SET depends_on_project = 1 WHERE id = ?",
                (subtask_id,),
            )
        else:
            if not db.execute("SELECT id FROM sub_tasks WHERE id = ?", (depends_on_id,)).fetchone():
                raise ToolError(f"Vorgaenger {depends_on_id} nicht gefunden")
            db.execute(
                "INSERT OR IGNORE INTO sub_task_dependencies (sub_task_id, depends_on_id) VALUES (?, ?)",
                (subtask_id, depends_on_id),
            )
    log_change(user, "dependency", subtask_id, "create", {"depends_on_id": depends_on_id})
    return {"added": True, "subtask_id": subtask_id, "depends_on_id": depends_on_id}


@mcp.tool
def remove_dependency(subtask_id: int, depends_on_id: int) -> dict:
    """Entfernt eine Abhaengigkeit. depends_on_id=0 entfernt die Abhaengigkeit vom Projektknoten."""
    user = _user()
    with db_transaction() as db:
        if depends_on_id == 0:
            db.execute(
                "UPDATE sub_tasks SET depends_on_project = 0 WHERE id = ?",
                (subtask_id,),
            )
        else:
            db.execute(
                "DELETE FROM sub_task_dependencies WHERE sub_task_id = ? AND depends_on_id = ?",
                (subtask_id, depends_on_id),
            )
    log_change(user, "dependency", subtask_id, "delete", {"depends_on_id": depends_on_id})
    return {"removed": True, "subtask_id": subtask_id, "depends_on_id": depends_on_id}


# ============================================================
# Notes
# ============================================================

@mcp.tool
def get_notes(task_id: int, subtask_id: int | None = None) -> list[dict]:
    """Listet Notizen einer Aufgabe oder Teilaufgabe (alle User, sortiert nach updated_at DESC).
    Wenn subtask_id gesetzt ist, werden die Notizen dieser Teilaufgabe geliefert,
    sonst die der Aufgabe (Projekt)."""
    with db_query() as db:
        if subtask_id is not None:
            rows = db.execute(
                """SELECT sn.user_id, sn.content, sn.updated_at,
                          u.vorname || ' ' || u.nachname AS user_name,
                          u.auth_source
                   FROM sub_task_notes sn
                   JOIN users u ON sn.user_id = u.id
                   WHERE sn.sub_task_id = ?
                   ORDER BY sn.updated_at DESC""",
                (subtask_id,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT tn.user_id, tn.content, tn.updated_at,
                          u.vorname || ' ' || u.nachname AS user_name,
                          u.auth_source
                   FROM task_notes tn
                   JOIN users u ON tn.user_id = u.id
                   WHERE tn.task_id = ?
                   ORDER BY tn.updated_at DESC""",
                (task_id,),
            ).fetchall()
        return [
            {
                "user_id": r["user_id"],
                "user_name": (r["user_name"] or "").strip(),
                "auth_source": r["auth_source"] or "local",
                "content": r["content"] or "",
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]


@mcp.tool
def get_note_entries(task_id: int, subtask_id: int | None = None, limit: int = 100) -> list[dict]:
    """Listet append-only Notiz-Eintraege einer Aufgabe oder Teilaufgabe.

    Fuer Handoffs, Fortschritt, Entscheidungen und Audit-Spuren verwenden.
    Neueste Eintraege werden zuerst geliefert. Wenn subtask_id gesetzt ist,
    muss sie zu task_id gehoeren.
    """
    limit = max(1, min(limit, 200))
    with db_query() as db:
        if subtask_id is not None:
            if not db.execute(
                "SELECT id FROM sub_tasks WHERE id = ? AND project_id = ?",
                (subtask_id, task_id),
            ).fetchone():
                raise ToolError(f"Teilaufgabe {subtask_id} gehoert nicht zu Projekt {task_id}")
            rows = db.execute(
                """SELECT sne.id, sne.sub_task_id, sne.user_id, sne.content, sne.created_at,
                          u.vorname || ' ' || u.nachname AS user_name,
                          u.auth_source
                   FROM sub_task_note_entries sne
                   JOIN users u ON sne.user_id = u.id
                   WHERE sne.sub_task_id = ?
                   ORDER BY sne.created_at DESC, sne.id DESC
                   LIMIT ?""",
                (subtask_id, limit),
            ).fetchall()
        else:
            if not db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone():
                raise ToolError(f"Aufgabe/Projekt {task_id} nicht gefunden")
            rows = db.execute(
                """SELECT tne.id, tne.task_id, tne.user_id, tne.content, tne.created_at,
                          u.vorname || ' ' || u.nachname AS user_name,
                          u.auth_source
                   FROM task_note_entries tne
                   JOIN users u ON tne.user_id = u.id
                   WHERE tne.task_id = ?
                   ORDER BY tne.created_at DESC, tne.id DESC
                   LIMIT ?""",
                (task_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "task_id": r["task_id"] if "task_id" in r.keys() else task_id,
                "subtask_id": r["sub_task_id"] if "sub_task_id" in r.keys() else None,
                "user_id": r["user_id"],
                "user_name": (r["user_name"] or "").strip(),
                "auth_source": r["auth_source"] or "local",
                "content": r["content"] or "",
                "created_at": r["created_at"],
            }
            for r in rows
        ]


@mcp.tool
def write_note(task_id: int, content: str, subtask_id: int | None = None) -> dict:
    """Schreibt/aktualisiert eine Notiz des aufrufenden MCP-Users an einer Aufgabe oder
    Teilaufgabe. Notizen sind per User unique; wiederholtes Schreiben ueberschreibt."""
    user = _user()
    with db_transaction() as db:
        if subtask_id is not None:
            if not db.execute(
                "SELECT id FROM sub_tasks WHERE id = ? AND project_id = ?",
                (subtask_id, task_id),
            ).fetchone():
                raise ToolError(f"Teilaufgabe {subtask_id} gehoert nicht zu Projekt {task_id}")
            db.execute(
                """INSERT INTO sub_task_notes (sub_task_id, user_id, content, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(sub_task_id, user_id) DO UPDATE SET
                       content = excluded.content, updated_at = datetime('now')""",
                (subtask_id, user["id"], content),
            )
            entity_id = subtask_id
            entity_type = "sub_task_note"
        else:
            if not db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone():
                raise ToolError(f"Aufgabe/Projekt {task_id} nicht gefunden")
            db.execute(
                """INSERT INTO task_notes (task_id, user_id, content, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(task_id, user_id) DO UPDATE SET
                       content = excluded.content, updated_at = datetime('now')""",
                (task_id, user["id"], content),
            )
            entity_id = task_id
            entity_type = "task_note"
    log_change(user, entity_type, entity_id, "update", {"content_len": len(content)})
    return {"saved": True, "task_id": task_id, "subtask_id": subtask_id}


@mcp.tool
def delete_note(task_id: int, subtask_id: int | None = None) -> dict:
    """Loescht die aktuelle eigene Upsert-Notiz des aufrufenden MCP-Users.

    Betrifft nur `task_notes` bzw. `sub_task_notes`. Append-only Eintraege aus
    `append_note` bleiben unveraendert.
    """
    user = _user()
    with db_transaction() as db:
        if subtask_id is not None:
            if not db.execute(
                "SELECT id FROM sub_tasks WHERE id = ? AND project_id = ?",
                (subtask_id, task_id),
            ).fetchone():
                raise ToolError(f"Teilaufgabe {subtask_id} gehoert nicht zu Projekt {task_id}")
            existing = db.execute(
                "SELECT id, content FROM sub_task_notes WHERE sub_task_id = ? AND user_id = ?",
                (subtask_id, user["id"]),
            ).fetchone()
            if not existing:
                return {"deleted": False, "task_id": task_id, "subtask_id": subtask_id}
            db.execute(
                "DELETE FROM sub_task_notes WHERE sub_task_id = ? AND user_id = ?",
                (subtask_id, user["id"]),
            )
            entity_id = subtask_id
            entity_type = "sub_task_note"
        else:
            if not db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone():
                raise ToolError(f"Aufgabe/Projekt {task_id} nicht gefunden")
            existing = db.execute(
                "SELECT id, content FROM task_notes WHERE task_id = ? AND user_id = ?",
                (task_id, user["id"]),
            ).fetchone()
            if not existing:
                return {"deleted": False, "task_id": task_id, "subtask_id": None}
            db.execute(
                "DELETE FROM task_notes WHERE task_id = ? AND user_id = ?",
                (task_id, user["id"]),
            )
            entity_id = task_id
            entity_type = "task_note"

    log_change(user, entity_type, entity_id, "delete", {"content_len": len(existing["content"] or "")})
    return {"deleted": True, "task_id": task_id, "subtask_id": subtask_id}


@mcp.tool
def append_note(task_id: int, content: str, subtask_id: int | None = None) -> dict:
    """Fuegt einen neuen append-only Notiz-Eintrag hinzu.

    Fuer Handoffs, Fortschritt, Entscheidungen, Testergebnisse, Gate-Notizen
    und Audit-Zusammenfassungen verwenden. Im Gegensatz zu write_note wird
    kein bestehender Inhalt desselben MCP-Users ueberschrieben.
    """
    user = _user()
    if not content.strip():
        raise ToolError("content darf nicht leer sein")

    with db_transaction() as db:
        if subtask_id is not None:
            if not db.execute(
                "SELECT id FROM sub_tasks WHERE id = ? AND project_id = ?",
                (subtask_id, task_id),
            ).fetchone():
                raise ToolError(f"Teilaufgabe {subtask_id} gehoert nicht zu Projekt {task_id}")
            cursor = db.execute(
                """INSERT INTO sub_task_note_entries (sub_task_id, user_id, content)
                   VALUES (?, ?, ?)""",
                (subtask_id, user["id"], content),
            )
            entity_id = subtask_id
            entity_type = "sub_task_note_entry"
        else:
            if not db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone():
                raise ToolError(f"Aufgabe/Projekt {task_id} nicht gefunden")
            cursor = db.execute(
                """INSERT INTO task_note_entries (task_id, user_id, content)
                   VALUES (?, ?, ?)""",
                (task_id, user["id"], content),
            )
            entity_id = task_id
            entity_type = "task_note_entry"
        entry_id = cursor.lastrowid

    log_change(user, entity_type, entity_id, "create", {"entry_id": entry_id, "content_len": len(content)})
    return {"saved": True, "entry_id": entry_id, "task_id": task_id, "subtask_id": subtask_id}


# ============================================================
# Hilfs-Tools
# ============================================================

@mcp.tool
def list_users() -> list[dict]:
    """Listet alle User (id, name, auth_source) - fuer Zuweisungs-Operationen."""
    with db_query() as db:
        rows = db.execute(
            """SELECT id, username, vorname, nachname, email, auth_source, is_active
               FROM users WHERE is_active = 1 ORDER BY username"""
        ).fetchall()
        return [
            {
                "id": r["id"],
                "username": r["username"],
                "display_name": f"{r['vorname']} {r['nachname']}".strip() or r["username"],
                "email": r["email"] or "",
                "auth_source": r["auth_source"] or "local",
            }
            for r in rows
        ]


@mcp.tool
def list_areas() -> list[dict]:
    """Listet alle Bereiche (Kategorien fuer Teilaufgaben)."""
    with db_query() as db:
        rows = db.execute("SELECT id, name FROM areas ORDER BY name").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]


@mcp.tool
def search(query: str, limit: int = 20) -> list[dict]:
    """Volltextsuche ueber Name + Description + Notes (LIKE-basiert).
    Liefert Treffer mit type ('task'|'sub_task'|'note') und kurzem Snippet."""
    if not query.strip():
        return []
    q = f"%{query.strip()}%"
    limit = max(1, min(limit, 200))
    results: list[dict] = []
    with db_query() as db:
        for r in db.execute(
            "SELECT id, name, description FROM tasks WHERE name LIKE ? OR description LIKE ? LIMIT ?",
            (q, q, limit),
        ).fetchall():
            results.append({
                "type": "task", "id": r["id"], "name": r["name"],
                "snippet": (r["description"] or "")[:200],
            })
        for r in db.execute(
            "SELECT id, project_id, name, description FROM sub_tasks WHERE name LIKE ? OR description LIKE ? LIMIT ?",
            (q, q, limit),
        ).fetchall():
            results.append({
                "type": "sub_task", "id": r["id"], "project_id": r["project_id"],
                "name": r["name"], "snippet": (r["description"] or "")[:200],
            })
        for r in db.execute(
            """SELECT tn.task_id, tn.user_id, tn.content, u.username
               FROM task_notes tn JOIN users u ON tn.user_id = u.id
               WHERE tn.content LIKE ? LIMIT ?""",
            (q, limit),
        ).fetchall():
            results.append({
                "type": "task_note", "task_id": r["task_id"], "user": r["username"],
                "snippet": (r["content"] or "")[:200],
            })
        for r in db.execute(
            """SELECT sn.sub_task_id, sn.user_id, sn.content, u.username
               FROM sub_task_notes sn JOIN users u ON sn.user_id = u.id
               WHERE sn.content LIKE ? LIMIT ?""",
            (q, limit),
        ).fetchall():
            results.append({
                "type": "sub_task_note", "sub_task_id": r["sub_task_id"], "user": r["username"],
                "snippet": (r["content"] or "")[:200],
            })
        for r in db.execute(
            """SELECT tne.id, tne.task_id, tne.user_id, tne.content, u.username
               FROM task_note_entries tne JOIN users u ON tne.user_id = u.id
               WHERE tne.content LIKE ? LIMIT ?""",
            (q, limit),
        ).fetchall():
            results.append({
                "type": "task_note_entry", "id": r["id"], "task_id": r["task_id"], "user": r["username"],
                "snippet": (r["content"] or "")[:200],
            })
        for r in db.execute(
            """SELECT sne.id, sne.sub_task_id, sne.user_id, sne.content, u.username
               FROM sub_task_note_entries sne JOIN users u ON sne.user_id = u.id
               WHERE sne.content LIKE ? LIMIT ?""",
            (q, limit),
        ).fetchall():
            results.append({
                "type": "sub_task_note_entry", "id": r["id"], "sub_task_id": r["sub_task_id"], "user": r["username"],
                "snippet": (r["content"] or "")[:200],
            })
    return results[:limit]


@mcp.tool
def assign_self(task_id: int | None = None, subtask_id: int | None = None) -> dict:
    """Weist die Aufgabe oder Teilaufgabe dem aufrufenden MCP-User zu."""
    user = _user()
    if task_id is None and subtask_id is None:
        raise ToolError("task_id oder subtask_id erforderlich")
    with db_transaction() as db:
        if subtask_id is not None:
            if not db.execute("SELECT id FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone():
                raise ToolError(f"Teilaufgabe {subtask_id} nicht gefunden")
            db.execute("UPDATE sub_tasks SET assigned_to = ? WHERE id = ?", (user["id"], subtask_id))
            entity_type, entity_id = "sub_task", subtask_id
        else:
            if not db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone():
                raise ToolError(f"Projekt {task_id} nicht gefunden")
            db.execute("UPDATE tasks SET assigned_to = ? WHERE id = ?", (user["id"], task_id))
            entity_type, entity_id = "task", task_id
    log_change(user, entity_type, entity_id, "update", {"assigned_to": {"new": user["id"]}})
    return {"assigned": True, "entity_type": entity_type, "entity_id": entity_id, "user_id": user["id"]}


@mcp.tool
def whoami() -> dict:
    """Liefert den aktuellen MCP-User (zur Selbst-Diagnose)."""
    user = _user()
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("mcp_display_name"),
        "auth_source": user.get("auth_source", "mcp"),
    }
