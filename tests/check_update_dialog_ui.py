"""Real HTTP/browser checks for the Update dialog ported from Tareas 7157218.

Uses a temporary Casos server, genuine cookies/REST/SQLite, genuine UI assets,
and a minimal page harness. Only an explicit failed request is intercepted.
No repo runtime data or real mail transport is used.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_support import browser_server


HTML = '''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/css/style.css">
<link rel="stylesheet" href="/static/css/markdown_editor.css">
<link rel="stylesheet" href="/static/css/update_dialog.css">
</head><body data-standalone="true">
<button id="add">Update hinzufügen</button>
<section id="foreign-dialog"><textarea id="foreign-draft">Anderer Entwurf</textarea></section>
<div id="updates-view"></div>
<script src="/static/js/i18n.js"></script>
<script src="/static/js/app_core.js"></script>
<script src="/static/js/vendor/marked.umd.js"></script>
<script src="/static/js/vendor/turndown.js"></script>
<script src="/static/js/markdown_editor.js"></script>
<script src="/static/js/update_dialog.js"></script>
</body></html>'''

CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'self'"
HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def main():
    artifacts = Path('/tmp/casos-update-dialog-evidence')
    artifacts.mkdir(exist_ok=True)
    with browser_server() as fixture, sync_playwright() as pw:
        base = fixture['url']
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.route(base + '/updates-harness', lambda route: route.fulfill(
            status=200, content_type='text/html', body=HTML, headers={'Content-Security-Policy': CSP}))
        # Allow the package test to run before root merges its translation artifact.
        additions = json.loads((ROOT / 'docs/project77-update-translations.json').read_text())['de']
        translations = {**json.loads((ROOT / 'dashboard/static/i18n/de.json').read_text()), **additions}
        context.route(base + '/static/i18n/de.json', lambda route: route.fulfill(json=translations))
        context.add_init_script("""window.cspViolations=[]; document.addEventListener('securitypolicyviolation', event =>
            window.cspViolations.push({directive:event.effectiveDirective, blocked:event.blockedURI}));""")
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = page.request.post(base + '/api/auth/login', data={'username': 'alice', 'password': 'Browser77!'}, headers=HEADERS)
        assert response.ok, response.text()
        issue = page.request.post(base + '/api/issues', data={'title': 'Dialog integration'}, headers=HEADERS).json()
        url = base + f'/api/issues/{issue["id"]}/updates'
        page.goto(base + '/updates-harness')
        page.evaluate('''issueId => {
            window.saved=[]; window.callbacks=[];
            window.addEventListener('update-saved', event => {
                saved.push(event.detail);
                document.getElementById('updates-view').textContent = event.detail.entry.content;
            });
            document.getElementById('add').onclick = () => openUpdateDialog(issueId, null, {
                onSaved: entry => callbacks.push(entry.id)
            });
        }''', issue['id'])
        posts = []
        page.on('request', lambda request: posts.append(request.post_data_json) if request.method == 'POST' and request.url == url else None)
        dialog = page.locator('dialog.update-dialog')
        page.locator('#add').click()
        expect(dialog.locator('textarea')).to_be_focused()
        dialog.locator('textarea').fill(' \n\t ')
        dialog.locator('[data-md-action="save"]').click()
        expect(dialog.locator('.markdown-error')).to_have_text(additions['updates.empty'])
        assert posts == []

        content = '## Neues Update ü ✓\n\n<script>window.injected = true</script>\n**Ergebnis**'
        dialog.locator('textarea').fill(content)
        page.route(url, lambda route: route.fulfill(status=503, json={'detail': 'Test transport unavailable'}) if route.request.method == 'POST' else route.continue_(), times=1)
        dialog.locator('[data-md-action="save"]').click()
        expect(dialog.locator('.markdown-error')).to_have_text('Test transport unavailable')
        expect(dialog.locator('textarea')).to_have_value(content)
        assert page.request.get(url).json()['total'] == 0
        page.evaluate('''() => {
            const save = document.querySelector('[data-md-action="save"]'); save.click(); save.click();
        }''')
        expect(dialog.locator('textarea')).to_be_hidden()
        expect(page.locator('#updates-view')).to_have_text(content)
        assert len(posts) == 2, posts
        listing = page.request.get(url).json()
        assert listing['total'] == 1
        item = listing['items'][0]
        assert item['content'] == content
        assert page.evaluate('window.injected') is None
        assert page.evaluate('saved.length') == 1
        assert page.evaluate('callbacks.length') == 1
        expect(dialog.locator('.update-dialog-title')).to_contain_text(f'#{item["id"]}')
        expect(dialog.locator('.update-dialog-title')).to_contain_text('Alice')

        # Correction uses PUT on the same ID and returns a fresh revision.
        dialog.locator('[data-md-action="edit"]').click()
        dialog.locator('textarea').fill('## Korrektur')
        dialog.locator('[data-md-action="save"]').click()
        expect(page.locator('#updates-view')).to_have_text('## Korrektur')
        assert page.request.get(url).json()['total'] == 1
        assert len(posts) == 2
        assert page.evaluate('saved[1].isNew') is False
        current = page.request.get(url + f'/{item["id"]}').json()

        # A genuine concurrent REST write causes a 409; draft and base revision survive.
        dialog.locator('[data-md-action="edit"]').click()
        dialog.locator('textarea').fill('Mein offener Entwurf')
        concurrent = page.request.put(url + f'/{item["id"]}', data={'content': 'Fremde aktuelle Fassung', 'revision': current['revision']}, headers=HEADERS)
        assert concurrent.ok, concurrent.text()
        dialog.locator('[data-md-action="save"]').click()
        expect(dialog.locator('.markdown-error')).to_have_text(additions['updates.conflict'])
        expect(dialog.locator('textarea')).to_have_value('Mein offener Entwurf')
        page.once('dialog', lambda prompt: prompt.dismiss())
        dialog.locator('[data-update-close]').click()
        expect(dialog.locator('textarea')).to_have_value('Mein offener Entwurf')
        page.screenshot(path=str(artifacts / 'revision-conflict.png'))
        page.once('dialog', lambda prompt: prompt.accept())
        dialog.locator('[data-update-close]').click()
        expect(dialog).to_have_count(0)
        expect(page.locator('#add')).to_be_focused()
        expect(page.locator('#foreign-draft')).to_have_value('Anderer Entwurf')

        # Cancel, blank Escape, focus return and preservation of another dialog's draft.
        page.locator('#add').click()
        dialog.locator('textarea').fill('Not saved')
        dialog.locator('[data-md-action="cancel"]').click()
        expect(dialog).to_have_count(0)
        page.locator('#add').click()
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        assert page.request.get(url).json()['total'] == 1
        expect(page.locator('#foreign-draft')).to_have_value('Anderer Entwurf')

        # Opening a different update cannot discard the existing draft silently.
        page.locator('#add').click()
        dialog.locator('textarea').fill('Keep active draft')
        page.once('dialog', lambda prompt: prompt.dismiss())
        page.evaluate('([issueId, updateId]) => openUpdateDialog(issueId, updateId)', [issue['id'], item['id']])
        expect(dialog.locator('textarea')).to_have_value('Keep active draft')
        dialog.locator('[data-md-action="cancel"]').click()

        # Narrow screen and keyboard traversal stay inside the native modal.
        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('#add').click()
        dialog.locator('textarea').fill('## Mobil ✓')
        page.keyboard.press('Tab')
        assert page.evaluate('document.querySelector("dialog").contains(document.activeElement)')
        bounds = dialog.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
        page.screenshot(path=str(artifacts / 'creation-mobile.png'))
        dialog.locator('[data-md-action="save"]').click()
        expect(dialog.locator('textarea')).to_be_hidden()
        dialog.locator('[data-update-close]').click()
        page.set_viewport_size({'width': 1280, 'height': 900})

        # A separate normal identity reads the same update, with no edit button.
        bob = browser.new_context(viewport={'width': 900, 'height': 700})
        bob.route(base + '/updates-harness', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML, headers={'Content-Security-Policy': CSP}))
        bob.route(base + '/static/i18n/de.json', lambda route: route.fulfill(json=translations))
        bobpage = bob.new_page()
        bobpage.on('pageerror', lambda error: errors.append(str(error)))
        assert bobpage.request.post(base + '/api/auth/login', data={'username': 'bob', 'password': 'Browser77!'}, headers=HEADERS).ok
        bobpage.goto(base + '/updates-harness')
        bobpage.evaluate('([issueId, updateId]) => openUpdateDialog(issueId, updateId)', [issue['id'], item['id']])
        bobdialog = bobpage.locator('dialog.update-dialog')
        expect(bobdialog.locator('.markdown-body')).to_contain_text('Fremde aktuelle Fassung')
        expect(bobdialog.locator('[data-md-action="edit"]')).to_have_count(0)
        bobdialog.locator('[data-update-close]').click()

        # Revoking assignment after opening is enforced by the actual POST.
        other = page.request.post(base + '/api/issues', data={'title': 'Permission revocation', 'assigned_to': fixture['identities']['bob']['id']}, headers=HEADERS).json()
        bobpage.evaluate('id => openUpdateDialog(id)', other['id'])
        bobdialog.locator('textarea').fill('Entwurf nach Rechteentzug')
        assert page.request.put(base + f'/api/issues/{other["id"]}', data={'assigned_to': None}, headers=HEADERS).ok
        bobdialog.locator('[data-md-action="save"]').click()
        expect(bobdialog.locator('.markdown-error')).to_be_visible()
        expect(bobdialog.locator('textarea')).to_have_value('Entwurf nach Rechteentzug')
        assert bobpage.request.get(base + f'/api/issues/{other["id"]}/updates').json()['total'] == 0
        bobpage.screenshot(path=str(artifacts / 'revoked-rights.png'))
        bobdialog.locator('[data-md-action="cancel"]').click()
        assert errors == [], errors
        assert page.evaluate('cspViolations') == [], page.evaluate('cspViolations')
        browser.close()
    print('Update browser checks passed: real cookie/REST creation, author metadata, empty input, failed save draft, double-submit lock, POST-to-PUT, conflict draft, cancel/Escape/focus, foreign draft, mobile, read-only user, revoked rights, sanitizing, strict CSP.')
    print(f'Evidence: {artifacts}')


if __name__ == '__main__':
    main()
