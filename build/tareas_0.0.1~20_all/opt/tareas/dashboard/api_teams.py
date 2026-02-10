"""
Tareas - API-Router fuer Team-Verwaltung und Teilaufgaben-Berechtigungen.
Sprint C: Teams + Berechtigungen
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from dashboard.database import get_db
from dashboard.auth import get_current_user

router = APIRouter()


# ============================================================
# Pydantic-Modelle
# ============================================================

class MemberAdd(BaseModel):
    user_id: int
    can_read: bool = True
    can_edit: bool = False
    can_create: bool = False


class MemberUpdate(BaseModel):
    can_read: bool
    can_edit: bool
    can_create: bool


class SubtaskPermissionUpdate(BaseModel):
    can_read: bool
    can_edit: bool


# ============================================================
# Hilfsfunktionen
# ============================================================

def _check_project_creator(db, task_id: int, user: dict):
    """Prueft: Task existiert, ist Projekt, User ist Ersteller. Wirft 404/400/403."""
    task = db.execute(
        "SELECT id, task_type, created_by FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    if task["task_type"] != "projekt":
        raise HTTPException(status_code=400, detail="Nur Projekte koennen Teams haben")
    if task["created_by"] != user["id"]:
        raise HTTPException(status_code=403, detail="Nur der Ersteller kann das Team verwalten")
    return task


# ============================================================
# Team-Endpoints (nur fuer Projekt-Ersteller)
# ============================================================

@router.get("/api/tasks/{task_id}/members")
async def get_members(task_id: int, user=Depends(get_current_user)):
    """Alle Teammitglieder eines Projekts mit Berechtigungen."""
    db = get_db()
    try:
        _check_project_creator(db, task_id, user)
        rows = db.execute(
            """SELECT pm.*, u.vorname, u.nachname, u.email
               FROM project_members pm
               JOIN users u ON pm.user_id = u.id
               WHERE pm.project_id = ?
               ORDER BY u.nachname, u.vorname""",
            (task_id,),
        ).fetchall()
        return {
            "items": [
                {
                    "user_id": r["user_id"],
                    "vorname": r["vorname"] or "",
                    "nachname": r["nachname"] or "",
                    "email": r["email"] or "",
                    "can_read": bool(r["can_read"]),
                    "can_edit": bool(r["can_edit"]),
                    "can_create": bool(r["can_create"]),
                    "added_at": r["added_at"],
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@router.post("/api/tasks/{task_id}/members")
async def add_member(task_id: int, member: MemberAdd, user=Depends(get_current_user)):
    """Mitglied zum Projekt-Team hinzufuegen."""
    db = get_db()
    try:
        _check_project_creator(db, task_id, user)

        # User existiert?
        target = db.execute("SELECT id FROM users WHERE id = ?", (member.user_id,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

        # Nicht sich selbst hinzufuegen
        if member.user_id == user["id"]:
            raise HTTPException(status_code=400, detail="Ersteller kann sich nicht selbst als Mitglied hinzufuegen")

        # Duplikat?
        existing = db.execute(
            "SELECT id FROM project_members WHERE project_id = ? AND user_id = ?",
            (task_id, member.user_id),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Benutzer ist bereits Teammitglied")

        db.execute(
            """INSERT INTO project_members (project_id, user_id, can_read, can_edit, can_create)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, member.user_id, int(member.can_read), int(member.can_edit), int(member.can_create)),
        )
        db.commit()
        return {"message": "Mitglied hinzugefuegt"}
    finally:
        db.close()


@router.put("/api/tasks/{task_id}/members/{member_user_id}")
async def update_member(task_id: int, member_user_id: int, member: MemberUpdate, user=Depends(get_current_user)):
    """Berechtigungen eines Teammitglieds aendern."""
    db = get_db()
    try:
        _check_project_creator(db, task_id, user)

        existing = db.execute(
            "SELECT id FROM project_members WHERE project_id = ? AND user_id = ?",
            (task_id, member_user_id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")

        db.execute(
            """UPDATE project_members SET can_read = ?, can_edit = ?, can_create = ?
               WHERE project_id = ? AND user_id = ?""",
            (int(member.can_read), int(member.can_edit), int(member.can_create), task_id, member_user_id),
        )
        db.commit()
        return {"message": "Berechtigungen aktualisiert"}
    finally:
        db.close()


@router.delete("/api/tasks/{task_id}/members/{member_user_id}")
async def remove_member(task_id: int, member_user_id: int, user=Depends(get_current_user)):
    """Mitglied aus Team entfernen + zugehoerige subtask_permissions loeschen."""
    db = get_db()
    try:
        _check_project_creator(db, task_id, user)

        existing = db.execute(
            "SELECT id FROM project_members WHERE project_id = ? AND user_id = ?",
            (task_id, member_user_id),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")

        # Subtask-Permissions dieses Users fuer alle Teilaufgaben des Projekts loeschen
        db.execute(
            """DELETE FROM subtask_permissions
               WHERE user_id = ? AND sub_task_id IN (
                   SELECT id FROM sub_tasks WHERE project_id = ?
               )""",
            (member_user_id, task_id),
        )

        db.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (task_id, member_user_id),
        )
        db.commit()
        return {"message": "Mitglied entfernt"}
    finally:
        db.close()


# ============================================================
# Teilaufgaben-Berechtigungs-Endpoints (nur Projekt-Ersteller)
# ============================================================

@router.get("/api/subtasks/{subtask_id}/permissions")
async def get_subtask_permissions(subtask_id: int, user=Depends(get_current_user)):
    """Berechtigungs-Ueberschreibungen fuer eine Teilaufgabe."""
    db = get_db()
    try:
        st = db.execute(
            "SELECT id, project_id FROM sub_tasks WHERE id = ?", (subtask_id,)
        ).fetchone()
        if not st:
            raise HTTPException(status_code=404, detail="Teilaufgabe nicht gefunden")

        _check_project_creator(db, st["project_id"], user)

        rows = db.execute(
            """SELECT sp.*, u.vorname, u.nachname
               FROM subtask_permissions sp
               JOIN users u ON sp.user_id = u.id
               WHERE sp.sub_task_id = ?
               ORDER BY u.nachname, u.vorname""",
            (subtask_id,),
        ).fetchall()
        return {
            "items": [
                {
                    "user_id": r["user_id"],
                    "vorname": r["vorname"] or "",
                    "nachname": r["nachname"] or "",
                    "can_read": bool(r["can_read"]),
                    "can_edit": bool(r["can_edit"]),
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@router.put("/api/subtasks/{subtask_id}/permissions/{perm_user_id}")
async def upsert_subtask_permission(subtask_id: int, perm_user_id: int, perm: SubtaskPermissionUpdate, user=Depends(get_current_user)):
    """Berechtigungs-Ueberschreibung fuer eine Teilaufgabe setzen (UPSERT)."""
    db = get_db()
    try:
        st = db.execute(
            "SELECT id, project_id FROM sub_tasks WHERE id = ?", (subtask_id,)
        ).fetchone()
        if not st:
            raise HTTPException(status_code=404, detail="Teilaufgabe nicht gefunden")

        _check_project_creator(db, st["project_id"], user)

        # User muss project_member sein
        member = db.execute(
            "SELECT id FROM project_members WHERE project_id = ? AND user_id = ?",
            (st["project_id"], perm_user_id),
        ).fetchone()
        if not member:
            raise HTTPException(status_code=400, detail="Benutzer ist kein Teammitglied")

        db.execute(
            """INSERT INTO subtask_permissions (sub_task_id, user_id, can_read, can_edit)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(sub_task_id, user_id) DO UPDATE SET
                   can_read = excluded.can_read,
                   can_edit = excluded.can_edit""",
            (subtask_id, perm_user_id, int(perm.can_read), int(perm.can_edit)),
        )
        db.commit()
        return {"message": "Berechtigung aktualisiert"}
    finally:
        db.close()


@router.delete("/api/subtasks/{subtask_id}/permissions/{perm_user_id}")
async def delete_subtask_permission(subtask_id: int, perm_user_id: int, user=Depends(get_current_user)):
    """Berechtigungs-Ueberschreibung entfernen (Fallback auf Standard)."""
    db = get_db()
    try:
        st = db.execute(
            "SELECT id, project_id FROM sub_tasks WHERE id = ?", (subtask_id,)
        ).fetchone()
        if not st:
            raise HTTPException(status_code=404, detail="Teilaufgabe nicht gefunden")

        _check_project_creator(db, st["project_id"], user)

        db.execute(
            "DELETE FROM subtask_permissions WHERE sub_task_id = ? AND user_id = ?",
            (subtask_id, perm_user_id),
        )
        db.commit()
        return {"message": "Ueberschreibung entfernt"}
    finally:
        db.close()
