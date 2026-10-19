"""Actual bounded parser processes, current auth and hostile attachment coverage."""
import hashlib
import io
import json
import os
import signal
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from dashboard import api_attachment_preview, attachment_preview, auth, database, preview_worker
from dashboard.errors import ApplicationError
from tests.attachment_test_helpers import AttachmentTestCase
from tests.preview_test_helpers import image_bytes, message_bytes

FIXTURES = Path(__file__).parent / 'fixtures/msg'


class AttachmentPreviewTests(AttachmentTestCase):
    def make_app(self, dedicated=False):
        app = super().make_app(dedicated)
        app.include_router(api_attachment_preview.router)
        return app

    def preview(self, attachment, mode='metadata', index=-1, who='reader'):
        return attachment_preview.preview(self.issue_id, attachment['id'], self.users[who], mode, index)

    def test_five_raster_formats_and_original_bytes(self):
        for format in ('JPEG', 'PNG', 'GIF', 'WEBP', 'BMP'):
            with self.subTest(format=format):
                raw = image_bytes(format)
                attachment = self.add(raw, 'bild.' + format.lower())
                data, _ = self.preview(attachment)
                self.assertEqual((data['kind'], data['width'], data['height']), ('image', 48, 32))
                _, png = self.preview(attachment, 'image')
                with Image.open(io.BytesIO(png)) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertFalse(image.info)
                self.assertEqual(self.read(attachment), raw)

    def test_animation_first_frame_and_metadata_removal(self):
        first, second = Image.new('RGB', (10, 9), 'red'), Image.new('RGB', (10, 9), 'blue')
        stream = io.BytesIO()
        first.save(stream, format='GIF', save_all=True, append_images=[second], duration=10, loop=0)
        attachment = self.add(stream.getvalue(), 'animation.gif')
        data, png = self.preview(attachment, 'image')
        self.assertEqual(data['warnings'], ['first_frame'])
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(image.getpixel((0, 0))[:3], (255, 0, 0))
            self.assertEqual(getattr(image, 'n_frames', 1), 1)

    def test_image_dimension_limits_without_large_fixture(self):
        import zlib
        # Valid IHDR with huge dimensions, rejected before decompression.
        header = __import__('struct').pack('>IIBBBBB', 10001, 1, 8, 2, 0, 0, 0)
        chunk = b'IHDR' + header
        png = b'\x89PNG\r\n\x1a\n' + len(header).to_bytes(4, 'big') + chunk + zlib.crc32(chunk).to_bytes(4, 'big') + b'\x00\x00\x00\x00IEND\xaeB`\x82'
        attachment = self.add(png, 'huge.png')
        with self.assertRaises(ApplicationError) as raised:
            self.preview(attachment)
        self.assertIn(raised.exception.code, {'preview_too_large', 'preview_invalid'})
        # Decodable tall image proves explicit dimension limit.
        attachment = self.add(image_bytes(size=(1, 10001)), 'tall.png')
        with self.assertRaises(ApplicationError) as raised:
            self.preview(attachment)
        self.assertEqual(raised.exception.code, 'preview_too_large')

    def test_corrupt_and_unsupported_formats_keep_original(self):
        for raw, name, code in [(b'broken image', 'broken.png', 'preview_invalid'),
                                 (b'<svg onload="alert(1)"><image href="https://example.invalid/x"/></svg>', 'active.svg', 'preview_unsupported'),
                                 (b'unknown', 'data.bin', 'preview_unsupported'),
                                 (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1broken', 'broken.msg', 'preview_invalid')]:
            attachment = self.add(raw, name)
            with self.assertRaises(ApplicationError) as raised:
                self.preview(attachment)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(self.read(attachment), raw)

    def test_unicode_html_cid_and_embedded_download(self):
        raw = message_bytes('html')
        attachment = self.add(raw, 'message.msg')
        data, _ = self.preview(attachment)
        self.assertEqual(data['subject'], 'Casos Vorschau ü ✓')
        self.assertIn('reader@example.invalid', data['to'])
        self.assertIn('cc@example.invalid', data['cc'])
        self.assertEqual(data['date'], '2026-10-19T12:00:00+02:00')
        self.assertIn('Nachricht ü ✓', data['body'])
        self.assertIn(f'/attachments/{attachment["id"]}/embedded/0/preview/image', data['body'])
        for forbidden in ['script', 'tracker', 'iframe', 'svg', 'style', 'onload', 'window.previewAttack']:
            self.assertNotIn(forbidden, data['body'])
        self.assertIn('resources_removed', data['warnings'])
        self.assertEqual(data['attachments'][0]['name'], 'pixel.png')
        _, embedded = self.preview(attachment, 'embedded', 0)
        self.assertEqual(embedded, image_bytes())
        _, raster = self.preview(attachment, 'embedded-image', 0)
        self.assertTrue(raster.startswith(b'\x89PNG'))
        self.assertEqual(self.read(attachment), raw)
        self.assertEqual(len(self.rows('attachments')), 1)

    def test_utf16_html_bom_preserves_unicode(self):
        data, _ = self.preview(self.add(message_bytes('html-utf16'), 'utf16.msg'))
        self.assertEqual(data['body_format'], 'html')
        self.assertIn('Nachricht ü ✓', data['body'])
        self.assertNotIn('\ufffd', data['body'])

    def test_plain_text_rtf_and_missing_fields(self):
        for kind in ('text', 'rtf'):
            data, _ = self.preview(self.add(message_bytes(kind, attachments=[], extra_headers=False), kind + '.msg'))
            self.assertEqual(data['body_format'], 'text')
            self.assertIn('Text' if kind == 'rtf' else 'Nachrichtentext ü ✓', data['body'])
            self.assertEqual(data['sender'], '')
            self.assertEqual(data['date'], '')
        self.assertIn('rtf_text', data['warnings'])

    def test_official_fixtures_hashes_headers_and_embedded_bytes(self):
        for fixture in json.loads((FIXTURES / 'manifest.json').read_text()):
            with self.subTest(fixture=fixture['name']):
                raw = (FIXTURES / fixture['name']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), fixture['sha256'])
                attachment = self.add(raw, fixture['name'])
                data, _ = self.preview(attachment)
                self.assertEqual(data['kind'], 'msg')
                self.assertTrue(data['body'])
                if fixture['name'] == 'unicode-header.msg':
                    self.assertIn('header_incomplete', data['warnings'])
                    self.assertNotIn('\x00', data['subject'])
                    self.assertTrue(data['to'])
                if fixture['name'] == 'unicode.msg':
                    self.assertEqual(len(data['attachments']), 2)
                    for index, length in enumerate((969674, 1033142)):
                        _, embedded = self.preview(attachment, 'embedded', index)
                        self.assertEqual(len(embedded), length)
                        self.assertTrue(embedded.startswith((b'II', b'MM')))

    def test_duplicate_names_cids_and_traversal_names(self):
        attachments = [{'name': '../../same.png', 'data': image_bytes(), 'cid': 'picture'}] * 2
        data, _ = self.preview(self.add(message_bytes(attachments=attachments), 'duplicates.msg'))
        self.assertEqual(len(data['attachments']), 2)
        self.assertEqual(data['attachments'][0]['name'], '../../same.png')
        self.assertNotEqual(data['attachments'][0]['download_url'], data['attachments'][1]['download_url'])
        self.assertNotIn('<img', data['body'])
        self.assertIn('resources_removed', data['warnings'])

    def test_sanitizer_allowlist_mutations_and_links(self):
        hostile = '<p onclick="alert(1)">safe &amp; text</p><img srcset="https://bad.invalid/a 1x" src="cid:known"><a href="javascript:alert(1)">bad</a><a href="https://example.invalid/page">good</a><math><mtext><img src="https://bad.invalid/m"></mtext></math><form><input name=x><p>hidden</p></form><div style="background:url(https://bad.invalid/s)">end</div><svg><foreignObject><iframe srcdoc="bad"></iframe></foreignObject></svg>'
        parser = preview_worker.MailHTML({'known': 3}, '/api/issues/1/attachments/2')
        parser.feed(hostile)
        clean = parser.result()
        for forbidden in ('onclick', 'srcset', 'javascript', 'bad.invalid', '<math', '<svg', '<form', 'hidden', 'style=', 'srcdoc'):
            self.assertNotIn(forbidden, clean)
        self.assertIn('/embedded/3/preview/image', clean)
        self.assertIn('rel="noopener noreferrer"', clean)
        self.assertIn('safe &amp; text', clean)

    def test_embedded_routes_current_rights_all_active_roles(self):
        attachment = self.add(message_bytes(), 'mail.msg')
        for who in ('reader', 'owner', 'admin', 'agent'):
            with self.subTest(who=who):
                headers = self.headers(who)
                base = self.url + f'/{attachment["id"]}'
                response = self.client.get(base + '/preview', headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                image = self.client.get(base + '/embedded/0/preview/image', headers=headers)
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.headers['content-type'], 'image/png')
                self.assertIn('no-store', image.headers['cache-control'])
                download = self.client.get(base + '/embedded/0/download', headers=headers)
                self.assertEqual(download.content, image_bytes())
                self.assertTrue(download.headers['content-disposition'].startswith('attachment;'))
        self.assertEqual(self.client.get(base + '/preview', headers=self.headers(None)).status_code, 401)
        self.assertEqual(self.client.get(base + '/embedded/-1/download', headers=self.headers('reader')).status_code, 404)
        self.assertEqual(self.client.get(base + '/embedded/1/download', headers=self.headers('reader')).status_code, 404)
        self.assertEqual(self.client.get(base.replace(f'issues/{self.issue_id}', 'issues/999999') + '/preview', headers=self.headers()).status_code, 404)

    def test_dedicated_bearer_and_revocation(self):
        attachment = self.add(message_bytes(), 'mail.msg')
        url = self.url + f'/{attachment["id"]}/embedded/0/download'
        with TestClient(self.make_app(dedicated=True)) as client:
            self.assertEqual(client.get(url, headers=self.headers('reader')).status_code, 401)
            self.assertEqual(client.get(url, headers=self.headers('agent')).status_code, 200)
            with closing(database.get_db()) as db, db:
                db.execute('UPDATE mcp_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE id=?', (self.token_id,))
            self.assertEqual(client.get(url, headers=self.headers('agent')).status_code, 401)
            with self.assertRaises(ApplicationError) as raised:
                self.preview(attachment, who='agent')
            self.assertEqual(raised.exception.code, 'invalid_token')

    def test_revocation_and_deactivation_during_worker(self):
        attachment = self.add(image_bytes(), 'image.png')
        original_wait = subprocess.Popen.wait
        for who, mutation, code in [('agent', 'UPDATE mcp_config SET enabled=0', 'invalid_token'),
                                     ('reader', f'UPDATE users SET is_active=0 WHERE id={self.users["reader"]["id"]}', 'inactive_user')]:
            def wait(process, *args, **kwargs):
                result = original_wait(process, *args, **kwargs)
                with closing(database.get_db()) as db, db:
                    db.execute(mutation)
                return result
            with patch.object(subprocess.Popen, 'wait', wait):
                with self.assertRaises(ApplicationError) as raised:
                    self.preview(attachment, who=who)
            self.assertEqual(raised.exception.code, code)

    def test_logout_during_worker_rechecks_cookie(self):
        attachment = self.add(image_bytes(), 'image.png')
        original = attachment_preview.preview
        def logout(*args, **kwargs):
            result = original(*args, **kwargs)
            with closing(database.get_db()) as db, db:
                db.execute('DELETE FROM sessions')
            return result
        with patch.object(attachment_preview, 'preview', logout):
            response = self.client.get(self.url + f'/{attachment["id"]}/preview', headers=self.headers('reader'))
        self.assertEqual(response.status_code, 401)

    def test_limits_input_count_depth_rtf_and_body(self):
        attachment = self.add(image_bytes(), 'image.png')
        with patch.object(attachment_preview, 'MAX_INPUT', 5):
            with self.assertRaises(ApplicationError) as raised:
                self.preview(attachment)
        self.assertEqual(raised.exception.code, 'preview_too_large')
        for key, limit in [('MAX_ENTRIES', 2), ('MAX_DEPTH', 1), ('MAX_ATTACHMENTS', 0), ('MAX_AGGREGATE', 20), ('MAX_BODY', 2)]:
            with self.subTest(limit=key), patch.object(preview_worker, key, limit):
                with self.assertRaises(preview_worker.PreviewFailure) as raised:
                    preview_worker.preflight_ole(io.BytesIO(message_bytes('rtf')))
                self.assertEqual(raised.exception.code, 'preview_too_large')
        oversized = message_bytes(attachments=[{'name': 'a', 'data': b''}] * 101)
        with self.assertRaises(ApplicationError) as raised:
            self.preview(self.add(oversized, 'too-many.msg'))
        self.assertEqual(raised.exception.code, 'preview_too_large')
        # Actual forged decompressed-size header is rejected by the real subprocess.
        raw = message_bytes('rtf')
        marker = b'LZFu'
        start = raw.index(marker) - 8
        forged = raw[:start+4] + (preview_worker.MAX_BODY + 1).to_bytes(4, 'little') + raw[start+8:]
        with self.assertRaises(ApplicationError) as raised:
            self.preview(self.add(forged, 'rtf-bomb.msg'))
        self.assertEqual(raised.exception.code, 'preview_too_large')

    def test_timeout_busy_and_temp_cleanup(self):
        attachment = self.add(image_bytes(), 'image.png')
        temp_root = self.root / 'preview-temp'
        temp_root.mkdir()
        original_tempdir = tempfile.TemporaryDirectory
        def tempdir(**kwargs):
            return original_tempdir(dir=temp_root, **kwargs)
        with patch.object(attachment_preview.tempfile, 'TemporaryDirectory', tempdir):
            self.preview(attachment)
            self.assertFalse(list(temp_root.iterdir()))
            with patch.object(attachment_preview, 'WORKER_TIMEOUT', 0.00001):
                with self.assertRaises(ApplicationError) as raised:
                    self.preview(attachment)
                self.assertEqual(raised.exception.code, 'preview_timeout')
            self.assertFalse(list(temp_root.iterdir()))
            with self.assertRaises(ApplicationError):
                self.preview(self.add(b'broken', 'bad.msg'))
            self.assertFalse(list(temp_root.iterdir()))
        semaphore = attachment_preview.WORKER_SLOTS
        semaphore.acquire(); semaphore.acquire()
        try:
            with self.assertRaises(ApplicationError) as raised:
                self.preview(attachment)
            self.assertEqual(raised.exception.code, 'preview_busy')
        finally:
            semaphore.release(); semaphore.release()

    def test_worker_resource_limits_are_effective(self):
        # The actual launcher runs this disposable test worker, inheriting no DB or credentials.
        script = self.root / 'limit-worker.py'
        script.write_text('import resource\nresource.setrlimit(resource.RLIMIT_AS,(40*1024*1024,40*1024*1024))\ntry:\n x=bytearray(100*1024*1024)\nexcept MemoryError:\n raise SystemExit(7)\n')
        attachment = self.add(image_bytes(), 'image.png')
        with patch.object(attachment_preview, 'WORKER', script):
            with self.assertRaises(ApplicationError) as raised:
                self.preview(attachment)
            self.assertEqual(raised.exception.code, 'preview_invalid')
        # Exercise production main() limit setup, not only constants in the plan.
        command = [os.sys.executable, '-I', '-c', 'import runpy,sys,resource; d=runpy.run_path(sys.argv[1]); d["main"].__globals__["run"]=lambda *a: ({"limits":list(resource.getrlimit(resource.RLIMIT_AS)), "cpu":list(resource.getrlimit(resource.RLIMIT_CPU)), "files":list(resource.getrlimit(resource.RLIMIT_NOFILE))},None); sys.argv=[sys.argv[1],"0","metadata","-1","/api/issues/1/attachments/1",".png",sys.argv[2]];d["main"]()', str(attachment_preview.WORKER), str(self.root)]
        subprocess.run(command, check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        limits = json.loads((self.root / 'result.json').read_text())
        self.assertEqual(limits['limits'], [512*1024*1024]*2)
        self.assertEqual(limits['cpu'], [5]*2)
        self.assertEqual(limits['files'], [32]*2)
