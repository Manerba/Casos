"""Current Issue/Update Markdown rendering and XSS regression using real assets/API.

Legacy project, personal-note, file-editor and HTML-migration paths are retired.
Only an isolated browser_support runtime is used.
"""
from pathlib import Path
from playwright.sync_api import expect,sync_playwright
from browser_support import browser_server,browser_login

SOURCE='# Issue scope\n\n**Bold** and `code`.\n\n- First\n- Second\n\n- [x] Done\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```html\n<div>Example</div>\n```\n'
HEADERS={'X-Requested-With':'XMLHttpRequest'}


def main():
    evidence=Path('/tmp/casos-markdown-evidence');evidence.mkdir(exist_ok=True)
    with browser_server() as fixture,sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page(viewport={'width':1280,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        dialogs=[];page.on('dialog',lambda dialog:(dialogs.append(dialog.message),dialog.dismiss()))
        base=fixture['url'];browser_login(page,base)
        response=page.request.post(base+'/api/issues',data={'title':'Markdown security','description':SOURCE},headers=HEADERS)
        assert response.ok,response.text()
        iid=response.json()['id'];url=base+f'/api/issues/{iid}'
        page.goto(base+f'/issues/{iid}')
        editor=page.locator('.issue-description-panel .markdown-editor')
        expect(editor.locator('h1')).to_have_text('Issue scope')
        expect(editor.locator('strong')).to_have_text('Bold')
        expect(editor.locator('table')).to_have_count(1)
        expect(editor.locator('tbody tr')).to_contain_text('1')
        expect(editor.locator('pre code')).to_have_text('<div>Example</div>\n')
        expect(editor.locator('.markdown-body')).to_contain_text('☑')
        editor.locator('[data-md-action=edit]').click()
        expect(editor.locator('textarea')).to_have_value(SOURCE)
        changed='<p>Literal HTML</p>\n\n'+SOURCE.replace('Issue scope','Updated scope')
        editor.locator('textarea').fill(changed);editor.locator('[data-md-action=save]').click()
        expect(editor.locator('textarea')).to_be_hidden()
        expect(editor.locator('.markdown-body')).to_contain_text('<p>Literal HTML</p>')
        assert page.request.get(url).json()['description']==changed

        # The production Markdown path displays HTML literally and removes unsafe URLs.
        unsafe='# Safe\n\n<script>window.mdXss=1</script>\n\n<img src=x onerror="window.mdXss=1">\n\n[bad](javascript:alert(1))\n\n[good](https://example.invalid)\n\n![svg](data:image/svg+xml,<svg%20onload=alert(1)>)\n\n```html\n<script>example</script>\n```'
        editor.locator('[data-md-action=edit]').click()
        editor.locator('textarea').fill(unsafe);editor.locator('[data-md-action=save]').click()
        expect(editor.locator('textarea')).to_be_hidden()
        expect(editor.locator('script,iframe,svg,math,object,embed,[onerror],[onclick]')).to_have_count(0)
        expect(editor.locator('a[href^="javascript:"],img[src^="data:"]')).to_have_count(0)
        expect(editor.locator('a[href="https://example.invalid"]')).to_have_count(1)
        expect(editor.locator('pre code')).to_have_text('<script>example</script>\n')
        assert page.evaluate('window.mdXss === undefined')
        assert page.request.get(url).json()['description']==unsafe
        page.locator('#issue-add-update').click()
        update=page.locator('.update-dialog')
        update.locator('textarea').fill(unsafe);update.locator('[data-md-action=save]').click()
        expect(update.locator('.markdown-body h1')).to_have_text('Safe')
        expect(update.locator('script,iframe,svg,[onerror],a[href^="javascript:"]')).to_have_count(0)
        update.locator('[data-update-close]').click()
        expect(page.locator('.issue-update-preview')).to_contain_text('Safe')

        # Readers render the same safe content with no editing controls.
        reader=browser.new_page();reader.on('pageerror',lambda error:errors.append(str(error)))
        browser_login(reader,base,'bob');reader.goto(base+f'/issues/{iid}')
        expect(reader.locator('.issue-description-panel [data-md-action=edit]')).to_have_count(0)
        expect(reader.locator('.issue-description-panel script,[onerror]')).to_have_count(0)
        reader.locator('.issue-update-open').click()
        expect(reader.locator('.update-dialog [data-md-action=edit]')).to_have_count(0)
        expect(reader.locator('.update-dialog pre code')).to_have_text('<script>example</script>\n')

        # Regression at the shared sanitizer boundary, including entity/protocol
        # normalization, namespace reparsing and DOM-clobbering attributes.
        payloads=[
            '<a href="java&#x09;script:alert(1)" onclick="window.mdXss=1">bad</a><img src="data:image/svg+xml,evil" onerror="window.mdXss=1">',
            '<svg><a xlink:href="javascript:window.mdXss=1"><text>x</text></a><foreignObject><img src=x onerror="window.mdXss=1"></foreignObject></svg>',
            '<math><mtext><table><mglyph><style><!--</style><img title="--><img src=1 onerror=window.mdXss=1>">',
            '<table><tr><td><template><img src=x onerror=window.mdXss=1></template><iframe srcdoc="<script>window.mdXss=1</script>"></iframe></td></tr></table>',
            '<div id="location"><a name="href" href="javascript:window.mdXss=1">link</a></div>',
            '<a href="&#x0a;javascript:window.mdXss=1">bad</a><img src="javascript:window.mdXss=1">',
        ]
        results=page.evaluate('''sources => {
            const box=document.createElement('div');document.body.append(box);
            return sources.map(source=>{
                box.innerHTML=sanitizeHtml(source);
                const dangerous=[...box.querySelectorAll('*')].filter(el=>['SCRIPT','IFRAME','SVG','MATH','OBJECT','EMBED','FORM'].includes(el.tagName)||[...el.attributes].some(a=>a.name.startsWith('on')||['id','name','srcdoc'].includes(a.name)));
                const protocols=[...box.querySelectorAll('[href],[src]')].map(el=>new URL(el.href||el.src,location.href).protocol);
                const result={dangerous:dangerous.length,protocols};box.replaceChildren();return result;
            });
        }''',payloads)
        assert all(result['dangerous']==0 and set(result['protocols'])<={'http:','https:','mailto:'} for result in results),results
        assert page.evaluate('window.mdXss === undefined')
        assert dialogs==[],dialogs
        assert errors==[],errors
        page.screenshot(path=str(evidence/'markdown-literal-html.png'),full_page=True,animations='disabled')
        browser.close()
    print('Markdown browser passed: real REST source roundtrip, tables/lists/tasks/code, literal HTML, Issue+Update reader rendering, script/event/protocol/namespace/DOM-clobbering defenses.')
    print(f'Evidence: {evidence}')


if __name__=='__main__':main()
