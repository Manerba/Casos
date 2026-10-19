"""Only run through browser_support: loopback fixture, temporary data, fake mail."""
import json
import os
import sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if not os.environ.get('CASOS_TEST_PORT') or not os.environ.get('CASOS_DATA_DIR'):
    raise RuntimeError('This fixture requires explicit isolated test configuration')

from dashboard import auth, database, mail_service

database.init_db()
password = auth.hash_password('Browser77!')
with closing(database.get_db()) as db, db:
    db.execute('UPDATE users SET password_hash=? WHERE id=1', (password,))
    identities = {'admin': {'id': 1}}
    for name in ('alice', 'bob'):
        uid = db.execute('INSERT INTO users(username,password_hash,vorname,email) VALUES(?,?,?,?)',
                         (name, password, name.title(), name+'@example.invalid')).lastrowid
        identities[name] = {'id': uid}
token, token_id = auth.create_mcp_token('Browser agent', 1)
with closing(database.get_db()) as db:
    uid = db.execute('SELECT user_id FROM mcp_tokens WHERE id=?', (token_id,)).fetchone()[0]
identities['agent'] = {'id': uid, 'token_id': token_id, 'token': token}
identity_file = database.DB_DIR / 'test-identities.json'
identity_file.write_text(json.dumps(identities))
identity_file.chmod(0o600)


def fake_mail(to_email, subject, html_body, text_body):
    with (database.DB_DIR / 'test-mail.jsonl').open('a') as output:
        output.write(json.dumps({'to': to_email, 'subject': subject, 'text': text_body})+'\n')
    return None


mail_service.send_mail = fake_mail
mail_service.test_smtp_connection = lambda config: None
from dashboard.app import app
import uvicorn
uvicorn.run(app, host='127.0.0.1', port=int(os.environ['CASOS_TEST_PORT']), log_level='warning')
