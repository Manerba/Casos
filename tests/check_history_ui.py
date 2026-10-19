"""Real Issue history and notification preferences, using the isolated mail fixture."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from browser_support import browser_server, browser_login

HEADERS={'X-Requested-With':'XMLHttpRequest'}


def main():
    evidence=Path('/tmp/casos-history-evidence');evidence.mkdir(exist_ok=True)
    with browser_server() as fixture,sync_playwright() as pw:
        base=fixture['url'];mail_path=fixture['root']/'data/test-mail.jsonl'
        def mails():return [json.loads(line) for line in mail_path.read_text().splitlines()] if mail_path.exists() else []
        browser=pw.chromium.launch()
        errors=[];missing=[]
        def page_for(name):
            page=browser.new_context(viewport={'width':1280,'height':900}).new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('console',lambda message:missing.append(message.text) if 'i18n: Missing key' in message.text else None)
            browser_login(page,base,name)
            return page
        admin=page_for('admin');alice=page_for('alice');bob=page_for('bob')
        assert admin.request.post(base+'/api/admin/mail/config',data={'smtp_server':'example.invalid','from_address':'casos@example.invalid'},headers=HEADERS).ok
        alice.locator('#issue-create').click()
        form=alice.locator('.issue-form-dialog')
        form.locator('[name=title]').fill('Verlauf und Benachrichtigungen')
        form.locator('[name=assigned_to]').select_option(str(fixture['identities']['bob']['id']))
        form.locator('[type=submit]').click()
        slot=alice.locator('#issue-history-slot')
        expect(slot.locator('li')).to_have_count(1)
        expect(slot).to_contain_text('Nicht zugewiesen')
        expect(slot).to_contain_text('Bob')
        iid=int(alice.url.rsplit('/',1)[-1]);url=base+f'/api/issues/{iid}'
        assert [m['to'] for m in mails()]==['bob@example.invalid']
        bob.goto(base+f'/issues/{iid}')
        bob.evaluate("openSettingsOverlay('personal')")
        bob.locator('#settingsLoadPreferences').click()
        expect(bob.locator('#settingsPref_new_update')).to_be_checked()
        expect(bob.locator('#settingsPref_task_assigned')).to_have_count(0)
        bob.locator('#settingsPref_new_update').uncheck()
        bob.locator('#settingsPreferencesSave').click()
        expect(bob.locator('[data-settings-notice]')).to_have_attribute('data-type','success')
        bob.locator('[data-settings-close]').first.click()

        alice.locator('.issue-description-panel [data-md-action=edit]').click()
        draft=alice.locator('.issue-description-panel textarea');draft.fill('Unabhängiger Entwurf bleibt erhalten')
        alice.locator('#issue-add-update').click()
        dialog=alice.locator('.update-dialog')
        dialog.locator('textarea').fill('Update von Alice <img src=x onerror=alert(1)>')
        dialog.locator('[data-md-action=save]').click()
        expect(slot.locator('li')).to_have_count(2)
        dialog.locator('[data-update-close]').click()
        expect(draft).to_have_value('Unabhängiger Entwurf bleibt erhalten')
        assert len(mails())==1
        expect(slot.locator('img')).to_have_count(0)
        bob.locator('#issue-add-update').click()
        bd=bob.locator('.update-dialog');bd.locator('textarea').fill('Update von Bob')
        bd.locator('[data-md-action=save]').click()
        expect(bob.locator('#issue-history-slot [data-history-kind=update]')).to_have_count(2)
        bd.locator('[data-update-close]').click()
        assert [m['to'] for m in mails()]==['bob@example.invalid','alice@example.invalid']
        bob_update=bob.request.get(url+'/updates').json()['items'][0]
        bob.locator(f'[data-history-update="{bob_update["id"]}"]').click()
        bd.locator('[data-md-action=edit]').click();bd.locator('textarea').fill('Update von Bob korrigiert')
        bd.locator('[data-md-action=save]').click()
        expect(bob.locator('#issue-history-slot')).to_contain_text('Update von Bob korrigiert')
        bd.locator('[data-update-close]').click()
        assert len(mails())==2
        for status in ('erledigt','offen'):
            alice.locator('#issue-edit').click()
            form.locator('[name=status]').select_option(status)
            form.locator('[type=submit]').click()
            expect(form).to_have_count(0)
        expect(slot.locator('li')).to_have_count(5)
        expect(slot.locator('li').first).to_contain_text('Erledigt')
        expect(slot.locator('li').first).to_contain_text('Offen')
        expect(draft).to_have_value('Unabhängiger Entwurf bleibt erhalten')
        assert [m['to'] for m in mails()][-2:]==['bob@example.invalid']*2

        # A failed refresh preserves the existing timeline and description draft.
        alice.route(url+'/history*',lambda route:route.fulfill(status=503,json={'detail':'History test failure'}),times=1)
        slot.locator('[data-history-refresh]').click()
        expect(slot.locator('[role=alert]')).to_have_text('History test failure')
        expect(slot.locator('li')).to_have_count(5)
        expect(draft).to_have_value('Unabhängiger Entwurf bleibt erhalten')
        slot.locator('[data-history-refresh]').click()
        expect(slot.locator('[role=alert]')).to_be_hidden()
        alice.screenshot(path=str(evidence/'history-desktop.png'),full_page=True,animations='disabled')
        alice.set_viewport_size({'width':390,'height':844})
        slot.scroll_into_view_if_needed()
        alice.screenshot(path=str(evidence/'history-mobile.png'),animations='disabled')
        assert alice.evaluate('document.documentElement.scrollWidth <= window.innerWidth')

        # Real user deletion records the admin and preserves the old assignee label.
        assert admin.request.delete(base+f'/api/admin/users/{fixture["identities"]["bob"]["id"]}',headers=HEADERS).ok
        slot.locator('[data-history-refresh]').click()
        expect(slot.locator('li').first).to_contain_text('Administrator')
        expect(slot.locator('li').first).to_contain_text('Bob')
        expect(slot.locator('li').first).to_contain_text('Nicht zugewiesen')
        expect(draft).to_have_value('Unabhängiger Entwurf bleibt erhalten')
        assert mails()[-1]['to']=='alice@example.invalid'
        admin.goto(base+f'/issues/{iid}')
        expect(admin.locator('#issue-history-slot li')).to_have_count(6)
        admin.once('dialog',lambda dialog:dialog.accept())
        admin.locator(f'[data-delete-update="{bob_update["id"]}"]').click()
        expect(admin.locator('#issue-history-slot li')).to_have_count(5)

        # Pagination remains ordered, with older entries fetched only on request.
        for index in range(52):
            assert alice.request.put(url,data={'status':'in_arbeit' if index%2==0 else 'offen'},headers=HEADERS).ok
        slot.locator('[data-history-refresh]').click()
        expect(slot.locator('li')).to_have_count(50)
        slot.locator('[data-history-more]').click()
        expect(slot.locator('li')).to_have_count(57)
        expect(slot.locator('[data-history-more]')).to_be_hidden()
        expect(draft).to_have_value('Unabhängiger Entwurf bleibt erhalten')
        assert errors==[],errors
        assert missing==[],missing
        browser.close()
    print('History browser passed: assignment/status/reopen, real authors and old/new values, updates/corrections, preferences and fake-mail recipients, drafts, load errors/retry, user deletion, admin update deletion, pagination, 390px layout.')
    print(f'Evidence: {evidence}')


if __name__=='__main__':main()
