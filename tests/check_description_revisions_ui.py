"""Real editor assets with isolated mock APIs: revisions and retained conflict drafts."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def revision(text):
    return hashlib.sha256(('markdown\0' + text).encode()).hexdigest()


def main():
    stored = {'/api/tasks/1': '# Project', '/api/subtasks/2': '# Subtask'}
    requests = []
    handoff = {'content': 'Own handoff', 'can_write': True, 'expired': False}
    errors = []

    def serve(route):
        path = urlparse(route.request.url).path
        if path == '/':
            route.fulfill(content_type='text/html', body='<div id="project"></div><div id="subtask"></div>')
            return
        data, status = {}, 200
        if path in stored and route.request.method == 'PUT':
            body = route.request.post_data_json
            requests.append((path, body))
            if body.get('description_revision') != revision(stored[path]):
                data, status = {'detail': 'description.conflict'}, 409
            else:
                stored[path] = body['description']
                data = {'description_revision': revision(stored[path])}
        elif path == '/api/tasks/1/note-entries/3':
            if route.request.method == 'PUT':
                body = route.request.post_data_json
                requests.append((path, body))
                if handoff['expired']:
                    data, status = {'detail': 'handoff.editWindowExpired'}, 403
                elif body['revision'] != revision(handoff['content']):
                    data, status = {'detail': 'handoff.conflict'}, 409
                else:
                    handoff['content'] = body['content']
                    data = {'revision': revision(handoff['content'])}
            else:
                data = dict(id=3, task_id=1, user_id=2, user_name='Author', created_at='11.10.2026 12:00',
                            format='markdown', content=handoff['content'], revision=revision(handoff['content']),
                            can_write=handoff['can_write'])
        route.fulfill(status=status, content_type='application/json', body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http://tareas.test/**', serve)
        page.goto('http://tareas.test/')
        page.evaluate('(translations) => window.t = key => translations[key] || key', json.loads((ROOT/'dashboard/static/i18n/en.json').read_text()))
        for name in ['app_core.js', 'vendor/marked.umd.js', 'vendor/turndown.js', 'markdown_editor.js', 'text_file_editor.js', 'tab_aufgaben.js']:
            page.add_script_tag(content=(ROOT/'dashboard/static/js'/name).read_text())
        for name in ['style.css', 'markdown_editor.css', 'text_file_editor.css']:
            page.add_style_tag(content=(ROOT/'dashboard/static/css'/name).read_text())

        def mount(target, url):
            page.evaluate('''({target, url, text, revision}) => {
                createMarkdownField(target, text, {url, model: {description: text, description_format:'markdown', description_revision:revision}});
            }''', dict(target=target, url=url, text=stored[url], revision=revision(stored[url])))

        for target, url in (('project','/api/tasks/1'), ('subtask','/api/subtasks/2')):
            mount(target, url)
            editor = page.locator('#' + target)
            initial = revision(stored[url])
            editor.get_by_role('button', name='Edit', exact=True).click()
            editor.locator('textarea').fill('## My draft')
            stored[url] = 'Concurrent change'
            editor.get_by_role('button', name='Save', exact=True).click()
            expect(editor.locator('.markdown-error')).to_contain_text('Your draft is retained')
            expect(editor.locator('textarea')).to_have_value('## My draft')
            assert requests[-1][1]['description_revision'] == initial
            assert stored[url] == 'Concurrent change'
            # Rebuilding a row after a reload must preserve the draft's old revision.
            mount(target, url)
            expect(editor.locator('textarea')).to_have_value('## My draft')
            editor.get_by_role('button', name='Save', exact=True).click()
            expect(editor.locator('.markdown-error')).to_be_visible()
            assert requests[-1][1]['description_revision'] == initial
            # Explicit discard picks up the loaded current base and its revision.
            editor.get_by_role('button', name='Cancel', exact=True).click()
            editor.get_by_role('button', name='Edit', exact=True).click()
            editor.locator('textarea').fill('Resolved')
            editor.get_by_role('button', name='Save', exact=True).click()
            expect(editor.locator('textarea')).to_be_hidden()
            assert stored[url] == 'Resolved'
            editor.get_by_role('button', name='Edit', exact=True).click()
            editor.locator('textarea').fill('Second save')
            editor.get_by_role('button', name='Save', exact=True).click()
            expect(editor.locator('textarea')).to_be_hidden()
            assert stored[url] == 'Second save'

        page.evaluate('openHandoffEditor(1, null, 3)')
        dialog = page.locator('.text-file-overlay')
        editor = dialog.locator('.markdown-editor')
        editor.get_by_role('button', name='Edit', exact=True).click()
        editor.locator('textarea').fill('Correct own handoff')
        editor.get_by_role('button', name='Save', exact=True).click()
        expect(editor.locator('textarea')).to_be_hidden()
        assert handoff['content'] == 'Correct own handoff'
        editor.get_by_role('button', name='Edit', exact=True).click()
        editor.locator('textarea').fill('Draft at timeout')
        handoff['expired'] = True
        editor.get_by_role('button', name='Save', exact=True).click()
        expect(editor.locator('.markdown-error')).to_contain_text('five-minute window')
        expect(editor.locator('textarea')).to_have_value('Draft at timeout')
        assert handoff['content'] == 'Correct own handoff'
        assert not errors, errors
        browser.close()
    print('Description project/subtask revision conflicts, reload draft retention, repeat saves and own-handoff expiry: OK')


if __name__ == '__main__':
    main()
