"""Tareas 7157218 creation/editing cases adapted to Casos Issue updates."""

import json
import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from dashboard import api_updates, auth, database, issue_service, update_service as service
from dashboard.errors import ApplicationError
from tests import test_issues as issue_tests


class UpdateTests(unittest.TestCase):
    setUp = issue_tests.IssueTests.setUp
    rows = issue_tests.IssueTests.rows

    def setup_issue(self, **kwargs):
        self.client.app.include_router(api_updates.router)
        self.issue = issue_service.create_issue({"title": "Update target", **kwargs}, self.users["alice"])
        return f'/api/issues/{self.issue["id"]}/updates'

    def test_rest_creation_preserves_markdown_author_revision_and_audit(self):
        url = self.setup_issue()
        content = "  # Unicode ü ✓\r\n**Outcome** & <script>alert(1)</script>\n"
        created = []
        for _ in range(2):
            response = self.client.post(url, json={"content": content, "reason": " Test "})
            self.assertEqual(response.status_code, 201, response.text)
            item = response.json()
            self.assertEqual(item["content"], content)
            self.assertEqual(item["content_format"], "markdown")
            self.assertEqual(item["user_id"], self.users["alice"]["id"])
            self.assertEqual(item["user_name"], "alice")
            self.assertEqual(item["revision"], service.update_revision(content))
            self.assertTrue(item["can_write"])
            self.assertFalse(item["can_delete"])
            self.assertEqual(self.client.get(f'{url}/{item["id"]}').json(), item)
            created.append(item)
            audit = self.rows("audit_log")[-1]
            self.assertEqual((audit["entity_type"], audit["entity_id"], audit["action"], audit["reason"]), ("update", item["id"], "create", "Test"))
            self.assertEqual(json.loads(audit["changes_json"]), {"issue_id": self.issue["id"], "owner_user_id": self.users["alice"]["id"], "content_len": len(content)})
            self.assertNotIn(content, audit["changes_json"])
        self.assertNotEqual(created[0]["id"], created[1]["id"])
        self.assertEqual(self.client.get(url).json()["total"], 2)
        self.assertEqual(self.client.post(url, json={"content": "x", "user_id": 1}).status_code, 422)

    def test_all_active_users_read_and_capabilities_match_creation(self):
        url = self.setup_issue(assigned_to=self.users["bob"]["id"])
        service.create_update(self.issue["id"], "First", self.users["alice"])
        for who, allowed in ((self.admin, True), (self.users["alice"], True), (self.users["bob"], True), (self.users["agent"], False)):
            self.user = who
            listing = self.client.get(url)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["can_create"], allowed)
            self.assertEqual(self.client.post(url, json={"content": "Browser"}).status_code, 201 if allowed else 403)
        rev = issue_service.get_editors(self.issue["id"], self.admin)["revision"]
        issue_service.set_editors(self.issue["id"], [self.users["agent"]["id"]], self.admin, revision=rev)
        item = service.create_update(self.issue["id"], "MCP service", self.users["agent"])
        self.assertEqual(item["user_id"], self.users["agent"]["id"])
        self.assertEqual(self.rows("audit_log")[-1]["actor_type"], "mcp")
        self.assertEqual(self.client.get(f'{url}/{item["id"]}').json()["content"], "MCP service")

    def test_author_window_boundaries_preserve_identity_time_and_revision(self):
        self.setup_issue()
        created = service.create_update(self.issue["id"], "Original", self.user)
        instant = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE issue_updates SET created_at=? WHERE id=?", (instant.isoformat(), created["id"]))
        for age, allowed in ((-1, False), (0, True), (299.999, True), (300, False), (301, False)):
            with self.subTest(age=age), patch.object(service, "_utc_now", return_value=instant + timedelta(seconds=age)):
                current = service.get_update(self.issue["id"], created["id"], self.user)
                self.assertEqual(current["can_write"], allowed)
                if allowed:
                    updated = service.edit_update(self.issue["id"], created["id"], f"Age {age}", self.user, current["revision"])
                    self.assertEqual(updated["user_id"], created["user_id"])
                    self.assertEqual(updated["created_at"], instant.isoformat())
                    self.assertEqual(updated["id"], created["id"])
                else:
                    with self.assertRaises(ApplicationError) as caught:
                        service.edit_update(self.issue["id"], created["id"], "Denied", self.user, current["revision"])
                    self.assertEqual(caught.exception.code, "update_edit_window_expired")
        current = service.get_update(self.issue["id"], created["id"], self.admin)
        with patch.object(service, "_utc_now", return_value=instant + timedelta(days=100)):
            self.assertTrue(service.get_update(self.issue["id"], created["id"], self.admin)["can_write"])
            self.assertEqual(service.edit_update(self.issue["id"], created["id"], "Admin correction", self.admin, current["revision"])["content"], "Admin correction")

    def test_only_author_corrects_and_only_admin_deletes(self):
        url = self.setup_issue(assigned_to=self.users["bob"]["id"])
        own = service.create_update(self.issue["id"], "Alice", self.users["alice"])
        self.user = self.users["bob"]
        self.assertFalse(self.client.get(f'{url}/{own["id"]}').json()["can_write"])
        self.assertEqual(self.client.put(f'{url}/{own["id"]}', json={"content": "wrong", "revision": own["revision"]}).status_code, 403)
        for who in (self.users["alice"], self.users["bob"]):
            self.user = who
            self.assertEqual(self.client.delete(f'{url}/{own["id"]}').status_code, 403)
        self.user = self.admin
        self.assertTrue(self.client.get(f'{url}/{own["id"]}').json()["can_delete"])
        self.assertEqual(self.client.delete(f'{url}/{own["id"]}').status_code, 200)
        self.assertEqual(self.client.get(f'{url}/{own["id"]}').status_code, 404)
        self.assertEqual(self.rows("audit_log")[-1]["actor_user_id"], 1)

    def test_revisions_required_for_admin_and_author_and_conflicts_do_not_write(self):
        url = self.setup_issue()
        created = service.create_update(self.issue["id"], "Original", self.user)
        for who in (self.admin, self.users["alice"]):
            self.user = who
            for revision in (None, "", 1, "z" * 64):
                response = self.client.put(f'{url}/{created["id"]}', json={"content": "No", "revision": revision})
                self.assertEqual(response.status_code, 422)
        current = service.edit_update(self.issue["id"], created["id"], "Changed", self.user, created["revision"])
        response = self.client.put(f'{url}/{created["id"]}', json={"content": "Lost", "revision": created["revision"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(service.get_update(self.issue["id"], created["id"], self.user)["revision"], current["revision"])

    def test_revocation_and_deactivation_apply_after_opening(self):
        self.setup_issue(assigned_to=self.users["bob"]["id"])
        created = service.create_update(self.issue["id"], "Bob", self.users["bob"])
        issue_service.update_issue(self.issue["id"], {"assigned_to": None}, self.admin)
        self.assertFalse(service.get_update(self.issue["id"], created["id"], self.users["bob"])["can_write"])
        for callback in (lambda: service.create_update(self.issue["id"], "No", self.users["bob"]),
                         lambda: service.edit_update(self.issue["id"], created["id"], "No", self.users["bob"], created["revision"])):
            with self.assertRaises(ApplicationError) as error:
                callback()
            self.assertEqual(error.exception.status_code, 403)
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE users SET is_active=0 WHERE id=?", (self.users["bob"]["id"],))
        for callback in (lambda: service.list_updates(self.issue["id"], self.users["bob"]),
                         lambda: service.get_update(self.issue["id"], created["id"], self.users["bob"])):
            with self.assertRaises(ApplicationError) as error:
                callback()
            self.assertEqual(error.exception.status_code, 401)

    def test_pagination_orders_time_then_id_and_preserves_authorless_entries(self):
        url = self.setup_issue()
        entries = [service.create_update(self.issue["id"], str(i), self.user) for i in range(4)]
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE issue_updates SET created_at='2026-10-19 12:00:00'")
            db.execute("UPDATE issue_updates SET created_at='2026-10-18 12:00:00' WHERE id=?", (entries[-1]["id"],))
            db.execute("DELETE FROM users WHERE id=?", (self.user["id"],))
        self.user = self.users["bob"]
        first = self.client.get(url + '?limit=2').json()
        second = self.client.get(url + '?limit=2&offset=2').json()
        self.assertEqual([row["id"] for row in first["items"] + second["items"]], [entries[2]["id"], entries[1]["id"], entries[0]["id"], entries[3]["id"]])
        self.assertEqual(first["next_offset"], 2)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(first["total"], 4)
        self.assertIsNone(first["items"][0]["user_id"])
        self.assertFalse(first["items"][0]["can_write"])

    def test_invalid_text_target_reason_and_limits_leave_no_update(self):
        url = self.setup_issue()
        for content in (None, 42, "", " \t\r\n", "\ud800", "ü" * (service.UPDATE_MAX_BYTES // 2 + 1)):
            with self.subTest(content_type=type(content).__name__), self.assertRaises(ApplicationError):
                service.create_update(self.issue["id"], content, self.user)
        with self.assertRaises(ApplicationError):
            service.create_update(self.issue["id"], "no", self.user, reason="x" * 1001)
        self.assertEqual(self.client.post(url, json={}).status_code, 422)
        self.assertEqual(self.rows("issue_updates"), [])
        created = service.create_update(self.issue["id"], "Valid", self.user)
        other = issue_service.create_issue({"title": "Other"}, self.user)
        with self.assertRaises(ApplicationError) as mismatch:
            service.get_update(other["id"], created["id"], self.user)
        self.assertEqual(mismatch.exception.status_code, 404)
        for bad in (True, "1", 0, -1):
            with self.subTest(bad=bad), self.assertRaises(ApplicationError):
                service.get_update(self.issue["id"], bad, self.user)
        for bad_offset, bad_limit in ((True, 1), (0, True), (-1, 50), (0, 501)):
            with self.assertRaises(ApplicationError):
                service.list_updates(self.issue["id"], self.user, bad_offset, bad_limit)

    def test_concurrent_corrections_have_one_winner(self):
        self.setup_issue()
        item = service.create_update(self.issue["id"], "Original", self.user)
        barrier = threading.Barrier(2)
        def edit(content):
            barrier.wait()
            try:
                service.edit_update(self.issue["id"], item["id"], content, self.user, item["revision"])
                return 200
            except ApplicationError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(edit, ("A", "B"))), [200, 409])

    def test_audit_failure_rolls_back_create_edit_and_delete(self):
        self.setup_issue()
        item = service.create_update(self.issue["id"], "Original", self.user)
        with closing(database.get_db()) as db, db:
            db.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON audit_log BEGIN SELECT RAISE(ABORT,'audit failure'); END")
        for action in (lambda: service.create_update(self.issue["id"], "No", self.user),
                       lambda: service.edit_update(self.issue["id"], item["id"], "No", self.user, item["revision"]),
                       lambda: service.delete_update(self.issue["id"], item["id"], self.admin)):
            with self.assertRaises(sqlite3.IntegrityError):
                action()
        self.assertEqual(len(self.rows("issue_updates")), 1)
        self.assertEqual(service.get_update(self.issue["id"], item["id"], self.user)["content"], "Original")


if __name__ == "__main__":
    unittest.main()
