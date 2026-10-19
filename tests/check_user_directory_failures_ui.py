"""Current user choices under failed/overlapping reads and inactive selections.

Real Chromium, HTTP identities and SQLite; only selected user-list responses
are delayed or failed. No production data, mail or browser state injection.
"""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from browser_support import browser_server, browser_login

HEADERS = {'X-Requested-With': 'XMLHttpRequest'}


def main():
    artifacts = Path('/tmp/casos-user-directory-failures-evidence')
    artifacts.mkdir(exist_ok=True)
    with browser_server() as fixture, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.set_default_timeout(10000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        base = fixture['url']
        browser_login(page, base, 'admin')
        bob = fixture['identities']['bob']['id']
        issue = page.request.post(base + '/api/issues', headers=HEADERS,
                                  data={'title': 'User directory races', 'assigned_to': bob}).json()
        path = base + f'/api/issues/{issue["id"]}'
        page.locator('.header-home').click()
        page.locator(f'tr[data-issue-id="{issue["id"]}"] a').click()
        expect(page.locator('#issue-edit')).to_be_visible()
        page.locator('.issue-description-panel [data-md-action=edit]').click()
        draft = page.locator('.issue-description-panel textarea')
        draft.fill('Retain description through user-list failures and races')
        form = page.locator('.issue-form-dialog')
        pattern = '**/api/users/list'

        # A failed read must not present stale choices or destroy the draft.
        page.route(pattern, lambda route: route.fulfill(status=503, json={'detail': 'User directory test failure'}))
        for trigger in ('#issue-edit', '#issue-editors'):
            page.locator(trigger).click()
            expect(page.locator('.notification')).to_have_text('User directory test failure')
            expect(form).to_have_count(0)
            expect(draft).to_have_value('Retain description through user-list failures and races')
        page.unroute(pattern)

        pending = []
        page.route(pattern, lambda route: pending.append(route))

        def next_read(count):
            # Playwright dispatches routed requests while awaiting this event.
            for _ in range(100):
                if len(pending) >= count:
                    return pending[count - 1]
                page.wait_for_timeout(20)
            raise AssertionError(f'Expected {count} user reads, got {len(pending)}')

        def release(route, data):
            with page.expect_request_finished(predicate=lambda request: request == route.request):
                route.fulfill(json=data)
            # Let the response JSON and UI continuation settle before checking
            # that a stale response did not mutate the still-current display.
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')

        # Two rapid clicks must open one form after the pending request completes.
        page.locator('#issue-edit').click()
        first = next_read(1)
        page.locator('#issue-edit').click()
        release(first, page.request.get(base + '/api/users/list').json())
        expect(form).to_have_count(1)
        assert len(pending) == 1
        form.locator('[data-cancel]').click()

        # A settings-close read started before a rename must not overwrite the
        # newer response used by the assignment dialog.
        old_users = page.request.get(base + '/api/users/list').json()
        page.evaluate("openSettingsOverlay('personal')")
        expect(page.locator('#settingsScheme')).to_be_visible()
        page.locator('[data-settings-close]').last.click()
        old = next_read(2)
        assert page.request.put(base + f'/api/admin/users/{bob}', headers=HEADERS,
                                data={'vorname': 'Current Bob'}).ok
        current_users = page.request.get(base + '/api/users/list').json()
        page.locator('#issue-edit').click()
        newest = next_read(3)
        release(newest, current_users)
        expect(form.locator(f'option[value="{bob}"]')).to_have_text('Current Bob')
        release(old, old_users)
        expect(page.locator(f'.issue-metadata [data-issue-user="{bob}"]')).to_have_text('Current Bob')
        expect(form.locator(f'option[value="{bob}"]')).to_have_text('Current Bob')
        form.locator('[data-cancel]').click()
        expect(draft).to_have_value('Retain description through user-list failures and races')

        # Navigation cancels the intention to open the old Issue's dialog.
        page.locator('#issue-editors').click()
        old_dialog = next_read(4)
        page.locator('.header-home').click()
        route_read = next_read(5)
        # Buttons from the previous DOM cannot acquire the new route's intent.
        page.locator('#issue-edit').click()
        page.wait_for_timeout(100)
        assert len(pending) == 5
        release(route_read, current_users)
        expect(page.locator('.issues-list')).to_be_visible()
        # The old pending intent must not block a new route's form.
        page.locator('#issue-create').click()
        new_dialog = next_read(6)
        release(new_dialog, current_users)
        expect(form).to_have_count(1)
        expect(form.locator('[name=title]')).to_have_value('')
        release(old_dialog, old_users)
        expect(form).to_have_count(1)
        expect(form.locator('[name=title]')).to_have_value('')
        form.locator('[data-cancel]').click()
        expect(form).to_have_count(0)
        page.unroute(pattern)

        # Keep a selected inactive filter explicit, rather than silently
        # showing All while requests still filter by the hidden old ID.
        user_filter = page.locator('#issue-assignee-filter')
        user_filter.select_option(str(bob))
        expect(page.locator(f'tr[data-issue-id="{issue["id"]}"]')).to_be_visible()
        grants = page.request.get(path + '/editors').json()
        assert page.request.put(path + '/editors', headers=HEADERS,
                                data={'user_ids': [bob], 'revision': grants['revision']}).ok
        assert page.request.put(base + f'/api/admin/users/{bob}', headers=HEADERS, data={'is_active': 0}).ok
        page.locator('#issue-status-filter').focus()
        with page.expect_response(lambda response: response.url.endswith('/api/users/list')):
            user_filter.focus()
        expect(user_filter).to_have_value(str(bob))
        expect(user_filter.locator('option:checked')).to_have_text(f'#{bob}')
        page.locator(f'tr[data-issue-id="{issue["id"]}"] a').click()
        expect(draft).to_have_value('Retain description through user-list failures and races')
        page.locator('#issue-edit').click()
        assignee = form.locator('[name=assigned_to]')
        expect(assignee).to_have_value(str(bob))
        expect(assignee.locator('option:checked')).to_have_js_property('disabled', True)
        form.locator('[name=title]').fill('Other metadata keeps inactive assignee')
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        assert page.request.get(path).json()['assigned_to'] == bob
        page.locator('#issue-editors').click()
        existing = form.locator(f'[name=editor-{bob}]')
        expect(existing).to_be_checked()
        expect(existing.locator('..')).to_contain_text('Deaktiviert')
        existing.uncheck()
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        assert page.request.get(path + '/editors').json()['user_ids'] == []
        expect(draft).to_have_value('Retain description through user-list failures and races')
        page.screenshot(path=str(artifacts / 'preserved-draft-inactive-assignee.png'))
        assert not errors, errors
        browser.close()
    result = {'result': 'passed', 'checks': ['failed reads and retry', 'double click during pending read',
        'out-of-order responses preserve current identities', 'navigation discards pending old dialog',
        'old DOM buttons rejected on new route', 'new route dialog not blocked by old pending read',
        'inactive selected filter preserved', 'inactive assignee retained on unrelated edit',
        'inactive existing grant explicitly removable', 'description draft retained'], 'page_errors': errors}
    (artifacts / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
