"""In-memory LDAP transport for isolated browser tests; never binds a real AD."""
import json
import time
from contextlib import closing

from ldap3 import Connection, MOCK_SYNC, NONE, Server

SID = 'S-1-5-21-111-222-333-1001'
OTHER_SID = 'S-1-5-21-111-222-333-1002'


def install_directory_fixture(root):
    from dashboard import ad_directory, database
    with closing(database.get_db()) as db, db:
        db.execute("INSERT INTO ldap_config(id,server,bind_dn,bind_password,search_base) VALUES(1,'ad.example.invalid','fixture','fixture','OU=Login,DC=example,DC=invalid')")
    state_file = root / 'test-ad-state.json'
    state_file.write_text('{}')

    def connection(server, *args, **kwargs):
        state = json.loads(state_file.read_text())
        if state.get('offline'):
            raise OSError('Simulated directory outage')
        conn = Connection(server, client_strategy=MOCK_SYNC)
        people = [(1001, 'emeyer', 'Eva', 'Meyer', 'Eva Meyer'),
                  (1002, 'emuster', 'Erik', 'Muster', 'Erik Muster'),
                  (1003, 'quoted', 'Eva', 'Quoted', 'Eva " onfocus="alert(1) <Team>'),
                  (1004, 'slow', 'Slow', 'Result', 'Slow Result')]
        people += [(2000+i, f'test{i:02}', 'Testkonto', str(i), f'Testkonto {i:02}') for i in range(53)]
        for number, username, first, last, full in people:
            conn.strategy.add_entry(f'CN={number},OU=People,DC=example,DC=invalid',
                                    {'objectClass':['person','user'], 'objectCategory':'person',
                                     'objectSid':ad_directory.sid_bytes(f'S-1-5-21-111-222-333-{number}'),
                                     'sAMAccountName':username,'givenName':first,'sn':last,'displayName':full})
        conn.bind()
        search = conn.search

        def delayed(*args, **kwargs):
            if '*slow*' in args[1]:
                time.sleep(1)
            return search(*args, **kwargs)
        conn.search = delayed
        return conn

    ad_directory._create_server = lambda *args, **kwargs: Server('ad.example.invalid', get_info=NONE)
    ad_directory._bind_connection = connection
