"""Shared, permission-checked Issue timeline and transactional event snapshots."""
import json
from datetime import datetime, timezone

from dashboard.db_utils import db_query
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_issue_access
from dashboard.user_utils import get_display_name


def user_label(db, user_id):
    if user_id is None:
        return ''
    row = db.execute('SELECT username,vorname,nachname FROM users WHERE id=?', (user_id,)).fetchone()
    return get_display_name(dict(row)) if row else f'#{user_id}'


def record_event(db, issue_id, actor_id, event_type, old, new):
    """Caller owns the mutation transaction; snapshots survive renamed/deleted users."""
    if event_type not in ('status', 'assignment'):
        raise ValueError('Unsupported Issue event')
    old_label = user_label(db, old) if event_type == 'assignment' else ''
    new_label = user_label(db, new) if event_type == 'assignment' else ''
    db.execute('INSERT INTO issue_events(issue_id,actor_id,actor_name,event_type,old_value,new_value,old_label,new_label,created_at) '
               'VALUES(?,?,?,?,?,?,?,?,?)', (issue_id, actor_id, user_label(db, actor_id), event_type,
                                         json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False),
                                         old_label, new_label, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')))
    return {'old': old, 'new': new, 'old_label': old_label, 'new_label': new_label}


def list_history(issue_id, user, offset=0, limit=50):
    if type(offset) is not int or offset < 0:
        raise ApplicationError(422, 'Invalid history offset', code='invalid_offset', field='offset')
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ApplicationError(422, 'Invalid history limit', code='invalid_limit', field='limit')
    with db_query() as db:
        db.execute('BEGIN')
        require_issue_access(db, issue_id, user)
        total = db.execute('SELECT (SELECT COUNT(*) FROM issue_events WHERE issue_id=?) + '
                           '(SELECT COUNT(*) FROM issue_updates WHERE issue_id=?)', (issue_id, issue_id)).fetchone()[0]
        rows = db.execute('''SELECT 'event' AS kind,id,created_at,actor_id,actor_name,event_type,
                                    old_value,new_value,old_label,new_label,NULL AS content_preview,NULL AS updated_at
                             FROM issue_events WHERE issue_id=?
                             UNION ALL
                             SELECT 'update' AS kind,e.id,e.created_at,e.user_id,
                                    trim(COALESCE(u.vorname,'') || ' ' || COALESCE(u.nachname,'')),
                                    'new_update',NULL,NULL,NULL,NULL,substr(e.content,1,200),e.updated_at
                             FROM issue_updates e LEFT JOIN users u ON u.id=e.user_id WHERE e.issue_id=?
                             ORDER BY created_at DESC,kind DESC,id DESC LIMIT ? OFFSET ?''',
                          (issue_id, issue_id, limit, offset)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item['actor_name'] = item['actor_name'] or user_label(db, item['actor_id'])
            if item['kind'] == 'event':
                item['old_value'] = json.loads(item['old_value'])
                item['new_value'] = json.loads(item['new_value'])
                # Existing events written before snapshots were introduced retain usable IDs.
                if item['event_type'] == 'assignment':
                    item['old_label'] = item['old_label'] or user_label(db, item['old_value'])
                    item['new_label'] = item['new_label'] or user_label(db, item['new_value'])
            else:
                item['update_id'] = item['id']
            items.append(item)
        return {'items': items, 'offset': offset, 'limit': limit, 'total': total,
                'next_offset': offset + len(items) if offset + len(items) < total else None}
