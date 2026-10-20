"""Run real Chromium settings workflows against temporary Casos runtime data."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parent))
from browser_support import browser_server, browser_login


def run():
    with browser_server() as fixture, sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1280,'height':900})
        page=context.new_page();page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        missing_translations=[]
        page.on('console',lambda message:missing_translations.append(message.text) if 'i18n: Missing key' in message.text else None)
        base=fixture['url']
        browser_login(page,base,'admin')
        page.locator('#settingsBtn').click()
        page.locator('#openSettingsBtn').click()
        expect(page.locator('#settingsScheme')).to_be_visible()
        page.locator('nav button[data-section="allgemein"]').click()
        expect(page.locator('#appServerAddress')).to_be_visible()
        expect(page.locator('nav button[data-section="mcp"]')).to_have_text('MCP')
        page.locator('#appServerAddress').fill('draft.example.invalid')
        page.locator('nav button[data-section="tls"]').click()
        expect(page.locator('#verifySmtp')).to_be_visible()
        page.locator('#tlsCertPath').fill('/draft/cert.pem')
        page.locator('#verifySmtp').check()
        page.locator('button[onclick="saveTlsVerifyConfig()"]').click()
        expect(page.locator('#tlsCertPath')).to_have_value('/draft/cert.pem')
        expect(page.locator('[data-settings-notice]')).to_have_attribute('data-type','success')
        page.locator('nav button[data-section="allgemein"]').click()
        expect(page.locator('#appServerAddress')).to_have_value('draft.example.invalid')
        # Current config load failure must be an error, never an empty form.
        page.route('**/api/admin/ldap/config',lambda route:route.fulfill(status=503,json={'detail':'Isolated LDAP load failure'}))
        page.locator('nav button[data-section="ldap"]').click()
        expect(page.locator('.settings-panel[data-section="ldap"] [role="alert"]')).to_contain_text('Isolated LDAP load failure')
        page.unroute('**/api/admin/ldap/config')
        page.locator('[data-retry]').click()
        expect(page.locator('#ldapServer')).to_be_visible()
        # Cross-section drafts survive failed writes and dialog-close cancellation.
        page.locator('nav button[data-section="allgemein"]').click()
        page.route('**/api/admin/app/config',lambda route:route.fulfill(status=409,json={'detail':'Conflict keeps draft'}))
        page.locator('button[onclick="saveAppConfig()"]').click()
        expect(page.locator('#appServerAddress')).to_have_value('draft.example.invalid')
        page.unroute('**/api/admin/app/config')
        page.keyboard.press('Escape')
        expect(page.locator('.settings-subdialog')).to_be_visible()
        page.locator('[data-no]').click()
        expect(page.locator('#appServerAddress')).to_have_value('draft.example.invalid')
        # beforeunload protects this overlay's drafts.
        assert page.evaluate("(() => {const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;})()")
        page.locator('button[onclick="saveAppConfig()"]').click()
        expect(page.locator('#appServerAddress')).to_be_enabled()
        assert page.request.get(base+'/api/admin/app/config').json()['config']['server_address']=='draft.example.invalid'
        # Mail template draft survives saving a different form in the same panel.
        page.locator('nav button[data-section="mail"]').click()
        expect(page.locator('#mailSmtpServer')).to_be_visible()
        page.locator('#tmplSubject_new_update').fill('Independent template draft')
        page.locator('#mailSmtpServer').fill('smtp.example.invalid')
        page.locator('#mailFromAddress').fill('test@example.invalid')
        page.locator('button[onclick="saveMailConfig()"]').click()
        expect(page.locator('#tmplSubject_new_update')).to_have_value('Independent template draft')
        expect(page.locator('[data-settings-notice]')).to_have_attribute('data-type','success')
        page.locator('button[onclick="saveMailConfig()"]').click()
        expect(page.locator('[data-settings-notice]')).to_have_attribute('data-type','success')
        # User fields also retain other users' independent drafts across a save.
        page.locator('nav button[data-section="benutzer"]').click()
        alice=fixture['identities']['alice']['id'];bob=fixture['identities']['bob']['id']
        page.locator(f'details[data-user-id="{alice}"] summary').click()
        page.locator(f'details[data-user-id="{bob}"] summary').click()
        page.locator(f'#editVorname_{alice}').fill('Alice saved')
        page.locator(f'#editVorname_{bob}').fill('Bob pending')
        page.locator(f'[data-save-user="{alice}"]').click()
        expect(page.locator(f'#editVorname_{bob}')).to_have_value('Bob pending')
        page.locator('#settingsNewUser').click()
        page.locator('#newUsername').fill('created-in-settings')
        page.locator('#newPassword').fill('Browser77!')
        page.locator('#createUserBtn').click()
        expect(page.locator('.settings-subdialog')).to_have_count(0)
        assert sum(user['username']=='created-in-settings' for user in page.request.get(base+'/api/admin/users').json()['items'])==1
        # Full response handling remains locked, including a body arriving later than headers.
        page.locator('nav button[data-section="mcp"]').click()
        expect(page.locator('#mcpNewTokenBtn')).to_be_visible()
        page.locator('#mcpNewTokenBtn').click()
        page.locator('#mcpNewTokenName').fill('One-time settings token')
        page.evaluate("""() => {
          window._settingsOriginalFetch=window.fetch;
          window.fetch=async function(url,options){
            const response=await window._settingsOriginalFetch(url,options);
            if(String(url).endsWith('/api/admin/mcp/tokens') && options?.method==='POST'){
              const bytes=await response.arrayBuffer();
              window._settingsSlowBodyReady=true;
              return new Response(new ReadableStream({start(controller){
                window._settingsReleaseBody=()=>{controller.enqueue(new Uint8Array(bytes));controller.close();};
              }}),{status:response.status,headers:response.headers});
            }
            return response;
          };
        }""")
        page.locator('#mcpCreateTokenBtn').click()
        page.wait_for_function('() => Boolean(window._settingsSlowBodyReady)')
        expect(page.locator('#mcpCreateTokenBtn')).to_be_disabled()
        page.keyboard.press('Escape')
        expect(page.locator('#mcpNewTokenName')).to_be_visible()
        page.evaluate('window._settingsReleaseBody()')
        expect(page.locator('#mcpTokenView')).to_be_visible()
        token=page.locator('#mcpTokenView').input_value()
        assert len(token)>20
        page.evaluate('window.fetch=window._settingsOriginalFetch')
        page.locator('.settings-subdialog button').last.click()
        expect(page.locator('.settings-subdialog')).to_have_count(0)
        page.locator('#mcpKillSwitchBtn').click();page.locator('[data-yes]').click()
        expect(page.locator('#mcpKillSwitchBtn')).to_be_enabled()
        assert not page.request.get(base+'/api/admin/mcp/config').json()['enabled']
        page.locator('#mcpKillSwitchBtn').click();page.locator('[data-yes]').click()
        expect(page.locator('#mcpKillSwitchBtn')).to_be_enabled()
        page.screenshot(path='/tmp/casos-settings-wide.png')
        page.set_viewport_size({'width':390,'height':844})
        expect(page.locator('.settings-dialog')).to_be_visible()
        assert page.locator('.settings-dialog').bounding_box()['width']<=390
        page.screenshot(path='/tmp/casos-settings-narrow.png')
        # Discard only settings drafts and keep an existing native foreign dialog intact.
        page.keyboard.press('Escape');page.locator('[data-yes]').click()
        expect(page.locator('.settings-overlay')).to_have_count(0)
        page.evaluate("""() => {const d=document.createElement('dialog');d.id='foreign-draft';d.innerHTML='<textarea id="foreign-text">unchanged update draft</textarea>';document.body.append(d);d.showModal();document.querySelector('#foreign-text').focus();} """)
        page.evaluate("openSettingsOverlay('personal')")
        expect(page.locator('#settingsScheme')).to_be_visible()
        assert page.locator('#foreign-text').input_value()=='unchanged update draft'
        page.keyboard.press('Escape')
        expect(page.locator('.settings-overlay')).to_have_count(0)
        assert page.evaluate("document.activeElement.id")=='foreign-text'
        assert page.locator('#foreign-draft').evaluate('(el)=>el.open')
        page.evaluate("document.querySelector('#foreign-draft').close();document.querySelector('#foreign-draft').remove()")
        # Non-admin deep link exposes personal options only and saves mail preferences.
        browser_login(page,base,'alice')
        page.goto(base+'/?settings=mcp')
        expect(page.locator('#settingsScheme')).to_be_visible()
        assert page.locator('.settings-layout nav button').count()==1
        page.locator('#settingsLoadPreferences').click()
        expect(page.locator('#settingsPref_status_change')).to_be_visible()
        page.locator('#settingsPref_status_change').uncheck()
        page.locator('#settingsPreferencesSave').click()
        expect(page.locator('#settingsPreferencesSave')).to_be_enabled()
        prefs=page.request.get(base+'/api/user/mail/preferences').json()['preferences']
        assert not next(p['enabled'] for p in prefs if p['event_type']=='status_change')
        page.locator('#settingsOldPassword').fill('Browser77!')
        page.locator('#settingsNewPassword').fill('ChangedBrowser77!')
        page.locator('#settingsConfirmPassword').fill('ChangedBrowser77!')
        page.locator('#settingsPasswordSave').click()
        expect(page.locator('#settingsNewPassword')).to_have_value('')
        assert not errors,errors
        assert not missing_translations,missing_translations
        print(json.dumps({'result':'passed','checks':['section drafts','HTTP load and mutation errors','cancel and beforeunload','TLS form isolation','SMTP/template draft isolation','user CRUD and independent drafts','MCP slow body lock and token display','kill switch','390px layout','foreign native dialog preservation','normal-user deep link and mail preferences'],'screenshots':['/tmp/casos-settings-wide.png','/tmp/casos-settings-narrow.png']},ensure_ascii=False))
        browser.close()

if __name__=='__main__':run()
