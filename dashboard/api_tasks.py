"""
Tareas - API-Router fuer Aufgaben, Teilaufgaben und Bereiche.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from dashboard.database import get_db
from dashboard.auth import get_current_user
from dashboard.components import Column, Filter, ExpandableTable

router = APIRouter()


# ============================================================
# Pydantic-Modelle
# ============================================================

class TaskCreate(BaseModel):
    name: str
    deadline: Optional[str] = None
    priority: int = 50
    task_type: str = "aufgabe"
    status: str = "offen"
    description: str = ""


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[int] = None
    task_type: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    nextcloud_path: Optional[str] = None


class SubTaskCreate(BaseModel):
    name: str
    area_id: Optional[int] = None
    deadline: Optional[str] = None
    priority: int = 50
    status_percent: int = 0
    predecessor_ids: list[int] = []
    description: str = ""


class SubTaskUpdate(BaseModel):
    name: Optional[str] = None
    area_id: Optional[int] = None
    deadline: Optional[str] = None
    priority: Optional[int] = None
    status_percent: Optional[int] = None
    position_number: Optional[int] = None
    predecessor_ids: Optional[list[int]] = None
    description: Optional[str] = None
    assigned_to: Optional[int] = None


class AreaCreate(BaseModel):
    name: str


class NoteUpdate(BaseModel):
    content: str


# ============================================================
# Hilfsfunktionen
# ============================================================

def _format_date(iso_str: Optional[str]) -> str:
    """Konvertiert ISO-Datum zu DD.MM.YYYY."""
    if not iso_str:
        return ""
    try:
        # Versuche verschiedene Formate
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(iso_str.strip(), fmt)
                return dt.strftime("%d.%m.%Y")
            except ValueError:
                continue
        # Bereits im DD.MM.YYYY Format?
        if "." in iso_str and len(iso_str.split(".")) == 3:
            return iso_str.strip()
        return iso_str.strip()
    except Exception:
        return iso_str or ""


def _parse_date_input(date_str: Optional[str]) -> Optional[str]:
    """Konvertiert Benutzereingabe zu ISO-Datum fuer DB."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    # DD.MM.YYYY -> YYYY-MM-DD
    if "." in date_str:
        parts = date_str.split(".")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    # Bereits ISO oder anderes Format -> durchreichen
    return date_str


# ============================================================
# Tasks CRUD
# ============================================================

@router.get("/api/tasks")
async def get_tasks(user=Depends(get_current_user)):
    """Aufgaben abrufen (eigene/zugewiesene/Team-Mitglied + Altdaten ohne created_by)."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT t.*,
                      uc.vorname || ' ' || uc.nachname AS created_by_name,
                      ua.vorname || ' ' || ua.nachname AS assigned_to_name,
                      (SELECT 1 FROM project_members pm WHERE pm.project_id = t.id AND pm.user_id = ?) AS is_team_member,
                      (SELECT COUNT(*) FROM sub_tasks st WHERE st.project_id = t.id) AS subtask_total,
                      (SELECT COUNT(*) FROM sub_tasks st WHERE st.project_id = t.id AND st.status_percent >= 100) AS subtask_done
               FROM tasks t
               LEFT JOIN users uc ON t.created_by = uc.id
               LEFT JOIN users ua ON t.assigned_to = ua.id
               WHERE t.created_by = ? OR t.assigned_to = ? OR t.created_by IS NULL
                  OR t.id IN (SELECT project_id FROM project_members WHERE user_id = ? AND can_read = 1)
               ORDER BY t.priority ASC, t.created_at DESC""",
            (user["id"], user["id"], user["id"], user["id"]),
        ).fetchall()

        items = []
        for row in rows:
            # Kategorie berechnen
            created_by = row["created_by"]
            assigned_to = row["assigned_to"]
            is_team = bool(row["is_team_member"])

            if not created_by:
                category = "eigene"
            elif created_by == user["id"] and (not assigned_to or assigned_to == user["id"]):
                category = "eigene"
            elif created_by == user["id"] and assigned_to != user["id"]:
                category = "vergebene"
            elif assigned_to == user["id"] and created_by != user["id"]:
                category = "zugewiesene"
            elif is_team and created_by != user["id"] and assigned_to != user["id"]:
                category = "team"
            else:
                category = "eigene"

            items.append({
                "id": row["id"],
                "_type": "task",
                "_category": category,
                "name": row["name"],
                "created_at": _format_date(row["created_at"]),
                "deadline": _format_date(row["deadline"]),
                "priority": row["priority"],
                "task_type": row["task_type"],
                "status": row["status"],
                "description": row["description"] or "",
                "created_by": row["created_by"],
                "assigned_to": row["assigned_to"],
                "created_by_name": (row["created_by_name"] or "").strip(),
                "assigned_to_name": (row["assigned_to_name"] or "").strip(),
                "is_team_member": bool(row["is_team_member"]),
                "nextcloud_path": row["nextcloud_path"] or "",
                "subtask_total": row["subtask_total"] or 0,
                "subtask_done": row["subtask_done"] or 0,
            })

        # Zugewiesene Teilaufgaben als Aufgaben-Eintraege
        st_rows = db.execute(
            """SELECT st.*, t.name AS project_name,
                      uc.vorname || ' ' || uc.nachname AS created_by_name,
                      ua.vorname || ' ' || ua.nachname AS assigned_to_name
               FROM sub_tasks st
               JOIN tasks t ON st.project_id = t.id
               LEFT JOIN users uc ON st.created_by = uc.id
               LEFT JOIN users ua ON st.assigned_to = ua.id
               WHERE st.assigned_to = ?
                 AND (t.created_by IS NULL OR t.created_by != ?)""",
            (user["id"], user["id"]),
        ).fetchall()

        for st in st_rows:
            pct = st["status_percent"] or 0
            if pct == 0:
                st_status = "offen"
            elif pct >= 100:
                st_status = "erledigt"
            else:
                st_status = "in_arbeit"

            items.append({
                "id": -st["id"],
                "_type": "assigned_subtask",
                "_category": "zugewiesene",
                "_subtask_id": st["id"],
                "_project_id": st["project_id"],
                "_project_name": st["project_name"],
                "_status_percent": pct,
                "name": st["name"],
                "created_at": _format_date(st["created_at"]),
                "deadline": _format_date(st["deadline"]),
                "priority": st["priority"],
                "task_type": "aufgabe",
                "status": st_status,
                "description": st["description"] or "",
                "created_by": st["created_by"],
                "assigned_to": st["assigned_to"],
                "created_by_name": (st["created_by_name"] or "").strip(),
                "assigned_to_name": (st["assigned_to_name"] or "").strip(),
                "is_team_member": False,
            })

        return {"items": items, "total": len(items)}
    finally:
        db.close()


@router.post("/api/tasks")
async def create_task(task: TaskCreate, user=Depends(get_current_user)):
    """Neue Aufgabe anlegen."""
    db = get_db()
    try:
        deadline = _parse_date_input(task.deadline)
        cursor = db.execute(
            """INSERT INTO tasks (name, deadline, priority, task_type, status, description, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task.name, deadline, task.priority, task.task_type, task.status, task.description, user["id"]),
        )
        db.commit()
        return {"id": cursor.lastrowid, "message": "Aufgabe erstellt"}
    finally:
        db.close()


@router.put("/api/tasks/{task_id}")
async def update_task(task_id: int, task: TaskUpdate, user=Depends(get_current_user)):
    """Aufgabe aktualisieren."""
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id, created_by, assigned_to FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

        updates = []
        values = []
        if task.name is not None:
            updates.append("name = ?")
            values.append(task.name)
        if task.deadline is not None:
            updates.append("deadline = ?")
            values.append(_parse_date_input(task.deadline))
        if task.priority is not None:
            updates.append("priority = ?")
            values.append(task.priority)
        if task.task_type is not None:
            updates.append("task_type = ?")
            values.append(task.task_type)
        if task.status is not None:
            updates.append("status = ?")
            values.append(task.status)
        if task.description is not None:
            updates.append("description = ?")
            values.append(task.description)

        # assigned_to: 0 = unassign, >0 = assign
        if task.assigned_to is not None:
            if task.assigned_to == 0:
                updates.append("assigned_to = NULL")
            else:
                updates.append("assigned_to = ?")
                values.append(task.assigned_to)

        # nextcloud_path: leerer String = entfernen, sonst setzen
        if task.nextcloud_path is not None:
            if task.nextcloud_path == "":
                updates.append("nextcloud_path = NULL")
            else:
                updates.append("nextcloud_path = ?")
                values.append(task.nextcloud_path)

        if updates:
            values.append(task_id)
            db.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            db.commit()

        return {"message": "Aufgabe aktualisiert"}
    finally:
        db.close()


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    """Aufgabe loeschen (inkl. SubTasks durch CASCADE)."""
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

        db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        db.commit()
        return {"message": "Aufgabe geloescht"}
    finally:
        db.close()


# ============================================================
# SubTasks CRUD
# ============================================================

@router.get("/api/tasks/{task_id}/subtasks")
async def get_subtasks(task_id: int, user=Depends(get_current_user)):
    """Teilaufgaben eines Projekts abrufen (mit Berechtigungsfilter)."""
    db = get_db()
    try:
        # Projekt pruefen
        task = db.execute(
            "SELECT id, created_by FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

        is_creator = task["created_by"] == user["id"]
        is_legacy = task["created_by"] is None

        # Teammitgliedschaft pruefen
        membership = None
        if not is_creator and not is_legacy:
            membership = db.execute(
                "SELECT can_read, can_edit, can_create FROM project_members WHERE project_id = ? AND user_id = ?",
                (task_id, user["id"]),
            ).fetchone()

        rows = db.execute(
            """SELECT st.*, a.name as area_name,
                      uc.vorname || ' ' || uc.nachname AS created_by_name,
                      ua.vorname || ' ' || ua.nachname AS assigned_to_name
               FROM sub_tasks st
               LEFT JOIN areas a ON st.area_id = a.id
               LEFT JOIN users uc ON st.created_by = uc.id
               LEFT JOIN users ua ON st.assigned_to = ua.id
               WHERE st.project_id = ?
               ORDER BY st.position_number ASC, st.created_at ASC""",
            (task_id,),
        ).fetchall()

        # Alle Dependencies fuer dieses Projekt laden
        sub_ids = [row["id"] for row in rows]
        deps = {}
        if sub_ids:
            placeholders = ",".join("?" * len(sub_ids))
            dep_rows = db.execute(
                f"SELECT sub_task_id, depends_on_id FROM sub_task_dependencies WHERE sub_task_id IN ({placeholders})",
                sub_ids,
            ).fetchall()
            for dr in dep_rows:
                deps.setdefault(dr["sub_task_id"], []).append(dr["depends_on_id"])

        # Subtask-Permissions laden (fuer Teammitglieder)
        st_perms = {}
        if membership and sub_ids:
            placeholders = ",".join("?" * len(sub_ids))
            perm_rows = db.execute(
                f"SELECT sub_task_id, can_read, can_edit FROM subtask_permissions WHERE user_id = ? AND sub_task_id IN ({placeholders})",
                [user["id"]] + sub_ids,
            ).fetchall()
            for pr in perm_rows:
                st_perms[pr["sub_task_id"]] = {"can_read": bool(pr["can_read"]), "can_edit": bool(pr["can_edit"])}

        # Mapping: sub_task id -> position_number (fuer predecessors_display)
        id_to_pos = {row["id"]: row["position_number"] for row in rows}

        items = []
        for row in rows:
            # Effektive Berechtigungen berechnen
            if is_creator or is_legacy:
                permissions = {"can_read": True, "can_edit": True, "can_create": True, "has_override": False}
            elif membership:
                override = st_perms.get(row["id"])
                if override:
                    permissions = {
                        "can_read": override["can_read"],
                        "can_edit": override["can_edit"],
                        "can_create": bool(membership["can_create"]),
                        "has_override": True,
                    }
                else:
                    permissions = {
                        "can_read": bool(membership["can_read"]),
                        "can_edit": bool(membership["can_edit"]),
                        "can_create": bool(membership["can_create"]),
                        "has_override": False,
                    }
                # Nicht-lesbare filtern
                if not permissions["can_read"]:
                    continue
            else:
                # Kein Zugriff (weder Ersteller, Legacy, noch Teammitglied)
                # Zugewiesene sehen nur ihre zugewiesene Subtask
                if row["assigned_to"] == user["id"]:
                    permissions = {"can_read": True, "can_edit": True, "can_create": False, "has_override": False}
                else:
                    continue

            pred_ids = deps.get(row["id"], [])
            pred_positions = sorted(id_to_pos.get(pid, 0) or 0 for pid in pred_ids)
            items.append({
                "id": row["id"],
                "project_id": row["project_id"],
                "position_number": row["position_number"],
                "name": row["name"],
                "area_id": row["area_id"],
                "area_name": row["area_name"] or "",
                "created_at": _format_date(row["created_at"]),
                "deadline": _format_date(row["deadline"]),
                "priority": row["priority"],
                "status_percent": row["status_percent"],
                "predecessor_ids": pred_ids,
                "predecessors_display": ", ".join(str(p) for p in pred_positions if p),
                "description": row["description"] or "",
                "created_by": row["created_by"],
                "assigned_to": row["assigned_to"],
                "created_by_name": (row["created_by_name"] or "").strip(),
                "assigned_to_name": (row["assigned_to_name"] or "").strip(),
                "permissions": permissions,
            })

        return {"items": items, "total": len(items)}
    finally:
        db.close()


@router.post("/api/tasks/{task_id}/subtasks")
async def create_subtask(task_id: int, subtask: SubTaskCreate, user=Depends(get_current_user)):
    """Teilaufgabe anlegen."""
    db = get_db()
    try:
        existing = db.execute("SELECT id, created_by FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

        # Berechtigung pruefen: Ersteller, Legacy, oder Teammitglied mit can_create
        is_creator = existing["created_by"] == user["id"]
        is_legacy = existing["created_by"] is None
        if not is_creator and not is_legacy:
            membership = db.execute(
                "SELECT can_create FROM project_members WHERE project_id = ? AND user_id = ?",
                (task_id, user["id"]),
            ).fetchone()
            if not membership or not membership["can_create"]:
                raise HTTPException(status_code=403, detail="Keine Berechtigung zum Erstellen von Teilaufgaben")

        # Naechste position_number ermitteln
        row = db.execute(
            "SELECT COALESCE(MAX(position_number), 0) + 1 as next_pos FROM sub_tasks WHERE project_id = ?",
            (task_id,),
        ).fetchone()
        next_pos = row["next_pos"]

        deadline = _parse_date_input(subtask.deadline)
        cursor = db.execute(
            """INSERT INTO sub_tasks (project_id, name, area_id, deadline, priority, status_percent, position_number, description, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, subtask.name, subtask.area_id, deadline, subtask.priority, subtask.status_percent, next_pos, subtask.description, user["id"]),
        )
        new_id = cursor.lastrowid

        # Vorgaenger eintragen
        for pred_id in subtask.predecessor_ids:
            db.execute(
                "INSERT OR IGNORE INTO sub_task_dependencies (sub_task_id, depends_on_id) VALUES (?, ?)",
                (new_id, pred_id),
            )

        db.commit()
        return {"id": new_id, "position_number": next_pos, "message": "Teilaufgabe erstellt"}
    finally:
        db.close()


@router.put("/api/subtasks/{subtask_id}")
async def update_subtask(subtask_id: int, subtask: SubTaskUpdate, user=Depends(get_current_user)):
    """Teilaufgabe aktualisieren."""
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id, project_id FROM sub_tasks WHERE id = ?", (subtask_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Teilaufgabe nicht gefunden")

        # Berechtigung pruefen
        task = db.execute(
            "SELECT created_by FROM tasks WHERE id = ?", (existing["project_id"],)
        ).fetchone()
        is_creator = task and task["created_by"] == user["id"]
        is_legacy = task and task["created_by"] is None
        if not is_creator and not is_legacy:
            # Subtask-Override pruefen
            override = db.execute(
                "SELECT can_edit FROM subtask_permissions WHERE sub_task_id = ? AND user_id = ?",
                (subtask_id, user["id"]),
            ).fetchone()
            if override:
                if not override["can_edit"]:
                    raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten")
            else:
                # Fallback auf Projekt-Berechtigung
                membership = db.execute(
                    "SELECT can_edit FROM project_members WHERE project_id = ? AND user_id = ?",
                    (existing["project_id"], user["id"]),
                ).fetchone()
                if not membership or not membership["can_edit"]:
                    # Zugewiesene duerfen ihre Subtask bearbeiten
                    st_row = db.execute("SELECT assigned_to FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
                    if not st_row or st_row["assigned_to"] != user["id"]:
                        raise HTTPException(status_code=403, detail="Keine Berechtigung zum Bearbeiten")

        updates = []
        values = []
        if subtask.name is not None:
            updates.append("name = ?")
            values.append(subtask.name)
        if subtask.area_id is not None:
            updates.append("area_id = ?")
            values.append(subtask.area_id)
        if subtask.deadline is not None:
            updates.append("deadline = ?")
            values.append(_parse_date_input(subtask.deadline))
        if subtask.priority is not None:
            updates.append("priority = ?")
            values.append(subtask.priority)
        if subtask.status_percent is not None:
            updates.append("status_percent = ?")
            values.append(subtask.status_percent)
        if subtask.position_number is not None:
            # Pruefen ob unique innerhalb des Projekts
            conflict = db.execute(
                "SELECT id FROM sub_tasks WHERE project_id = ? AND position_number = ? AND id != ?",
                (existing["project_id"], subtask.position_number, subtask_id),
            ).fetchone()
            if conflict:
                raise HTTPException(status_code=400, detail="Positionsnummer bereits vergeben")
            updates.append("position_number = ?")
            values.append(subtask.position_number)
        if subtask.description is not None:
            updates.append("description = ?")
            values.append(subtask.description)

        # assigned_to: 0 = unassign, >0 = assign
        if subtask.assigned_to is not None:
            if subtask.assigned_to == 0:
                updates.append("assigned_to = NULL")
            else:
                updates.append("assigned_to = ?")
                values.append(subtask.assigned_to)

        if updates:
            values.append(subtask_id)
            db.execute(
                f"UPDATE sub_tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )

        # Vorgaenger aktualisieren (komplett ersetzen)
        if subtask.predecessor_ids is not None:
            db.execute(
                "DELETE FROM sub_task_dependencies WHERE sub_task_id = ?", (subtask_id,)
            )
            for pred_id in subtask.predecessor_ids:
                db.execute(
                    "INSERT OR IGNORE INTO sub_task_dependencies (sub_task_id, depends_on_id) VALUES (?, ?)",
                    (subtask_id, pred_id),
                )

        db.commit()
        return {"message": "Teilaufgabe aktualisiert"}
    finally:
        db.close()


@router.delete("/api/subtasks/{subtask_id}")
async def delete_subtask(subtask_id: int, user=Depends(get_current_user)):
    """Teilaufgabe loeschen (nur Ersteller oder Legacy)."""
    db = get_db()
    try:
        existing = db.execute("SELECT id, project_id FROM sub_tasks WHERE id = ?", (subtask_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Teilaufgabe nicht gefunden")

        # Nur Ersteller oder Legacy darf loeschen
        task = db.execute(
            "SELECT created_by FROM tasks WHERE id = ?", (existing["project_id"],)
        ).fetchone()
        is_creator = task and task["created_by"] == user["id"]
        is_legacy = task and task["created_by"] is None
        if not is_creator and not is_legacy:
            raise HTTPException(status_code=403, detail="Nur der Ersteller kann Teilaufgaben loeschen")

        db.execute("DELETE FROM sub_tasks WHERE id = ?", (subtask_id,))
        db.commit()
        return {"message": "Teilaufgabe geloescht"}
    finally:
        db.close()


# ============================================================
# Users List
# ============================================================

@router.get("/api/users/list")
async def get_users_list():
    """Alle Benutzer als Liste (fuer Zuweisungs-Dropdown)."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, vorname, nachname FROM users ORDER BY vorname, nachname"
        ).fetchall()
        return {
            "items": [
                {"id": r["id"], "vorname": r["vorname"], "nachname": r["nachname"]}
                for r in rows
            ]
        }
    finally:
        db.close()


# ============================================================
# Task Notes
# ============================================================

@router.get("/api/tasks/{task_id}/notes")
async def get_task_notes(task_id: int):
    """Notizen fuer eine Aufgabe abrufen."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT tn.*, u.vorname || ' ' || u.nachname AS user_name
               FROM task_notes tn
               JOIN users u ON tn.user_id = u.id
               WHERE tn.task_id = ?
               ORDER BY tn.updated_at DESC""",
            (task_id,),
        ).fetchall()
        return {
            "items": [
                {
                    "user_id": r["user_id"],
                    "user_name": (r["user_name"] or "").strip(),
                    "content": r["content"] or "",
                    "updated_at": _format_date(r["updated_at"]),
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@router.put("/api/tasks/{task_id}/notes")
async def upsert_task_note(task_id: int, note: NoteUpdate, user=Depends(get_current_user)):
    """Eigene Notiz fuer eine Aufgabe erstellen/aktualisieren."""
    db = get_db()
    try:
        db.execute(
            """INSERT INTO task_notes (task_id, user_id, content, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(task_id, user_id) DO UPDATE SET
                   content = excluded.content,
                   updated_at = datetime('now')""",
            (task_id, user["id"], note.content),
        )
        db.commit()
        return {"message": "Notiz gespeichert"}
    finally:
        db.close()


@router.get("/api/tasks/{task_id}/subtasks/{subtask_id}/notes")
async def get_subtask_notes(task_id: int, subtask_id: int):
    """Notizen fuer eine Teilaufgabe abrufen."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT sn.*, u.vorname || ' ' || u.nachname AS user_name
               FROM sub_task_notes sn
               JOIN users u ON sn.user_id = u.id
               WHERE sn.sub_task_id = ?
               ORDER BY sn.updated_at DESC""",
            (subtask_id,),
        ).fetchall()
        return {
            "items": [
                {
                    "user_id": r["user_id"],
                    "user_name": (r["user_name"] or "").strip(),
                    "content": r["content"] or "",
                    "updated_at": _format_date(r["updated_at"]),
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@router.put("/api/tasks/{task_id}/subtasks/{subtask_id}/notes")
async def upsert_subtask_note(task_id: int, subtask_id: int, note: NoteUpdate, user=Depends(get_current_user)):
    """Eigene Notiz fuer eine Teilaufgabe erstellen/aktualisieren."""
    db = get_db()
    try:
        db.execute(
            """INSERT INTO sub_task_notes (sub_task_id, user_id, content, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(sub_task_id, user_id) DO UPDATE SET
                   content = excluded.content,
                   updated_at = datetime('now')""",
            (subtask_id, user["id"], note.content),
        )
        db.commit()
        return {"message": "Notiz gespeichert"}
    finally:
        db.close()


# ============================================================
# Areas
# ============================================================

@router.get("/api/areas")
async def get_areas():
    """Alle Bereiche abrufen."""
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM areas ORDER BY name").fetchall()
        return {"items": [{"id": r["id"], "name": r["name"]} for r in rows]}
    finally:
        db.close()


@router.post("/api/areas")
async def create_area(area: AreaCreate):
    """Neuen Bereich anlegen."""
    db = get_db()
    try:
        cursor = db.execute("INSERT INTO areas (name) VALUES (?)", (area.name,))
        db.commit()
        return {"id": cursor.lastrowid, "name": area.name}
    except Exception:
        raise HTTPException(status_code=400, detail="Bereich existiert bereits")
    finally:
        db.close()


# ============================================================
# ExpandableTable Config
# ============================================================

@router.get("/api/tasks/config")
async def get_tasks_config():
    """ExpandableTable-Konfiguration fuer den Aufgaben-Tab."""
    table = ExpandableTable(
        id="aufgaben",
        api_endpoint="/api/tasks",
        expandable=True,
        columns=[
            Column("Name", "name", width=0, sortable=True),
            Column("Typ", "task_type", width=90, sortable=True, renderer="badge"),
            Column("Status", "status", width=90, sortable=True, renderer="badge"),
            Column("Prioritaet", "priority", width=80, sortable=True, align="center"),
            Column("Von", "created_by_name", width=120, sortable=True),
            Column("Zugewiesen an", "assigned_to_name", width=120, sortable=True),
            Column("Erstellt", "created_at", width=100, sortable=True),
            Column("Deadline", "deadline", width=100, sortable=True),
        ],
        detail_fields=[],
        default_sort=("priority", "asc"),
        filters=[
            Filter(
                id="typeFilter",
                label="Typ",
                type="select",
                field="task_type",
                options=[
                    {"value": "", "label": "Alle"},
                    {"value": "aufgabe", "label": "Aufgabe"},
                    {"value": "projekt", "label": "Projekt"},
                ],
            ),
            Filter(
                id="statusFilter",
                label="Status",
                type="select",
                field="status",
                options=[
                    {"value": "", "label": "Alle"},
                    {"value": "offen", "label": "Offen"},
                    {"value": "in_arbeit", "label": "In Arbeit"},
                    {"value": "erledigt", "label": "Erledigt"},
                ],
            ),
            Filter(
                id="searchFilter",
                label="Suche",
                type="input",
                field="name",
                placeholder="Suche...",
                wildcard=True,
                wildcard_fields=["description"],
            ),
        ],
    )
    return table.to_dict()
