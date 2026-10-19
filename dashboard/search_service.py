"""Shared Issue/Update FTS5 search with current identity and one read snapshot.

The single BM25 corpus indexes issue title/description and update content. The
inclusive `since` filter uses updated_at for both sources; this is a content
search, not a change feed. DB timestamps without a timezone are UTC.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import html
import re
import sqlite3
import unicodedata
import uuid

from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user

SEARCH_TYPES = ("issue", "update")
_INDEX_VERSION = 2
_SOURCES = (
    ("issues", "issue", "title", "description", "id", "created_by", 1),
    ("issue_updates", "update", None, "content", "issue_id", "user_id", -1),
)


@contextmanager
def _savepoint(db, name):
    # Names are fixed internal constants, never supplied by callers.
    db.execute("SAVEPOINT " + name)
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO SAVEPOINT " + name)
        db.execute("RELEASE SAVEPOINT " + name)
        raise
    else:
        db.execute("RELEASE SAVEPOINT " + name)


def rebuild_search_index(db: sqlite3.Connection) -> None:
    """Rebuild derived index atomically, preserving the caller's transaction."""
    with _savepoint(db, "rebuild_search_index"):
        db.execute("INSERT INTO search_fts(search_fts) VALUES ('rebuild')")
        db.execute("INSERT INTO search_fts(search_fts, rank) VALUES ('integrity-check', 1)")


def initialize_search_index(db: sqlite3.Connection) -> None:
    """Run after source DDL within init_db's IMMEDIATE transaction/process lock."""
    with _savepoint(db, "initialize_search_index"):
        db.execute("CREATE TABLE IF NOT EXISTS search_index_meta (version INTEGER NOT NULL)")
        versions = db.execute("SELECT version FROM search_index_meta").fetchall()
        existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'search_%'")}
        expected = {"search_documents", "search_fts"} | {
            f"search_{table}_{event}" for table, *_ in _SOURCES for event in ("ai", "au", "ad")
        }
        if len(versions) == 1 and versions[0][0] == _INDEX_VERSION and expected <= existing:
            try:
                db.execute("SELECT rowid FROM search_fts LIMIT 0")
            except sqlite3.OperationalError as exc:
                _raise_if_fts_missing(exc)
                raise
            return
        # Only derived search objects are replaced. Source rows are authoritative.
        trigger_names = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'search_%'")]
        for name in trigger_names:
            db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        db.execute("DROP TABLE IF EXISTS search_fts")
        db.execute("DROP VIEW IF EXISTS search_documents")
        selects = []
        for table, kind, title, body, issue_id, author, sign in _SOURCES:
            title_sql = f"coalesce(s.{title}, '')" if title else "''"
            selects.append(
                f"SELECT s.id * {sign} AS search_id, '{kind}' AS type, s.id AS id, "
                f"{title_sql} AS title, coalesce(s.{body}, '') AS body, "
                f"s.{issue_id} AS issue_id, s.{author} AS user_id, "
                f"s.created_at AS created_at, s.updated_at AS updated_at FROM {table} s"
            )
        db.execute("CREATE VIEW search_documents AS " + " UNION ALL ".join(selects))
        try:
            db.execute("CREATE VIRTUAL TABLE search_fts USING fts5(title, body, "
                       "content='search_documents', content_rowid='search_id', "
                       "tokenize='unicode61 remove_diacritics 2', prefix='2 3 4')")
        except sqlite3.OperationalError as exc:
            _raise_if_fts_missing(exc)
            raise
        for table, kind, title, body, issue_id, author, sign in _SOURCES:
            def value(prefix, column):
                return f"coalesce({prefix}.{column}, '')" if column else "''"
            insert = ("INSERT INTO search_fts(rowid,title,body) VALUES "
                      f"(new.id * {sign}, {value('new', title)}, {value('new', body)});")
            delete = ("INSERT INTO search_fts(search_fts,rowid,title,body) VALUES "
                      f"('delete', old.id * {sign}, {value('old', title)}, {value('old', body)});")
            columns = ', '.join(['id', body] + ([title] if title else []))
            for suffix, event, statements in (("ai", "INSERT", insert), ("au", f"UPDATE OF {columns}", delete + insert), ("ad", "DELETE", delete)):
                db.execute(f"CREATE TRIGGER search_{table}_{suffix} AFTER {event} ON {table} BEGIN {statements} END")
        rebuild_search_index(db)
        db.execute("DELETE FROM search_index_meta")
        db.execute("INSERT INTO search_index_meta(version) VALUES (?)", (_INDEX_VERSION,))


def _raise_if_fts_missing(exc):
    if "no such module" in str(exc).lower():
        raise RuntimeError("Casos requires SQLite FTS5/unicode61. Use a Python/SQLite build with FTS5; no source data was changed.") from exc


def _invalid_query(detail: str):
    return ApplicationError(400, detail, code="invalid_search_query", field="query")


def prepare_query(query: str) -> str | None:
    """Compile a small literal AND/phrase/prefix language into bound FTS syntax.

    Other punctuation separates ordinary terms; FTS control syntax is rejected.
    Uppercase AND/OR/NOT are literal words, never injected FTS operators.
    """
    if not isinstance(query, str) or len(query) > 1000:
        raise _invalid_query("Suchanfrage muss Text mit hoechstens 1000 Zeichen sein")
    if any(unicodedata.category(char) == "Cs" or (unicodedata.category(char) == "Cc" and not char.isspace()) for char in query):
        raise _invalid_query("Suchanfrage enthaelt ungueltige Steuerzeichen")
    query = unicodedata.normalize("NFC", query).strip()
    if not query:
        return None
    parts = []
    pos = 0
    while pos < len(query):
        if query[pos].isspace():
            pos += 1
            continue
        if query[pos] == '"':
            end = query.find('"', pos + 1)
            if end == -1:
                raise _invalid_query("Anfuehrungszeichen der Suchphrase sind nicht geschlossen")
            value = query[pos + 1:end]
            if not re.search(r"[^\W_]", value) or "*" in value:
                raise _invalid_query("Suchphrase braucht Woerter; Praefix * nur nach einem einzelnen Wort verwenden")
            if end + 1 < len(query) and not query[end + 1].isspace():
                raise _invalid_query("Suchphrasen durch Leerzeichen trennen")
            parts.append('"' + value + '"')
            pos = end + 1
        else:
            end = pos
            while end < len(query) and not query[end].isspace():
                end += 1
            value = query[pos:end]
            if any(char in value for char in '"():{}[]^\\'):
                raise _invalid_query("Suchsyntax ungueltig; Woerter, \"Phrasen\" oder wort* verwenden")
            prefix = value.endswith("*")
            stem = value[:-1] if prefix else value
            if "*" in stem or (prefix and (not stem or not stem[-1].isalnum())):
                raise _invalid_query("Praefix * nur unmittelbar nach einem Wort verwenden")
            words = re.findall(r"[^\W_]+", stem)
            if not words:
                raise _invalid_query("Suchanfrage enthaelt keine durchsuchbaren Woerter")
            parts.extend('"' + word + '"' for word in words)
            if prefix:
                parts[-1] += "*"
            pos = end
        if len(parts) > 32:
            raise _invalid_query("Suchanfrage darf hoechstens 32 Begriffe oder Phrasen enthalten")
    return " AND ".join(parts)


def _since_utc(value: str) -> str:
    try:
        if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
            raise ValueError
        parsed = _parse_utc(value, require_timezone=True)
        return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        raise ApplicationError(
            400, "since muss ein ISO-8601-Zeitpunkt mit Zeitzone sein, z.B. 2026-10-11T12:00:00Z",
            code="invalid_search_since", field="since",
        ) from None


def _parse_utc(value: str, *, require_timezone: bool = False) -> datetime:
    if not isinstance(value, str) or re.search(r"[.,]\d{7,}", value):
        # datetime.fromisoformat silently truncates higher precision. Reject
        # it so an inclusive lower bound cannot accidentally include an older
        # microsecond. Source services write at most six fractional digits.
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if require_timezone:
            raise ValueError
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_utc(value: str | None) -> str | None:
    """Sortable exact SQLite key; invalid source timestamps sort last.

    SQLite julianday rounds to milliseconds, so it cannot compare current
    Update timestamps. Fixed-width UTC strings preserve all six fractional
    digits and make old second-resolution and offset timestamps comparable.
    """
    try:
        return _parse_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _date_utc(value: str | None) -> str | None:
    try:
        return _parse_utc(value).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _snippets(raw: str, opening: str, closing: str) -> tuple[str, str]:
    """Bound visible text to 320 characters; only our escaped mark tags are HTML."""
    pieces = re.split(f"({re.escape(opening)}|{re.escape(closing)})", raw or "")
    spans = []
    highlighted = False
    offset = 0
    first_match = None
    for piece in pieces:
        if piece == opening:
            highlighted = True
        elif piece == closing:
            highlighted = False
        else:
            text = re.sub(r"\s+", " ", piece)
            text = "".join(c for c in text if unicodedata.category(c) != "Cc")
            if highlighted and first_match is None:
                first_match = offset
            spans.append((offset, text, highlighted))
            offset += len(text)
    start = max(0, (first_match or 0) - 90) if offset > 320 else 0
    end = min(offset, start + 320)
    plain = ["…" if start else ""]
    rendered = plain.copy()
    for position, value, marked in spans:
        value = value[max(0, start - position):max(0, end - position)]
        if not value:
            continue
        plain.append(value)
        escaped = html.escape(value)
        rendered.append(f"<mark>{escaped}</mark>" if marked else escaped)
    if end < offset:
        plain.append("…")
        rendered.append("…")
    return "".join(plain), "".join(rendered)


def search_content(
    db: sqlite3.Connection, user: dict, query: str, limit: int = 20, *,
    offset: int = 0, issue_id: int | None = None,
    types: list[str] | None = None, since: str | None = None,
) -> dict:
    """Paginated common BM25 search; rights and count/results share a snapshot.

    Types are `issue` and `update`. Empty text/type lists give an empty page.
    `since` requires a timezone and is inclusive on each source's updated_at.
    Ranking is BM25, then modification time descending, type, ID descending.
    Snippets are bounded plain text plus escaped HTML with only our <mark> tags.
    """
    with _savepoint(db, "issue_search_snapshot"):
        require_active_user(db, user)
        return _search_snapshot(db, query, limit, offset, issue_id, types, since)


def _search_snapshot(db, query, limit, offset, issue_id, types, since):
    prepared = prepare_query(query)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ApplicationError(400, "limit muss ganzzahlig zwischen 1 und 200 sein", code="invalid_search_limit", field="limit")
    if type(offset) is not int or not 0 <= offset <= 2**63 - 1:
        raise ApplicationError(400, "offset muss eine nichtnegative ganze Zahl sein", code="invalid_search_offset", field="offset")
    if issue_id is not None and (type(issue_id) is not int or not 1 <= issue_id <= 2**63 - 1):
        raise ApplicationError(400, "issue_id muss positiv sein", code="invalid_issue_id", field="issue_id")
    selected = list(SEARCH_TYPES)
    if types is not None:
        if not isinstance(types, list) or any(not isinstance(kind, str) or kind not in SEARCH_TYPES for kind in types):
            raise ApplicationError(400, "Unbekannter Suchtyp", code="invalid_search_types", field="types")
        selected = [kind for kind in SEARCH_TYPES if kind in types]
    timestamp = _since_utc(since) if since is not None else None
    page = {"items": [], "total": 0, "offset": offset, "limit": limit, "next_offset": None}
    if not prepared or not selected:
        return page
    db.create_function("casos_search_utc", 1, _canonical_utc, deterministic=True)
    conditions = ["search_fts MATCH ?", "d.type IN (" + ','.join('?' for _ in selected) + ")"]
    params = [prepared, *selected]
    if issue_id is not None:
        conditions.append("d.issue_id = ?")
        params.append(issue_id)
    if timestamp is not None:
        conditions.append("casos_search_utc(d.updated_at) >= ?")
        params.append(timestamp)
    joins = ("FROM search_fts JOIN search_documents d ON d.search_id = search_fts.rowid "
             "JOIN issues i ON i.id = d.issue_id LEFT JOIN users u ON u.id = d.user_id WHERE " + " AND ".join(conditions))
    marker = uuid.uuid4().hex
    opening, closing = f"<{marker}>", f"</{marker}>"
    try:
        total = db.execute("SELECT COUNT(*) " + joins, params).fetchone()[0]
        rows = db.execute(
            "SELECT d.type,d.id,d.issue_id,d.user_id,d.created_at,d.updated_at, "
            "substr(i.title,1,240) AS issue_title,substr(u.username,1,160) AS username, "
            "snippet(search_fts,-1,?,?,' … ',24) AS excerpt " + joins +
            " ORDER BY bm25(search_fts),casos_search_utc(d.updated_at) DESC,d.type ASC,d.id DESC LIMIT ? OFFSET ?",
            [opening, closing, *params, limit, offset],
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if any(text in str(exc).lower() for text in ("no such table", "no such module", "no such tokenizer")):
            raise ApplicationError(503, "Suchindex nicht verfuegbar; Datenbankinitialisierung und SQLite FTS5 pruefen", code="search_unavailable") from exc
        raise
    for row in rows:
        plain, rendered = _snippets(row["excerpt"], opening, closing)
        update_id = row["id"] if row["type"] == "update" else None
        page["items"].append({
            "type": row["type"], "id": row["id"], "issue_id": row["issue_id"], "update_id": update_id,
            "title": row["issue_title"], "created_at": _date_utc(row["created_at"]), "updated_at": _date_utc(row["updated_at"]),
            "user_id": row["user_id"], "user": row["username"],
            "snippet": plain, "snippet_html": rendered,
            "url": f"/issues/{row['issue_id']}" + (f"?update={update_id}" if update_id else ""),
        })
    page["total"] = total
    if offset + len(page["items"]) < total:
        page["next_offset"] = offset + len(page["items"])
    return page
