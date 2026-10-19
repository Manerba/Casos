"""Real session/Bearer REST, stream limits and authentication during upload."""

import tempfile
from contextlib import closing
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette import formparsers

from dashboard import attachment_service as service, auth, database
from tests.attachment_test_helpers import AttachmentTestCase


class AttachmentAuthTests(AttachmentTestCase):
    def test_rest_cookie_and_bearer_round_trips_download_headers_and_delete(self):
        for who in ("owner", "agent"):
            with self.subTest(who=who):
                response = self.client.post(self.url, headers=self.headers(who), files={"file": ("Grüße ' #.bin", b"exact\x00\xff", "application/octet-stream")})
                self.assertEqual(response.status_code, 201, response.text)
                item = response.json()
                meta = self.client.get(self.url + f'/{item["id"]}', headers=self.headers("reader"))
                self.assertEqual(meta.status_code, 200)
                self.assertFalse(meta.json()["can_delete"])
                download = self.client.get(item["download_url"], headers=self.headers("reader"))
                self.assertEqual(download.content, b"exact\x00\xff")
                self.assertEqual(download.headers["content-security-policy"], "sandbox")
                self.assertEqual(download.headers["x-content-type-options"], "nosniff")
                self.assertEqual(download.headers["cache-control"], "private, no-store")
                self.assertIn("filename*=UTF-8''Gr%C3%BC%C3%9Fe%20%27%20%23.bin", download.headers["content-disposition"])
                self.assertEqual(self.client.delete(self.url + f'/{item["id"]}', headers=self.headers(who)).status_code, 200)
        self.assertEqual(self.storage_files(), [])

    def test_csrf_bearer_precedence_revocation_kill_switch_and_deactivation(self):
        item = self.add()
        for who in ("owner", "agent"):
            no_csrf = self.headers(who, csrf=False)
            self.assertEqual(self.client.post(self.url, headers=no_csrf, files={"file": ("x", b"x")}).status_code, 403)
            self.assertEqual(self.client.delete(self.url + f'/{item["id"]}', headers=no_csrf).status_code, 403)
        privileged_cookie = self.headers("admin")
        self.assertEqual(self.client.get(self.url, headers={**privileged_cookie, "Authorization": "Bearer invalid"}).status_code, 401)
        auth.set_mcp_enabled(False)
        self.assertEqual(self.client.get(self.url, headers=self.headers("agent")).status_code, 403)
        auth.set_mcp_enabled(True)
        auth.revoke_mcp_token(self.token_id)
        self.assertEqual(self.client.get(self.url, headers=self.headers("agent")).status_code, 401)
        cookie = self.headers("reader")
        with closing(database.get_db()) as db, db:
            db.execute("UPDATE users SET is_active=0 WHERE id=?", (self.users["reader"]["id"],))
        for url in (self.url, self.url + f'/{item["id"]}', item["download_url"]):
            self.assertEqual(self.client.get(url, headers=cookie).status_code, 401)

    def test_unauthorized_body_is_not_consumed_on_main_or_dedicated_app(self):
        for dedicated in (False, True):
            app = self.make_app(dedicated)
            cases = [(self.headers(None), 401), (self.headers("admin") | {"Authorization": "Bearer invalid"}, 401)]
            if dedicated:
                cases.append((self.headers("owner"), 401))
            else:
                cases.append((self.headers("reader"), 403))
            for headers, expected in cases:
                headers["Content-Type"] = "multipart/form-data; boundary=upload"
                with self.subTest(dedicated=dedicated, expected=expected), patch.object(formparsers, "SpooledTemporaryFile") as spool:
                    status, _, consumed = self.streamed_request(app, headers, [b"not received"])
                    self.assertEqual(status, expected)
                    self.assertEqual(consumed, [])
                    spool.assert_not_called()

    def test_dedicated_bearer_api_rejects_cookie_and_supports_upload(self):
        with TestClient(self.make_app(True)) as client:
            self.assertEqual(client.get(self.url, headers=self.headers("owner")).status_code, 401)
            response = client.post(self.url, headers=self.headers("agent"), files={"file": ("agent.bin", b"data")})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(client.get(response.json()["download_url"], headers=self.headers("agent")).content, b"data")

    def test_actual_main_and_dedicated_application_router_integration(self):
        from dashboard.app import app as main
        from dashboard.mcp_app import app as dedicated
        # No lifespan here: DB and all identities already use this test's
        # isolated data root, and no service or runtime logging is started.
        for app, who in ((main, "owner"), (dedicated, "agent")):
            client = TestClient(app)
            try:
                response = client.post(self.url, headers=self.headers(who), files={"file": ("real-router.bin", b"router\x00\xff")})
                self.assertEqual(response.status_code, 201, response.text)
                item = response.json()
                self.assertEqual(client.get(item["download_url"], headers=self.headers(who)).content, b"router\x00\xff")
                self.assertEqual(client.get(self.url, headers=self.headers(who)).json()["items"][0]["id"], item["id"])
                self.assertEqual(client.delete(self.url + f'/{item["id"]}', headers=self.headers(who, csrf=False)).status_code, 403)
                self.assertEqual(client.delete(self.url + f'/{item["id"]}', headers=self.headers(who)).status_code, 200)
            finally:
                client.close()

    def test_stream_limit_counts_file_bytes_ignores_content_length_and_closes_spool(self):
        prefix = b'--upload\r\nContent-Disposition: form-data; name="file"; filename="stream.bin"\r\n\r\n'
        suffix = b'\r\n--upload--\r\n'
        for declared in (None, "1", "9999999999"):
            for size in (0, 16, 17):
                chunks = [prefix, b"x" * min(size, 16)] + ([b"x"] if size > 16 else []) + [suffix]
                headers = self.headers("agent") | {"Content-Type": "multipart/form-data; boundary=upload"}
                if declared:
                    headers["Content-Length"] = declared
                spools = []
                def spool(*args, **kwargs):
                    f = tempfile.SpooledTemporaryFile(*args, **kwargs)
                    spools.append(f)
                    return f
                before = len(self.rows("attachments"))
                with self.subTest(declared=declared, size=size), patch.object(service, "MAX_UPLOAD_SIZE", 16), \
                        patch.object(formparsers.MultiPartParser, "spool_max_size", 4), \
                        patch.object(formparsers, "SpooledTemporaryFile", spool):
                    status, body, consumed = self.streamed_request(self.app, headers, chunks)
                self.assertEqual(len(spools), 1)
                self.assertTrue(spools[0].closed)
                if size > 16:
                    self.assertEqual(status, 413, body)
                    self.assertEqual(consumed, chunks[:-1])
                    self.assertEqual(len(self.rows("attachments")), before)
                else:
                    self.assertEqual(status, 201, body)
                    self.assertEqual(self.read(body), b"x" * size)
        self.assertEqual(self.rows("attachment_gc"), [])

    def test_disconnect_incomplete_invalid_multipart_and_wrong_field_leave_no_files(self):
        prefix = b'--upload\r\nContent-Disposition: form-data; name="file"; filename="partial.bin"\r\n\r\n'
        for disconnect in (True, False):
            spools = []
            def spool(*args, **kwargs):
                f = tempfile.SpooledTemporaryFile(*args, **kwargs)
                spools.append(f)
                return f
            with patch.object(formparsers, "SpooledTemporaryFile", spool):
                status, _, _ = self.streamed_request(self.app, self.headers() | {"Content-Type": "multipart/form-data; boundary=upload"},
                                                     [prefix, b"unfinished"], disconnect=disconnect)
            self.assertIn(status, (400, 422))
            self.assertTrue(all(f.closed for f in spools))
        # Even a fully ended file part is not a complete multipart message until
        # the terminal boundary arrives; Starlette otherwise returns this file.
        for ending in (b"\r\n--upload", b"\r\n--upload-", b"\r\n--upload\r\n"):
            with self.subTest(truncated_boundary=ending):
                status, _, _ = self.streamed_request(self.app, self.headers() | {"Content-Type": "multipart/form-data; boundary=upload"},
                                                     [prefix, b"complete file", ending])
                self.assertEqual(status, 400)
        for files in ({"other": ("x", b"x")}, [("file", ("x", b"x")), ("file", ("y", b"y"))]):
            response = self.client.post(self.url, headers=self.headers(), files=files)
            self.assertIn(response.status_code, (400, 422))
        response = self.client.post(self.url, headers=self.headers() | {"Content-Type": "multipart/form-data; boundary=upload"}, content=b"bad data")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.rows("attachments"), [])
        self.assertEqual(self.storage_files(), [])

    def test_token_or_contribution_revoked_during_upload_prevents_publication(self):
        prefix = b'--upload\r\nContent-Disposition: form-data; name="file"; filename="partial.bin"\r\n\r\n'
        suffix = b'\r\n--upload--\r\n'
        for who in ("editor", "agent", "owner"):
            def revoke(index):
                if index == 1:
                    if who == "agent":
                        auth.revoke_mcp_token(self.token_id)
                    elif who == "owner":
                        with closing(database.get_db()) as db, db:
                            db.execute("DELETE FROM sessions WHERE user_id=?", (self.users[who]["id"],))
                    else:
                        with closing(database.get_db()) as db, db:
                            db.execute("DELETE FROM issue_editors WHERE user_id=?", (self.users[who]["id"],))
            status, body, _ = self.streamed_request(self.app, self.headers(who) | {"Content-Type": "multipart/form-data; boundary=upload"},
                                                   [prefix, b"x", suffix], before_chunk=revoke)
            self.assertEqual(status, 403 if who == "editor" else 401, body)
        self.assertEqual(self.rows("attachments"), [])
        self.assertEqual(self.storage_files(), [])
