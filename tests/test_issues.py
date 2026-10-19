"""Issue lifecycle, current permissions, revisions and authentication isolation."""

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from dashboard import api_auth, api_issues, auth, database, issue_service as service
from dashboard.errors import ApplicationError


class IssueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="casos-issues-")
        self.addCleanup(temp.cleanup)
        for module, name, value in (
            (database, "DB_DIR", Path(temp.name)),
            (database, "DB_PATH", Path(temp.name) / "casos.db"),
            (auth, "SECRET_KEY_PATH", Path(temp.name) / "secret.key"),
        ):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        database.init_db()
        self.admin = {"id": 1}
        self.users = {}
        with closing(database.get_db()) as db, db:
            for name in ("alice", "bob", "agent"):
                uid = db.execute("INSERT INTO users(username,password_hash,auth_source) VALUES(?, '', ?)",
                                 (name, "mcp" if name == "agent" else "local")).lastrowid
                self.users[name] = {"id": uid}
        self.user = self.users["alice"]
        app = FastAPI()
        app.include_router(api_issues.router)
        app.dependency_overrides[auth.get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def create(self, **extra):
        return service.create_issue({"title": "An Issue", **extra}, self.users["alice"])

    def rows(self, table):
        self.assertIn(table, {"issues", "issue_updates", "issue_events", "attachments", "issue_editors", "attachment_gc", "audit_log"})
        with closing(database.get_db()) as db:
            return [dict(row) for row in db.execute("SELECT * FROM " + table)]

    def test_every_active_identity_reads_and_creates_but_reader_cannot_mutate(self):
        issue = self.create(description="# Content")
        for who in (*self.users.values(), self.admin):
            with self.subTest(who=who):
                self.user = who
                item = self.client.get(f'/api/issues/{issue["id"]}').json()
                self.assertEqual(item["description"], "# Content")
                self.assertTrue(item["permissions"]["can_read"])
                self.assertEqual(self.client.post("/api/issues", json={"title": "Own"}).status_code, 201)
        self.user = self.users["bob"]
        self.assertFalse(self.client.get(f'/api/issues/{issue["id"]}').json()["permissions"]["can_edit"])
        for method, suffix, body in (("put", "", {"status": "erledigt"}), ("delete", "", None),
                                     ("put", "/editors", {"user_ids": [], "revision": "a" * 64})):
            response = self.client.request(method, f'/api/issues/{issue["id"]}{suffix}', json=body)
            self.assertEqual(response.status_code, 403, response.text)

    def test_assignees_browser_and_mcp_edit_but_do_not_manage(self):
        issue = self.create()
        for role in ("bob", "agent"):
            who = self.users[role]
            service.update_issue(issue["id"], {"assigned_to": who["id"]}, self.users["alice"])
            rights = service.get_issue(issue["id"], who)["permissions"]
            self.assertEqual(rights, {"can_read": True, "can_edit": True, "can_contribute": True, "can_manage": False})
            service.update_issue(issue["id"], {"status": "in_arbeit"}, who)
            for action in (lambda: service.update_issue(issue["id"], {"assigned_to": None}, who),
                           lambda: service.delete_issue(issue["id"], who),
                           lambda: service.get_editors(issue["id"], who)):
                with self.assertRaises(ApplicationError) as caught:
                    action()
                self.assertEqual(caught.exception.status_code, 403)
        service.update_issue(issue["id"], {"assigned_to": None}, self.users["alice"])
        self.assertFalse(service.get_issue(issue["id"], self.users["agent"])["permissions"]["can_edit"])

    def test_editor_grants_revision_current_rights_and_strict_members(self):
        issue = self.create()
        before = service.get_editors(issue["id"], self.users["alice"])
        granted = service.set_editors(issue["id"], [self.users["bob"]["id"]], self.users["alice"], revision=before["revision"])
        service.update_issue(issue["id"], {"priority": 99}, self.users["bob"])
        with self.assertRaises(ApplicationError) as conflict:
            service.set_editors(issue["id"], [], self.users["alice"], revision=before["revision"])
        self.assertEqual(conflict.exception.status_code, 409)
        service.set_editors(issue["id"], [], self.users["alice"], revision=granted["revision"])
        with self.assertRaises(ApplicationError) as revoked:
            service.update_issue(issue["id"], {"priority": 0}, self.users["bob"])
        self.assertEqual(revoked.exception.status_code, 403)
        for ids in ([True], [1, 1], [99999], ["2"]):
            with self.subTest(ids=ids), self.assertRaises(ApplicationError):
                service.set_editors(issue["id"], ids, self.admin, revision=before["revision"])
        self.assertEqual(service.get_editors(issue["id"], self.admin)["user_ids"], [])

    def test_current_admin_active_flags_and_missing_id_are_rechecked(self):
        issue = self.create()
        forged = {**self.users["bob"], "is_admin": True, "is_active": True}
        with self.assertRaises(ApplicationError) as caught:
            service.delete_issue(issue["id"], forged)
        self.assertEqual(caught.exception.status_code, 403)
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE users SET is_admin=1 WHERE id=?", (forged["id"],))
        self.assertTrue(service.get_issue(issue["id"], forged)["permissions"]["can_manage"])
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE users SET is_admin=0,is_active=0 WHERE id=?", (forged["id"],))
        for identity in (forged, None, {}, {"id": True}, {"id": "1"}):
            with self.subTest(identity=identity), self.assertRaises(ApplicationError) as error:
                service.get_issue(issue["id"], identity)
            self.assertEqual(error.exception.status_code, 401)

    def test_lifecycle_null_clearing_events_and_audit_reason(self):
        issue = self.create(assigned_to=self.users["bob"]["id"], deadline="2026-10-20")
        for status in ("in_arbeit", "erledigt", "offen", "abgebrochen", "offen"):
            service.update_issue(issue["id"], {"status": status}, self.users["alice"], reason=" reopen ")
        changed = service.update_issue(issue["id"], {"assigned_to": None, "deadline": None}, self.users["alice"])
        self.assertIsNone(changed["assigned_to"])
        self.assertIsNone(changed["deadline"])
        events = self.rows("issue_events")
        self.assertEqual([event["event_type"] for event in events], ["assignment", *("status" for _ in range(5)), "assignment"])
        self.assertEqual([json.loads(event["new_value"]) for event in events], [self.users["bob"]["id"], "in_arbeit", "erledigt", "offen", "abgebrochen", "offen", None])
        self.assertEqual({event["actor_id"] for event in events}, {self.users["alice"]["id"]})
        self.assertEqual([a["reason"] for a in self.rows("audit_log")][1:6], ["reopen"] * 5)

    def test_strict_fields_status_title_priority_deadline_and_unicode(self):
        invalid = [{"title": " "}, {"title": "x" * 501}, {"title": None}, {"priority": True}, {"priority": 1.5},
                   {"priority": "50"}, {"priority": 101}, {"status": []}, {"status": "closed"}, {"deadline": ""},
                   {"deadline": "2026-02-30"}, {"assigned_to": True}, {"assigned_to": 99999},
                   {"created_by": 1}, {"subtask_id": 1}, {"description": "\ud800"}, {"description": None}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ApplicationError):
                self.create(**data)
        self.assertEqual(self.rows("issues"), [])
        self.assertEqual(self.rows("audit_log"), [])
        for bad_id in (True, 0, -1, "1"):
            with self.subTest(bad_id=bad_id), self.assertRaises(ApplicationError):
                service.get_issue(bad_id, self.admin)
        self.assertEqual(self.client.post("/api/issues", json={"title": "Good", "name": "old"}).status_code, 422)

    def test_utf8_description_limit_applies_to_create_update_and_patch(self):
        too_large = "ü" * (service.DESCRIPTION_MAX_BYTES // 2 + 1)
        with self.assertRaises(ApplicationError):
            self.create(description=too_large)
        issue = self.create(description="unchanged")
        for action in (lambda: service.update_issue(issue["id"], {"description": too_large, "description_revision": issue["description_revision"]}, self.admin),
                       lambda: service.patch_issue_description(issue["id"], self.admin, revision=issue["description_revision"], operation="append", text=too_large)):
            with self.assertRaises(ApplicationError):
                action()
        self.assertEqual(service.get_issue(issue["id"], self.admin)["description"], "unchanged")

    def test_description_revision_preserves_text_and_rejects_conflict_atomically(self):
        issue = self.create(description="  # ü ✓\r\nOriginal\n")
        self.user = self.users["alice"]
        url = f'/api/issues/{issue["id"]}'
        self.assertEqual(self.client.put(url, json={"description": "lost"}).status_code, 422)
        changed = self.client.put(url, json={"description": "Changed", "description_revision": issue["description_revision"]})
        self.assertEqual(changed.status_code, 200)
        failed = self.client.put(url, json={"description": "lost", "status": "erledigt", "description_revision": issue["description_revision"]})
        self.assertEqual(failed.status_code, 409)
        self.assertEqual(self.client.get(url).json()["description"], "Changed")
        self.assertEqual(self.client.get(url).json()["status"], "offen")
        self.assertEqual(self.rows("issue_events"), [])
        self.assertEqual(len(self.rows("audit_log")), 2)

    def test_exact_patch_append_replace_and_overlapping_ambiguity(self):
        issue = self.create(description="## ü\nA unique target.\n")
        updated = service.patch_issue_description(issue["id"], self.admin, revision=issue["description_revision"], operation="append", text="No extra newline")
        current = service.get_issue(issue["id"], self.admin)
        self.assertEqual(current["description"], issue["description"] + "No extra newline")
        service.patch_issue_description(issue["id"], self.admin, revision=updated["description_revision"], operation="replace", old_text="unique target", text="aaaa")
        current = service.get_issue(issue["id"], self.admin)
        for old, code in (("aaa", "description_target_ambiguous"), ("missing", "description_target_not_found")):
            with self.assertRaises(ApplicationError) as error:
                service.patch_issue_description(issue["id"], self.admin, revision=current["description_revision"], operation="replace", old_text=old, text="x")
            self.assertEqual(error.exception.code, code)
        response = self.client.patch(f'/api/issues/{issue["id"]}/description', json={"revision": current["description_revision"], "operation": "append", "text": "✓"})
        self.assertEqual(response.status_code, 200)

    def test_concurrent_description_updates_have_one_winner(self):
        issue = self.create()
        barrier = threading.Barrier(2)
        def update(text):
            barrier.wait()
            try:
                service.update_issue(issue["id"], {"description": text, "description_revision": issue["description_revision"]}, self.admin)
                return 200
            except ApplicationError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(update, ("first", "second")))
        self.assertEqual(sorted(results), [200, 409])
        self.assertIn(service.get_issue(issue["id"], self.admin)["description"], ("first", "second"))

    def test_concurrent_editor_updates_have_one_winner(self):
        issue = self.create()
        revision = service.get_editors(issue["id"], self.admin)["revision"]
        barrier = threading.Barrier(2)
        def grant(uid):
            barrier.wait()
            try:
                service.set_editors(issue["id"], [uid], self.admin, revision=revision)
                return 200
            except ApplicationError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(grant, (self.users["bob"]["id"], self.users["agent"]["id"])))
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(len(service.get_editors(issue["id"], self.admin)["user_ids"]), 1)

    def test_pagination_filters_compact_rows_and_restart(self):
        first = self.create()
        second = self.create(status="erledigt", assigned_to=self.users["bob"]["id"])
        database.init_db()
        page = service.list_issues(self.users["bob"], limit=1)
        self.assertEqual(page["items"][0]["id"], second["id"])
        self.assertNotIn("description", page["items"][0])
        self.assertEqual(page["next_offset"], 1)
        self.assertEqual(service.list_issues(self.users["bob"], offset=1)["items"][0]["id"], first["id"])
        filtered = service.list_issues(self.users["agent"], status="erledigt", assigned_to=self.users["bob"]["id"], include_description=True)
        self.assertEqual(filtered["total"], 1)
        self.assertIn("description", filtered["items"][0])
        self.assertIsNone(filtered["next_offset"])

    def test_issue_delete_cascades_and_queues_attachment_cleanup(self):
        issue = self.create(status="in_arbeit")
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO issue_updates(issue_id,user_id,content) VALUES(?,?, 'update')", (issue["id"], self.user["id"]))
            db.execute("INSERT INTO attachments(issue_id,storage_name,original_name,media_type,size) VALUES(?,'unique','name','text/plain',4)", (issue["id"],))
            db.execute("INSERT INTO issue_editors(issue_id,user_id) VALUES(?,?)", (issue["id"], self.users["bob"]["id"]))
        service.delete_issue(issue["id"], self.admin)
        for table in ("issues", "issue_updates", "attachments", "issue_editors", "issue_events"):
            self.assertEqual(self.rows(table), [])
        self.assertEqual(self.rows("attachment_gc")[0]["storage_name"], "unique")
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_cookie_and_bearer_revoke_and_kill_switch_use_current_database(self):
        session = auth.create_session(self.users["bob"]["id"])
        self.assertEqual(auth.validate_session(session)["id"], self.users["bob"]["id"])
        plain, token_id = auth.create_mcp_token("MCP test", 1)
        identity = auth.validate_mcp_bearer(plain)
        issue = self.create(assigned_to=identity["id"])
        self.assertTrue(service.get_issue(issue["id"], identity)["permissions"]["can_edit"])
        auth.set_mcp_enabled(False)
        self.assertIsNone(auth.validate_mcp_bearer(plain))
        with self.assertRaises(ApplicationError):
            service.update_issue(issue["id"], {"status": "erledigt"}, identity)
        auth.set_mcp_enabled(True)
        self.assertIsNotNone(auth.validate_mcp_bearer(plain))
        auth.revoke_mcp_token(token_id)
        self.assertIsNone(auth.validate_mcp_bearer(plain))
        with self.assertRaises(ApplicationError):
            service.get_issue(issue["id"], identity)
        plain2, _ = auth.create_mcp_token("Deactivated", 1)
        other = auth.validate_mcp_bearer(plain2)
        with closing(database.get_db()) as db, db:
            db.executemany("UPDATE users SET is_active=0 WHERE id=?", [(self.users["bob"]["id"],), (other["id"],)])
        self.assertIsNone(auth.validate_session(session))
        self.assertIsNone(auth.validate_mcp_bearer(plain2))
        self.user = self.admin
        ids = [u["id"] for u in self.client.get("/api/users/list").json()["items"]]
        self.assertNotIn(self.users["bob"]["id"], ids)

    def test_user_deletion_retains_issue_and_nulls_author_and_assignment(self):
        issue = self.create(assigned_to=self.users["alice"]["id"])
        with closing(database.get_db()) as db, db:
            db.execute("DELETE FROM users WHERE id=?", (self.users["alice"]["id"],))
        remaining = service.get_issue(issue["id"], self.users["bob"])
        self.assertIsNone(remaining["created_by"])
        self.assertIsNone(remaining["assigned_to"])
        self.assertFalse(remaining["permissions"]["can_manage"])
        self.assertTrue(service.get_issue(issue["id"], self.admin)["permissions"]["can_manage"])
        with closing(database.get_db()) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_audit_failure_rolls_back_issue_event_grants_and_cleanup_queue(self):
        issue = self.create()
        grant_revision = service.get_editors(issue["id"], self.admin)["revision"]
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO attachments(issue_id,storage_name,original_name,media_type,size) VALUES(?,'retain','name','text/plain',4)", (issue["id"],))
            db.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON audit_log BEGIN SELECT RAISE(ABORT, 'audit failure'); END")
        actions = (
            lambda: service.create_issue({"title": "must rollback"}, self.admin),
            lambda: service.update_issue(issue["id"], {"status": "erledigt"}, self.admin),
            lambda: service.patch_issue_description(issue["id"], self.admin, revision=issue["description_revision"], operation="append", text="no"),
            lambda: service.set_editors(issue["id"], [self.users["bob"]["id"]], self.admin, revision=grant_revision),
            lambda: service.delete_issue(issue["id"], self.admin),
        )
        for action in actions:
            with self.assertRaises(sqlite3.IntegrityError):
                action()
        self.assertEqual(len(self.rows("issues")), 1)
        self.assertEqual(service.get_issue(issue["id"], self.admin)["status"], "offen")
        self.assertEqual(service.get_issue(issue["id"], self.admin)["description"], "")
        self.assertEqual(self.rows("issue_events"), [])
        self.assertEqual(self.rows("issue_editors"), [])
        self.assertEqual(self.rows("attachment_gc"), [])
        self.assertEqual(len(self.rows("attachments")), 1)

    def test_login_rejects_deactivated_local_and_mcp_users(self):
        app = FastAPI()
        app.include_router(api_auth.router)
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE users SET is_active=0 WHERE id=1")
        api_auth._rate_limits.clear()
        self.addCleanup(api_auth._rate_limits.clear)
        with TestClient(app) as client:
            for username in ("admin", "agent"):
                response = client.post("/api/auth/login", json={"username": username, "password": "admin"})
                self.assertEqual(response.status_code, 401, response.text)
        with self.assertRaises(HTTPException):
            auth.create_session(1)


if __name__ == "__main__":
    unittest.main()
