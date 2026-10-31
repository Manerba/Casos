"""Read-only AD people lookup, independent of the Casos login group."""
import re
import time

from ldap3 import SUBTREE

from dashboard.crypto_utils import decrypt
from dashboard.db_utils import db_query
from dashboard.errors import ApplicationError
from dashboard.issue_permissions import require_active_user
from dashboard.ldap_utils import _bind_connection, _create_server, _escape_ldap_filter, _get_domain_root
from dashboard.tls_utils import get_tls_verify_config

ATTRIBUTES = ['objectSid', 'sAMAccountName', 'givenName', 'sn', 'displayName']
USER_FILTER = '(&(objectCategory=person)(objectClass=user)'
PAGE_CONTROL = '1.2.840.113556.1.4.319'


def sid_bytes(value):
    """Validate a canonical SID and encode its LDAP binary representation."""
    if not isinstance(value, str) or len(value) > 184 or not re.fullmatch(r'S-1-\d+(?:-\d+){1,15}', value):
        raise ApplicationError(422, 'adPeople.invalidSid', code='invalid_ad_sid', field='affected_person_sid')
    parts = value.split('-')
    numbers = [int(part) for part in parts[2:]]
    if any(str(number) != part for number, part in zip(numbers, parts[2:])) or numbers[0] >= 2**48 or any(n >= 2**32 for n in numbers[1:]):
        raise ApplicationError(422, 'adPeople.invalidSid', code='invalid_ad_sid', field='affected_person_sid')
    return bytes([1, len(numbers) - 1]) + numbers[0].to_bytes(6, 'big') + b''.join(n.to_bytes(4, 'little') for n in numbers[1:])


def _sid_text(raw):
    if isinstance(raw, str):
        sid_bytes(raw)
        return raw
    if not isinstance(raw, bytes) or len(raw) < 12 or raw[0] != 1 or not 1 <= raw[1] <= 15 or len(raw) != 8 + 4 * raw[1]:
        raise ValueError('Invalid directory SID')
    return 'S-1-' + str(int.from_bytes(raw[2:8], 'big')) + ''.join('-' + str(int.from_bytes(raw[i:i+4], 'little')) for i in range(8, len(raw), 4))


def _person(entry):
    attributes = {key.lower(): value for key, value in entry.get('raw_attributes', {}).items()}

    def first(name):
        values = attributes.get(name.lower(), [])
        return values[0] if values else b''

    def text(name):
        value = first(name)
        return (value.decode('utf-8', errors='strict') if isinstance(value, bytes) else str(value)).strip()

    username = text('sAMAccountName')
    if not username:
        return None
    return {'sid': _sid_text(first('objectSid')), 'username': username,
            'full_name': text('displayName') or ' '.join(filter(None, (text('givenName'), text('sn')))) or username}


def _config(user):
    with db_query() as db:
        require_active_user(db, user)
        row = db.execute('SELECT * FROM ldap_config WHERE id=1').fetchone()
    if not row:
        raise ApplicationError(503, 'adPeople.notConfigured', code='ad_not_configured')
    config = dict(row)
    config['bind_password'] = decrypt(config['bind_password'])
    config['verify_cert'] = get_tls_verify_config()['verify_ldap']
    return config


def _lookup(config, search_filter, offset, limit):
    """Page on one LDAP connection; never silently truncate at AD's size limit.

    REST offsets are reapplied to a fresh paged query, so no LDAP cookies or
    open binds are kept across browser requests. A time bound caps broad scans.
    """
    server = _create_server(config['server'], config['port'], config['use_ssl'], verify_cert=config['verify_cert'])
    conn = _bind_connection(server, config['bind_dn'], config['bind_password'], config['use_ssl'])
    try:
        cookie, seen, items = None, 0, []
        deadline = time.monotonic() + 10
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('Directory search deadline')
            conn.search(_get_domain_root(config['search_base']), search_filter, search_scope=SUBTREE,
                        attributes=ATTRIBUTES, paged_size=100, paged_criticality=True,
                        paged_cookie=cookie, time_limit=5)
            if conn.result.get('result') != 0:
                raise RuntimeError('Directory search failed')
            for entry in conn.response:
                if entry.get('type') != 'searchResEntry':
                    continue
                person = _person(entry)
                if person is None:
                    continue
                if seen >= offset:
                    items.append(person)
                    if len(items) > limit:
                        return {'items': items[:limit], 'offset': offset, 'limit': limit, 'next_offset': offset + limit}
                seen += 1
            cookie = conn.result.get('controls', {}).get(PAGE_CONTROL, {}).get('value', {}).get('cookie')
            if not cookie:
                return {'items': items, 'offset': offset, 'limit': limit, 'next_offset': None}
    finally:
        conn.unbind()


def _query(user, search_filter, offset=0, limit=50):
    try:
        config = _config(user)
        result = _lookup(config, search_filter, offset, limit)
    except ApplicationError:
        raise
    except Exception:
        # LDAP exceptions can contain server addresses, DNs or credentials.
        raise ApplicationError(503, 'adPeople.unavailable', code='ad_unavailable') from None
    with db_query() as db:
        require_active_user(db, user)  # A bind/search may outlive a session/token revocation.
    return result


def search_people(query, user, offset=0, limit=50):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200 or '\x00' in query:
        raise ApplicationError(422, 'adPeople.invalidQuery', code='invalid_ad_query', field='query')
    try:
        query.encode('utf-8')
    except UnicodeError:
        raise ApplicationError(422, 'adPeople.invalidQuery', code='invalid_ad_query', field='query') from None
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ApplicationError(422, 'adPeople.invalidQuery', code='invalid_pagination')
    # AND between words, OR between attributes: "Eva Meyer" matches both parts.
    filters = ''.join('(|' + ''.join(f'({name}=*{_escape_ldap_filter(word)}*)' for name in
                                   ('givenName', 'sn', 'sAMAccountName', 'displayName')) + ')'
                      for word in query.split())
    return _query(user, USER_FILTER + filters + ')', offset, limit)


def resolve_person(sid, user):
    binary = sid_bytes(sid)
    encoded = ''.join(f'\\{byte:02x}' for byte in binary)
    result = _query(user, USER_FILTER + f'(objectSid={encoded}))', limit=2)
    if len(result['items']) != 1 or result['items'][0]['sid'] != sid:
        raise ApplicationError(422, 'adPeople.notFound', code='ad_person_not_found', field='affected_person_sid')
    return result['items'][0]
