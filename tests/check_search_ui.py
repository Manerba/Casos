"""Real HTTP Chromium search, navigation, safety, drafts and pagination checks."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parent))
from browser_support import browser_server, browser_login


def run():
    with browser_server() as fixture, sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1280,'height':900},timezone_id='Europe/Berlin')
        page=context.new_page();page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        unsafe_requests=[]
        page.on('request',lambda request:unsafe_requests.append(request.url) if '/forbidden-search-resource' in request.url else None)
        base=fixture['url'];headers={'X-Requested-With':'XMLHttpRequest'}
        browser_login(page,base,'alice')
        def create(title,description):
            response=page.request.post(base+'/api/issues',headers=headers,data={'title':title,'description':description})
            assert response.status==201,response.text()
            return response.json()['id']
        target=create('Suchprobe Café Proxy','Alpha Beta Freigabe `<img src="/forbidden-search-resource" onerror="window.__searchXss=1">`')
        create('Andere Reihenfolge','Beta Zwischentext Alpha')
        response=page.request.post(f'{base}/api/issues/{target}/updates',headers=headers,data={'content':'Chronikneedle Unicode Київ <script>window.__searchXss=1</script> Endtext'})
        assert response.status==201,response.text()
        update=response.json()['id']
        for index in range(23):create(f'Page item {index:02d}','Paginierungswort gleich lang')
        browser_login(page,base,'bob')
        query=page.locator('#issue-search-query');kind=page.locator('#issue-search-type');since=page.locator('#issue-search-since')
        results=page.locator('.issue-search-results li')
        expect(query).to_be_visible()
        query.fill('"Alpha Beta"');query.press('Enter')
        expect(results).to_have_count(1)
        expect(page.locator('.issue-search-result-link')).to_have_text('Suchprobe Café Proxy')
        expect(page.locator('.issue-search-snippet mark')).to_contain_text(['Alpha Beta'])
        assert page.locator('.issue-search-snippet img,.issue-search-snippet script').count()==0
        assert not unsafe_requests
        query.fill('Alpha Beta');query.press('Enter');expect(results).to_have_count(2)
        query.fill('cafe');query.press('Enter');expect(results).to_have_count(1)
        # Query/types/since use the actual backend and local time becomes an explicit UTC bound.
        query.fill('Chronik*');kind.select_option('update');since.fill('2099-01-01T00:00');query.press('Enter')
        expect(page.locator('.issue-search-empty')).to_be_visible()
        since.fill('2000-01-01T00:00');query.press('Enter');expect(results).to_have_count(1)
        expect(page.locator('.issue-search-result-link')).to_have_attribute('href',f'/issues/{target}?update={update}')
        page.locator('.issue-search-result-link').click()
        expect(page.locator('.update-dialog')).to_be_visible()
        expect(page.locator('.update-dialog-content')).to_contain_text('Chronikneedle')
        page.locator('[data-update-close]').click()
        page.go_back()
        expect(query).to_have_value('Chronik*');expect(kind).to_have_value('update');expect(since).to_have_value('2000-01-01T00:00')
        expect(results).to_have_count(1)
        # List filters rerender the slot while the search keeps an unsubmitted draft.
        query.fill('Unsubmitted text retained')
        page.locator('#issue-status-filter').select_option('offen')
        expect(query).to_have_value('Unsubmitted text retained')
        expect(results).to_have_count(1)
        # Pagination preserves the submitted query and returns without duplicates.
        query.fill('Paginierungswort');kind.select_option('');since.fill('');query.press('Enter')
        expect(results).to_have_count(20)
        first=page.locator('.issue-search-result-link').all_text_contents()
        page.locator('.issue-search-pagination button').last.click()
        expect(results).to_have_count(3)
        expect(page.locator('.issue-search-result-link').first).to_be_focused()
        second=page.locator('.issue-search-result-link').all_text_contents()
        assert not set(first)&set(second)
        page.locator('.issue-search-result-link').first.click()
        expect(page.locator('.issue-detail')).to_be_visible();page.go_back()
        expect(results).to_have_count(3)
        expect(query).to_have_value('Paginierungswort')
        # Errors are visible, retain drafts, and retry through real HTTP.
        page.route('**/api/search?*',lambda route:route.fulfill(status=503,json={'detail':'Isolated search failure'}))
        query.fill('Chronik*');kind.select_option('update');query.press('Enter')
        expect(page.locator('.issue-search-feedback[role="alert"]')).to_contain_text('Isolated search failure')
        expect(query).to_have_value('Chronik*');expect(kind).to_have_value('update')
        page.unroute('**/api/search?*');page.locator('.issue-search-feedback button').click();expect(results).to_have_count(1)
        # A slow old response must not replace newer matching results.
        page.evaluate("""() => {
          window._searchFetch=window.fetch;
          window.fetch=async function(url,options){
            const response=await window._searchFetch(url,options);
            if(String(url).includes('/api/search?') && new URL(url,location.href).searchParams.get('query')==='Paginierungswort') {
              window._searchDelayed=true;
              await new Promise(resolve=>{window._releaseSearch=resolve;});
            }
            return response;
          };
        }""")
        query.fill('Paginierungswort');kind.select_option('');query.press('Enter')
        page.wait_for_function('() => Boolean(window._searchDelayed)')
        expect(page.locator('.issue-search')).to_have_attribute('aria-busy','true')
        query.fill('Chronik*');kind.select_option('update');query.press('Enter');expect(results).to_have_count(1)
        page.evaluate('window._releaseSearch()')
        expect(page.locator('.issue-search-result-link')).to_have_attribute('href',f'/issues/{target}?update={update}')
        page.evaluate('window.fetch=window._searchFetch')
        assert not page.evaluate('Boolean(window.__searchXss)')
        assert not unsafe_requests
        # Keyboard focus, compact dark-mode mobile layout, and explicit reset.
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate("setColorScheme('dark')")
        expect(query).to_be_visible()
        assert page.locator('.issue-search').bounding_box()['width']<=390
        query.focus();page.keyboard.press('Tab');expect(kind).to_be_focused()
        page.locator('.issue-search').scroll_into_view_if_needed()
        page.screenshot(path='/tmp/casos-search-mobile.png')
        page.set_viewport_size({'width':1280,'height':900});page.evaluate("setColorScheme('light')")
        page.screenshot(path='/tmp/casos-search-wide.png')
        page.locator('#issue-search-reset').click()
        expect(query).to_have_value('');expect(kind).to_have_value('');expect(since).to_have_value('')
        expect(query).to_be_focused();expect(results).to_have_count(0)
        assert not errors,errors
        print(json.dumps({'result':'passed','checks':['global reader search','phrase/AND/Unicode/prefix','safe highlighted snippets','local-time since filter','update deep link','draft and result-page preservation','pagination without duplicates','HTTP error and retry','stale-response protection','keyboard/reset','390px dark/light layouts'],'screenshots':['/tmp/casos-search-mobile.png','/tmp/casos-search-wide.png']},ensure_ascii=False))
        browser.close()

if __name__=='__main__':run()
