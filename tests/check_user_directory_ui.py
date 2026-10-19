"""PL-401-01: user changes remain usable without reloading the Issue page.

Mutations use genuine settings/Issue UI and real HTTP services. A public overlay
opener layers settings over an actual Update draft; no private user cache,
refresh hook, or synthetic user-change event is touched.
"""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_support import browser_server, browser_login

HEADERS = {'X-Requested-With': 'XMLHttpRequest'}


def main():
    artifacts = Path('/tmp/casos-user-directory-evidence')
    artifacts.mkdir(exist_ok=True)
    with browser_server() as fixture, sync_playwright() as playwright:
        base = fixture['url']
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.set_default_timeout(10000)
        errors, missing, documents, static_errors = [], [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: missing.append(message.text) if 'i18n: Missing key' in message.text else None)
        page.on('request', lambda request: documents.append(request.url) if request.is_navigation_request() and request.resource_type == 'document' else None)
        page.on('response', lambda response: static_errors.append((response.url, response.status)) if '/static/' in response.url and response.status >= 400 else None)
        browser_login(page, base, 'admin')
        expect(page.locator('#issue-create')).to_be_visible()
        response = page.request.post(base + '/api/issues', headers=HEADERS,
                                     data={'title': 'Live user directory', 'description': 'Saved description'})
        assert response.status == 201, response.text()
        issue = response.json()
        issue_url = base + f'/api/issues/{issue["id"]}'
        page.locator('.header-home').click()
        expect(page.locator(f'tr[data-issue-id="{issue["id"]}"] a')).to_be_visible()
        page.locator(f'tr[data-issue-id="{issue["id"]}"] a').click()
        expect(page.locator('#issue-edit')).to_be_visible()
        form = page.locator('.issue-form-dialog')
        description = page.locator('.issue-description-panel textarea')
        description_draft = '## Description stays open through directory changes ü ✓'
        page.locator('.issue-description-panel [data-md-action=edit]').click()
        description.fill(description_draft)

        def open_settings(name, over_update=False):
            if over_update:
                page.evaluate('(section) => openSettingsOverlay(section)', name)
            else:
                page.locator('#settingsBtn').click()
                page.locator('#openSettingsBtn').click()
                page.locator(f'.settings-layout nav [data-section="{name}"]').click()
            expect(page.locator(f'.settings-panel[data-section="{name}"]')).to_be_visible()

        def close_settings():
            page.locator('[data-settings-close]').last.click()
            expect(page.locator('.settings-overlay')).to_have_count(0)

        def section(name):
            page.locator(f'.settings-layout nav [data-section="{name}"]').click()

        def open_user(uid):
            row = page.locator(f'details[data-user-id="{uid}"]')
            if row.get_attribute('open') is None:
                row.locator('summary').click()
            expect(page.locator(f'#editVorname_{uid}')).to_be_visible()

        def save_user(uid):
            with page.expect_response(lambda response: response.url == base + f'/api/admin/users/{uid}' and response.request.method == 'PUT') as saved:
                page.locator(f'[data-save-user="{uid}"]').click()
            assert saved.value.ok, saved.value.text()
            expect(page.locator(f'[data-save-user="{uid}"]')).to_be_enabled()

        def save_general():
            with page.expect_response(lambda response: response.url == base + '/api/admin/app/config' and response.request.method == 'POST') as saved:
                page.locator('button[onclick="saveAppConfig()"]').click()
            assert saved.value.ok, saved.value.text()
            expect(page.locator('#appServerAddress')).to_be_enabled()

        def assign(uid):
            page.locator('#issue-edit').click()
            expect(form).to_be_visible()
            form.locator('[name=assigned_to]').select_option('' if uid is None else str(uid))
            form.locator('[type=submit]').click()
            expect(form).to_have_count(0)
            assert page.request.get(issue_url).json()['assigned_to'] == uid
            expect(description).to_have_value(description_draft)

        def grant(uids):
            page.locator('#issue-editors').click()
            expect(form).to_be_visible()
            for uid in uids:
                expect(form.locator(f'[name="editor-{uid}"]')).to_have_count(1)
            for checkbox in form.locator('input[type=checkbox]').all():
                checkbox.set_checked(int(checkbox.input_value()) in uids)
            form.locator('[type=submit]').click()
            expect(form).to_have_count(0)
            assert set(page.request.get(issue_url + '/editors').json()['user_ids']) == set(uids)
            expect(description).to_have_value(description_draft)

        def show_list():
            page.locator('.header-home').click()
            expect(page.locator('#issue-assignee-filter')).to_be_visible()
            expect(page.locator('.issues-list')).to_be_visible()

        def show_issue():
            page.locator(f'tr[data-issue-id="{issue["id"]}"] a').click()
            expect(page.locator('#issue-edit')).to_be_visible()
            expect(description).to_have_value(description_draft)

        # Real creation retains independent settings and description drafts.
        open_settings('allgemein')
        page.locator('#appServerAddress').fill('directory-draft.example.invalid')
        section('benutzer')
        bob = fixture['identities']['bob']['id']
        open_user(bob)
        page.locator(f'#editVorname_{bob}').fill('Independent Bob draft')
        page.locator('#settingsNewUser').click()
        page.locator('#newUsername').fill('directory-user')
        page.locator('#newVorname').fill('Directory Original')
        page.locator('#newPassword').fill('Browser77!')
        page.locator('#createUserBtn').click()
        expect(page.locator('.settings-subdialog')).to_have_count(0)
        users = page.request.get(base + '/api/users/list').json()['items']
        created = next(user for user in users if user['username'] == 'directory-user')
        uid = created['id']
        expect(page.locator(f'#editVorname_{bob}')).to_have_value('Independent Bob draft')
        page.locator(f'#editVorname_{bob}').fill('Bob')  # Explicitly cancel this test draft.
        section('allgemein')
        expect(page.locator('#appServerAddress')).to_have_value('directory-draft.example.invalid')
        save_general()
        close_settings()
        expect(description).to_have_value(description_draft)

        # A freshly created normal user has global read access, no implicit writes.
        reader_context = browser.new_context()
        reader = reader_context.new_page()
        browser_login(reader, base, 'directory-user')
        rights = reader.request.get(issue_url).json()['permissions']
        assert rights['can_read'] and not rights['can_edit'] and not rights['can_manage'], rights
        assert reader.request.put(issue_url, headers=HEADERS, data={'title': 'Forbidden'}).status == 403

        # The baseline fails here: REST user missing from the cached choices.
        page.locator('#issue-edit').click()
        expect(form).to_be_visible()
        option = form.locator(f'[name=assigned_to] option[value="{uid}"]')
        expect(option).to_have_count(1)
        expect(option).to_have_text('Directory Original')
        page.screenshot(path=str(artifacts / 'new-user-assignment-current.png'))
        form.locator('[name=assigned_to]').select_option(str(uid))
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        assert page.request.get(issue_url).json()['assigned_to'] == uid
        rights = reader.request.get(issue_url).json()['permissions']
        assert rights['can_edit'] and not rights['can_manage'], rights
        assert reader.request.put(issue_url, headers=HEADERS, data={'assigned_to': None}).status == 403
        expect(description).to_have_value(description_draft)
        grant([uid])
        assign(None)
        assert reader.request.get(issue_url).json()['permissions']['can_edit']
        grant([])
        assert not reader.request.get(issue_url).json()['permissions']['can_edit']
        assign(uid)

        # Filter selection and visible names refresh within the same document.
        show_list()
        user_filter = page.locator('#issue-assignee-filter')
        expect(user_filter.locator(f'option[value="{uid}"]')).to_have_text('Directory Original')
        user_filter.select_option(str(uid))
        expect(page.locator(f'tr[data-issue-id="{issue["id"]}"]')).to_be_visible()
        open_settings('benutzer')
        open_user(uid)
        page.locator(f'#editVorname_{uid}').fill('Directory Renamed')
        save_user(uid)
        close_settings()
        user_filter.focus()
        expect(user_filter.locator(f'option[value="{uid}"]')).to_have_text('Directory Renamed')
        expect(user_filter).to_have_value(str(uid))
        expect(page.locator(f'tr[data-issue-id="{issue["id"]}"]')).to_contain_text('Directory Renamed')
        user_filter.select_option('')
        show_issue()
        page.locator('#issue-edit').click()
        expect(form.locator(f'[name=assigned_to] option[value="{uid}"]')).to_have_text('Directory Renamed')
        form.locator('[data-cancel]').click()
        page.locator('#issue-editors').click()
        expect(form.locator(f'label:has(input[name="editor-{uid}"])')).to_have_text('Directory Renamed')
        form.locator('[data-cancel]').click()
        assign(None)

        # Actual Update modal underneath settings survives an activity change.
        page.locator('#issue-add-update').click()
        update = page.locator('.update-dialog')
        update_draft = '## Update draft survives settings directory mutation ü ✓'
        update.locator('textarea').fill(update_draft)
        open_settings('allgemein', over_update=True)
        page.locator('#appServerAddress').fill('second-directory-draft.example.invalid')
        section('benutzer')
        open_user(uid)
        page.locator(f'#editActive_{uid}').uncheck()
        save_user(uid)
        assert uid not in {user['id'] for user in page.request.get(base + '/api/users/list').json()['items']}
        assert reader.request.get(issue_url).status == 401
        section('allgemein')
        expect(page.locator('#appServerAddress')).to_have_value('second-directory-draft.example.invalid')
        save_general()
        close_settings()
        expect(update.locator('textarea')).to_have_value(update_draft)
        expect(description).to_have_value(description_draft)
        update.locator('[data-md-action=save]').click()
        expect(update.locator('textarea')).to_be_hidden()
        update.locator('[data-update-close]').click()
        assert page.request.get(issue_url + '/updates').json()['items'][0]['content'] == update_draft
        page.locator('#issue-edit').click()
        expect(form).to_be_visible()
        expect(form.locator(f'[name=assigned_to] option[value="{uid}"]')).to_have_count(0)
        form.locator('[data-cancel]').click()
        page.locator('#issue-editors').click()
        expect(form).to_be_visible()
        expect(form.locator(f'[name="editor-{uid}"]')).to_have_count(0)
        form.locator('[data-cancel]').click()
        show_list()
        expect(user_filter.locator(f'option[value="{uid}"]')).to_have_count(0)

        open_settings('benutzer')
        open_user(uid)
        page.locator(f'#editActive_{uid}').check()
        save_user(uid)
        close_settings()
        user_filter.focus()
        expect(user_filter.locator(f'option[value="{uid}"]')).to_have_text('Directory Renamed')
        show_issue()
        assign(uid)
        grant([uid])

        # Token creation adds a normal active MCP identity to every chooser.
        open_settings('mcp')
        page.locator('#mcpNewTokenBtn').click()
        page.locator('#mcpNewTokenName').fill('Directory MCP identity')
        page.locator('#mcpCreateTokenBtn').click()
        expect(page.locator('#mcpTokenView')).to_be_visible()
        token = page.locator('#mcpTokenView').input_value()
        assert len(token) > 20
        mcp_user = next(user for user in page.request.get(base + '/api/admin/users').json()['items']
                        if user['auth_source'] == 'mcp' and user['vorname'] == 'Directory MCP identity')
        assert not mcp_user['is_admin'] and mcp_user['is_active']
        mid = mcp_user['id']
        page.locator('.settings-subdialog button').last.click()
        expect(page.locator('.settings-subdialog')).to_have_count(0)
        close_settings()
        bearer = {**HEADERS, 'Authorization': 'Bearer ' + token}
        payload = {'file': {'name': 'directory-rights.txt', 'mimeType': 'text/plain', 'buffer': b'test-only'}}
        assert page.request.post(issue_url + '/attachments', headers=bearer, multipart=payload).status == 403
        assign(mid)
        grant([mid])
        assert page.request.post(issue_url + '/attachments', headers=bearer, multipart=payload).status == 201
        show_list()
        expect(user_filter.locator(f'option[value="{mid}"]')).to_have_text('Directory MCP identity')
        user_filter.select_option(str(mid))
        expect(page.locator(f'tr[data-issue-id="{issue["id"]}"]')).to_be_visible()
        show_issue()
        expect(description).to_have_value(description_draft)
        assert page.request.get(issue_url).json()['description'] == 'Saved description'
        page.screenshot(path=str(artifacts / 'directory-final-draft.png'))
        assign(None)
        grant([])
        assert page.request.post(issue_url + '/attachments', headers=bearer, multipart=payload).status == 403
        assert page.request.get(issue_url).json()['created_by'] == fixture['identities']['admin']['id']
        assert documents == [base + '/'], documents
        assert not errors, errors
        assert not missing, missing
        assert not static_errors, static_errors
        result = {'status': 'passed', 'issue_id': issue['id'], 'normal_user_id': uid, 'mcp_user_id': mid,
                  'admin_document_requests': len(documents), 'page_errors': errors,
                  'checks': ['settings user creation', 'actual assignment and editor grants', 'REST rights unchanged',
                             'active user filter', 'renamed labels', 'deactivation and reactivation', 'MCP token identity',
                             'description/update/settings drafts', 'no admin reload', 'no private state manipulation'],
                  'screenshots': ['new-user-assignment-current.png', 'directory-final-draft.png']}
        (artifacts / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    main()
