"""Real-browser Issue lifecycle, rights, drafts, navigation and attachments.

Uses the isolated browser_support server and test mail transport. Production
templates/assets and real REST/SQLite are exercised; a single upload failure
is intercepted deliberately to verify retry state.
"""

from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from browser_support import browser_server, browser_login

HEADERS = {'X-Requested-With': 'XMLHttpRequest'}


def main():
    artifacts = Path('/tmp/casos-issues-evidence')
    artifacts.mkdir(exist_ok=True)
    with browser_server() as fixture, sync_playwright() as pw:
        base = fixture['url']
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        page = context.new_page()
        errors, missing = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: missing.append(message.text) if 'i18n: Missing key' in message.text else None)
        # Exercise the actual login form, including its post-login navigation.
        page.goto(base)
        expect(page).to_have_url(base + '/login')
        page.locator('#loginUsername').fill('alice')
        page.locator('#loginPassword').fill('Browser77!')
        page.locator('#loginBtn').click()
        expect(page).to_have_url(base + '/')
        expect(page.locator('.issues-list')).to_be_visible()
        expect(page.locator('.issues-list > .issue-empty')).to_contain_text('Keine passenden Issues')
        page.locator('#issue-create').click()
        form = page.locator('.issue-form-dialog')
        expect(form.locator('input[name=title]')).to_be_focused()
        form.locator('[type=submit]').click()
        expect(form).to_be_visible()
        form.locator('input[name=title]').fill('UI Issue ü ✓ <literal>')
        form.locator('input[name=priority]').fill('88')
        form.locator('input[name=deadline]').fill('2026-11-10')
        form.locator('textarea[name=description]').fill('## Beschreibung\n\nOriginal text.')
        form.locator('[type=submit]').click()
        expect(page.locator('.issue-detail')).to_be_visible()
        issue_id = int(page.url.rsplit('/', 1)[-1])
        issue_url = base + f'/api/issues/{issue_id}'
        expect(page.locator('#issue-metadata-panel h2')).to_have_text('UI Issue ü ✓ <literal>')
        expect(page.locator('.issue-description-panel .markdown-body')).to_contain_text('Original text.')
        assert page.request.get(issue_url).json()['priority'] == 88

        bob_context = browser.new_context(viewport={'width': 1280, 'height': 900})
        bob = bob_context.new_page()
        bob.on('pageerror', lambda error: errors.append(str(error)))
        browser_login(bob, base, 'bob')
        bob.locator(f'tr[data-issue-id="{issue_id}"] a').click()
        expect(bob.locator('#issue-metadata-panel h2')).to_have_text('UI Issue ü ✓ <literal>')
        expect(bob.locator('#issue-edit')).to_have_count(0)
        expect(bob.locator('#issue-add-update')).to_be_hidden()
        expect(bob.locator('#issue-attach')).to_be_hidden()

        # Assignment is a management action; the assignee edits status, including reopening.
        page.locator('#issue-edit').click()
        form.locator('select[name=assigned_to]').select_option(str(fixture['identities']['bob']['id']))
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        bob.reload()
        expect(bob.locator('#issue-edit')).to_be_visible()
        expect(bob.locator('#issue-editors')).to_have_count(0)
        expect(bob.locator('#issue-delete')).to_have_count(0)
        for status in ('erledigt', 'offen'):
            bob.locator('#issue-edit').click()
            bobform = bob.locator('.issue-form-dialog')
            expect(bobform.locator('[name=assigned_to]')).to_have_count(0)
            bobform.locator('[name=status]').select_option(status)
            bobform.locator('[type=submit]').click()
            expect(bobform).to_have_count(0)
            assert bob.request.get(issue_url).json()['status'] == status

        # Updates refresh in place while an independent description draft remains.
        page.locator('.issue-description-panel [data-md-action=edit]').click()
        draft = page.locator('.issue-description-panel textarea')
        draft.fill('## Ungespeicherter Beschreibungsentwurf')
        page.locator('#issue-add-update').click()
        update_dialog = page.locator('.update-dialog')
        update_dialog.locator('textarea').fill('## UI-Update von Alice')
        update_dialog.locator('[data-md-action=save]').click()
        expect(page.locator('.issue-update-card')).to_have_count(1)
        update_dialog.locator('[data-update-close]').click()
        expect(draft).to_have_value('## Ungespeicherter Beschreibungsentwurf')
        bob.locator('#issue-add-update').click()
        bobdialog = bob.locator('.update-dialog')
        bobdialog.locator('textarea').fill('## UI-Update von Bob')
        bobdialog.locator('[data-md-action=save]').click()
        expect(bob.locator('.issue-update-card')).to_have_count(2)
        bobdialog.locator('[data-update-close]').click()
        updates = page.request.get(issue_url + '/updates').json()['items']
        bob_update = next(item for item in updates if item['user_id'] == fixture['identities']['bob']['id'])

        # Description draft survives actual list navigation and browser back/forward.
        page.locator('.header-home').click()
        expect(page.locator('.issues-list')).to_be_visible()
        page.go_back()
        expect(draft).to_have_value('## Ungespeicherter Beschreibungsentwurf')
        page.go_forward()
        expect(page.locator('.issues-list')).to_be_visible()
        page.locator(f'tr[data-issue-id="{issue_id}"] a').click()
        expect(draft).to_have_value('## Ungespeicherter Beschreibungsentwurf')
        original = page.request.get(issue_url).json()
        assert page.request.put(issue_url, data={'description': 'Concurrent server value', 'description_revision': original['description_revision']}, headers=HEADERS).ok
        page.locator('.issue-description-panel [data-md-action=save]').click()
        expect(page.locator('.issue-description-panel .markdown-error')).to_be_visible()
        expect(draft).to_have_value('## Ungespeicherter Beschreibungsentwurf')
        assert page.request.get(issue_url).json()['description'] == 'Concurrent server value'
        page.screenshot(path=str(artifacts / 'description-conflict.png'), full_page=True)
        page.locator('.issue-description-panel [data-md-action=cancel]').click()
        page.reload()
        expect(page.locator('.issue-description-panel .markdown-body')).to_have_text('Concurrent server value')

        # A detail refresh waits for the active save before reading the replacement snapshot.
        held_saves = []
        def hold_description_save(route):
            if route.request.method == 'PUT':
                held_saves.append(route)
            else:
                route.continue_()
        page.route(issue_url, hold_description_save)
        page.locator('.issue-description-panel [data-md-action=edit]').click()
        draft.fill('Saved during detail refresh')
        with page.expect_request(lambda request: request.url == issue_url and request.method == 'PUT'):
            page.locator('.issue-description-panel [data-md-action=save]').click()
        page.evaluate('(id) => { window.refreshIssueDetail(id); }', issue_id)
        assert len(held_saves) == 1
        held_saves[0].continue_()
        expect(page.locator('.issue-description-panel .markdown-body')).to_have_text('Saved during detail refresh')
        page.unroute(issue_url, hold_description_save)
        assert page.request.get(issue_url).json()['description'] == 'Saved during detail refresh'

        # Two files with identical names remain separate. Retry keeps the selected file.
        file_input = page.locator('#issue-attachment-file')
        first_bytes, second_bytes = b'first upload\x00\xff', b'second upload'
        file_input.set_input_files({'name': 'same-name.bin', 'mimeType': 'application/octet-stream', 'buffer': first_bytes})
        expect(page.locator('.issue-attachment')).to_have_count(1)
        file_input.set_input_files({'name': 'same-name.bin', 'mimeType': 'application/octet-stream', 'buffer': second_bytes})
        expect(page.locator('.issue-attachment')).to_have_count(2)
        stored = page.request.get(issue_url + '/attachments').json()['items']
        assert len({entry['id'] for entry in stored}) == 2
        downloads = {page.request.get(base + entry['download_url']).body() for entry in stored}
        assert downloads == {first_bytes, second_bytes}
        with page.expect_download() as download_info:
            page.locator('.issue-attachment a[download]').first.click()
        download = download_info.value
        assert download.suggested_filename == 'same-name.bin'
        download.save_as(artifacts / 'download.bin')
        assert (artifacts / 'download.bin').read_bytes() == second_bytes
        page.route(issue_url + '/attachments', lambda route: route.fulfill(status=503, json={'detail': 'Upload test failure'}) if route.request.method == 'POST' else route.continue_(), times=1)
        file_input.set_input_files({'name': 'retry.txt', 'mimeType': 'text/plain', 'buffer': b'retry preserved'})
        expect(page.locator('#issue-attachments-panel .issue-section-error')).to_have_text('Upload test failure')
        expect(page.locator('#issue-upload-retry')).to_be_visible()
        page.locator('#issue-upload-retry').click()
        expect(page.locator('.issue-attachment')).to_have_count(3)
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('[data-delete-attachment]').first.click()
        expect(page.locator('.issue-attachment')).to_have_count(2)

        # Removing assignment removes write controls. Explicit grant restores editing only.
        page.locator('#issue-edit').click()
        form.locator('[name=assigned_to]').select_option('')
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        bob.reload()
        expect(bob.locator('#issue-edit')).to_have_count(0)
        expect(bob.locator('.issue-attachment')).to_have_count(2)
        expect(bob.locator('[data-delete-attachment]')).to_have_count(0)
        page.locator('#issue-editors').click()
        form.locator(f'[name="editor-{fixture["identities"]["bob"]["id"]}"]').check()
        # A concurrent grants save must preserve the local checkbox draft after 409.
        grants = page.request.get(issue_url + '/editors').json()
        assert page.request.put(issue_url + '/editors', data={'user_ids': [fixture['identities']['agent']['id']], 'revision': grants['revision']}, headers=HEADERS).ok
        form.locator('[type=submit]').click()
        expect(form.locator('.issue-form-error')).to_be_visible()
        expect(form.locator(f'[name="editor-{fixture["identities"]["bob"]["id"]}"]')).to_be_checked()
        page.once('dialog', lambda dialog: dialog.accept())
        form.locator('[data-cancel]').click()
        page.locator('#issue-editors').click()
        form.locator(f'[name="editor-{fixture["identities"]["agent"]["id"]}"]').uncheck()
        form.locator(f'[name="editor-{fixture["identities"]["bob"]["id"]}"]').check()
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        bob.reload()
        expect(bob.locator('#issue-edit')).to_be_visible()
        expect(bob.locator('#issue-editors')).to_have_count(0)

        # Sort/filter apply to all server pages; the selected filters survive detail navigation.
        for index in range(29):
            response = page.request.post(base + '/api/issues', data={'title': f'Paging {index:02}', 'priority': index,
                'status': 'offen' if index % 2 == 0 else 'erledigt'}, headers=HEADERS)
            assert response.ok, response.text()
        page.locator('.issue-back').click()
        page.locator('#issue-sort-filter').select_option('priority')
        page.locator('#issue-direction-filter').select_option('asc')
        expect(page.locator('.issue-table tbody tr')).to_have_count(25)
        values = page.locator('.issue-table tbody tr td:nth-child(4)').all_text_contents()
        assert [int(value) for value in values] == list(range(25)), values
        page.locator('#issue-next').click()
        expect(page.locator('.issue-table tbody tr')).to_have_count(5)
        values = page.locator('.issue-table tbody tr td:nth-child(4)').all_text_contents()
        assert [int(value) for value in values] == [25, 26, 27, 28, 88], values
        page.locator(f'tr[data-issue-id="{issue_id}"] a').click()
        page.go_back()
        expect(page.locator('#issue-sort-filter')).to_have_value('priority')
        expect(page.locator('#issue-direction-filter')).to_have_value('asc')
        expect(page.locator('.issue-table tbody tr')).to_have_count(5)
        page.locator('#issue-status-filter').select_option('erledigt')
        expect(page.locator('.issue-table tbody tr')).to_have_count(14)
        page.locator('#issue-assignee-filter').select_option('unassigned')
        expect(page.locator('.issue-table tbody tr')).to_have_count(14)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(artifacts / 'issue-list-mobile.png'), full_page=True, animations='disabled')
        page.screenshot(path=str(artifacts / 'issue-list-mobile-viewport.png'), animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.locator('#issue-status-filter').select_option('')
        page.goto(base + f'/issues/{issue_id}')
        expect(page.locator('#issue-metadata-panel')).to_be_visible()
        page.evaluate("setColorScheme('dark')")
        expect(page.locator('body')).to_have_css('background-color', 'rgb(11, 18, 32)')
        page.screenshot(path=str(artifacts / 'issue-detail-mobile-dark.png'), full_page=True, animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.locator('#issue-edit').click()
        form.locator('input[name=title]').fill('Unsaved title')
        page.once('dialog', lambda dialog: dialog.dismiss())
        page.keyboard.press('Escape')
        expect(form.locator('input[name=title]')).to_have_value('Unsaved title')
        page.once('dialog', lambda dialog: dialog.accept())
        form.locator('[data-cancel]').click()
        expect(page.locator('#issue-edit')).to_be_focused()

        # Admin can delete another author's update and then the whole Issue.
        admin_context = browser.new_context(viewport={'width': 1280, 'height': 900})
        admin = admin_context.new_page()
        admin.on('pageerror', lambda error: errors.append(str(error)))
        browser_login(admin, base, 'admin')
        admin.goto(base + f'/issues/{issue_id}?update={bob_update["id"]}')
        expect(admin.locator('.update-dialog .markdown-body')).to_contain_text('UI-Update von Bob')
        admin.locator('.update-dialog [data-update-close]').click()
        admin.once('dialog', lambda dialog: dialog.accept())
        admin.locator(f'[data-delete-update="{bob_update["id"]}"]').click()
        expect(admin.locator('.issue-update-card')).to_have_count(1)
        admin.screenshot(path=str(artifacts / 'issue-detail-desktop.png'), full_page=True)
        admin.once('dialog', lambda dialog: dialog.accept())
        admin.locator('#issue-delete').click()
        expect(admin.locator('.issues-list')).to_be_visible()
        assert admin.request.get(issue_url).status == 404
        assert errors == [], errors
        assert missing == [], missing
        browser.close()
    print('Issue browser checks passed: login form and redirect, real creation/read/assignment/reopen, Alice/Bob/Admin permissions, update integration, drafts across navigation, revisions/grant conflicts, duplicate filenames/download/retry/delete, server pagination/sort/filter, mobile dark mode, keyboard, admin cleanup.')
    print(f'Evidence: {artifacts}')


if __name__ == '__main__':
    main()
