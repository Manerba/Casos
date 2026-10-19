"""Actual Chromium/HTTP/SQLite preview flows; isolated data and fake mail only."""
import json
import re
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from browser_support import browser_server, browser_login
from preview_test_helpers import image_bytes, message_bytes


def main():
    artifacts = Path('/tmp/casos-preview-evidence')
    artifacts.mkdir(exist_ok=True)
    headers = {'X-Requested-With': 'XMLHttpRequest'}
    with browser_server() as fixture, sync_playwright() as pw:
        base = fixture['url']
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(15000)
        errors, missing, unsafe, image_active, image_counts = [], [], [], set(), []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: missing.append(message.text) if 'i18n: Missing key' in message.text else None)
        def request(request):
            if 'tracker.example.invalid' in request.url or 'forbidden-preview-resource' in request.url:
                unsafe.append(request.url)
            if request.url.endswith('/preview/image'):
                image_active.add(request)
                image_counts.append(len(image_active))
        page.on('request', request)
        page.on('requestfinished', lambda request: image_active.discard(request))
        page.on('requestfailed', lambda request: image_active.discard(request))
        browser_login(page, base)
        result = page.request.post(base + '/api/issues', headers=headers, data={'title': 'Vorschau ü ✓', 'description': 'Draft baseline'})
        assert result.status == 201, result.text()
        issue_id = result.json()['id']
        issue_url = base + f'/api/issues/{issue_id}'
        fixtures = [(f'Bild.{fmt.lower()}', image_bytes(fmt)) for fmt in ('JPEG', 'PNG', 'GIF', 'WEBP', 'BMP')]
        triple = [{'name': f'Bild-{i}.png', 'data': image_bytes(size=(60+i, 40)), 'mime': 'image/png', 'cid': f'image{i}'} for i in range(3)]
        mail_html = '<h2>HTML ü ✓</h2>' + ''.join(f'<img src="cid:image{i}">' for i in range(3)) + '<script>window.previewAttack=1</script><img src="https://tracker.example.invalid/pixel"><img src="/forbidden-preview-resource"><svg onload="window.previewAttack=2"></svg><iframe src="https://tracker.example.invalid/frame"></iframe>'
        fixtures += [('Drei-CID.msg', message_bytes('html', attachments=triple, body=mail_html)),
                     ('Text.msg', message_bytes('text')), ('RTF.msg', message_bytes('rtf')),
                     ('UTF16.msg', message_bytes('html-utf16')),
                     ('Aktiv.svg', b'<svg onload="window.previewAttack=3"><image href="https://tracker.example.invalid/svg"/></svg>'),
                     ('Defekt.msg', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1broken'),
                     ('Defekt.png', b'broken')]
        official = Path(__file__).parent / 'fixtures/msg'
        fixtures += [(name, (official / name).read_bytes()) for name in ('unicode-header.msg', 'strangeDate.msg', 'unicode.msg')]
        uploaded = {}
        for name, raw in fixtures:
            response = page.request.post(issue_url + '/attachments', headers=headers,
                multipart={'file': {'name': name, 'mimeType': 'application/octet-stream', 'buffer': raw}})
            assert response.status == 201, response.text()
            uploaded[name] = {'id': response.json()['id'], 'raw': raw}
        page.goto(base + f'/issues/{issue_id}')
        expect(page.locator('.issue-attachment')).to_have_count(len(fixtures))
        page.locator('.issue-description-panel [data-md-action=edit]').click()
        draft = page.locator('.issue-description-panel textarea')
        draft.fill('Ungespeicherter Entwurf während Vorschau ü ✓')
        dialog = page.locator('.attachment-preview')
        def open_preview(name):
            trigger = page.locator(f'[data-preview-attachment="{uploaded[name]["id"]}"]')
            trigger.focus()
            trigger.press('Enter')
            expect(dialog).to_be_visible()
            expect(dialog.locator('[data-preview-close]')).to_be_focused()
            expect(dialog.locator('#attachment-preview-title')).to_have_text(name)
            expect(dialog.locator('.preview-content')).to_have_attribute('aria-busy', 'false')
            return trigger
        def close_preview(trigger):
            page.keyboard.press('Escape')
            expect(dialog).to_have_count(0)
            expect(trigger).to_be_focused()
            expect(draft).to_have_value('Ungespeicherter Entwurf während Vorschau ü ✓')
        for fmt in ('JPEG', 'PNG', 'GIF', 'WEBP', 'BMP'):
            trigger = open_preview('Bild.' + fmt.lower())
            image = dialog.locator('.preview-raster')
            expect(image).to_have_attribute('src', re.compile('^blob:'))
            expect(image).to_be_visible()
            assert image.evaluate('(image) => image.naturalWidth') == 48
            dialog.get_by_role('button', name='Vergrößern', exact=True).click()
            expect(image).to_have_class(re.compile('preview-zoomed'))
            dialog.get_by_role('button', name='Einpassen', exact=True).click()
            expect(image).not_to_have_class(re.compile('preview-zoomed'))
            if fmt == 'PNG': page.screenshot(path=str(artifacts / 'image-png.png'))
            close_preview(trigger)
        trigger = open_preview('Drei-CID.msg')
        images = dialog.locator('.preview-mail-body img')
        expect(images).to_have_count(3)
        for image in images.all():
            expect(image).to_have_attribute('src', re.compile('^blob:'))
            assert image.evaluate('(image) => image.naturalWidth') >= 60
        expect(dialog.locator('.preview-embedded li')).to_have_count(3)
        expect(dialog.locator('.preview-embedded-image')).to_have_count(0)
        assert max(image_counts) == 1, image_counts
        assert not unsafe, unsafe
        assert page.evaluate('window.previewAttack') is None
        assert not dialog.locator('script,iframe,svg,style').count()
        with page.expect_download() as download:
            dialog.locator('.preview-embedded a').first.click()
        download.value.save_as(artifacts / 'embedded.png')
        assert (artifacts / 'embedded.png').read_bytes() == triple[0]['data']
        with page.expect_download() as download:
            dialog.locator('.preview-actions a').click()
        download.value.save_as(artifacts / 'original.msg')
        assert (artifacts / 'original.msg').read_bytes() == uploaded['Drei-CID.msg']['raw']
        page.screenshot(path=str(artifacts / 'mail-three-cid.png'))
        # Native dialog traps tab focus; return to the issue trigger after Escape.
        for _ in range(10):
            page.keyboard.press('Tab')
            assert page.evaluate('Boolean(document.activeElement.closest(".attachment-preview"))')
        close_preview(trigger)
        for name, text in [('Text.msg', 'Reiner Nachrichtentext ü ✓'), ('RTF.msg', 'Normaler RTF Text'), ('UTF16.msg', 'HTML Nachricht ü ✓')]:
            trigger = open_preview(name)
            expect(dialog.locator('.preview-mail-body')).to_contain_text(text)
            if name == 'RTF.msg': page.screenshot(path=str(artifacts / 'mail-rtf.png'))
            close_preview(trigger)
        for name in ('unicode-header.msg', 'strangeDate.msg', 'unicode.msg'):
            trigger = open_preview(name)
            expect(dialog.locator('.preview-mail-body')).not_to_be_empty()
            if name == 'unicode-header.msg':
                expect(dialog.locator('.preview-warning')).to_contain_text('Mailkopffelder')
            page.screenshot(path=str(artifacts / (name + '.png')))
            close_preview(trigger)
        for name in ('Aktiv.svg', 'Defekt.msg', 'Defekt.png'):
            trigger = open_preview(name)
            expect(dialog.locator('.preview-error')).to_be_visible()
            expect(dialog.locator('.preview-actions a')).to_be_visible()
            assert not dialog.locator('img,svg,iframe,object').count()
            close_preview(trigger)
        # A real image response failure offers explicit retry and then succeeds.
        image_url = issue_url + f'/attachments/{uploaded["Bild.png"]["id"]}/preview/image'
        page.route(image_url, lambda route: route.fulfill(status=503, json={'code': 'preview_busy'}), times=1)
        trigger = open_preview('Bild.png')
        retry = dialog.get_by_role('button', name='Erneut versuchen')
        expect(retry).to_be_visible()
        retry.click()
        expect(dialog.locator('.preview-raster')).to_have_attribute('src', re.compile('^blob:'))
        close_preview(trigger)
        # Main parser failure also retries, retaining focus and original download.
        preview_url = issue_url + f'/attachments/{uploaded["Text.msg"]["id"]}/preview'
        page.route(preview_url, lambda route: route.fulfill(status=503, json={'code': 'preview_busy'}), times=1)
        trigger = open_preview('Text.msg')
        expect(dialog.locator('.preview-error')).to_be_visible()
        dialog.get_by_role('button', name='Erneut versuchen').click()
        expect(dialog.locator('.preview-mail-body')).to_contain_text('Nachrichtentext')
        close_preview(trigger)
        # Closing a pending fetch aborts and returns focus without later reopening.
        held = []
        page.route(preview_url, lambda route: held.append(route))
        trigger = page.locator(f'[data-preview-attachment="{uploaded["Text.msg"]["id"]}"]')
        trigger.click()
        expect(dialog.locator('.preview-loading')).to_be_visible()
        expect(dialog.locator('.preview-actions a')).to_be_visible()
        close_preview(trigger)
        for route in held: route.abort()
        page.unroute(preview_url)
        # Narrow viewport and dark theme keep content and controls usable.
        page.set_viewport_size({'width': 390, 'height': 844})
        page.evaluate("setColorScheme('dark')")
        trigger = open_preview('Drei-CID.msg')
        expect(dialog.locator('.preview-mail-body img').first).to_have_attribute('src', re.compile('^blob:'))
        assert dialog.bounding_box()['width'] <= 390
        expect(page.locator('html')).to_have_attribute('data-color-scheme', 'dark')
        assert dialog.evaluate('(element) => getComputedStyle(element).backgroundColor') == 'rgb(11, 18, 32)'
        expect(dialog.locator('[data-preview-close]')).to_be_visible()
        page.screenshot(path=str(artifacts / 'mail-mobile-dark.png'))
        close_preview(trigger)
        # Another normal reader can open the same content without contribution rights.
        bob_context = browser.new_context()
        bob = bob_context.new_page()
        browser_login(bob, base, 'bob')
        bob.goto(base + f'/issues/{issue_id}')
        bob.locator(f'[data-preview-attachment="{uploaded["Drei-CID.msg"]["id"]}"]').click()
        expect(bob.locator('.preview-mail-body')).to_contain_text('HTML ü ✓')
        expect(bob.locator('#issue-attach')).to_be_hidden()
        assert not unsafe, unsafe
        assert not errors, errors
        assert not missing, missing
        assert len(page.request.get(issue_url + '/attachments').json()['items']) == len(fixtures)
        (artifacts / 'result.json').write_text(json.dumps({'status':'passed','formats':['JPEG','PNG','GIF','WebP','BMP'], 'message_fixtures':8,'unsafe_requests':unsafe,'page_errors':errors,'max_parallel_image_requests':max(image_counts),'fixture_count':len(fixtures)},indent=2)+'\n')
        browser.close()
    print('Preview browser checks passed; evidence: ' + str(artifacts))


if __name__ == '__main__':
    main()
