CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 vorname TEXT NOT NULL DEFAULT '', nachname TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
 is_admin INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1,
 auth_source TEXT NOT NULL DEFAULT 'local', ldap_dn TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 token TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT (datetime('now')), expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issues (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL CHECK(length(trim(title)) > 0),
 description TEXT NOT NULL DEFAULT '', description_format TEXT NOT NULL DEFAULT 'markdown',
 priority INTEGER NOT NULL DEFAULT 50 CHECK(typeof(priority) = 'integer' AND priority BETWEEN 0 AND 100),
 deadline TEXT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
 assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
 status TEXT NOT NULL DEFAULT 'offen' CHECK(status IN ('offen','in_arbeit','erledigt','abgebrochen')),
 created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS issue_editors (
 issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, PRIMARY KEY(issue_id,user_id)
);
CREATE TABLE IF NOT EXISTS issue_updates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
 user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, content TEXT NOT NULL,
 content_format TEXT NOT NULL DEFAULT 'markdown', created_at TEXT NOT NULL DEFAULT (datetime('now')),
 updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS issue_updates_order ON issue_updates(issue_id,created_at,id);
CREATE TABLE IF NOT EXISTS attachments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
 storage_name TEXT NOT NULL UNIQUE, original_name TEXT NOT NULL, media_type TEXT NOT NULL,
 size INTEGER NOT NULL CHECK(size >= 0), uploader_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS attachments_issue ON attachments(issue_id,id);
CREATE TABLE IF NOT EXISTS attachment_gc (
 storage_name TEXT PRIMARY KEY, queued_at TEXT NOT NULL DEFAULT (datetime('now')), last_error TEXT
);
CREATE TABLE IF NOT EXISTS issue_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
 actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL, event_type TEXT NOT NULL,
 old_value TEXT, new_value TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
 actor_name TEXT NOT NULL DEFAULT '', old_label TEXT, new_label TEXT
);
CREATE INDEX IF NOT EXISTS issue_events_order ON issue_events(issue_id,created_at,id);
CREATE TABLE IF NOT EXISTS ldap_config (
 id INTEGER PRIMARY KEY, server TEXT NOT NULL, port INTEGER DEFAULT 389, use_ssl INTEGER DEFAULT 0,
 bind_dn TEXT NOT NULL, bind_password TEXT NOT NULL, search_base TEXT NOT NULL,
 group_dn TEXT, group_name TEXT, sync_interval_minutes INTEGER DEFAULT 60, last_sync_at TEXT,
 created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS app_config (id INTEGER PRIMARY KEY, server_address TEXT NOT NULL DEFAULT 'localhost:8514');
CREATE TABLE IF NOT EXISTS tls_config (
 id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0, cert_path TEXT NOT NULL, key_path TEXT NOT NULL,
 created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tls_verify_config (
 id INTEGER PRIMARY KEY, verify_smtp INTEGER DEFAULT 0, verify_ldap INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mail_config (
 id INTEGER PRIMARY KEY, smtp_server TEXT NOT NULL, smtp_port INTEGER DEFAULT 587,
 encryption TEXT DEFAULT 'starttls', auth_enabled INTEGER DEFAULT 1, username TEXT DEFAULT '',
 password TEXT DEFAULT '', from_address TEXT NOT NULL, from_name TEXT DEFAULT 'Casos',
 created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS mail_templates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL UNIQUE, subject TEXT NOT NULL,
 body_text TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS user_mail_preferences (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 event_type TEXT NOT NULL, enabled INTEGER DEFAULT 1, days_before INTEGER DEFAULT 2, UNIQUE(user_id,event_type)
);
CREATE TABLE IF NOT EXISTS mcp_tokens (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')),
 last_used_at TEXT, revoked_at TEXT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS mcp_tokens_hash ON mcp_tokens(token_hash);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT (datetime('now')),
 actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, actor_type TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id INTEGER, action TEXT NOT NULL, changes_json TEXT, reason TEXT
);
CREATE INDEX IF NOT EXISTS audit_log_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS audit_log_entity ON audit_log(entity_type,entity_id);
CREATE TABLE IF NOT EXISTS mcp_config (id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1);
INSERT OR IGNORE INTO mcp_config(id,enabled) VALUES(1,1);
