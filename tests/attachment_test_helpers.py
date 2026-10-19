"""Isolated attachment tests with real current identities and API middleware."""

import asyncio
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import api_attachments, attachment_service, auth, database, issue_service, mcp_transport
from dashboard.mcp_transport import MCPAuthMiddleware, api_csrf_protection


class AttachmentTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="casos-attachments-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.patch(database, "DB_DIR", self.root)
        self.patch(database, "DB_PATH", self.root / "casos.db")
        self.patch(auth, "SECRET_KEY_PATH", self.root / "secret.key")
        # Full-app lifespans in subclasses must not open the host security log.
        # Logging assertions still capture events; DB audit remains unchanged.
        self.patch(mcp_transport, "setup_security_logger", lambda: None)
        database.init_db()
        self.users = {"admin": {"id": 1}}
        with closing(database.get_db()) as db, db:
            for name in ("owner", "assignee", "editor", "reader"):
                uid = db.execute("INSERT INTO users(username,password_hash,vorname) VALUES(?, '', ?)", (name, name.title())).lastrowid
                self.users[name] = {"id": uid}
        self.token, self.token_id = auth.create_mcp_token("Attachments agent", 1)
        self.users["agent"] = auth.validate_mcp_bearer(self.token)
        self.issue = issue_service.create_issue({"title": "Attachments", "assigned_to": self.users["assignee"]["id"]}, self.users["owner"])
        self.issue_id = self.issue["id"]
        with closing(database.get_db()) as db, db:
            db.executemany("INSERT INTO issue_editors(issue_id,user_id) VALUES(?,?)",
                           [(self.issue_id, self.users[name]["id"]) for name in ("editor", "agent")])
        self.app = self.make_app()
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.url = f"/api/issues/{self.issue_id}/attachments"

    def make_app(self, dedicated=False):
        app = FastAPI()
        app.include_router(api_attachments.router)
        app.middleware("http")(api_csrf_protection)
        if dedicated:
            app.dependency_overrides[auth.get_file_user] = auth.get_mcp_user
            app.add_middleware(MCPAuthMiddleware, dedicated=True)
        return app

    def patch(self, obj, name, value):
        patcher = patch.object(obj, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def headers(self, who="owner", csrf=True):
        headers = {"X-Requested-With": "XMLHttpRequest"} if csrf else {}
        if who == "agent":
            headers["Authorization"] = "Bearer " + self.token
        elif who is not None:
            session = auth.create_session(self.users[who]["id"])
            headers["Cookie"] = auth.COOKIE_NAME + "=" + auth.sign_token(session)
        return headers

    def add(self, content=b"binary\x00\xff", name="same.bin", who="owner", **kwargs):
        return attachment_service.add_attachment(self.issue_id, self.users[who], original_name=name, content=content, **kwargs)

    def read(self, attachment, who="reader"):
        _, stream = attachment_service.open_attachment(self.issue_id, attachment["id"], self.users[who])
        with stream:
            return stream.read()

    def rows(self, table):
        self.assertIn(table, {"attachments", "attachment_gc", "audit_log"})
        with closing(database.get_db()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM " + table)]

    def storage_files(self):
        folder = self.root / "attachments"
        return sorted(p.name for p in folder.iterdir() if p.name != ".gc.lock") if folder.exists() else []

    def streamed_request(self, app, headers, chunks, *, before_chunk=None, disconnect=False):
        consumed, sent = [], []

        async def receive():
            if len(consumed) >= len(chunks):
                return {"type": "http.disconnect"}
            if before_chunk:
                before_chunk(len(consumed))
            chunk = chunks[len(consumed)]
            consumed.append(chunk)
            return {"type": "http.request", "body": chunk,
                    "more_body": disconnect or len(consumed) < len(chunks)}

        async def send(message):
            sent.append(message)

        async def run():
            await app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                       "http_version": "1.1", "method": "POST", "scheme": "http", "path": self.url,
                       "raw_path": self.url.encode(), "root_path": "", "query_string": b"",
                       "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                       "client": ("127.0.0.1", 12000), "server": ("casos.test", 8514)}, receive, send)

        asyncio.run(run())
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return status, json.loads(body) if body else {}, consumed
