"""Real browser/API/SQLite flows against an isolated in-memory AD transport."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from browser_support import browser_login, browser_server
from ad_directory_fixture import SID, OTHER_SID


def main():
    artifacts = Path(__file__).resolve().parents[1] / 'dist/ad-people-check'
    artifacts.mkdir(parents=True, exist_ok=True)
    with browser_server(ad_fixture=True) as fixture, sync_playwright() as playwright:
        base = fixture['url']
        state_file = fixture['root'] / 'data/test-ad-state.json'
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width':1280, 'height':960})
        page.set_default_timeout(10000)
        errors, missing, queries = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: missing.append(message.text) if 'i18n: Missing key' in message.text else None)
        page.on('request', lambda request: queries.append(request.url) if '/api/ad/people?' in request.url else None)
        browser_login(page, base, 'alice')
        page.locator('#issue-create').click()
        form = page.locator('.issue-form-dialog')
        field = form.locator('[name=affected_person_query]')
        options = form.locator('[role=option]')
        form.locator('[name=title]').fill('Drucker am Empfang')
        form.locator('[name=description]').fill('Entwurf bleibt bei der Personensuche erhalten.')
        form.locator('[name=assigned_to]').select_option(str(fixture['identities']['bob']['id']))
        for query in ('Eva', 'Meyer', 'emeyer'):
            field.fill(query)
            expect(options.filter(has_text='Eva Meyer')).to_have_count(1)
        field.press('ArrowDown'); field.press('Enter')
        expect(form.locator('[name=affected_person_sid]')).to_have_value(SID)
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        expect(page.locator('.issue-metadata')).to_contain_text('Eva Meyer (emeyer)')
        issue_id = int(page.url.rsplit('/',1)[1])
        issue_url = base + f'/api/issues/{issue_id}'
        issue = page.request.get(issue_url).json()
        assert issue['assigned_to'] == fixture['identities']['bob']['id']
        assert issue['affected_person']['sid'] == SID
        assert not any(user['username'] == 'emeyer' for user in page.request.get(base+'/api/users/list').json()['items'])
        # Explicitly reselecting the same SID must still refresh its cached names.
        page.locator('#issue-edit').click(); field.fill('emeyer')
        expect(options).to_have_count(1); options.click()
        with page.expect_request(lambda request: request.url == issue_url and request.method == 'PUT') as saved:
            form.locator('[type=submit]').click()
        assert saved.value.post_data_json['affected_person_sid'] == SID
        expect(form).to_have_count(0)

        # Display/reload and unrelated edits keep working with AD unavailable.
        state_file.write_text('{"offline":true}')
        count = len(queries)
        page.reload()
        expect(page.locator('.issue-metadata')).to_contain_text('Eva Meyer (emeyer)')
        assert len(queries) == count
        page.locator('.issue-description-panel [data-md-action=edit]').click()
        description = page.locator('.issue-description-panel textarea')
        description.fill('Unabhängiger Beschreibungsentwurf')
        page.locator('#issue-edit').click()
        form.locator('[name=priority]').fill('70')
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        assert page.request.get(issue_url).json()['affected_person']['sid'] == SID
        page.locator('#issue-edit').click()
        field.fill('Erik')
        expect(form.locator('[role=status]')).to_contain_text('nicht erreichbar')
        expect(description).to_have_value('Unabhängiger Beschreibungsentwurf')
        expect(form.locator('[name=priority]')).to_have_value('70')
        state_file.write_text('{}')
        form.locator('[data-ad-more]').click()
        expect(options.filter(has_text='Erik Muster')).to_have_count(1)
        options.filter(has_text='Erik Muster').click()
        state_file.write_text('{"offline":true}')
        form.locator('[type=submit]').click()
        expect(form.locator('.issue-form-error')).to_contain_text('nicht erreichbar')
        expect(field).to_have_value('Erik Muster (emuster)')
        assert page.request.get(issue_url).json()['affected_person_sid'] == SID
        state_file.write_text('{}')
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        assert page.request.get(issue_url).json()['affected_person_sid'] == OTHER_SID
        expect(description).to_have_value('Unabhängiger Beschreibungsentwurf')
        expect(page.locator('#issue-history-slot')).to_contain_text('Eva Meyer (emeyer)')
        expect(page.locator('#issue-history-slot')).to_contain_text('Erik Muster (emuster)')

        # Old responses, missing matches, incomplete free text and pagination.
        page.locator('#issue-edit').click()
        with page.expect_request('**/api/ad/people?query=slow&*'):
            field.fill('slow')
        field.fill('Meyer')
        expect(options.filter(has_text='Eva Meyer')).to_have_count(1)
        page.wait_for_timeout(1100)
        expect(options.filter(has_text='Slow Result')).to_have_count(0)
        field.fill('no-such-user')
        expect(form.locator('[role=status]')).to_contain_text('Keine passenden')
        form.locator('[type=submit]').click()
        expect(form).to_be_visible()
        assert page.request.get(issue_url).json()['affected_person_sid'] == OTHER_SID
        field.fill('Testkonto')
        expect(options).to_have_count(50)
        form.locator('[data-ad-more]').click()
        expect(options).to_have_count(53)
        field.focus(); field.press('Escape')
        expect(form).to_be_visible()
        expect(form.locator('.ad-person-dropdown')).to_be_hidden()
        form.locator('[data-ad-clear]').click()
        form.locator('[type=submit]').click()
        expect(form).to_have_count(0)
        assert page.request.get(issue_url).json()['affected_person'] is None

        # Attribute injection stays literal when reopening a cached selection.
        page.locator('#issue-edit').click(); field.fill('quoted')
        expect(options).to_have_count(1); options.click()
        form.locator('[type=submit]').click(); expect(form).to_have_count(0)
        page.locator('#issue-edit').click()
        expect(field).to_have_value('Eva " onfocus="alert(1) <Team> (quoted)')
        assert field.get_attribute('onfocus') is None
        expect(form.locator('[data-ad-person] script')).to_have_count(0)
        form.locator('[data-cancel]').click()

        # Keyboard dropdown and responsive layout in both themes.
        for theme in ('light','dark'):
            page.evaluate('(theme) => applyColorScheme(theme)', theme)
            page.locator('#issue-edit').click(); field.fill('Eva')
            expect(options).to_have_count(2)
            field.press('ArrowUp')
            expect(options.last).to_have_attribute('aria-selected', 'true')
            page.screenshot(path=str(artifacts/f'{theme}-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            field.focus()
            page.screenshot(path=str(artifacts/f'{theme}-mobile.png'))
            assert form.evaluate('(node) => node.scrollWidth <= node.clientWidth + 1')
            form.locator('[data-ad-clear]').click()
            page.once('dialog', lambda dialog: dialog.accept())
            form.locator('[data-cancel]').click()
            page.set_viewport_size({'width':1280,'height':960})
        # List displays cached names without a directory request.
        description.fill('Entwurf bleibt bei der Personensuche erhalten.')
        page.locator('.issue-description-panel [data-md-action=cancel]').click()
        state_file.write_text('{"offline":true}')
        count = len(queries)
        page.locator('.header-home').click()
        expect(page.locator(f'tr[data-issue-id="{issue_id}"]')).to_contain_text('quoted')
        assert len(queries) == count
        assert not errors, errors
        assert not missing, missing
        (artifacts/'report.json').write_text(json.dumps({'ok':True,'js_errors':errors,'missing_translations':missing,
            'checks':['AD search','SID cache','offline display','draft retention','retry','stale responses','pagination','keyboard','escaping','light/dark mobile']}, ensure_ascii=False, indent=2)+'\n')
        browser.close()
        print('AD people browser checks passed')


if __name__ == '__main__':
    main()
