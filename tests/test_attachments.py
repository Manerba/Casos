"""Attachment data, permissions, crash recovery and filesystem isolation."""

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from dashboard import attachment_service as service, auth, database, issue_service
from dashboard.errors import ApplicationError
from tests.attachment_test_helpers import AttachmentTestCase


class AttachmentTests(AttachmentTestCase):
    def test_binary_equal_names_empty_files_metadata_pagination_and_audit(self):
        one = self.add(b"first\x00\xff", "Prüfung ' #.bin", reason=" test ")
        two = self.add(b"second", "Prüfung ' #.bin")
        empty = self.add(b"")
        self.assertNotEqual(one["id"], two["id"])
        self.assertEqual(self.read(one), b"first\x00\xff")
        self.assertEqual(self.read(two), b"second")
        self.assertEqual(self.read(empty), b"")
        self.assertNotIn("storage_name", one)
        self.assertEqual(one["uploader_name"], "Owner")
        page = service.list_attachments(self.issue_id, self.users["reader"], limit=2)
        self.assertEqual([r["id"] for r in page["items"]], [empty["id"], two["id"]])
        self.assertEqual((page["total"], page["next_offset"], page["can_upload"]), (3, 2, False))
        self.assertEqual(service.list_attachments(self.issue_id, self.users["reader"], offset=2)["items"][0]["id"], one["id"])
        audit = [r for r in self.rows("audit_log") if r["entity_type"] == "attachment"]
        self.assertEqual(audit[0]["reason"], "test")
        self.assertEqual(json.loads(audit[0]["changes_json"])["size"], 7)
        self.assertNotIn("first", audit[0]["changes_json"])
        self.assertEqual(self.rows("attachment_gc"), [])

    def test_concurrent_equal_names_are_distinct(self):
        barrier = threading.Barrier(4)
        def upload(number):
            barrier.wait()
            return self.add(str(number).encode())
        with ThreadPoolExecutor(max_workers=4) as pool:
            attachments = list(pool.map(upload, range(4)))
        self.assertEqual(len({r["id"] for r in attachments}), 4)
        self.assertEqual({self.read(r) for r in attachments}, {b"0", b"1", b"2", b"3"})
        self.assertEqual(len(self.storage_files()), 4)

    def test_permissions_include_uploader_current_contribution_and_current_admin(self):
        other = self.add(who="owner")
        for who in self.users:
            self.assertEqual(self.read(other, who), b"binary\x00\xff")
        for who in ("assignee", "editor", "agent", "admin"):
            own = self.add(who=who)
            self.assertTrue(service.get_attachment(self.issue_id, own["id"], self.users[who])["can_delete"])
            if who != "admin":
                with self.assertRaises(ApplicationError) as e:
                    service.delete_attachment(self.issue_id, other["id"], self.users[who])
                self.assertEqual(e.exception.status_code, 403)
            service.delete_attachment(self.issue_id, own["id"], self.users[who])
        with self.assertRaises(ApplicationError):
            self.add(who="reader")
        own = self.add(who="editor")
        with closing(database.get_db()) as db, db:
            db.execute("DELETE FROM issue_editors WHERE user_id=?", (self.users["editor"]["id"],))
        self.assertFalse(service.get_attachment(self.issue_id, own["id"], self.users["editor"])["can_delete"])
        with self.assertRaises(ApplicationError):
            service.delete_attachment(self.issue_id, own["id"], self.users["editor"])
        # A forged cached administrator flag does not grant deletion.
        with self.assertRaises(ApplicationError):
            service.delete_attachment(self.issue_id, other["id"], {**self.users["reader"], "is_admin": 1})
        service.delete_attachment(self.issue_id, other["id"], self.users["admin"])

    def test_stream_is_bounded_and_limit_failure_leaves_no_attachment(self):
        sizes = []
        class Bounded(io.BytesIO):
            def read(self, size=-1):
                sizes.append(size)
                if not 0 < size <= service.COPY_CHUNK_SIZE:
                    raise AssertionError("unbounded read")
                return super().read(size)
        good = self.add(Bounded(b"x" * (service.COPY_CHUNK_SIZE + 1)))
        self.assertEqual(len(self.read(good)), service.COPY_CHUNK_SIZE + 1)
        self.assertGreater(len(sizes), 1)
        with patch.object(service, "MAX_UPLOAD_SIZE", 8), self.assertRaises(ApplicationError) as e:
            self.add(Bounded(b"123456789"))
        self.assertEqual(e.exception.status_code, 413)
        self.assertEqual(len(self.rows("attachments")), 1)
        self.assertEqual(self.rows("attachment_gc"), [])
        self.assertEqual(len(self.storage_files()), 1)

    def test_filename_type_reason_validation_precedes_mutations(self):
        for filename in ("", " ", ".", "..", "../x", "/tmp/x", "a\\b", "%252e%252e%252fetc", "a\nheader", "a\x00b", "\ud800", "a" * 256):
            with self.subTest(filename=repr(filename)), self.assertRaises(ApplicationError):
                self.add(name=filename)
        for kwargs in ({"media_type": "text/plain\r\nX: x"}, {"reason": "x" * 1001}, {"content": "text"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ApplicationError):
                self.add(**kwargs)
        self.assertEqual(self.rows("attachments"), [])
        self.assertEqual(self.rows("attachment_gc"), [])
        self.assertEqual(self.storage_files(), [])
        safe = self.add(name="100% done.bin")
        self.assertEqual(safe["original_name"], "100% done.bin")
        text = self.add(b"utf-8", "text.txt", media_type="text/plain; charset=UTF-8")
        self.assertEqual(text["media_type"], "text/plain")

    def test_storage_audit_and_read_failures_preserve_existing_files(self):
        original = self.add(b"keep")
        with patch.object(service.os, "fsync", side_effect=OSError("disk failed")), self.assertRaises(ApplicationError):
            self.add(b"failed")
        # Failed cleanup fsync leaves a durable job even if its file is gone.
        service.process_attachment_gc()
        class Broken:
            def read(self, size):
                raise OSError("read failed")
        with self.assertRaises(ApplicationError):
            self.add(Broken())
        with closing(database.get_db()) as db, db:
            db.execute("CREATE TRIGGER audit_failure BEFORE INSERT ON audit_log BEGIN SELECT RAISE(ABORT,'audit failed'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add(b"not published")
        with self.assertRaises(sqlite3.IntegrityError):
            service.delete_attachment(self.issue_id, original["id"], self.users["owner"])
        self.assertEqual(self.read(original), b"keep")
        self.assertEqual(len(self.rows("attachments")), 1)
        self.assertEqual(len(self.storage_files()), 1)
        self.assertEqual(self.rows("attachment_gc"), [])

    def test_cleanup_failure_is_durable_and_retryable_and_issue_delete_cleans_all(self):
        one = self.add()
        with patch.object(service.os, "unlink", side_effect=PermissionError("disk busy")):
            self.assertEqual(service.delete_attachment(self.issue_id, one["id"], self.users["owner"]), {"ok": True})
        self.assertEqual(len(self.rows("attachment_gc")), 1)
        self.assertEqual(self.rows("attachment_gc")[0]["last_error"], "PermissionError")
        self.assertEqual(len(self.storage_files()), 1)
        self.assertEqual(service.process_attachment_gc(), {"removed": 1, "pending": 0, "failed": 0})
        self.assertEqual(service.process_attachment_gc()["removed"], 0)
        self.add(b"one")
        self.add(b"two")
        with patch.object(service.os, "unlink", side_effect=PermissionError("disk busy")):
            issue_service.delete_issue(self.issue_id, self.users["owner"])
        self.assertEqual(len(self.rows("attachment_gc")), 2)
        self.assertEqual(service.process_attachment_gc()["removed"], 2)
        self.assertEqual(self.storage_files(), [])

    def test_gc_cannot_remove_live_upload_and_revoked_user_cannot_publish(self):
        entered, resume = threading.Event(), threading.Event()
        class Paused(io.BytesIO):
            def read(self, size=-1):
                if not entered.is_set():
                    entered.set()
                    if not resume.wait(10):
                        raise AssertionError("upload not resumed")
                return super().read(size)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.add, Paused(b"pending"), who="agent")
            self.assertTrue(entered.wait(10))
            try:
                result = service.process_attachment_gc()
                self.assertEqual((result["removed"], result["pending"]), (0, 1))
                self.assertTrue(self.storage_files()[0].endswith(".part"))
                auth.revoke_mcp_token(self.token_id)
            finally:
                resume.set()
            with self.assertRaises(ApplicationError) as e:
                future.result(10)
            self.assertEqual(e.exception.status_code, 401)
        self.assertEqual(self.rows("attachments"), [])
        self.assertEqual(self.rows("attachment_gc"), [])
        self.assertEqual(self.storage_files(), [])

    def test_crashed_upload_is_removed_after_restart(self):
        code = """
import os
from dashboard import attachment_service as s
phase = os.environ['ATTACHMENT_TEST_PHASE']
original_open, original_replace = os.open, os.replace
def opened(path, *args, **kwargs):
    fd = original_open(path, *args, **kwargs)
    if phase == 'create' and str(path).endswith('.part'): os._exit(0)
    return fd
def replaced(*args, **kwargs):
    original_replace(*args, **kwargs)
    if phase == 'publish': os._exit(0)
os.open, os.replace = opened, replaced
class Die:
    def read(self, size): os._exit(0)
s.add_attachment(int(os.environ['ATTACHMENT_TEST_ISSUE']), {'id': int(os.environ['ATTACHMENT_TEST_USER'])}, original_name='interrupted', content=Die() if phase == 'copy' else b'complete')
"""
        env = {**os.environ, "CASOS_DATA_DIR": str(self.root), "ATTACHMENT_TEST_ISSUE": str(self.issue_id),
               "ATTACHMENT_TEST_USER": str(self.users["owner"]["id"])}
        for phase in ("create", "copy", "publish"):
            with self.subTest(phase=phase):
                subprocess.run([sys.executable, "-c", code], env=env | {"ATTACHMENT_TEST_PHASE": phase}, check=True, timeout=15)
                self.assertEqual(len(self.rows("attachment_gc")), 1)
                self.assertEqual(len(self.storage_files()), 1)
                self.assertEqual(self.rows("attachments"), [])
                database.init_db()
                self.assertEqual(service.process_attachment_gc()["removed"], 1)
                self.assertEqual(self.storage_files(), [])

    def test_symlinks_hardlinks_corrupt_queue_and_live_metadata_are_safe(self):
        attachment = self.add(b"original")
        path = service.attachment_path(self.issue_id, attachment["id"], self.users["owner"])
        outside = self.root / "outside"
        outside.write_bytes(b"original")
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(ApplicationError):
            self.read(attachment)
        path.unlink()
        os.link(outside, path)
        with self.assertRaises(ApplicationError):
            self.read(attachment)
        path.unlink()
        path.write_bytes(b"original")
        with closing(database.get_db()) as db, db:
            db.execute("INSERT INTO attachment_gc(storage_name) VALUES(?)", (path.name,))
            db.execute("INSERT INTO attachment_gc(storage_name) VALUES('../outside')")
        result = service.process_attachment_gc()
        self.assertEqual(result, {"removed": 1, "pending": 1, "failed": 1})
        self.assertEqual(self.read(attachment), b"original")
        self.assertEqual(outside.read_bytes(), b"original")
        self.assertEqual(self.rows("attachment_gc")[0]["last_error"], "invalid_storage_name")

    def test_storage_root_symlink_is_rejected(self):
        target = self.root / "other"
        target.mkdir()
        (self.root / "attachments").symlink_to(target, target_is_directory=True)
        with self.assertRaises(ApplicationError) as e:
            self.add()
        self.assertEqual(e.exception.status_code, 503)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(self.rows("attachment_gc"), [])

    def test_backup_restore_preserves_mapping_bytes_and_current_rights(self):
        attachment = self.add(b"backup\x00\xff")
        with tempfile.TemporaryDirectory(prefix="casos-attachment-restore-") as tmp:
            backup = Path(tmp)
            with closing(database.get_db()) as source, closing(sqlite3.connect(backup / "casos.db")) as dest:
                source.backup(dest)
            shutil.copytree(self.root / "attachments", backup / "attachments")
            with patch.object(database, "DB_DIR", backup), patch.object(database, "DB_PATH", backup / "casos.db"):
                database.init_db()
                self.assertEqual(self.read(attachment), b"backup\x00\xff")
                self.assertEqual(service.get_attachment(self.issue_id, attachment["id"], self.users["reader"])["id"], attachment["id"])

    def test_wrong_issue_inactive_user_invalid_ids_and_missing_files(self):
        attachment = self.add()
        other = issue_service.create_issue({"title": "Other"}, self.users["reader"])
        with self.assertRaises(ApplicationError) as e:
            service.get_attachment(other["id"], attachment["id"], self.users["owner"])
        self.assertEqual(e.exception.status_code, 404)
        for bad in (0, -1, True, "1"):
            with self.subTest(bad=bad), self.assertRaises(ApplicationError):
                service.get_attachment(self.issue_id, bad, self.users["owner"])
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE users SET is_active=0 WHERE id=?", (self.users["reader"]["id"],))
        with self.assertRaises(ApplicationError):
            self.read(attachment)
        path = service.attachment_path(self.issue_id, attachment["id"], self.users["owner"])
        path.unlink()
        with self.assertRaises(ApplicationError) as missing:
            self.read(attachment, "owner")
        self.assertEqual(missing.exception.code, "attachment_file_missing")
