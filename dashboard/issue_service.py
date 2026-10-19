"""Flat Issues, revisions and grants shared by REST and MCP."""

import hashlib
import json
import re
from datetime import date

from dashboard.audit_log import log_change, normalize_reason
from dashboard.db_utils import db_query, db_transaction
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user, require_issue_access, issue_permissions

STATUSES = frozenset({"offen", "in_arbeit", "erledigt", "abgebrochen"})
ISSUE_FIELDS = frozenset({"title", "description", "priority", "deadline", "assigned_to", "status"})
DESCRIPTION_MAX_BYTES = 1024 * 1024


def description_revision(content: str | None, content_format: str = "markdown") -> str:
    return hashlib.sha256(f"{content_format}\0{content or ''}".encode("utf-8")).hexdigest()


def _invalid(field, message, code="invalid_field"):
    raise ApplicationError(422, message, code=code, field=field)


def _text(value, field, *, nonempty=False, max_length=None):
    if not isinstance(value, str) or (nonempty and not value.strip()):
        _invalid(field, f"{field} muss ein nichtleerer Text sein" if nonempty else f"{field} muss Text sein")
    if max_length and len(value) > max_length:
        _invalid(field, f"{field} ist zu lang")
    try:
        value.encode("utf-8")
    except UnicodeError:
        _invalid(field, f"{field} muss gueltiger Unicode-Text sein")
    return value


def _description_limit(value):
    if len(value.encode("utf-8")) > DESCRIPTION_MAX_BYTES:
        _invalid("description", "Beschreibung darf hoechstens 1 MiB UTF-8 enthalten", "content_too_large")


def validate_issue_data(data, *, creating=False):
    if not isinstance(data, dict):
        _invalid("data", "Ein JSON-Objekt ist erforderlich")
    allowed = ISSUE_FIELDS if creating else ISSUE_FIELDS | {"description_revision"}
    unknown = set(data) - allowed
    if unknown:
        raise ApplicationError(422, "Unbekannte Issue-Felder", code="unknown_fields", fields=sorted(unknown))
    result = dict(data)
    if creating and "title" not in result:
        _invalid("title", "Ein Titel ist erforderlich")
    if "title" in result:
        result["title"] = _text(result["title"], "title", nonempty=True, max_length=500).strip()
    if "description" in result:
        _text(result["description"], "description")
        _description_limit(result["description"])
    if "priority" in result and (type(result["priority"]) is not int or not 0 <= result["priority"] <= 100):
        _invalid("priority", "Prioritaet muss eine ganze Zahl zwischen 0 und 100 sein")
    if "status" in result and (not isinstance(result["status"], str) or result["status"] not in STATUSES):
        _invalid("status", "Ungueltiger Issue-Status", "invalid_status")
    if "assigned_to" in result and result["assigned_to"] is not None:
        if type(result["assigned_to"]) is not int or result["assigned_to"] < 1:
            _invalid("assigned_to", "Verantwortlicher muss eine Benutzer-ID oder null sein")
    if "deadline" in result and result["deadline"] is not None:
        value = result["deadline"]
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            _invalid("deadline", "Frist muss YYYY-MM-DD oder null sein")
        try:
            date.fromisoformat(value)
        except ValueError:
            _invalid("deadline", "Ungueltiges Fristdatum")
    if "description_revision" in result and (
        not isinstance(result["description_revision"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", result["description_revision"])
    ):
        _invalid("description_revision", "Ungueltige Beschreibungsrevision", "invalid_revision")
    return result


def _check_revision(row, revision):
    if revision is None:
        _invalid("description_revision", "Eine Beschreibungsrevision ist erforderlich", "revision_required")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        _invalid("description_revision", "Ungueltige Beschreibungsrevision", "invalid_revision")
    if revision != description_revision(row["description"], row["description_format"]):
        raise ApplicationError(409, "description.conflict", code="revision_conflict", field="description_revision")


def _active_target(db, user_id, field="assigned_to"):
    if user_id is not None and not db.execute(
        "SELECT 1 FROM users WHERE id = ? AND is_active = 1", (user_id,),
    ).fetchone():
        _invalid(field, "Benutzer fehlt oder ist deaktiviert", "invalid_user")


def _serialize(db, row, user, *, include_description=True):
    item = dict(row)
    item["permissions"] = issue_permissions(db, row, user)
    item["description_revision"] = description_revision(row["description"], row["description_format"])
    if not include_description:
        item.pop("description", None)
    return item


def get_issue(issue_id, user):
    with db_query() as db:
        db.execute("BEGIN")
        current = require_active_user(db, user)
        row, _ = require_issue_access(db, issue_id, current)
        return _serialize(db, row, current)


def list_issues(user, offset=0, limit=50, status=None, assigned_to=None, include_description=False,
                sort_by="id", sort_direction="desc", unassigned=False):
    if type(offset) is not int or offset < 0:
        _invalid("offset", "offset muss eine nichtnegative ganze Zahl sein")
    if type(limit) is not int or not 1 <= limit <= 500:
        _invalid("limit", "limit muss zwischen 1 und 500 liegen")
    if type(include_description) is not bool:
        _invalid("include_description", "include_description muss boolesch sein")
    if status is not None and (not isinstance(status, str) or status not in STATUSES):
        _invalid("status", "Ungueltiger Issue-Status", "invalid_status")
    if assigned_to is not None and (type(assigned_to) is not int or assigned_to < 1):
        _invalid("assigned_to", "Verantwortlicher muss eine Benutzer-ID sein")
    order_columns = {"id": "id", "title": "title COLLATE NOCASE", "priority": "priority",
                     "deadline": "deadline", "created_at": "created_at"}
    if not isinstance(sort_by, str) or sort_by not in order_columns:
        _invalid("sort_by", "Ungueltige Sortierspalte")
    if sort_direction not in ("asc", "desc"):
        _invalid("sort_direction", "Sortierrichtung muss asc oder desc sein")
    if type(unassigned) is not bool or (unassigned and assigned_to is not None):
        _invalid("unassigned", "Unzugewiesen und Verantwortlicher sind alternative Filter")
    ordering = ("deadline IS NULL ASC, " if sort_by == "deadline" else "")
    ordering += order_columns[sort_by] + " " + sort_direction.upper()
    if sort_by != "id":
        ordering += ", id DESC"
    clauses, values = [], []
    if status is not None:
        clauses.append("status = ?")
        values.append(status)
    if assigned_to is not None:
        clauses.append("assigned_to = ?")
        values.append(assigned_to)
    if unassigned:
        clauses.append("assigned_to IS NULL")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_query() as db:
        db.execute("BEGIN")
        current = require_active_user(db, user)
        total = db.execute("SELECT COUNT(*) FROM issues" + where, values).fetchone()[0]
        rows = db.execute("SELECT * FROM issues" + where + " ORDER BY " + ordering + " LIMIT ? OFFSET ?",
                          [*values, limit, offset]).fetchall()
        return {"items": [_serialize(db, row, current, include_description=include_description) for row in rows],
                "offset": offset, "limit": limit, "total": total,
                "next_offset": offset + len(rows) if offset + len(rows) < total else None}


def _event(db, issue_id, actor_id, event_type, old, new):
    from dashboard.issue_history_service import record_event
    return record_event(db, issue_id, actor_id, event_type, old, new)


def create_issue(data, user, reason=None):
    reason = normalize_reason(reason)
    data = validate_issue_data(data, creating=True)
    values = {"title": data["title"], "description": "", "priority": 50, "deadline": None,
              "assigned_to": None, "status": "offen", **data}
    notifications = []
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        _active_target(db, values["assigned_to"])
        cursor = db.execute(
            "INSERT INTO issues (title, description, description_format, priority, deadline, assigned_to, status, created_by) "
            "VALUES (?, ?, 'markdown', ?, ?, ?, ?, ?)",
            (values["title"], values["description"], values["priority"], values["deadline"],
             values["assigned_to"], values["status"], current["id"]),
        )
        issue_id = cursor.lastrowid
        if values["assigned_to"] is not None:
            change = _event(db, issue_id, current["id"], "assignment", None, values["assigned_to"])
            notifications.append(("issue_assigned", change))
        if values["status"] != "offen":
            change = _event(db, issue_id, current["id"], "status", "offen", values["status"])
            notifications.append(("status_change", change))
        result = _serialize(db, db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone(), current)
        log_change(current, "issue", issue_id, "create", {"title": values["title"], "status": values["status"]}, reason=reason, db=db)
    from dashboard.mail_service import notify_issue_event
    for event_type, change in notifications:
        notify_issue_event(issue_id, event_type, current["id"], changes=change)
    return result


def update_issue(issue_id, data, user, reason=None):
    reason = normalize_reason(reason)
    data = validate_issue_data(data)
    notifications = []
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        row, rights = require_issue_access(db, issue_id, current, "edit")
        if "assigned_to" in data:
            if not rights["can_manage"]:
                raise ApplicationError(403, "Nur Ersteller und Admins duerfen zuweisen", code="permission_denied", field="assigned_to")
            _active_target(db, data["assigned_to"])
        if "description" in data:
            _check_revision(row, data.get("description_revision"))
        changes = {key: {"old": row[key], "new": value} for key, value in data.items()
                   if key in ISSUE_FIELDS and row[key] != value}
        if changes:
            # Field names originate exclusively from ISSUE_FIELDS, never arbitrary caller input.
            fields = list(changes)
            db.execute("UPDATE issues SET " + ", ".join(f"{key} = ?" for key in fields)
                       + ", updated_at = datetime('now') WHERE id = ?",
                       [*(data[key] for key in fields), issue_id])
            for field, event_type in (("status", "status"), ("assigned_to", "assignment")):
                if field in changes:
                    change = _event(db, issue_id, current["id"], event_type, row[field], data[field])
                    notifications.append(("issue_assigned" if event_type == "assignment" else "status_change", change))
        result = _serialize(db, db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone(), current)
        if changes:
            audit = {key: value for key, value in changes.items() if key != "description"}
            if "description" in changes:
                audit["description_len"] = len(data["description"])
            log_change(current, "issue", issue_id, "update", audit, reason=reason, db=db)
    from dashboard.mail_service import notify_issue_event
    for event_type, change in notifications:
        notify_issue_event(issue_id, event_type, current["id"], changes=change)
    return result


def delete_issue(issue_id, user, reason=None):
    reason = normalize_reason(reason)
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        require_issue_access(db, issue_id, current, "manage")
        db.execute("INSERT OR IGNORE INTO attachment_gc (storage_name) SELECT storage_name FROM attachments WHERE issue_id = ?", (issue_id,))
        db.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
        log_change(current, "issue", issue_id, "delete", reason=reason, db=db)
    from dashboard.attachment_service import process_attachment_gc
    cleanup = process_attachment_gc(limit=1000)
    return {"ok": True, "cleanup_pending": cleanup["pending"]}


def patch_issue_description(issue_id, user, *, revision, operation, text, old_text=None, reason=None):
    reason = normalize_reason(reason)
    if operation not in ("append", "replace"):
        _invalid("operation", "Operation muss append oder replace sein", "invalid_description_operation")
    _text(text, "text")
    if operation == "append" and old_text is not None:
        _invalid("old_text", "old_text ist nur fuer replace erlaubt", "invalid_description_target")
    if operation == "replace" and (not isinstance(old_text, str) or not old_text):
        _invalid("old_text", "Ein nichtleerer exakter Suchtext ist erforderlich", "invalid_description_target")
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        row, _ = require_issue_access(db, issue_id, current, "edit")
        _check_revision(row, revision)
        source = row["description"] or ""
        if operation == "append":
            updated = source + text
        else:
            start = source.find(old_text)
            if start < 0:
                _invalid("old_text", "Der exakte Suchtext wurde nicht gefunden", "description_target_not_found")
            if source.find(old_text, start + 1) >= 0:
                _invalid("old_text", "Der Suchtext kommt mehrfach vor", "description_target_ambiguous")
            updated = source[:start] + text + source[start + len(old_text):]
        _description_limit(updated)
        if updated != source:
            db.execute("UPDATE issues SET description = ?, updated_at = datetime('now') WHERE id = ?", (updated, issue_id))
        result = {"ok": True, "issue_id": issue_id, "description_revision": description_revision(updated, row["description_format"])}
        if updated != source:
            log_change(current, "issue", issue_id, "update", {"description_operation": operation, "description_len": len(updated)}, reason=reason, db=db)
    return result


def _editors(db, issue_id):
    rows = db.execute("SELECT u.id, u.username, u.vorname, u.nachname, u.is_active FROM issue_editors e "
                      "JOIN users u ON u.id = e.user_id WHERE e.issue_id = ? ORDER BY u.id", (issue_id,)).fetchall()
    ids = [row["id"] for row in rows]
    revision = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    return {"user_ids": ids, "items": [dict(row) for row in rows], "revision": revision}


def get_editors(issue_id, user):
    with db_query() as db:
        db.execute("BEGIN")
        require_issue_access(db, issue_id, user, "manage")
        return _editors(db, issue_id)


def set_editors(issue_id, user_ids, user, *, revision, reason=None):
    reason = normalize_reason(reason)
    if not isinstance(user_ids, list) or any(type(uid) is not int or uid < 1 for uid in user_ids):
        _invalid("user_ids", "Bearbeiter muessen eine Liste von Benutzer-IDs sein")
    if len(set(user_ids)) != len(user_ids):
        _invalid("user_ids", "Doppelte Bearbeiter sind nicht erlaubt")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
        _invalid("revision", "Eine gueltige Freigabenrevision ist erforderlich", "invalid_revision")
    with db_transaction() as db:
        db.execute("BEGIN IMMEDIATE")
        current = require_active_user(db, user)
        require_issue_access(db, issue_id, current, "manage")
        existing = _editors(db, issue_id)
        if revision != existing["revision"]:
            raise ApplicationError(409, "Freigaben wurden zwischenzeitlich geaendert", code="revision_conflict", field="revision")
        for uid in user_ids:
            _active_target(db, uid, "user_ids")
        db.execute("DELETE FROM issue_editors WHERE issue_id = ?", (issue_id,))
        db.executemany("INSERT INTO issue_editors (issue_id, user_id) VALUES (?, ?)", [(issue_id, uid) for uid in user_ids])
        result = _editors(db, issue_id)
        if result["user_ids"] != existing["user_ids"]:
            log_change(current, "issue", issue_id, "permissions", {"old": existing["user_ids"], "new": result["user_ids"]}, reason=reason, db=db)
    return result
